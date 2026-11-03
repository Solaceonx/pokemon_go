import copy
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np

from pogo.dqn import Network
from pogo.dqn_relational import Network as RelationalNetwork
from scripts import dqn_final
from scripts.double_dqn import BASE, ci, sha
from scripts.dqn_final import BLOCKS, compact, lock, validate_confirmation, validate_pairing, validate_canary


class LockedFinalTests(unittest.TestCase):
    def test_only_matching_fresh_full_engine_confirmation_can_spend_final_evidence(self):
        values = [.5, 1.] * 64
        report = dict(ci(values), pair_scores=values, split='validation', seed=38412, samples=32,
                      model_sha256='selected', baseline_commit=BASE)
        validate_confirmation(report, 'selected', 38412)
        for field, bad in (('split', 'test'), ('seed', 38411), ('samples', 8),
                           ('model_sha256', 'other'), ('baseline_commit', 'other'), ('lower95', .99),
                           ('clusters', 64), ('field', 'standard')):
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_confirmation(dict(report, **{field: bad}), 'selected', 38412)
        losing = dict(report, **ci([0., .5] * 64), pair_scores=[0., .5] * 64)
        with self.assertRaisesRegex(ValueError, 'preserve final teams'):
            validate_confirmation(losing, 'selected', 38412)
        validate_confirmation(losing, 'selected', 38412, require_competitive=False)
        with self.assertRaises(ValueError):
            validate_confirmation(losing, 'changed', 38412, require_competitive=False)

    def test_lock_binds_policy_recipe_sources_and_predeclared_final_blocks(self):
        self.assertEqual(BLOCKS, (('mixed', 38091), ('mixed', 38092), ('standard', 38091)))
        plan = {'policy': 'a', 'recipe': {'mode': 'average', 'samples': 0},
                'sources': {'code': 'b'}, 'pairs_per_block': 1000}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'lock.json'
            lock(path, plan)
            lock(path, copy.deepcopy(plan))
            for changed in (dict(plan, policy='c'), dict(plan, pairs_per_block=100),
                            dict(plan, recipe={'mode': 'direct'}), dict(plan, sources={'code': 'c'})):
                with self.assertRaises(ValueError):
                    lock(path, changed)

    def test_compact_export_retains_exact_parameters_and_rejects_another_source(self):
        with tempfile.TemporaryDirectory() as directory:
            a, b, target = [Path(directory) / name for name in ('a.npz', 'b.npz', 'policy.npz')]
            net = Network(hidden=8, seed=12)
            for moment in (*net.m, *net.v): moment.fill(1)
            net.steps = 9
            net.save(a)
            restored = compact(a, target)
            for original, exported in zip(net.p, restored.p):
                np.testing.assert_array_equal(original, exported)
            self.assertEqual(restored.steps, 0)
            self.assertFalse(any(np.any(m) for m in restored.m + restored.v))
            compact(a, Path(directory) / 'another.npz')
            self.assertEqual(sha(target), sha(Path(directory) / 'another.npz'))
            net.p[-1][0] += 1
            net.save(b)
            with self.assertRaises(ValueError):
                compact(b, target)

    def test_relational_export_retains_predictions_without_changing_flat_loader(self):
        x = np.random.default_rng(23).normal(size=(5, 400)).astype(np.float32)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            net = RelationalNetwork(hidden=8, seed=24)
            net.steps = 7
            for moment in net.m + net.v:
                moment.fill(1)
            net.save(root / 'source.npz')
            exported = compact(root / 'source.npz', root / 'policy.npz')
            self.assertIs(type(exported), RelationalNetwork)
            self.assertEqual(exported.steps, 0)
            self.assertFalse(any(np.any(m) for m in exported.m + exported.v))
            np.testing.assert_array_equal(net.predict(x), exported.predict(x))
            flat = Network(hidden=8, seed=25)
            flat.save(root / 'flat.npz')
            restored, _, _ = dqn_final.load_network(root / 'flat.npz')
            self.assertIs(type(restored), Network)
            np.testing.assert_array_equal(flat.predict(x), restored.predict(x))
            np.savez(root / 'unknown.npz', architecture=np.array('unknown'))
            with self.assertRaisesRegex(ValueError, 'Unsupported'):
                dqn_final.load_network(root / 'unknown.npz')

    def test_teacher_selection_binds_all_screens_selected_weights_and_fresh_confirmation(self):
        def report(path, seed, pairs, values):
            return dict(ci(values), pair_scores=values, split='validation', seed=seed, pairs=pairs,
                        samples=32, model_sha256=sha(path), baseline_commit=BASE)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'runs/double-dqn/teacher32-v1'
            source.mkdir(parents=True)
            candidates = {'reference': 'reference.npz', 'teacher32_fit': 'teacher32_fit.npz',
                          'last_complete_rl_endpoint': 'endpoint.npz'}
            for i, filename in enumerate(candidates.values()):
                RelationalNetwork(hidden=8, seed=i).save(source / filename)
            selected = source / 'teacher32_fit.npz'
            compact(selected, source / 'policy.npz')
            code = root / 'code.py'
            code.write_text('# selected runtime')
            plan = {'selection': {'pairs': 64, 'seed': 38811, 'opponent_samples': 32, 'split': 'validation'},
                    'confirmation': {'pairs': 128, 'seed': 38812, 'opponent_samples': 32, 'split': 'validation'},
                    'baseline_commit': BASE, 'source_sha256': {'code.py': sha(code)}}
            (source / 'plan.json').write_text(json.dumps(plan))
            screens = {name: report(source / filename, 38811, 64,
                [.5, 1.] * 32 if name != 'reference' else [0., .5] * 32)
                for name, filename in candidates.items()}
            result = {'selected': 'teacher32_fit', 'selected_sha256': sha(selected),
                      'policy_sha256': sha(source / 'policy.npz'), 'screens': screens,
                      'confirmation': report(selected, 38812, 128, [.5, 1.] * 64)}

            def select(record, canary=False):
                (source / 'result.json').write_text(json.dumps(record))
                with patch.object(dqn_final, 'ROOT', root):
                    return dqn_final.selection('teacher32-v1', canary)

            model, opponents, recipe, _ = select(result)
            self.assertEqual(model, selected)
            self.assertEqual(opponents, [])
            self.assertEqual(recipe['network'], 'shared-matchup-v1')
            self.assertEqual(recipe['mode'], 'direct')
            self.assertEqual(recipe['selection_plan_sha256'], sha(source / 'plan.json'))
            for key, value in (('selected', 'last_complete_rl_endpoint'), ('selected_sha256', 'other'),
                               ('policy_sha256', 'other')):
                with self.subTest(key=key), self.assertRaises(ValueError):
                    select(dict(result, **{key: value}))
            changed = copy.deepcopy(result)
            changed['screens']['reference']['model_sha256'] = 'other'
            with self.assertRaises(ValueError):
                select(changed)
            changed = copy.deepcopy(result)
            changed['confirmation']['seed'] = 38811
            with self.assertRaises(ValueError):
                select(changed, canary=True)
            # Good screening results cannot override a losing fresh confirmation.
            losing = dict(result, confirmation=report(selected, 38812, 128, [0., .5] * 64))
            select(losing, canary=True)
            with self.assertRaisesRegex(ValueError, 'preserve final teams'):
                select(losing)
            code.write_text('# changed after validation')
            with self.assertRaisesRegex(ValueError, 'runtime source changed'):
                select(result)

    def test_resume_rejects_another_seed_team_or_half_pair(self):
        teams, seeds = [['a', 'b', 'c'], ['d', 'e', 'f']], [1, 2, 3, 4, 5, 6]
        row = {'pair': 0, 'teams': teams, 'game_seeds': seeds, 'player_sides': [0, 1],
               'scores': [1., .5], 'mean': .75}
        validate_pairing(row, 0, teams, seeds)
        for field, bad in (('game_seeds', [6, 5, 4, 3, 2, 1]), ('teams', list(reversed(teams))),
                           ('scores', [1.]), ('mean', 1.), ('player_sides', [1, 0])):
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_pairing(dict(row, **{field: bad}), 0, teams, seeds)

    def test_production_requires_matching_complete_canary_artifacts(self):
        protocol = {'source_run': 'trial', 'source_model_sha256': 'a', 'recipe': {'mode': 'average'},
                    'artifacts': {'policy.npz': 'b'}, 'source_sha256': {'code': 'c'},
                    'baseline': {'commit': BASE}, 'confirmation': {'score': .8}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, 'canary before final'):
                validate_canary(root, protocol)
            blocks = [('mixed', 38995), ('mixed', 38996), ('standard', 38995)]
            receipt = dict(protocol, canary=True, split='validation', pairs_per_block=2,
                           blocks=[list(b) for b in blocks])
            (root / 'protocol.json').write_text(json.dumps(receipt))
            reports = []
            for field, seed in blocks:
                raw = root / f'rows_{field}_{seed}.jsonl'
                raw.write_text('{}\n{}\n')
                reports.append({'field': field, 'seed': seed, 'split': 'validation', 'pairs': 2,
                                'opponent_samples': 32, 'pair_scores': [.5, 1.], 'raw_sha256': sha(raw)})
            verdict = {'canary': True, 'strength_target_met': None,
                       'protocol_sha256': sha(root / 'protocol.json'), 'final_tests': reports}
            (root / 'verdict.json').write_text(json.dumps(verdict))
            validate_canary(root, protocol)
            with self.assertRaises(ValueError):
                validate_canary(root, dict(protocol, recipe={'mode': 'direct'}))
            with self.assertRaises(ValueError):
                validate_canary(root, dict(protocol, budget_finalization={'selection_sha256': 'other'}))
            (root / 'rows_mixed_38995.jsonl').write_text('{}\n')
            with self.assertRaises(ValueError):
                validate_canary(root, protocol)


if __name__ == '__main__':
    unittest.main()
