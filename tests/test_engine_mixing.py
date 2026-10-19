"""Simultaneous choices use legal public information and replayable private dice."""
import random
import unittest
from unittest.mock import patch

from pogo.agents import Planner
from pogo.battle import Battle, CHARGED, FAST, SWITCH, damage
from pogo.engine import Engine, imagine
from pogo.evaluation import material
from pogo.gamedata import GameData
from pogo.learner import Learner
from pogo.realtime import RealTime


class Mixing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gd = GameData()
        cls.pool = cls.gd.meta(50)
        cls.team = [cls.gd.default(x) for x in ("melmetal", "altaria", "jellicent")]

    def position(self, **settings):
        player = Engine(material, self.pool, samples=1, horizon=1, seed=29, **settings)
        battle = Battle(self.team, self.team, player, Planner(seed=1), seed=2)
        for side in battle.sides:
            side.mon.energy = 100
        return player, battle, battle.views[0]

    def test_shield_columns_land_the_selected_move_once(self):
        player, original, view = self.position(mix_shield=True)
        player._foe_energy = 100
        self.assertEqual(player._mixed_actions("shield", view), list(CHARGED))
        player._foe_energy = min(m.energy for m in view.foe.build.charged)
        self.assertEqual(player._mixed_actions("shield", view), [])
        player._foe_energy = 100
        for action in CHARGED:
            battle = imagine(view, random.Random(1), self.pool, Planner(), Planner())
            move = battle.sides[1].mon.build.charged[action - CHARGED[0]]
            expected = damage(battle.sides[1].mon, move, battle.sides[0].mon)
            hp = battle.sides[0].mon.hp
            player._their_first = action
            player._land_their_throw(battle, random.Random(2), shielded=False)
            self.assertEqual(battle.sides[1].mon.energy, 100 - move.energy)
            self.assertEqual(battle.sides[0].mon.hp, hp - expected)
        self.assertEqual(original.sides[1].mon.energy, 100)

    def test_shield_game_can_require_a_mix_and_clones_replay_it(self):
        player, battle, view = self.position(mix_shield=True, heads=("shield",))
        player._foe_energy = 100
        table = [[1.0, 0.0], [0.0, 1.0]]

        def look(this, v, head, option, seed):
            return table[option][this._their_first - CHARGED[0]]

        twin = player.clone()
        with patch.object(Engine, "_look", look):
            choices = [player._decide("shield", view, (True, True), lambda: 0, 100) for _ in range(12)]
            replay = [twin._decide("shield", view, (True, True), lambda: 0, 100) for _ in range(12)]
        self.assertEqual(choices, replay)
        self.assertEqual(set(choices), {0, 1})
        self.assertIsNone(player._their_first)
        self.assertEqual(battle.sides[0].shields, 2)

    def test_switch_columns_use_imagined_slot_order_and_require_free_switches(self):
        player, battle, view = self.position(mix_switch=True)
        foe = battle.sides[1]
        foe.active, foe.shown = 2, [0, 2]
        foe.mon.energy = 0
        self.assertEqual(player._mixed_actions("simultaneous", view), [FAST, SWITCH[0], SWITCH[2]])
        foe.team[1].build = self.gd.default("umbreon")
        self.assertEqual(player._mixed_actions("simultaneous", view), [FAST, SWITCH[0], SWITCH[2]])
        foe.switch_wait = 1
        self.assertEqual(player._mixed_actions("simultaneous", view), [])
        foe.switch_wait, foe.busy = 0, 1
        self.assertEqual(player._mixed_actions("simultaneous", view), [])

    def test_staying_cannot_become_a_rollout_switch(self):
        player, battle, view = self.position(mix_switch=True)
        player._their_first = FAST
        player.evaluator = lambda v: v.me.active
        with patch.object(Planner, "act", return_value=SWITCH[1]):
            self.assertEqual(player._look(view, "simultaneous", FAST, 1), 0)
        self.assertEqual(battle.sides[0].active, 0)

    def test_switch_game_executes_its_exact_action_and_includes_ready_throws(self):
        for action in (FAST, CHARGED[0], SWITCH[1]):
            player, battle, view = self.position(mix_switch=True)
            with self.subTest(action=action), patch.object(player, "_mixed", return_value=action) as mixed:
                with patch.object(Learner, "_pick_move", return_value=CHARGED[0]):
                    self.assertEqual(player.act(view), action)
                    self.assertEqual(mixed.call_args.args[2], view.legal())
                    self.assertIn(CHARGED[0], mixed.call_args.args[2])
                    self.assertFalse(player._mix_fallback)
                    battle.sides[1].switch_wait = 1
                    self.assertEqual(player.act(view), CHARGED[0])
            self.assertEqual(battle.sides[0].mon.energy, 100)

    def test_switch_mixing_revisits_an_ongoing_matchup_without_a_learned_head(self):
        player, battle, view = self.position(mix_switch=True)
        player._judged = (view.me.active, view.foe.build.uid)
        view.me.mon.energy = view.foe.energy = 0
        self.assertIsNone(player.q)
        with patch.object(player, "_mixed", return_value=SWITCH[1]) as mixed:
            self.assertEqual(player.act(view), SWITCH[1])
            self.assertEqual(mixed.call_args.args[1], "simultaneous")
        self.assertEqual(battle.sides[0].active, 0)

    def test_switch_game_with_no_complete_round_uses_the_bot_and_records_fallback(self):
        player, battle, view = self.position(mix_switch=True)
        player._deadline = -1
        with patch.object(Learner, "act", return_value=CHARGED[0]):
            self.assertEqual(player.act(view), CHARGED[0])
        self.assertEqual(player.looks, 1)
        self.assertEqual(player.fell_back, 1)
        self.assertFalse(player._mix_fallback)
        self.assertIsNone(player._their_first)
        self.assertEqual(battle.sides[0].mon.energy, 100)

    def test_hold_draws_stay_inside_the_existing_timing_window(self):
        player, battle, view = self.position(random_hold=True)
        view.me.mon.energy = 50
        view.foe.energy = 0
        player.hold_cost = 10
        latest = Planner._hold_plan(Planner(hold_cost=10), view)
        self.assertGreater(latest, 0)
        twin = player.clone()
        draws = [player._hold_plan(view) for _ in range(20)]
        self.assertEqual(draws, [twin._hold_plan(view) for _ in range(20)])
        self.assertGreater(len(set(draws)), 1)
        self.assertTrue(all(0 <= j <= latest for j in draws))
        self.assertTrue(all((j * view.me.mon.build.fast.turns) % view.foe.build.fast.turns
                            == (latest * view.me.mon.build.fast.turns) % view.foe.build.fast.turns for j in draws))
        view.foe.energy = 100
        self.assertIsNone(player._hold_plan(view))

    def test_real_shield_prompt_has_a_deadline_and_records_fallback(self):
        rt = RealTime(material, self.pool, heads=("shield",), mix_shield=True,
                      samples=1, seed=1, after_charged_ms=-1)
        battle = Battle(self.team, self.team, rt, Planner(), seed=1)
        battle.sides[1].mon.energy = 100
        rt.shield(battle.views[0], 100)
        self.assertEqual(rt.rows[0][0], "incoming charged move")
        self.assertTrue(rt.rows[0][6])
        self.assertIsNone(rt._deadline)


if __name__ == "__main__":
    unittest.main()
