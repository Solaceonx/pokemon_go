"""Opt-in distributions, actual matrix cells, private dice, and pre-edit game digests."""
import hashlib
import json
import math
from pathlib import Path
import random
import subprocess
import sys
import unittest
from unittest.mock import patch

from pogo.agents import Planner
from pogo.battle import Battle, CHARGED, FAST, Mon, change_form
from pogo.engine import Engine, imagine
from pogo.evaluation import material
from pogo.lab.mixed import equilibrium, logit, shield_floor
from pogo.learner import Learner
from pogo.realtime import RealTime
from scripts import engine_versus as ev

ROOT = Path(__file__).resolve().parents[1]


class MixedLab(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ev.setup()
        cls.pool = ev._state['pool']
        cls.team = [ev._state['gd'].default(s) for s in ('melmetal', 'altaria', 'jellicent')]

    def position(self, cls=Engine, **kw):
        player = cls(material, self.pool, samples=1, horizon=1, seed=51, **kw)
        battle = Battle(self.team, self.team, player, Planner(seed=52), seed=53)
        for side in battle.sides:
            side.mon.energy = 100
        return player, battle, battle.views[0]

    def test_default_games_match_pre_edit_digests(self):
        fixture = json.loads((ROOT / 'runs/lab-mixed/default-digests.json').read_text())
        for row in fixture['games']:
            with self.subTest(seed=row['seed']):
                seed = row['seed']
                rng = random.Random(seed)
                a, b = rng.sample(self.pool, 3), rng.sample(self.pool, 3)
                player = ev.pilot(ev.parse(row['spec']), seed + 1)
                self.assertNotIn('shield', player.heads)
                battle = Battle(a, b, player, ev.pilot(None, seed + 2), seed=seed, record=True)
                winner = battle.run()
                payload = json.dumps([winner, battle.turn, battle.log, battle.hits],
                                     ensure_ascii=True, separators=(',', ':'))
                self.assertEqual(hashlib.sha256(payload.encode()).hexdigest(), row['sha256'])

    def test_zero_temperature_is_existing_argmax_including_edge_and_ties(self):
        cases = ({0: .5, 1: .6, 2: .2}, {0: .5, 1: .52, 2: .2}, {0: .5, 1: .5, 2: .5})
        for head in ('shield', 'throw'):
            for worth in cases:
                values = dict(list(worth.items())[:2]) if head == 'shield' else worth
                for pick in values:
                    old, _, view = self.position(edge=.03, heads=(head,))
                    new, _, _ = self.position(edge=.03, heads=(head,), **{head + '_mix': 0})
                    with patch.object(Engine, '_look', side_effect=lambda v, h, k, s: values[k]):
                        expected = old._decide(head, view, (True,) * len(values), lambda: pick, 100)
                        before = new._mix_rng.getstate()
                        actual = new._decide(head, view, (True,) * len(values), lambda: pick, 100)
                    self.assertEqual(actual, expected)
                    self.assertEqual(new._mix_rng.getstate(), before)
        self.assertEqual(logit({0: 0., 1: .03}, 0, .03, 0), {0: 1., 1: 0.})

    def test_positive_temperatures_match_empirical_head_frequencies(self):
        for head, values in (('shield', {0: .4, 1: .5}), ('throw', {0: .4, 1: .5, 2: .45})):
            p, _, view = self.position(edge=.03, **{head + '_mix': .1})
            probabilities = logit(values, 0, .03, .1)
            counts = dict.fromkeys(values, 0)
            with patch.object(p, '_look', side_effect=lambda v, h, k, s: values[k]):
                for _ in range(12000):
                    choice = p._decide(head, view, (True,) * len(values), lambda: 0, 100)
                    counts[choice] += 1
                    self.assertAlmostEqual(getattr(p, 'last_' + head + '_probability'), probabilities[choice])
            for k, probability in probabilities.items():
                self.assertAlmostEqual(counts[k] / 12000, probability, delta=.018)
        # Numerically stable even for huge gaps / tiny positive temperatures.
        self.assertEqual(logit({0: 0., 1: 1.}, 0, 0., 1e-300), {0: 0., 1: 1.})

    def test_floor_only_bounds_close_values(self):
        for probability in (0., .02, .5, .98, 1.):
            base = {0: 1 - probability, 1: probability}
            close = shield_floor(base, {0: .5, 1: .51}, .03, .15)
            self.assertTrue(.15 <= close[1] <= .85)
            self.assertEqual(shield_floor(base, {0: .3, 1: .7}, .03, .15), base)
        player, _, view = self.position(shield_floor=.2, edge=.03)
        with patch.object(player, '_look', return_value=.5):
            answers = [player.shield(view, 100) for _ in range(100)]
        self.assertEqual(set(answers), {True, False})

    def test_exact_solver_known_games(self):
        self.assertEqual(equilibrium([[1., -1.], [-1., 1.]]), [.5, .5])
        self.assertEqual(equilibrium([[3., 2.], [1., 0.]]), [1., 0.])
        self.assertEqual(equilibrium([[0., 1.], [2., 3.]]), [0., 1.])
        self.assertEqual(equilibrium([[1., 1.], [1., 1.]]), [1., 0.])
        self.assertAlmostEqual(equilibrium([[3., 0.], [0., 1.]])[0], .25)

    def test_equilibrium_throw_preserves_hold_and_mixes_only_charged_mass(self):
        player, _, view = self.position(equilibrium=True, throw_mix=.1)
        seen = []
        def look(v, head, option, seed):
            if player._their_shield is None:
                return .5
            seen.append((option, player._their_shield))
            return float((option == 1) == player._their_shield)
        # Uniform initial three-way logit, then split its 2/3 throw mass with the exact game.
        with patch.object(player, '_look', side_effect=look), patch.object(player, '_draw', return_value=0) as draw:
            player._decide('throw', view, (True, True, True), lambda: 0)
        probabilities = draw.call_args.args[1]
        self.assertEqual(set(seen), {(1, True), (1, False), (2, True), (2, False)})
        for probability in probabilities.values():
            self.assertAlmostEqual(probability, 1 / 3)
        self.assertIsNone(player._their_shield)
        # When search prefers holding outright, the bait matrix is not needed.
        player.throw_mix = None
        with patch.object(player, '_look', side_effect=lambda v, h, k, s: float(k == 0)), \
                patch.object(player, '_matrix') as matrix:
            self.assertEqual(player._decide('throw', view, (True, True, True), lambda: 0), 0)
            matrix.assert_not_called()

    def test_equilibrium_shield_uses_affordable_moves_and_prompt_energy(self):
        player, _, view = self.position(equilibrium=True)
        view.foe.energy = 0  # supplied pre-cost energy, not this value, selects columns
        def look(v, head, option, seed):
            return float(option == player._their_first - CHARGED[0])
        with patch.object(player, '_look', side_effect=look):
            answers = [player.shield(view, 100) for _ in range(100)]
        self.assertEqual(set(answers), {True, False})
        self.assertEqual(player.last_shield_probability, .5)
        self.assertIsNone(player._their_first)
        player._foe_energy = min(m.energy for m in view.foe.build.charged)
        self.assertEqual(player._mixed_actions('shield', view), [])

    def test_actual_throw_cells_force_only_the_first_shield(self):
        player, battle, view = self.position(equilibrium=True)
        player.evaluator = lambda v: v.foe_shields
        for shielded in (False, True):
            player._their_shield = shielded
            self.assertEqual(player._look(view, 'throw', 1, 123), 2 - shielded)
        self.assertEqual(battle.sides[1].shields, 2)
        self.assertEqual(view.me.mon.energy, 100)

    def doomed_position(self, **kw):
        player = Engine(material, self.pool, samples=1, horizon=1, seed=51, q=ev._state['net'], **kw)
        team = [ev._state['gd'].default(s) for s in ('altaria', 'melmetal', 'umbreon')]
        battle = Battle(team, self.team, player, Planner(seed=52), seed=53)
        view = battle.views[0]
        view.me.mon.hp, view.me.mon.energy, view.foe.energy = 10, 65, 100
        return player, view

    def test_hypothetical_shields_keep_default_doomed_and_throw_advice_across_seeds(self):
        default, view = self.doomed_position()
        expected = default._doomed(view, 3), Planner._pick_move(default, view)
        self.assertEqual(expected, (True, CHARGED[1]))
        # This fixture is sensitive to the shield answer, rather than already lost to fast damage.
        with patch.object(default, 'shield', return_value=True):
            self.assertEqual((default._doomed(view, 3), Planner._pick_move(default, view)), (False, FAST))
        for options in ({'shield_mix': .05}, {'equilibrium': True},
                        {'shield_mix': .05, 'equilibrium': True}):
            for seed in range(30):
                with self.subTest(options=options, seed=seed):
                    player, view = self.doomed_position(**options)
                    player._mix_rng.seed(seed)
                    player.last_shield_probability = .25
                    def advice():
                        before = player.looks, player.rng.getstate(), player._mix_rng.getstate()
                        self.assertEqual((player._doomed(view, 3), Planner._pick_move(player, view)), expected)
                        self.assertEqual((player.looks, player.rng.getstate(), player._mix_rng.getstate()), before)
                        self.assertEqual(player.last_shield_probability, .25)
                        return 2
                    # Force the outer search to hold; no bait matrix or random outer choice is needed.
                    with patch.object(player, '_look', side_effect=lambda v, h, k, s: float(k == 0)) as look:
                        self.assertEqual(player._decide('throw', view, (True, True, True), advice), 0)
                    self.assertEqual({call.args[1] for call in look.call_args_list}, {'throw'})
                    self.assertEqual(player.looks, 1)
                    self.assertEqual(player._decision_depth, 0)

    def test_learner_timing_postcheck_uses_hypothetical_shield_without_search_or_dice(self):
        for options in ({}, {'shield_mix': .05}, {'equilibrium': True},
                        {'shield_mix': .05, 'equilibrium': True}):
            for seed in range(30):
                player, view = self.doomed_position(respect_timing=True, **options)
                player._mix_rng.seed(seed)
                player.force('throw', 0)
                before = player.looks, player.rng.getstate(), player._mix_rng.getstate()
                with patch.object(player, '_look', side_effect=AssertionError('hypothetical search')):
                    self.assertEqual(player._pick_move(view), CHARGED[1])
                self.assertEqual(player.timing_fixes, 1)
                self.assertEqual((player.looks, player.rng.getstate(), player._mix_rng.getstate()), before)
                self.assertEqual(player._decision_depth, 0)

    def test_decision_guard_unwinds_on_error_and_real_shield_still_searches(self):
        player, _, view = self.position(shield_mix=.05)
        with patch.object(player, '_act', side_effect=RuntimeError('probe')):
            with self.assertRaisesRegex(RuntimeError, 'probe'):
                player.act(view)
        def fail():
            raise RuntimeError('probe')
        with self.assertRaisesRegex(RuntimeError, 'probe'):
            player._decide('throw', view, (True, True, True), fail)
        self.assertEqual(player._decision_depth, 0)
        before = player._mix_rng.getstate()
        with patch.object(player, '_look', return_value=.5):
            player.shield(view, 100)
        self.assertEqual(player.looks, 1)
        self.assertNotEqual(player._mix_rng.getstate(), before)

    def test_last_pokemon_keeps_default_rule_without_search_or_dice(self):
        for last_always in (True, False):
            for options in ({'shield_mix': 0}, {'shield_mix': .05}, {'shield_floor': .2},
                            {'equilibrium': True}, {'shield_mix': .05, 'equilibrium': True}):
                default, _, view = self.position(last_always=last_always, shields='never', q=ev._state['net'])
                for mon in view.me.team[1:]:
                    mon.hp = 0
                expected = default.shield(view, 100)
                self.assertEqual(expected, last_always)
                player, _, _ = self.position(cls=RealTime, last_always=last_always, shields='never',
                                             q=ev._state['net'], **options)
                for seed in range(30):
                    player._mix_rng.seed(seed)
                    before = player.rng.getstate(), player._mix_rng.getstate()
                    with patch.object(player, '_look', side_effect=AssertionError('last-Pokemon search')):
                        self.assertEqual(player.shield(view, 100), expected)
                    self.assertEqual((player.rng.getstate(), player._mix_rng.getstate()), before)
                    self.assertEqual(player.last_shield_probability, 1.)
                self.assertEqual((player.looks, player.rows), (0, []))

    def test_real_shield_timed_fallback_is_unchanged(self):
        player, battle, view = self.position(cls=RealTime, shield_mix=.05, after_charged_ms=-1)
        expected = Planner.shield(player, view, 100)
        self.assertEqual(player.shield(view, 100), expected)
        self.assertEqual(player.fell_back, 1)
        self.assertTrue(player.rows[0][-1])
        self.assertEqual(player.last_shield_probability, 1.)
        player.after_charged_ms = 1e9
        with patch.object(player, '_look', side_effect=lambda v, h, k, s: float(k == 0)):
            self.assertFalse(player.shield(view, 100))
        self.assertEqual(battle.sides[0].shields, 2)

    def test_throw_cell_cannot_carry_its_shield_response_past_a_cmp_knockout(self):
        class ThrowAll:
            def act(self, view):
                return CHARGED[0] if CHARGED[0] in view.legal() else FAST

            def shield(self, view, energy):
                return False

            def replace(self, view):
                return view.me.bench()[0]

        player, _, _ = self.position(equilibrium=True)
        team = [ev._state['gd'].default('azumarill'), *self.team[:2]]
        battle = Battle(team, self.team, ThrowAll(), ThrowAll(), seed=1, shields=(0, 2))
        battle.sides[0].mon.hp = 1
        for mon in battle.sides[0].team:
            mon.energy = 100
        battle.sides[1].mon.energy = 100
        self.assertGreater(battle.sides[1].mon.build.cmp_atk, battle.sides[0].mon.build.cmp_atk)
        player.horizon, player._their_first = 2, CHARGED[0]
        observed = []
        def judge(view):
            observed.append((view.me.active, view.me.team[0].energy, view.me.mon.energy))
            return view.foe_shields
        player.evaluator = judge
        for shielded in (True, False):
            player._their_shield = shielded
            with patch('pogo.engine._rollout', side_effect=ThrowAll):
                self.assertEqual(player._look(battle.views[0], 'throw', 1, 123), 2)
        self.assertEqual(len(observed), 2)
        for slot, canceled_energy, later_energy in observed:
            self.assertEqual((slot, canceled_energy), (1, 100))
            self.assertLess(later_energy, 100)  # the replacement really threw, without the fixed shield

    def test_shield_landing_uses_simulator_form_rules(self):
        player, _, _ = self.position(equilibrium=True)
        battle = Battle([ev._state['gd'].default('mimikyu')], self.team, player, Planner(), seed=1)
        battle.sides[1].mon.energy = 100
        player._foe_energy, player._their_first = 100, CHARGED[0]
        hp = battle.sides[0].mon.hp
        player._land_their_throw(battle, random.Random(1), shielded=False)
        self.assertEqual(battle.sides[0].mon.hp, hp - 1)
        self.assertEqual(battle.sides[0].mon.build.species_id, 'mimikyu_busted')
        self.assertEqual(battle.sides[0].shields, 2)

    def test_shield_landing_replacements_are_simultaneous_after_gulp_double_faint(self):
        class Observer:
            def __init__(self):
                self.seen = []

            def act(self, view):
                return CHARGED[0] if CHARGED[0] in view.legal() else FAST

            def shield(self, view, energy):
                return False

            def replace(self, view):
                self.seen.append((view.foe.build.species_id, view.foe.hp))
                return view.me.bench()[0]

        player, _, _ = self.position(equilibrium=True)
        snapshots = []
        for landing in (False, True):
            cramorant = Mon(ev._state['gd'].default('cramorant'))
            change_form(cramorant, 'cramorant_gulping')
            agents = Observer(), Observer()
            battle = Battle([cramorant, *self.team[1:]], self.team, *agents, seed=1)
            for side in battle.sides:
                side.mon.hp = 1
            battle.sides[1].mon.energy = 100
            if landing:
                player._foe_energy, player._their_first = 100, CHARGED[0]
                player._land_their_throw(battle, random.Random(1), shielded=False)
            else:
                battle.step()
            for agent in agents:
                self.assertEqual(len(agent.seen), 1)
                self.assertLessEqual(agent.seen[0][1], 0)  # neither observes a replacement already in
            self.assertEqual([s.active for s in battle.sides], [1, 1])
            snapshots.append((battle.turn, battle.winner, [a.seen for a in agents],
                              [(s.active, s.shown, s.shields, s.busy, s.switch_wait,
                                [(m.hp, m.energy, m.build.species_id) for m in s.team]) for s in battle.sides]))
        self.assertEqual(*snapshots)

    def test_incomplete_matrix_is_discarded_and_fixed_actions_are_restored(self):
        player, _, view = self.position(equilibrium=True)
        with patch.object(player, '_out_of_time', side_effect=[False, False, True, True]), \
                patch.object(player, '_look', return_value=.5):
            table, rounds = player._matrix(view, 'throw', [1, 2], [1], [True, False], shield_columns=True)
        self.assertEqual((table, rounds), ([], 0))
        self.assertIsNone(player._their_shield)

    def test_clones_and_independent_processes_replay_private_mixing_dice(self):
        player, _, _ = self.position(shield_mix=.05)
        twin = player.clone()
        self.assertEqual([player._mix_rng.random() for _ in range(20)], [twin._mix_rng.random() for _ in range(20)])
        code = ('from pogo.engine import Engine; p=Engine(None, [], seed=51, shield_mix=.05); '
                'print([p._mix_rng.random() for _ in range(8)])')
        a = subprocess.check_output([sys.executable, '-X', 'utf8', '-c', code], cwd=ROOT)
        b = subprocess.check_output([sys.executable, '-X', 'utf8', '-c', code], cwd=ROOT)
        self.assertEqual(a, b)

    def test_probabilities_count_only_real_prompts_and_throw_heads(self):
        player, _, view = self.position(shield_mix=.05, throw_mix=.03)
        wrapped = ev.Counted(player)
        with patch.object(player, '_look', return_value=.5):
            wrapped.shield(view, 100)
            # A hypothetical shield call during act must not enter the real prompt denominator.
            with patch.object(player, '_act', side_effect=lambda v: int(player.shield(v, 100))):
                player.act(view)
            with patch.object(player, '_act', side_effect=lambda v: player._decide('throw', v, (True, True, True), lambda: 0)):
                wrapped.act(view)
        counts = wrapped.counts()
        self.assertEqual(counts['prompts'], 1)
        self.assertEqual(counts['probability_choices'], 2)
        self.assertAlmostEqual(counts['choice_probability_sum'], .5 + 1 / 3)
        self.assertIn('mean P(chosen) 0.417', ev.activity_summary({0: {'ours': counts}}))

    def test_legacy_random_paths_are_excluded_from_probability_counter(self):
        for options, head in (({'temperature': .1}, 'throw'), ({'temperature': .1}, 'shield'),
                              ({'mix': True}, 'throw'), ({'mix_shield': True}, 'shield')):
            player, _, view = self.position(heads=('throw', 'shield'), **options)
            wrapped = ev.Counted(player)
            with patch.object(player, '_look', return_value=.5):
                if head == 'shield':
                    wrapped.shield(view, 100)
                else:
                    with patch.object(player, '_act', side_effect=lambda v: player._decide(
                            'throw', v, (True, True, True), lambda: 0)):
                        wrapped.act(view)
            self.assertIsNone(getattr(player, 'last_' + head + '_probability'))
            counts = wrapped.counts()
            self.assertEqual((counts['probability_choices'], counts['choice_probability_sum']), (0, 0))
            summary = ev.activity_summary({0: {'ours': counts}})
            self.assertIn('mean P(chosen) n/a', summary)
            self.assertIn('legacy random choices excluded', summary)

    def test_legacy_switch_mix_does_not_log_fallback_throw_probability(self):
        player, _, view = self.position(mix_switch=True)
        wrapped = ev.Counted(player)
        with patch.object(player, '_look', return_value=.5), patch.object(
                Learner, 'act', side_effect=lambda v: player._decide('throw', v, (True, True, True), lambda: 1)):
            wrapped.act(view)
        self.assertEqual(player.mixed, 1)
        self.assertIsNone(player.last_throw_probability)
        self.assertEqual(wrapped.counts()['probability_choices'], 0)

    def test_legacy_and_lab_mix_conflicts_fail_in_parser_and_constructor(self):
        for legacy in ('temperature', 'mix', 'mix_shield', 'mix_switch'):
            for lab, value in (('shield_mix', 0), ('throw_mix', .03), ('shield_floor', .1), ('equilibrium', 1)):
                with self.subTest(legacy=legacy, lab=lab):
                    message = rf'legacy mixing options \({legacy}\) cannot be combined with lab options \({lab}\)'
                    with self.assertRaisesRegex(SystemExit, message):
                        ev.parse(f'website,{legacy}=1,{lab}={value}')
                    with self.assertRaisesRegex(ValueError, message):
                        self.position(**{legacy: 1, lab: value})
        # Disabled legacy flags are harmless, and zero-temperature lab search is still an active key.
        self.position(temperature=0, mix=False, mix_shield=False, mix_switch=False, shield_mix=0)
        ev.parse('website,temperature=0,mix=0,mix_shield=0,mix_switch=0,shield_mix=0')

    def test_spec_keys_and_invalid_values(self):
        settings = ev.parse('website,shield_mix=0,throw_mix=.03,shield_floor=.1,equilibrium=1')
        player = ev.pilot(settings, 1)
        self.assertEqual(player.shield_mix, 0.)
        self.assertTrue(player.equilibrium)
        self.assertIn('shield', player.heads)
        for key in ('shield_mix', 'throw_mix', 'shield_floor'):
            for value in (-.1, math.inf, math.nan):
                with self.assertRaises(SystemExit):
                    ev.parse(f'website,{key}={value}')
                with self.assertRaises(ValueError):
                    self.position(**{key: value})
        with self.assertRaises(SystemExit):
            ev.parse('shield_floor=.51')


if __name__ == '__main__':
    unittest.main()
