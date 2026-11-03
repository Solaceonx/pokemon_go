"""The follow-up must really use greedy learned opponent continuations."""
import contextlib
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pogo.rl_experiment import atomic_json, schedule
from pogo.standalone_rl import StandaloneAgent
from pogo.standalone_rl_v2 import ActorCritic
from scripts import evaluate_greedy_rollouts_rl as driver


class GreedyRolloutDriver(unittest.TestCase):
    @contextlib.contextmanager
    def fixture(self):
        parent, base = driver.parent, driver.parent.base
        with tempfile.TemporaryDirectory() as tmp, contextlib.ExitStack() as stack:
            folder = Path(tmp) / "run"
            model = Path(tmp) / "model.npz"
            ActorCritic(seed=851, hidden=8).save(model)
            args = SimpleNamespace(ref="59836c86f4c9ccf7e8d35ef7c94268e64c1a4ba9", start=model,
                                   opponent_policy=model, seed=852, network="independent", hidden=8,
                                   budget_deadline=time.time()+120, validation_pairings=2,
                                   samples=1, confidence=1.)
            stack.enter_context(patch.multiple(parent, **{k: getattr(parent, k)
                for k in ("sources", "prepare", "initialize", "_context")}))
            stack.enter_context(patch.multiple(base, **{k: getattr(base, k)
                for k in ("source_hashes", "initialize", "evaluate_job", "_runtime", "_deadline_unix", "_model_cache")}))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            driver.configure(folder)
            config, runtime = driver.prepare(folder, args)
            yield folder, args, config, runtime

    def test_registration_and_reload_bind_greedy_mode_and_nine_sources(self):
        with self.fixture() as (folder, args, config, _):
            self.assertFalse(config["planning"]["stochastic_opponent"])
            self.assertEqual(len(config["sources"]), 9)
            again, _ = driver.prepare(folder, args)
            self.assertEqual(again, config)

    def test_stochastic_setting_cannot_resume_under_greedy_entry_point(self):
        with self.fixture() as (folder, args, config, _):
            config["planning"]["stochastic_opponent"] = True
            atomic_json(folder / "experiment.json", config)
            with self.assertRaisesRegex(ValueError, "separate run"):
                driver.prepare(folder, args)

    def test_real_pair_worker_uses_only_greedy_neural_continuations(self):
        with self.fixture() as (folder, _, config, runtime):
            driver.initialize(str(driver.ROOT / config["snapshot"]), time.time()+60,
                              config_path=str(folder / "experiment.json"))
            observed = []
            class Probe(StandaloneAgent):
                def __init__(self, *args, **kwargs):
                    super().__init__(*args, **kwargs)
                    observed.append(self.greedy)
            case = schedule(runtime, "train", "mixed", 853, 1)[0]
            with patch("pogo.planning_rl.StandaloneAgent", Probe):
                row = driver.parent.play_job((str(folder / "initial.npz"), case, True, "engine", 1))
            self.assertTrue(observed)
            self.assertTrue(all(observed))
            self.assertEqual(len(row["scores"]), 2)
            self.assertTrue(all(x["searches"] > 0 for x in row["planning_diagnostics"]))


if __name__ == "__main__":
    unittest.main()
