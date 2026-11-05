"""Policy/critic isolation and exact continuation in the second RL prototype."""
import contextlib
import io
import json
import random
import tempfile
import unittest
from pathlib import Path

import numpy as np

from pogo.standalone_rl import ActorCritic as SharedModel, HEADS, N_FEATURES
from pogo.standalone_rl import StandaloneAgent
from pogo.standalone_rl_v2 import ActorCritic
from pogo.rl_experiment import FrozenRuntime, canonical_json_digest, digest, freeze
from scripts.standalone_rl import TeacherRecorder, lock, restore_snapshot, train


class IndependentActorCritic(unittest.TestCase):
    def data(self, head="act"):
        rng = np.random.default_rng(3)
        x = rng.normal(size=(8, N_FEATURES)).astype(np.float32)
        return x, np.ones((8, HEADS[head]), dtype=bool), np.zeros(8, dtype=int), np.ones(8, np.float32)

    def test_learning_one_head_does_not_change_any_other_policy(self):
        model = ActorCritic(hidden=16)
        x, mask, actions, returns = self.data()
        old = {k: p.copy() for k, p in model.params.items() if k.startswith(("shield.", "replace."))}
        for _ in range(3):
            model.update("act", x, mask, actions, returns, imitation=True)
        for k, expected in old.items():
            np.testing.assert_array_equal(expected, model.params[k])
            self.assertEqual(model.steps[k], 0)

    def test_critic_only_error_cannot_change_policy(self):
        model = ActorCritic(hidden=16)
        x, mask, actions, returns = self.data()
        p, _, _ = model.forward(x, "act", mask)
        old = {k: v.copy() for k, v in model.params.items() if k.startswith("act.")}
        model.update("act", x, mask, actions, returns, advantages=np.zeros(8), old_logp=np.log(p[:, 0]), entropy=0.)
        for k, expected in old.items():
            np.testing.assert_array_equal(expected, model.params[k])

    def test_legacy_migration_preserves_every_policy_and_value(self):
        old = SharedModel(hidden=16)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "old.npz"
            old.save(path)
            model, meta = ActorCritic.load(path)
        self.assertTrue(meta["optimizer_reset_for_migration"])
        for head in HEADS:
            x, mask, _, _ = self.data(head)
            a, av, _ = old.forward(x, head, mask)
            b, bv, _ = model.forward(x, head, mask)
            np.testing.assert_array_equal(a, b)
            np.testing.assert_array_equal(av, bv)

    def test_resume_preserves_per_parameter_adam_clocks(self):
        model = ActorCritic(hidden=16)
        x, mask, actions, returns = self.data()
        model.update("act", x, mask, actions, returns, imitation=True)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "model.npz"
            model.save(path)
            restored, _ = ActorCritic.load(path)
        self.assertEqual(model.steps, restored.steps)
        model.update("act", x, mask, actions, returns, imitation=True)
        restored.update("act", x, mask, actions, returns, imitation=True)
        for k in model.params:
            np.testing.assert_array_equal(model.params[k], restored.params[k])

    def test_public_demonstration_gradient_can_teach_without_policy_advantage(self):
        model = ActorCritic(hidden=16)
        x, mask, actions, returns = self.data()
        p, value, _ = model.forward(x, "act", mask)
        model.update("act", x, mask, actions, value, advantages=np.zeros(8),
                     old_logp=np.log(p[:, 0]), entropy=0., demo_x=x, demo_mask=mask,
                     demo_actions=np.full(8, 3), demo_weight=.2)
        after = model.forward(x, "act", mask)[0]
        self.assertGreater(float(after[:, 3].mean()), float(p[:, 3].mean()))

    def test_generic_loader_accepts_independent_checkpoint(self):
        model = ActorCritic(hidden=16)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "model.npz"
            model.save(path)
            restored, _ = SharedModel.load(path)
        self.assertIsInstance(restored, ActorCritic)
        x, mask, _, _ = self.data()
        np.testing.assert_array_equal(model.forward(x, "act", mask)[0], restored.forward(x, "act", mask)[0])

    def test_lock_preserves_selected_greedy_mode_and_blocks_further_training(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            model = ActorCritic(hidden=16)
            model.save(root / "best.npz", {"state": {"best_greedy": True}})
            (root / "experiment.json").write_text("{}")
            with contextlib.redirect_stdout(io.StringIO()):
                lock(root, {"commit": "frozen"})
            record = json.loads((root / "lock.json").read_text())
            self.assertTrue(record["greedy"])
            with self.assertRaisesRegex(ValueError, "locked"):
                train(root, {}, None)


class PublicEngineDemonstrations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = freeze("59836c86f4c9ccf7e8d35ef7c94268e64c1a4ba9")
        cls.runtime = FrozenRuntime(cls.path)

    def test_recording_public_actions_does_not_change_frozen_engine_play(self):
        rt, model = self.runtime, ActorCritic(hidden=16)
        rng = random.Random(42)
        teams = [rt.draw(rng, "train") for _ in range(2)]
        original, wrapped = rt.engine(7, 1), rt.engine(7, 1)
        log = []
        a = rt.Battle(*teams, original, StandaloneAgent(model, 3), seed=9)
        b = rt.Battle(*teams, TeacherRecorder(wrapped, log), StandaloneAgent(model, 3), seed=9)
        self.assertEqual(a.run(), b.run())
        self.assertEqual(a.turn, b.turn)
        self.assertEqual(original.looks, wrapped.looks)
        self.assertGreater(len(log), 0)
        for left, right in zip(a.sides, b.sides):
            self.assertEqual([(m.hp, m.energy) for m in left.team], [(m.hp, m.energy) for m in right.team])
        for head, x, mask, action, *_ in log:
            self.assertTrue(mask[action])
            self.assertEqual(len(x), N_FEATURES)

    def test_missing_frozen_cache_is_rebuilt_from_the_recorded_commit(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / self.runtime.manifest["commit"]
            config = {"snapshot": str(target), "commit": self.runtime.manifest["commit"],
                      "frozen_manifest_sha256": digest(self.path / "manifest.json"),
                      "frozen_manifest_canonical_sha256": canonical_json_digest(self.runtime.manifest)}
            rebuilt = restore_snapshot(config)
            self.assertEqual(rebuilt.manifest, self.runtime.manifest)
            self.assertEqual(rebuilt.modules["gamedata"].DATA, target / "data")


if __name__ == "__main__":
    unittest.main()
