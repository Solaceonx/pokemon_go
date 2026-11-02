"""Counterfactual collection, mixed behavior and checkpoint resumption."""
import contextlib
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from pogo.counterfactual_rl import CounterfactualModel, capture, branch
from pogo.rl_experiment import FrozenRuntime, freeze
from scripts import counterfactual_rl as driver


class InlinePool:
    """No additional battle workers during unit checks of the controller."""
    def __init__(self, *args, initializer, initargs):
        initializer(*initargs)
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def imap(self, function, tasks):
        return map(function, tasks)


class CounterfactualController(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = freeze("59836c86f4c9ccf7e8d35ef7c94268e64c1a4ba9")
        cls.runtime = FrozenRuntime(cls.snapshot)

    def args(self, name, rounds):
        return SimpleNamespace(run=name, ref="59836c86f4c9ccf7e8d35ef7c94268e64c1a4ba9", seed=37001,
                               network="independent", start=None, hidden=16, validation_pairings=2,
                               budget_deadline=time.time() + 3600, hours=.1, test_reserve_hours=0,
                               workers=1, batch_games=1, max_rounds=rounds, train_samples=1, playouts=1,
                               replay_rounds=2, action_epochs=1, ppo_epochs=1, rate=3e-4,
                               demo_weight=.05, validation_every=1)

    def test_collector_uses_public_features_and_no_greedy_act_policy_gradient_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "model.npz"
            CounterfactualModel(hidden=16).save(path)
            driver.experiment.initialize(str(self.snapshot))
            positions, auxiliary, demos, games = driver.collect_job((str(path), 37001, 0, 1, 1, 1, time.time() + 60))
        self.assertEqual(len(positions), 1)
        x, mask, returns = positions[0]
        self.assertEqual(x.shape, (366,))
        self.assertTrue(np.isfinite(returns[mask]).all())
        self.assertTrue(all(row[0] in ("shield", "replace") for row in auxiliary))
        self.assertTrue(all(row[0] in ("shield", "replace") for row in demos))
        self.assertEqual(games[0]["index"], 0)

    def test_collection_agent_is_greedy_only_on_act_and_capture_can_force_all_greedy(self):
        rt = self.runtime
        teams = [[rt.gd.default(s) for s in ("melmetal", "jellicent", "altaria")]] * 2
        agent = driver.CollectionAgent(CounterfactualModel(hidden=16), seed=2, greedy=False)
        battle = rt.Battle(*teams, agent, rt.engine(3, 1), seed=4)
        view = battle.views[0]
        choices = {agent.act(view) for _ in range(30)}
        self.assertEqual(len(choices), 1)
        self.assertFalse(agent.greedy)
        self.assertEqual({agent.shield(view, 100) for _ in range(100)}, {False, True})
        point = capture(battle, 0)
        replay = branch(point, next(iter(choices)), greedy_continuation=True)
        forced = replay.agents[0].inner
        self.assertTrue(forced.greedy)
        self.assertEqual(len({forced.shield(replay.views[0], 100) for _ in range(30)}), 1)

    def test_split_and_continuous_training_match_and_train_does_not_open_final_test(self):
        fake_context = SimpleNamespace(Pool=InlinePool)
        validation = lambda *args, **kwargs: ({"score": .25}, True)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with contextlib.redirect_stdout(io.StringIO()), \
                 patch.object(driver.mp, "get_context", return_value=fake_context), \
                 patch.object(driver.experiment, "validate_modes", side_effect=validation):
                continuous_args = self.args("continuous", 2)
                continuous = root / "continuous"
                cfg_a = driver.prepare(continuous, continuous_args)
                driver.train(continuous, cfg_a, continuous_args)
                split_args = self.args("split", 1)
                split = root / "split"
                cfg_b = driver.prepare(split, split_args)
                driver.train(split, cfg_b, split_args)
                split_args.max_rounds = 2
                driver.train(split, cfg_b, split_args)
            a = CounterfactualModel.load(continuous / "round_00002.npz")[0]
            b = CounterfactualModel.load(split / "round_00002.npz")[0]
            for key in a.params:
                np.testing.assert_array_equal(a.params[key], b.params[key])
            self.assertEqual(a.steps, b.steps)
            state = json.loads((split / "state.json").read_text())
            self.assertEqual((state["round"], state["training_games"]), (2, 2))
            self.assertFalse((split / "lock.json").exists())
            self.assertFalse((split / "test_plan.json").exists())


if __name__ == "__main__":
    unittest.main()
