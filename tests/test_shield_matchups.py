"""Remaining-matchup shield decisions use visible state without changing the live battle.

The good-matchup rule is off throughout, so the shield rule is tested on its own.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pogo.agents import Masher, Planner
from pogo.battle import Battle, Mon
from pogo.gamedata import GameData

GD = GameData()


class ShieldMatchups(unittest.TestCase):
    def test_remaining_teammate_decides_whether_to_save_the_shield(self):
        # The active pair and incoming threat are identical. With Altaria in back,
        # keep the shield for the remaining matchups; with Melmetal, spend it here.
        for backup, expected in (("altaria", False), ("melmetal", True)):
            with self.subTest(backup=backup):
                battle = Battle(
                    [Mon(GD.default("ninetales_shadow"), hp=26, energy=85),
                     GD.default(backup), GD.default("feraligatr")],
                    [Mon(GD.default("ninetales"), hp=85, energy=100),
                     GD.default("clodsire"), GD.default("hydreigon_shadow")],
                    Masher(), Masher(), shields=(1, 1), switch_wait=(60, 60))
                battle.sides[1].shown = [0, 1, 2]
                view = battle.views[0]
                self.assertTrue(Planner(good_matchup=False, seed=0).shield(view, 100))
                self.assertEqual(Planner(good_matchup=False, shield_matchups=True, seed=0).shield(view, 100), expected)

    def position(self):
        return Battle(
            [Mon(GD.default("melmetal"), hp=25, energy=80), GD.default("altaria"), GD.default("jellicent")],
            [Mon(GD.default("azumarill"), energy=100), GD.default("medicham"), GD.default("venusaur")],
            Masher(), Masher(), shields=(1, 1), switch_wait=(60, 60))

    def values(self, planner, view):
        return [planner._after_hit(view, move, shielded, view.me.shields)
                for move in view.foe.build.charged for shielded in (False, True)]

    def test_rollouts_do_not_mutate_live_state(self):
        battle = self.position()
        battle.sides[1].shown = [0, 1, 2]
        battle.sides[0].mon.atk_stage = -1
        battle.sides[1].mon.def_stage = 1

        def snapshot():
            return (battle.turn, battle.rng.getstate(),
                    [(s.active, s.shields, s.switch_wait, s.busy, tuple(s.shown),
                      [(m.build.uid, m.hp, m.energy, m.atk_stage, m.def_stage) for m in s.team])
                     for s in battle.sides])

        before = snapshot()
        planner = Planner(good_matchup=False, shield_matchups=True, seed=7)
        self.values(planner, battle.views[0])
        choice = planner.shield(battle.views[0], 100)
        self.assertEqual(snapshot(), before)
        self.assertEqual(planner.clone().shield(battle.views[0], 100), choice)

    def test_hidden_opponents_cannot_change_the_evaluation(self):
        battle = self.position()
        planner = Planner(good_matchup=False, shield_matchups=True, seed=7)
        before = self.values(planner, battle.views[0])
        battle.sides[1].team[1:] = [Mon(GD.default("registeel"), hp=1, energy=100),
                                   Mon(GD.default("torterra"), energy=80)]
        self.assertEqual(self.values(planner, battle.views[0]), before)

    def test_rule_is_off_by_default_and_inactive_above_health_limit(self):
        battle = self.position()
        view = battle.views[0]
        base = Planner(good_matchup=False, seed=7)
        self.assertFalse(base.shield_matchups)
        self.assertEqual(self.values(base, view), self.values(Planner(good_matchup=False, shield_matchups=False), view))
        enabled = Planner(good_matchup=False, shield_matchups=True, shield_matchup_hp=0.2, seed=7)
        view.me.mon.hp = int(0.2 * view.me.mon.build.hp) + 1
        self.assertEqual(self.values(enabled, view), self.values(base, view))
        # The option changes incoming shield evaluation only, even below the health limit.
        view.me.mon.hp = 10
        for shielded in (False, True):
            self.assertEqual(enabled._after_throw(view, 0, shielded), base._after_throw(view, 0, shielded))

    def test_explicit_shield_styles_and_last_pokemon_keep_their_rules(self):
        battle = self.position()
        view = battle.views[0]
        for style, expected in (("always", True), ("never", False)):
            self.assertEqual(Planner(good_matchup=False, shields=style, shield_matchups=True).shield(view, 100), expected)
        for mon in view.me.team[1:]:
            mon.hp = 0
        self.assertTrue(Planner(good_matchup=False, shield_matchups=True).shield(view, 100))


if __name__ == "__main__":
    unittest.main()
