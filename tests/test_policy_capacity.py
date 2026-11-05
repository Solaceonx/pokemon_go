"""Capacity expansion preserves functions but allows independently learned units."""
import tempfile
import unittest
from pathlib import Path

import numpy as np

from pogo.standalone_rl import N_FEATURES
from pogo.standalone_rl_v2 import ActorCritic
from scripts.pretrain_engine_policy import imitate
from scripts.widen_standalone_policy import transfer_check, widen


class PolicyCapacity(unittest.TestCase):
    def test_probabilities_values_and_original_weights_are_preserved(self):
        old = ActorCritic(hidden=8)
        before = {k: v.copy() for k, v in old.params.items()}
        grown = widen(old, factor=4, seed=71)
        errors = transfer_check(old, grown)
        self.assertTrue(all(v["changed_greedy_actions"] == 0 for v in errors.values()))
        for k, v in before.items():
            np.testing.assert_array_equal(v, old.params[k])
        self.assertEqual(grown.params["act.w1"].shape, (N_FEATURES, 32))
        self.assertTrue(all(s == 0 for s in grown.steps.values()))
        self.assertTrue(all(not np.any(v) for g in (grown.m, grown.v) for v in g.values()))

    def test_training_can_break_duplicate_unit_symmetry(self):
        grown = widen(ActorCritic(hidden=8), factor=4, seed=72, jitter=.02)
        x = np.random.default_rng(73).normal(size=(32, N_FEATURES)).astype(np.float32)
        mask = np.ones((32, 6), bool)
        actions = np.arange(32) % 6
        np.testing.assert_array_equal(grown.params["act.w1"][:, 0], grown.params["act.w1"][:, 1])
        for _ in range(3):
            imitate(grown, "act", x, mask, actions, 3e-4)
        self.assertFalse(np.array_equal(grown.params["act.w1"][:, 0], grown.params["act.w1"][:, 1]))
        self.assertTrue(np.isfinite(grown.params["act.w1"]).all())

    def test_expansion_and_checkpoint_reload_are_deterministic(self):
        model = ActorCritic(hidden=8)
        a, b = (widen(model, factor=2, seed=74) for _ in range(2))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "expanded.npz"
            a.save(path)
            c = ActorCritic.load(path)[0]
        for key in a.params:
            np.testing.assert_array_equal(a.params[key], b.params[key])
            np.testing.assert_array_equal(a.params[key], c.params[key])
        with self.assertRaises(ValueError):
            widen(model, factor=1)


if __name__ == "__main__":
    unittest.main()
