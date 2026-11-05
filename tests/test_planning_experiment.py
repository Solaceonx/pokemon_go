"""Rollout experiment provenance, seat pairing and frozen-physics compatibility."""
import contextlib
import io
import random
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from pogo.planning_rl import public_world
from pogo.rl_experiment import FrozenRuntime, freeze, schedule
from pogo.standalone_rl import StandaloneAgent
from pogo.standalone_rl_v2 import ActorCritic
from scripts import evaluate_planning_rl as driver


class PlanningExperiment(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = FrozenRuntime(freeze("59836c86f4c9ccf7e8d35ef7c94268e64c1a4ba9"))

    @staticmethod
    def state(b):
        return (b.winner, b.turn, [(s.active, s.busy, s.shields, s.switch_wait,
                [(m.build.species_id, m.hp, m.energy, m.atk_stage, m.def_stage) for m in s.team])
                for s in b.sides])

    def test_world_matches_frozen_rules_on_both_seats(self):
        rt = self.runtime
        teams = [rt.draw(random.Random(seed), "train") for seed in (33, 34)]
        model = ActorCritic(hidden=8)
        for seat in (0, 1):
            original = rt.Battle(*teams, StandaloneAgent(model, 1), StandaloneAgent(model, 2), seed=3)
            for _ in range(6):
                original.step()
            for side in original.sides:
                side.shown = [0, 1, 2]
            view = original.views[seat]
            players = [original.agents[i].clone() for i in (seat, 1-seat)]
            expected = rt.modules["engine"].imagine(view, random.Random(91), rt.pool, *players)
            actual = public_world(view, rt.pool, *(p.clone() for p in players), random.Random(91))
            actual.rng.setstate(expected.rng.getstate())
            self.assertEqual(self.state(actual), self.state(expected))
            actual.run()
            expected.run()
            self.assertEqual(self.state(actual), self.state(expected))
            self.assertEqual(actual.rng.getstate(), expected.rng.getstate())

    def test_zero_rollout_evaluator_reproduces_pure_policy_pair(self):
        rt, model = self.runtime, ActorCritic(hidden=8)
        case = schedule(rt, "validation", "mixed", 1234, 2)[0]
        expected = driver.base.play_case(rt, model, case, greedy=True, samples=1)
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = Path(tmp) / "model.npz"
            model.save(checkpoint)
            context = {"config": {"planning": {"samples": 0, "confidence": .98}}, "opponent_model": model}
            with patch.object(driver, "_context", context), patch.object(driver.base, "_runtime", rt), \
                 patch.object(driver.base, "_deadline_unix", time.time() + 60), \
                 patch.object(driver.base, "_model_cache", {}):
                actual = driver.play_job((str(checkpoint), case, True, "engine", 1))
        for key in ("index", "scores", "score", "winners"):
            self.assertEqual(actual[key], expected[key])
        self.assertTrue(all(g["searches"] == 0 for g in actual["planning_diagnostics"]))

    def test_protocol_hashes_both_models_and_rules_and_rejects_opponent_mutation(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            folder = Path(tmp)
            opponent = folder / "seed-opponent.npz"
            ActorCritic(hidden=8).save(opponent)
            args = SimpleNamespace(ref="59836c86f4c9ccf7e8d35ef7c94268e64c1a4ba9", start=None,
                                   opponent_policy=opponent, seed=1234, network="independent", hidden=8,
                                   validation_pairings=2, budget_deadline=time.time()+60, samples=1, confidence=.98)
            with patch.object(driver.base, "source_hashes", driver.sources):
                config, _ = driver.prepare(folder / "run", args)
                self.assertIn("pogo/battle.py", config["sources"])
                self.assertIn("pogo/planning_rl.py", config["sources"])
                self.assertEqual(config["validation_modes"], [True])
                with (folder / "run/opponent.npz").open("ab") as f:
                    f.write(b"tamper")
                with self.assertRaisesRegex(ValueError, "opponent changed"):
                    driver.prepare(folder / "run", args)


if __name__ == "__main__":
    unittest.main()
