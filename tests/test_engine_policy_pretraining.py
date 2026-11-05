"""Full-engine demonstration provenance and actor-only exact resumption."""
import contextlib
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from pogo.rl_experiment import atomic_json, team_split
from pogo.standalone_rl import N_FEATURES
from pogo.standalone_rl_v2 import ActorCritic
from scripts import pretrain_engine_policy as bc
from scripts.standalone_rl import save_batch, source_hashes


class EnginePolicyPretraining(unittest.TestCase):
    def data(self):
        rng = np.random.default_rng(42)
        x = rng.normal(size=(24, N_FEATURES)).astype(np.float32)
        mask = np.tile([True, True, False, False, False, False], (24, 1))
        return {"act": {"x": x, "mask": mask, "actions": np.ones(24, dtype=np.int64)}}

    def source(self, root):
        folder = root / "teacher"
        folder.mkdir()
        atomic_json(folder / "experiment.json", {"sources": source_hashes(), "commit": "frozen-fixture"})
        team = next([str(i), "fixture-b", "fixture-c"] for i in range(100)
                    if team_split([str(i), "fixture-b", "fixture-c"]) == "train")
        games = [{"teams": [team, team], "kind": "engine", "samples": 32,
                  "public_teacher_decisions": 24}]
        atomic_json(folder / "training_games_00001.json", games)
        save_batch(folder / "demo_00001.npz", self.data())
        return folder, games

    def test_cross_entropy_improves_without_changing_other_heads_or_critic(self):
        model = ActorCritic(hidden=8)
        group = self.data()["act"]
        frozen = {k: v.copy() for k, v in model.params.items() if not k.startswith("act.")}
        before = bc.imitate(model, "act", **group, rate=.001)[0]
        for _ in range(10):
            after = bc.imitate(model, "act", **group, rate=.001)[0]
        self.assertLess(after, before)
        for k, value in frozen.items():
            np.testing.assert_array_equal(value, model.params[k])
            self.assertEqual(model.steps[k], 0)

    def test_data_audit_rejects_weak_teachers_nontraining_teams_and_wrong_row_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder, games = self.source(Path(tmp))
            groups, audit = bc.read_demonstrations(folder, 1, 1)
            self.assertEqual(audit["rows"], {"act": 24})
            self.assertEqual(len(groups["act"]["x"]), 24)
            for field, value, message in (("samples", 8, "32-sample"),
                                           ("public_teacher_decisions", 23, "rows")):
                altered = [{**games[0], field: value}]
                atomic_json(folder / "training_games_00001.json", altered)
                with self.assertRaisesRegex(ValueError, message):
                    bc.read_demonstrations(folder, 1, 1)
            wrong = next([str(i), "fixture-b", "fixture-c"] for i in range(100)
                         if team_split([str(i), "fixture-b", "fixture-c"]) == "test")
            atomic_json(folder / "training_games_00001.json", [{**games[0], "teams": [wrong, wrong]}])
            with self.assertRaisesRegex(ValueError, "training trios"):
                bc.read_demonstrations(folder, 1, 1)

    def test_split_and_continuous_epochs_are_bit_exact_and_source_mutation_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            root = Path(tmp)
            folder, games = self.source(root)
            start = root / "start.npz"
            ActorCritic(hidden=8).save(start)
            args = SimpleNamespace(demo_folder=folder, first_round=1, last_round=1,
                                   start=start, seed=411, batch_size=8, rate=3e-4,
                                   budget_deadline=time.time() + 60, epochs=2)
            bc.train(root / "continuous", args)
            args.epochs = 1
            bc.train(root / "split", args)
            args.epochs = 2
            bc.train(root / "split", args)
            a = ActorCritic.load(root / "continuous/round_00002.npz")[0]
            b = ActorCritic.load(root / "split/round_00002.npz")[0]
            for left, right in ((a.params, b.params), (a.m, b.m), (a.v, b.v)):
                for key in left:
                    np.testing.assert_array_equal(left[key], right[key])
            self.assertEqual(a.steps, b.steps)
            self.assertFalse((root / "split/lock.json").exists())
            self.assertFalse((root / "split/test_plan.json").exists())
            source = folder / "experiment.json"
            changed = json.loads(source.read_text())
            changed["note"] = "changed after registration"
            atomic_json(source, changed)
            with self.assertRaisesRegex(ValueError, "changed"):
                bc.train(root / "split", args)


if __name__ == "__main__":
    unittest.main()
