"""Comparison players share model weights but cannot contaminate one another's cached outlooks."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import engine_versus
from pogo.agents import Masher
from pogo.battle import Battle
from pogo.evaluation import Evaluator
from pogo.gamedata import GameData


class MeasurementIsolation(unittest.TestCase):
    def test_each_pilot_has_a_private_matchup_cache(self):
        gd = GameData()
        foe = [gd.default(s) for s in ("melmetal", "altaria", "jellicent")]
        teams = [[gd.default(s) for s in (lead, "umbreon", "jellicent")]
                 for lead in ("altaria", "stunfisk")]
        views = [Battle(team, foe, Masher(), Masher(), seed=0).views[0] for team in teams]
        loaded = Evaluator()
        with patch.object(engine_versus, "evaluator", return_value=loaded), \
                patch.dict(engine_versus._state, pool=gd.meta(50), net=None):
            players = [engine_versus.pilot(engine_versus.parse(""), seed) for seed in (1, 2)]
        a, b = (player.evaluator for player in players)
        self.assertIsNot(a, b)
        self.assertIs(a.model, loaded.model)
        self.assertIs(b.model, loaded.model)
        first = a.features(views[0])
        second = b.features(views[1])
        self.assertNotEqual(first[33], second[33])
        self.assertEqual(second, Evaluator().features(views[1]))
        self.assertFalse(loaded._agent._outlooks)


if __name__ == "__main__":
    unittest.main()
