"""Opt-in creator tactics, seeded choices, real-search gates and frozen default games."""
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys
import unittest
from unittest.mock import patch

import numpy as np

from pogo.agents import Planner
from pogo.battle import Battle, CHARGED, FAST, SWITCH, damage
from pogo.engine import Engine
from pogo.evaluation import material
from pogo.lab.mixed import bait_pair
from pogo.lab.people import PeopleLike, people_player
from pogo.lab.tactics import before_swap
from pogo.learner import Learner
from scripts import engine_versus as ev

ROOT = Path(__file__).resolve().parents[1]
OFF = 'finish_safe=0,bait_mix=off,shield_two=off,shield_one=off'


class TacticsLab(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ev.setup()
        cls.gd, cls.pool = ev._state['gd'], ev._state['pool']

    def position(self, spec='bot', mine='swampert', foe='azumarill', shields=(2, 2)):
        player = ev.pilot(ev.parse(spec), 51)
        a = [self.gd.default(s) for s in (mine, 'altaria', 'umbreon')]
        b = [self.gd.default(s) for s in (foe, 'altaria', 'umbreon')]
        battle = Battle(a, b, player, Planner(seed=52), seed=53, shields=shields)
        battle.sides[0].mon.energy = 100
        return player, battle, battle.views[0]

    def test_finish_safe_henry_position_reaches_throw_search(self):
        for base in ('bot', 'website'):
            for safe in (0, 1):
                p, b, v = self.position(f'{base},finish_safe={safe}', 'empoleon', 'diggersby', (0, 0))
                v.me.mon.hp, v.me.mon.energy = 62, 48
                v.foe.hp, v.foe.energy, b.sides[1].busy = 4, 100, 1
                self.assertTrue(p._doomed(v, v.me.mon.build.fast.turns))
                self.assertEqual(p._pick_move(v), CHARGED[0] if safe else FAST)
                if base == 'website':
                    self.assertEqual(p.looks, safe)

    def test_safe_fast_finish_and_no_energy_still_hold(self):
        p, b, v = self.position('website,finish_safe=1', 'empoleon', 'diggersby', (0, 0))
        v.foe.hp, v.foe.energy = 4, 0
        b.sides[1].busy = 1
        self.assertFalse(p._doomed(v, 2))
        self.assertEqual(p._pick_move(v), FAST)
        v.me.mon.hp, v.me.mon.energy, v.foe.energy = 1, 0, 100
        self.assertEqual(p._pick_move(v), FAST)
        self.assertEqual(p.looks, 0)

    def test_bait_mix_extremes_override_final_charged_choice_bot_and_engine(self):
        for base in ('bot', 'website'):
            for p, expected in ((0, CHARGED[1]), (1, CHARGED[0])):
                player, _, view = self.position(f'{base},bait_mix={p}')
                self.assertEqual(bait_pair(view), (0, 1))
                for original in (1, 2):
                    player.force('throw', original)
                    self.assertEqual(player._pick_move(view), expected)
                self.assertEqual(player.bait_opportunities, 2)
                self.assertEqual(player.baits_thrown, 2 * p)

    def test_bait_mix_preserves_holds_switches_and_ineligible_moves_without_dice(self):
        player, battle, view = self.position('bot,bait_mix=.4')
        state = player._mix_rng.getstate()
        player.force('throw', 0)
        self.assertEqual(player._pick_move(view), FAST)
        for action in (FAST, *SWITCH):
            self.assertEqual(player._bait_action(view, action), action)
        for energy, shields, hp in ((40, 2, 191), (100, 0, 191), (100, 2, 1)):
            view.me.mon.energy, battle.sides[1].shields, view.foe.hp = energy, shields, hp
            self.assertIsNone(bait_pair(view))
            self.assertEqual(player._bait_action(view, CHARGED[0]), CHARGED[0])
        for mine, foe in (('empoleon', 'diggersby'), ('melmetal', 'altaria')):
            _, _, other = self.position(mine=mine, foe=foe)
            self.assertIsNone(bait_pair(other))  # equal cost, and dearer hit too weak
        self.assertEqual(player._mix_rng.getstate(), state)
        self.assertEqual(player.bait_opportunities, 0)

    def test_baits_use_private_seeded_rng_and_clone_independently(self):
        player, _, view = self.position('bot,bait_mix=.4')
        twin = player.clone()
        self.assertIsNot(player._mix_rng, twin._mix_rng)
        search_state = player.rng.getstate()
        expected = random.Random()
        expected.setstate(player._mix_rng.getstate())
        throws = [player._bait_action(view, CHARGED[1]) for _ in range(400)]
        self.assertEqual(throws, [CHARGED[0] if expected.random() < .4 else CHARGED[1] for _ in throws])
        self.assertEqual(throws, [twin._bait_action(view, CHARGED[1]) for _ in throws])
        self.assertEqual(player.rng.getstate(), search_state)
        self.assertEqual(player.baits_thrown, throws.count(CHARGED[0]))
        self.assertGreater(player.baits_thrown, 100)
        self.assertLess(player.baits_thrown, 220)
        code = ('from pogo.engine import Engine; p=Engine(None, [], seed=51, bait_mix=.4); '
                'print([p._mix_rng.random() for _ in range(8)])')
        self.assertEqual(subprocess.check_output([sys.executable, '-X', 'utf8', '-c', code], cwd=ROOT),
                         subprocess.check_output([sys.executable, '-X', 'utf8', '-c', code], cwd=ROOT))

    def test_counted_reports_real_baits_once(self):
        p, _, v = self.position('website,bait_mix=1')
        wrapped = ev.Counted(p)
        p.force('throw', 2)
        with patch.object(p, '_pick_switch', return_value=None):
            self.assertEqual(wrapped.act(v), CHARGED[0])
        counts = wrapped.counts()
        self.assertEqual((counts['bait_opportunities'], counts['baits_thrown']), (1, 1))
        self.assertEqual(counts['probability_choices'], 0)
        self.assertIn('baits 1 / 1', ev.activity_summary({0: {'ours': counts}}))

    def test_simultaneous_search_mixes_only_final_throw(self):
        p, _, v = self.position('website,bait_mix=1,mix_switch=1')
        with patch.object(p, '_mixed_actions', return_value=[FAST, CHARGED[0]]), \
                patch.object(p, '_mixed', return_value=CHARGED[1]), \
                patch.object(p, '_pick_switch', return_value=None):
            p.force('throw', 2)
            self.assertEqual(p.act(v), CHARGED[0])
        self.assertEqual(p.bait_opportunities, 1)

    def test_shield_margins_are_separate_and_fall_back_per_state(self):
        p, b, v = self.position('bot,shield_two=.2,shield_one=0,shield_margin=.15')
        with patch.object(p.q, 'values', return_value=np.array([.6, .5])):
            self.assertEqual(p._decide('shield', v, (True, True), lambda: 1), 1)
            b.sides[0].shields = 1
            self.assertEqual(p._decide('shield', v, (True, True), lambda: 1), 0)
            p.shield_one = None
            self.assertEqual(p._decide('shield', v, (True, True), lambda: 1), 1)
            p.shield_one, p.shield_toward = 0, True
            self.assertEqual(p._decide('shield', v, (True, True), lambda: 1), 1)
        self.assertEqual(p._head_margin('throw', v), .02)

    def test_shield_last_pokemon_rule_is_unchanged(self):
        for base in ('bot', 'website'):
            p, _, v = self.position(f'{base},shield_two=0,shield_one=1')
            for mon in v.me.team[1:]:
                mon.hp = 0
            with patch.object(p, '_decide', side_effect=AssertionError('last Pokemon reached head')):
                self.assertTrue(p.shield(v, 100))
                p.last_always = False
                with patch.object(Planner, 'shield', return_value=False):
                    self.assertFalse(p.shield(v, 100))

    def swap_position(self, enabled=True, judged=False):
        p, b, v = self.position('website,swap_after_throw=' + str(int(enabled)), shields=(2, 0))
        p.samples, p.horizon, p.sac, p.fast_first = 1, 1, False, 0
        b.turn, v.foe.energy = 10, 100
        if judged:
            p.mid_swap_search = 'ready'
            p._judged = (v.me.active, v.foe.build.uid)
        return p, b, v

    def test_searched_swap_throws_then_reopens_question_without_forcing_a_switch(self):
        for judged in (False, True):
            p, b, v = self.swap_position(judged=judged)
            with patch.object(p, '_look', side_effect=lambda v, h, k, s: float(k == 1)):
                self.assertEqual(p.act(v), CHARGED[1])
                self.assertEqual(p.swap_after_throws, 1)
                self.assertIsNone(p._judged)
                self.assertEqual(p.act(v), SWITCH[1])
                self.assertEqual(p.swap_after_throws, 1)
        p, b, v = self.swap_position()
        with patch.object(p, '_look', side_effect=lambda v, h, k, s: float(k == 1)):
            p.act(v)
        with patch.object(p, '_look', side_effect=lambda v, h, k, s: float(k == 0)):
            self.assertEqual(p.act(v), FAST)

    def test_swap_gate_skips_lead_rulebook_switch_and_incomplete_search(self):
        for case in ('off', 'lead', 'rulebook', 'fallback'):
            p, b, v = self.swap_position(enabled=case != 'off')
            p.q = None  # fix the fallback advice too; test the search gate, not the trained swap head
            if case == 'lead':
                b.turn = 0
            if case == 'fallback':
                p.samples = 0
            with patch.object(p, '_look', side_effect=lambda v, h, k, s: float(k == 1)), \
                    patch.object(Planner, '_swap_choice', return_value=1):
                if case == 'rulebook':
                    with patch.object(Planner, '_pick_switch', return_value=SWITCH[1]):
                        action = p.act(v)
                else:
                    action = p.act(v)
            self.assertEqual(action, SWITCH[1])
            self.assertEqual(p.swap_after_throws, 0)

    def test_swap_throw_worthwhile_depends_on_shields_damage_and_energy(self):
        _, b, v = self.position()
        self.assertIsNone(before_swap(v))  # both hits fail to threaten KO through a shield
        v.foe.hp = 80
        self.assertEqual(before_swap(v), CHARGED[1])
        v.foe.hp, b.sides[1].shields = 191, 0
        self.assertEqual(before_swap(v), CHARGED[1])
        v.me.mon.energy = 0
        self.assertIsNone(before_swap(v))
        v.me.mon.energy, v.foe.hp = 100, 1
        self.assertIsNone(before_swap(v))

    def test_people_factory_preserves_exam_draws_and_clones_shield_rng(self):
        from pogo.engine import human_settings
        from scripts.lab import creator_exam
        rng = random.Random(71)
        settings = human_settings(rng, self.pool)
        old = PeopleLike(rng, q=ev._state['net'], margin=rng.choice((.02, .05)), **settings)
        new = people_player(random.Random(71), ev._state['net'], self.pool)
        self.assertIs(creator_exam.PeopleLike, PeopleLike)
        self.assertEqual(old.rng.getstate(), new.rng.getstate())
        self.assertEqual(old._draw.getstate(), new._draw.getstate())
        self.assertEqual(old.margin, new.margin)
        twin = new.clone()
        self.assertIsNot(new._draw, twin._draw)
        _, _, view = self.position()
        self.assertEqual([new.shield(view, 100) for _ in range(50)],
                         [twin.shield(view, 100) for _ in range(50)])

    def test_people_field_is_paired_and_available_inside_search(self):
        recorded = []
        def factory(*args):
            p = people_player(*args)
            recorded.append((p.rng.getstate(), p._draw.getstate()))
            return p
        with patch('pogo.lab.people.people_player', side_effect=factory):
            first = ev._job(('people', 'bot', 'bot', 'bot', 0, 2, 54))
            second = ev._job(('people', 'off', 'bot,' + OFF, 'bot', 0, 2, 54))
        self.assertEqual(recorded[:2], recorded[2:])
        self.assertEqual(first[2], second[2])
        p = ev.pilot(ev.parse('website,opponents=people'), 1)
        self.assertIsInstance(p._imagined_opponent(random.Random(4)), PeopleLike)
        modelled = ev.pilot(ev.parse('website,opponents=people,opp_q=runs/general-decide/q.npz'), 1)
        self.assertIsInstance(modelled._imagined_opponent(random.Random(4)), PeopleLike)

    def test_spec_keys_validation_and_bot_policy_passthrough(self):
        for base in ('website', 'bot', 'bot,margin=.02'):
            p = ev.pilot(ev.parse(base + ',finish_safe=1,bait_mix=.4,shield_two=.05,shield_one=0'), 1)
            self.assertTrue(p.finish_safe)
            self.assertEqual((p.bait_mix, p.shield_two, p.shield_one), (.4, .05, 0))
        for key in ('bait_mix', 'shield_two', 'shield_one'):
            for bad in ('nan', 'inf', '-.1'):
                with self.assertRaises(SystemExit):
                    ev.parse('website,' + key + '=' + bad)
                with self.assertRaises(ValueError):
                    Learner(**{key: float(bad)})
        for spec in ('bait_mix=1.1', 'finish_safe=2', 'swap_after_throw=false'):
            with self.assertRaises(SystemExit):
                ev.parse('website,' + spec)
        with self.assertRaises(SystemExit):
            ev.parse('bot,swap_after_throw=1')

    def test_keys_off_match_pre_mixed_game_digests(self):
        fixture = json.loads((ROOT / 'runs/lab-mixed/default-digests.json').read_text())
        for row in fixture['games']:
            with self.subTest(spec=row['spec'], seed=row['seed']):
                seed = row['seed']
                rng = random.Random(seed)
                a, b = rng.sample(self.pool, 3), rng.sample(self.pool, 3)
                player = ev.pilot(ev.parse(row['spec'] + ',' + OFF + ',swap_after_throw=0'), seed + 1)
                foe = ev.pilot(ev.parse('bot,' + OFF), seed + 2)
                battle = Battle(a, b, player, foe, seed=seed, record=True)
                winner = battle.run()
                payload = json.dumps([winner, battle.turn, battle.log, battle.hits],
                                     ensure_ascii=True, separators=(',', ':'))
                self.assertEqual(hashlib.sha256(payload.encode()).hexdigest(), row['sha256'])


if __name__ == '__main__':
    unittest.main()
