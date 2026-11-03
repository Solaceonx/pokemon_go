import copy
import json
from pathlib import Path
import random
import statistics
import tempfile
from types import SimpleNamespace
import unittest

from scripts.check_dqn_verdict import audit_block, paired_interval, sha
from scripts.double_dqn import bucket, draw_split


class VerdictEvidenceTests(unittest.TestCase):
    def test_interval_keeps_uncertainty_for_constant_results_and_rejects_half_pair(self):
        report = paired_interval([1.] * 1000)
        self.assertEqual(report['score'], 1.)
        self.assertGreater(report['margin95'], 0.)
        self.assertLess(report['lower95'], 1.)
        self.assertEqual(report['upper95'], 1.)
        for values in ([.5], [0., float('nan')], [.5, .4]):
            with self.subTest(values=values), self.assertRaises(ValueError):
                paired_interval(values)

    def test_raw_canary_audit_rejects_tampering_even_with_rehashed_journal(self):
        # Synthetic journal only: no engine game and no final-test composition or seed is used.
        choices = []
        for i in range(100):
            team = [SimpleNamespace(home=f'audit-{i}-{j}', species_id=f'audit-{i}-{j}') for j in range(3)]
            if bucket(team) == 'validation':
                choices.append(team)
            if len(choices) == 2:
                break
        draw = lambda rng: choices[rng.randrange(len(choices))]
        f = SimpleNamespace(mixed_draw=draw, standard_draw=draw)
        rng = random.Random(38995)
        rows = []
        for i in range(2):
            teams = [draw_split(draw, rng, 'validation'), draw_split(draw, rng, 'validation')]
            scores = [1., float(i) / 2]
            rows.append({'pair': i, 'teams': [[m.home for m in team] for team in teams],
                'game_seeds': [rng.getrandbits(32) for _ in range(6)], 'player_sides': [(i + o) % 2 for o in range(2)],
                'scores': scores, 'mean': statistics.mean(scores), 'seconds': [.1, .2]})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / 'rows_mixed_38995.jsonl'

            def saved(data):
                raw.write_text(''.join(json.dumps(row) + '\n' for row in data))
                values = [row['mean'] for row in data]
                report = dict(paired_interval(values), pair_scores=values, field='mixed', seed=38995,
                    split='validation', pairs=2, battles=4, opponent_samples=32, raw_sha256=sha(raw))
                (root / 'mixed_38995_summary.json').write_text(json.dumps(report))
                return report

            valid = saved(rows)
            result = audit_block(root, valid, f, 'mixed', 38995, 2, 'validation')
            self.assertEqual(result['score'], .625)
            for field, value in (('teams', [['changed'] * 3] * 2), ('game_seeds', [0] * 6),
                                 ('player_sides', [1, 0]), ('scores', [1.]), ('pair', 1)):
                changed = copy.deepcopy(rows)
                changed[0][field] = value
                # Rehash the corrupted raw file and save a matching summary. Draw reconstruction
                # and completeness checks must still catch the change, independently of hashes.
                report = saved(changed)
                with self.subTest(field=field), self.assertRaises(ValueError):
                    audit_block(root, report, f, 'mixed', 38995, 2, 'validation')
            report = saved(rows)
            report['margin95'] += .01
            (root / 'mixed_38995_summary.json').write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError, 'independent paired calculation'):
                audit_block(root, report, f, 'mixed', 38995, 2, 'validation')


if __name__ == '__main__':
    unittest.main()
