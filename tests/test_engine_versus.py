"""Comparison players must not inherit another player's cached matchup features."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import engine_versus

from pogo.agents import Masher
from pogo.battle import Battle
from pogo.evaluation import Evaluator


class EvaluatorIsolation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        engine_versus.setup()
        cls.pool = engine_versus._state["pool"]

    def test_other_players_and_prior_battles_cannot_change_features(self):
        first = Battle(self.pool[:3], self.pool[10:13], Masher(), Masher(), seed=1)
        second = Battle(self.pool[3:6], self.pool[10:13], Masher(), Masher(), seed=1)
        settings = engine_versus.parse("")
        a = engine_versus.pilot(settings, 1)
        b = engine_versus.pilot(settings, 2)
        expected = Evaluator().features(second.views[0])
        a.evaluator.features(first.views[0])
        self.assertEqual(b.evaluator.features(second.views[0]), expected)
        # A new battle on a reused worker also starts independently of both players.
        c = engine_versus.pilot(settings, 3)
        self.assertEqual(c.evaluator.features(second.views[0]), expected)


if __name__ == "__main__":
    unittest.main()
