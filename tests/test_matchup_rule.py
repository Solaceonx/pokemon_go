"""The matchup table guides swaps and replacements, with an off switch for comparisons."""
import random
import unittest
from unittest.mock import patch

from pogo.agents import Planner, varied_settings
from pogo.battle import SWITCH, Battle
from pogo.gamedata import GameData


class GoodMatchup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gd = GameData()

    def battle(self, mine, foe):
        return Battle([self.gd.default(s) for s in mine], [self.gd.default(foe)],
                      Planner(seed=0), Planner(seed=0))

    def test_table_steers_a_switch_to_a_winning_matchup(self):
        battle = self.battle(["corviknight", "carbink", "malamar_shadow"], "ninetales")
        view = battle.views[0]
        plain = Planner(good_matchup=False, sac=False, seed=0)
        rule = Planner(good_matchup=True, sac=False, seed=0)
        self.assertIsNone(plain._pick_switch(view))
        self.assertEqual(rule._pick_switch(view), SWITCH[1])
        self.assertGreater(plain._outlook(view, 1), 0)  # the live position also wins
        view.me.switch_wait = 1
        self.assertIsNone(Planner(good_matchup=True, sac=False)._pick_switch(view))

    def test_table_can_change_a_replacement(self):
        battle = self.battle(["empoleon_shadow", "quagsire", "mandibuzz"], "electrode_hisuian")
        view = battle.views[0]
        view.me.mon.hp = 0
        self.assertEqual(Planner(good_matchup=False, sac=False).replace(view), 1)
        self.assertEqual(Planner(good_matchup=True, sac=False).replace(view), 2)
        view.me.team[2].hp = 0
        self.assertEqual(Planner(good_matchup=True, sac=False).replace(view), 1)

    def test_off_and_zero_weight_never_load_the_table(self):
        view = self.battle(["corviknight", "carbink", "malamar_shadow"], "ninetales").views[0]
        with patch("pogo.agents._matchup_table", side_effect=AssertionError("table loaded")):
            plain = Planner(good_matchup=False, sac=False, seed=7)
            self.assertFalse(plain.good_matchup)
            expected = plain.act(view)
            for options in ({"good_matchup": False}, {"good_matchup": True, "matchup_weight": 0}):
                self.assertEqual(Planner(sac=False, seed=7, **options).act(view), expected)

    def test_missing_pairs_and_fainted_foes_use_live_position(self):
        view = self.battle(["corviknight", "carbink"], "ninetales").views[0]
        plain, rule = Planner(good_matchup=False), Planner(good_matchup=True)
        with patch("pogo.agents._matchup_table", return_value={"carbink": {}}):
            for slot in (0, 1):
                self.assertEqual(rule._outlook(view, slot), plain._outlook(view, slot))
        view.foe.hp = 0  # simultaneous faints: no matchup to steer toward yet
        with patch("pogo.agents._matchup_table", side_effect=AssertionError("table loaded")):
            self.assertEqual(rule._outlook(view, 1), plain._outlook(view, 1))

    def test_live_health_energy_and_shields_still_matter(self):
        view = self.battle(["corviknight", "carbink"], "ninetales").views[0]
        rule = Planner(good_matchup=True)
        fresh = rule._outlook(view, 1)
        view.me.team[1].hp = 1
        self.assertLess(rule._outlook(view, 1), fresh)
        hurt = rule._outlook(view, 1)
        view.me.team[1].energy = 100
        view.foe.hp = 1
        view.foe.energy = 0
        view._foe.shields = 0
        self.assertGreater(rule._outlook(view, 1), hurt)

    def test_weight_range_and_clone(self):
        for weight in (-0.1, 1.1, float("nan")):
            with self.assertRaises(ValueError):
                Planner(matchup_weight=weight)
        rule = Planner(good_matchup=True, matchup_weight=0.25, seed=8)
        twin = rule.clone()
        self.assertTrue(twin.good_matchup)
        self.assertEqual(twin.matchup_weight, 0.25)
        self.assertEqual(twin.rng.getstate(), rule.rng.getstate())

    def test_confirmed_setting_is_default_and_usual_in_the_crowd(self):
        self.assertTrue(Planner().good_matchup)
        self.assertEqual(Planner().matchup_weight, 0.75)
        rng = random.Random(18)
        enabled = sum(varied_settings(rng)["good_matchup"] for _ in range(1000))
        self.assertGreater(enabled, 750)
        self.assertLess(enabled, 850)


if __name__ == "__main__":
    unittest.main()
