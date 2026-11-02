"""Expert corrections must describe the student's public trajectory, not control it."""
import random
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from pogo.rl_experiment import FrozenRuntime, freeze
from pogo.standalone_rl import encode
from pogo.standalone_rl_v2 import ActorCritic
from pogo.student_correction import CorrectedStudent
from scripts import student_correction_rl as driver


class StudentCorrections(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rt = FrozenRuntime(freeze("59836c86f4c9ccf7e8d35ef7c94268e64c1a4ba9"))

    def teams(self):
        return [self.rt.draw(random.Random(seed), "train") for seed in (971, 972)]

    @staticmethod
    def state(b):
        return (b.winner, b.turn, [(s.active, s.shields, s.switch_wait,
                [(m.hp, m.energy, m.atk_stage, m.def_stage) for m in s.team]) for s in b.sides])

    def test_expert_control_reproduces_frozen_engine_on_both_seats(self):
        rt, teams = self.rt, self.teams()
        for seat in (0, 1):
            log, demo = [], []
            student = CorrectedStudent(ActorCritic(hidden=8), rt.engine(11, 1),
                                        seed=12, log=log, demonstrations=demo, expert_control=True)
            a, b = rt.engine(11, 1), rt.engine(13, 1)
            original = rt.Battle(*teams, *((a, b) if seat == 0 else (b, a)), seed=14)
            foe = rt.engine(13, 1)
            replay = rt.Battle(*teams, *((student, foe) if seat == 0 else (foe, student)), seed=14)
            original.run()
            replay.run()
            self.assertEqual(self.state(original), self.state(replay))
            self.assertEqual(original.rng.getstate(), replay.rng.getstate())
            self.assertTrue(demo)
            self.assertFalse(log)  # No off-policy PPO rows under expert control.

    def test_rejected_advice_is_logged_but_unexecuted_plan_is_rolled_back(self):
        rt = self.rt
        model = ActorCritic(hidden=8)
        model.params["act.out_b"][0] = 100.
        class Expert:
            _judged, _hold, _fasted = None, 0, None
            def act(self, view):
                self._judged, self._hold = ("unexecuted",), 7
                return 3 + view.me.bench()[0]
        expert, demo, log = Expert(), [], []
        student = CorrectedStudent(model, expert, log=log, demonstrations=demo)
        battle = rt.Battle(*self.teams(), student, rt.engine(13, 1), seed=14)
        view = battle.views[0]
        before = encode(view)
        self.assertEqual(student.act(view), 0)
        self.assertIsNone(expert._judged)
        self.assertEqual(expert._hold, 0)
        self.assertEqual(expert._fasted, (view.me.active, view.foe.build.uid))
        self.assertEqual(demo[0][3], 3 + view.me.bench()[0])
        self.assertEqual(log[0][3], 0)
        np.testing.assert_array_equal(before, demo[0][1])

    def test_collector_keeps_actual_student_returns_and_both_expert_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = Path(tmp) / "model.npz"
            ActorCritic(hidden=8).save(checkpoint)
            with patch.object(driver.base, "_runtime", self.rt), \
                 patch.object(driver.base, "_model_cache", {}), \
                 patch.object(driver.base, "_deadline_unix", time.time() + 60):
                rows, games, demos = driver.collect_job(("ppo", str(checkpoint), 973, 0, 1, 1, 1))
        self.assertTrue(rows)
        self.assertGreater(games[0]["student_state_expert_decisions"], 0)
        self.assertGreater(games[0]["opponent_expert_decisions"], 0)
        self.assertEqual(len(demos), games[0]["public_teacher_decisions"])
        reward = 2 * games[0]["score"] - 1
        np.testing.assert_allclose([r[7] for r in rows], reward, atol=1e-6)
        self.assertTrue(all(row[2][row[3]] for row in demos))

    def test_expert_replay_window_is_bounded_and_ordered(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            for i in range(10):
                driver.base.save_batch(folder / f"demo_{i:05d}.npz", {"act": {
                    "x": np.full((1, 366), i, np.float32), "mask": np.ones((1, 6), bool),
                    "actions": np.zeros(1, np.int64)}})
            with patch.object(driver, "_folder", folder), patch.object(driver, "_fit", return_value=iter([])) as fit:
                driver.fit(ActorCritic(hidden=8), {}, 1, demos={"act": {}}, imitation=False)
            values = fit.call_args.kwargs["demos"]["act"]["x"][:, 0]
            np.testing.assert_array_equal(values, np.arange(2, 10))


if __name__ == "__main__":
    unittest.main()
