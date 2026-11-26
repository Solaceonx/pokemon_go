import tempfile
import unittest
from pathlib import Path

import numpy as np

from pogo.agents import Planner
from pogo.battle import Battle, damage
from pogo.gamedata import GameData
from pogo.learner import Learner
from pogo.people_shield import FEATURES, PeopleShield, cached, describe, fit, view_features


class PeopleShieldTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gd = GameData()
        cls.team = [cls.gd.default(x) for x in ("melmetal", "altaria", "jellicent")]

    def test_describe(self):
        x = describe(50, 100, [(45, 60), (35, 20)], 2, 1, 3, 2)
        self.assertEqual(len(x), len(FEATURES))
        self.assertEqual(x, [0.5, 1.2, 0.4, 1.0, 0.0, 2.0, 1.0, 3.0, 2.0, 1.0])

    def test_view_features_match_the_battle(self):
        battle = Battle(self.team, self.team, Planner(seed=1), Planner(seed=2), seed=3)
        view = battle.views[0]
        x = view_features(view)
        hits = [damage(view.foe, m, view.me.mon) for m in view.foe.build.charged]
        self.assertAlmostEqual(x[1], min(3, max(hits) / view.me.mon.hp))
        self.assertEqual(x[5:9], [2.0, 2.0, 3.0, 3.0])

    def test_fit_learns_and_saves(self):
        rng = np.random.default_rng(0)
        x = rng.uniform(0, 2, (400, len(FEATURES)))
        y = (x[:, 1] > 1).astype(int)  # shield when the hardest hit takes more than all our health
        model = fit(x, y, steps=600, l2=0.1)
        self.assertGreater(((model.probabilities(x) > 0.5) == y).mean(), 0.95)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "shield.npz"
            model.save(path)
            again = PeopleShield.load(path)
            self.assertTrue(np.allclose(again.probabilities(x[:5]), model.probabilities(x[:5])))
            self.assertIs(cached(path), cached(path))

    def test_learner_uses_it_but_the_last_pokemon_stays_the_rulebooks(self):
        x = np.zeros((2, len(FEATURES)))
        never = PeopleShield(np.zeros(len(FEATURES)), np.ones(len(FEATURES)), np.zeros((len(FEATURES), 1)),
                             np.zeros(1), np.zeros(1), np.array(-5.0))  # always "no shield"
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "never.npz"
            never.save(path)
            player = Learner(people_shield=str(path), seed=1)
            battle = Battle(self.team, self.team, player, Planner(seed=2), seed=3)
            view = battle.views[0]
            self.assertFalse(never.probabilities(x)[0] > 0.5)
            self.assertFalse(player.shield(view, 100))
            for m in battle.sides[0].team[1:]:
                m.hp = 0
            self.assertTrue(player.shield(battle.views[0], 100))  # one left: the rulebook shields


class KnockOutSooner(unittest.TestCase):
    """Learner(ko_wait=True): the cheap move that leaves them alive is not thrown when the one that knocks out comes
    sooner and we cannot faint meanwhile."""

    def position(self, foe_hp_share: float, my_energy: int, foe_energy: int):
        gd = GameData()
        mine = [gd.build("snorlax", ["LICK", "BODY_SLAM", "EARTHQUAKE"])] + [gd.default(x) for x in ("altaria", "jellicent")]
        theirs = [gd.default(x) for x in ("thievul", "altaria", "jellicent")]
        player = Learner(ko_wait=True, seed=1)
        battle = Battle(mine, theirs, player, Planner(seed=2), seed=3, shields=(0, 0))
        us, them = battle.sides
        us.mon.energy, them.mon.energy = my_energy, foe_energy
        them.mon.hp = round(foe_hp_share * them.mon.build.hp)
        return player, battle.views[0]

    def test_waits_for_the_knock_out(self):
        from pogo.battle import CHARGED, FAST
        player, view = self.position(0.55, 60, 0)
        me, foe = view.me.mon, view.foe
        slam, quake = me.build.charged
        if not (damage(me, slam, foe) < foe.hp <= damage(me, quake, foe)):
            self.skipTest("the builds no longer give this position")
        self.assertIn(player._ko_sooner(view, 0), (FAST, CHARGED[1]))
        self.assertIsNone(player._ko_sooner(view, 1))  # the knock-out itself

    def test_throws_when_it_could_faint_while_waiting(self):
        player, view = self.position(0.55, 60, 100)
        view.me.mon.hp = 1
        self.assertIsNone(player._ko_sooner(view, 0))


if __name__ == "__main__":
    unittest.main()
