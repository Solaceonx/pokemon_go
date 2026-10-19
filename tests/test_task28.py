"""Task-28 team priors and the measurement interface."""
import json
import random
import sys
import tempfile
import unittest
from pathlib import Path

from pogo.agents import Masher
from pogo.battle import Battle
from pogo.engine import Engine, STYLES, imagine
from pogo.evaluation import Evaluator
from pogo.gamedata import GameData

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import engine_versus  # noqa: E402
import realtime_trial  # noqa: E402


class TeamPriors(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gd = GameData()
        cls.pool = cls.gd.meta(50)

    def test_explicit_weights_and_species_outside_pool_survive(self):
        lead, second, third = self.pool[:3]
        extra = next(b for b in self.gd.meta(100) if b.species_id not in {p.species_id for p in self.pool})
        listed = [dict(team=[lead.species_id, second.species_id, third.species_id], weight=0),
                  dict(team=[lead.species_id, extra.species_id, third.species_id], weight=0.001)]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "teams.json"
            path.write_text(json.dumps({"teams": listed}))
            engine = Engine(None, self.pool, unseen="teams", team_file=path)
        live = Battle(self.pool[3:6], self.pool[:3], Masher(), Masher(), seed=1)
        imagined = imagine(live.views[0], random.Random(1), self.pool, Masher(), Masher(),
                           teams=engine._teams, team_builds=engine._team_builds)
        self.assertEqual(engine._teams[0][0], 0)
        self.assertEqual(engine._teams[1][0], 0.001)
        self.assertEqual([m.build.species_id for m in imagined.sides[1].team],
                         [lead.species_id, extra.species_id, third.species_id])
        self.assertEqual([m.build.species_id for m in live.sides[1].team],
                         [lead.species_id, second.species_id, third.species_id])

    def test_no_positive_fitting_team_falls_back_to_pool(self):
        lead, second, third = self.pool[:3]
        live = Battle(self.pool[3:6], self.pool[:3], Masher(), Masher(), seed=1)
        teams = [(0, [lead.species_id, second.species_id, third.species_id]),
                 (1, [b.species_id for b in self.pool[3:6]])]
        imagined = imagine(live.views[0], random.Random(2), self.pool, Masher(), Masher(), teams=teams)
        self.assertEqual(len(imagined.sides[1].team), 3)
        self.assertEqual(imagined.sides[1].mon.build, lead)
        self.assertEqual(len({m.build.species_id for m in imagined.sides[1].team}), 3)

    def test_timing_parser_accepts_the_same_candidate(self):
        settings = realtime_trial.parse("opponents=mix,profile=1,unseen=teams,team_file=data/teams_v2.json")
        self.assertEqual(settings, engine_versus.parse(
            "opponents=mix,profile=1,unseen=teams,team_file=data/teams_v2.json"))
        self.assertEqual(settings["team_file"], "data/teams_v2.json")
        self.assertTrue(settings["profile"])

    def test_calibrated_file_routes_human_settings_into_rollouts(self):
        styles = {name: {**settings, "weight": float(name == "human")}
                  for name, settings in STYLES.items()}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "styles.json"
            path.write_text(json.dumps({"styles": styles, "human_settings": {"farm": True, "farm_cost": 0.7}}))
            engine = Engine(None, self.pool, opponents="mix", style_file=path)
        opponent = engine._imagined_opponent(random.Random(28))
        self.assertTrue(opponent.farm)
        self.assertEqual(opponent.farm_cost, 0.7)

    def test_explicit_missing_calibration_is_an_error(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(FileNotFoundError):
                Engine(None, self.pool, opponents="mix", style_file=Path(folder) / "missing.json")

    def test_measured_players_never_share_matchup_cache(self):
        saved = engine_versus._state.copy()
        try:
            engine_versus._state["evals"] = {"test-model": None}
            first = engine_versus.evaluator("test-model")
            second = engine_versus.evaluator("test-model")
            a = Battle(self.pool[:3], self.pool[3:6], Masher(), Masher(), seed=0).views[0]
            b = Battle(self.pool[6:9], self.pool[3:6], Masher(), Masher(), seed=0).views[0]
            first.features(a)
            self.assertEqual(second.features(b), Evaluator().features(b))
            self.assertIsNot(first._agent._outlooks, second._agent._outlooks)
        finally:
            engine_versus._state.clear()
            engine_versus._state.update(saved)


if __name__ == "__main__":
    unittest.main()
