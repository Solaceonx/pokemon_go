"""Slot averaging must preserve physical actions and public-state semantics."""
import copy
import json
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from pogo.rl_experiment import FrozenRuntime, freeze, schedule
from pogo.standalone_rl import encode, mask_for
from pogo.standalone_rl_v2 import ActorCritic
from pogo.slot_ensemble import (
    PERMUTATIONS, SlotEnsembleAgent, action_order, permute_features, probabilities,
)
from scripts import slot_ensemble_rl as driver


class SlotEnsemble(unittest.TestCase):
    def test_tensor_relabeling_matches_encoding_a_reordered_public_side(self):
        rt = FrozenRuntime(freeze("59836c86f4c9ccf7e8d35ef7c94268e64c1a4ba9"))
        teams = [rt.draw(random.Random(seed), "train") for seed in (971, 972)]
        battle = rt.Battle(*teams, None, None, seed=14)
        view = battle.views[0]
        class Proxy:
            def __init__(self, permutation):
                self.me = copy.copy(view.me)
                self.me.team = [view.me.team[j] for j in permutation]
                self.me.active = permutation.index(view.me.active)
                self.order = action_order("act", permutation)
            def __getattr__(self, key):
                return getattr(view, key)
            def legal(self):
                return [self.order.index(a) for a in view.legal()]
        for permutation in PERMUTATIONS:
            proxy = Proxy(permutation)
            np.testing.assert_array_equal(permute_features(encode(view)[None], permutation)[0], encode(proxy))
            for head in ("act", "shield", "replace"):
                order = action_order(head, permutation)
                np.testing.assert_array_equal(mask_for(proxy, head), mask_for(view, head)[list(order)])

    def test_ensemble_probabilities_are_equivariant_and_illegal_actions_are_zero(self):
        model = ActorCritic(seed=31, hidden=8)
        x = np.random.default_rng(32).normal(size=366).astype(np.float32)
        masks = {"act": [True, True, False, True, False, True],
                 "shield": [True, True], "replace": [False, True, True]}
        for head, mask in masks.items():
            mask = np.array(mask)
            expected = probabilities(model, x, head, mask)
            self.assertAlmostEqual(expected.sum(), 1.)
            self.assertTrue((expected[~mask] == 0).all())
            for permutation in PERMUTATIONS:
                order = action_order(head, permutation)
                actual = probabilities(model, permute_features(x[None], permutation)[0], head, mask[list(order)])
                physical = np.empty_like(actual)
                physical[list(order)] = actual
                np.testing.assert_allclose(physical, expected, atol=2e-7, rtol=2e-7)

    def test_forced_decisions_need_no_network_and_training_logs_are_rejected(self):
        agent = SlotEnsembleAgent(None)
        view = SimpleNamespace(legal=lambda: [0], me=SimpleNamespace(shields=0, bench=lambda: [2]))
        self.assertEqual(agent.act(view), 0)
        self.assertFalse(agent.shield(view, 50))
        self.assertEqual(agent.replace(view), 2)
        with self.assertRaisesRegex(ValueError, "inference-only"):
            SlotEnsembleAgent(None, log=[])

    def test_clone_keeps_independent_identical_rng(self):
        agent = SlotEnsembleAgent(ActorCritic(hidden=8), seed=33, greedy=False)
        twin = agent.clone()
        self.assertIsNot(agent.rng, twin.rng)
        np.testing.assert_array_equal(agent.rng.random(10), twin.rng.random(10))

    def test_deployment_loader_imports_no_engine_planner_learner_or_simulator(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "model.npz"
            ActorCritic(hidden=8).save(path)
            code = "from pogo.slot_ensemble import load_agent; import sys,json; load_agent(sys.argv[1]); print(json.dumps(sorted(set(sys.modules)&{'pogo.engine','pogo.agents','pogo.learner','pogo.battle'})))"
            result = subprocess.run([sys.executable, "-c", code, str(path)], capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(result.stdout), [])

    def test_actual_pairing_worker_uses_ensemble_in_both_seats(self):
        rt = FrozenRuntime(freeze("59836c86f4c9ccf7e8d35ef7c94268e64c1a4ba9"))
        case = schedule(rt, "train", "mixed", 441, 1)[0]
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            checkpoint = folder / "model.npz"
            ActorCritic(seed=36, hidden=8).save(checkpoint)
            names = ("source_hashes", "prepare", "StandaloneAgent", "initialize", "evaluate_job")
            with patch.multiple(driver.base, **{k: getattr(driver.base, k) for k in names}), \
                 patch.object(driver.base, "_runtime", rt), \
                 patch.object(driver.base, "_model_cache", {}), \
                 patch.object(driver.base, "_deadline_unix", None):
                driver.configure(folder)
                self.assertIs(driver.base.evaluate_job, driver.play_job)
                result = driver.base.evaluate_job((str(checkpoint), case, True, "engine", 1))
            self.assertEqual(len(result["scores"]), 2)
            self.assertTrue(all(n > 0 for n in result["ensemble_decisions"]))


if __name__ == "__main__":
    unittest.main()
