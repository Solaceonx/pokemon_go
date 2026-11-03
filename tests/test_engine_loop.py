"""Task 39's loop (scripts/engine_loop.py): recording leaves the engine's play unchanged, the saved inputs give back
the trained bot's picks, the loss's gradient is right, games save and resume, and engine_versus reads a q= path."""
import random
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import engine_loop
import engine_versus

from pogo.battle import Battle
from pogo.engine import Engine
from pogo.evaluation import Evaluator
from pogo.gamedata import GameData
from pogo.learner import N_FEATURES, QNet

QUICK = {"rollout": "bot", "samples": 1, "edge": 0.03, "margin": 0.02, "horizon": 2}  # the website's engine, cut short


class Recording(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pool = GameData().meta(50)
        cls.q = QNet.load(engine_loop.START_Q)
        cls.model = Evaluator.load(engine_loop.START_EVAL).model

    def game(self, cls, seed):
        rng = random.Random(seed)
        teams = rng.sample(self.pool, 3), rng.sample(self.pool, 3)
        players = [cls(Evaluator(self.model), self.pool, q=self.q, seed=rng.getrandbits(32), **QUICK) for _ in range(2)]
        battle = Battle(*teams, *players, seed=rng.getrandbits(32), record=True)
        battle.run()
        return battle, players

    def test_recording_does_not_change_play(self):
        for seed in (1, 2):
            plain, _ = self.game(Engine, seed)
            recorded, players = self.game(engine_loop.Recorder, seed)
            self.assertEqual(recorded.log, plain.log)
            self.assertTrue(all(p.record for p in players))

    def test_saved_inputs_give_back_the_bots_picks(self):
        _, players = self.game(engine_loop.Recorder, 3)
        for player in players:
            self.assertEqual(sum(bot != pick for _, _, _, bot, pick in player.record), player.changed)
            for head in {row[0] for row in player.record}:
                rows = [row for row in player.record if row[0] == head]
                x = np.array([row[1] for row in rows])
                legal = np.array([list(row[2]) + [False] * (engine_loop.OPTIONS - len(row[2])) for row in rows])
                bot = np.array([row[3] for row in rows])
                pick = np.array([row[4] for row in rows])
                self.assertEqual(x.shape[1], N_FEATURES)
                self.assertTrue(legal[np.arange(len(pick)), pick].all())
                np.testing.assert_array_equal(engine_loop.bot_picks(self.q, head, x, legal), bot)


class Loss(unittest.TestCase):
    def data(self, head, n=24, seed=0):
        rng = np.random.default_rng(seed)
        x = rng.random((n, N_FEATURES))
        width = 3 if head in ("throw", "swap") else 2
        legal = np.zeros((n, engine_loop.OPTIONS), bool)
        legal[:, :width] = rng.random((n, width)) < 0.7
        legal[:, 0] = True
        pick = np.array([rng.choice(np.flatnonzero(row)) for row in legal])
        return x, legal, pick, rng.choice([0.0, 0.5, 1.0], n)

    def test_gradient_matches_finite_differences(self):
        for head in ("throw", "swap", "replace", "shield"):
            q = QNet(seed=1)
            q.params[head][2] *= 30  # outputs spread out, as in a trained network
            x, legal, pick, result = self.data(head)

            def total():
                value, choice, _, _ = engine_loop.loss(q, head, x, legal, pick, result)
                return value + engine_loop.CHOICE_WEIGHT * choice

            _, _, dz, h = engine_loop.loss(q, head, x, legal, pick, result)
            w1, _, w2, _ = q.params[head]
            analytic = {0: x.T @ ((dz @ w2.T) * (h > 0)), 2: h.T @ dz}
            for k, grad in analytic.items():
                for i, j in ((0, 0), (3, 1), (7, grad.shape[1] - 1)):
                    old = q.params[head][k][i, j]
                    q.params[head][k][i, j] = old + 1e-6
                    up = total()
                    q.params[head][k][i, j] = old - 1e-6
                    down = total()
                    q.params[head][k][i, j] = old
                    self.assertAlmostEqual((up - down) / 2e-6, grad[i, j], places=5, msg=f"{head} param {k} [{i}, {j}]")

    def test_refit_lowers_the_loss(self):
        q = QNet(seed=2)
        x, legal, pick, result = self.data("throw", n=300, seed=1)
        before = engine_loop.loss(q, "throw", x, legal, pick, result)
        engine_loop.refit(q, "throw", x, legal, pick, result, epochs=20)
        after = engine_loop.loss(q, "throw", x, legal, pick, result)
        self.assertLess(after[0] + 0.3 * after[1], before[0] + 0.3 * before[1])
        self.assertLess(after[1], 0.8 * before[1])


class SaveAndResume(unittest.TestCase):
    def test_games_save_fit_and_skip_when_done(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(engine_loop, "low_priority"):
            here = Path(tmp)
            games = here / "games"
            games.mkdir()
            task = (str(games), str(engine_loop.START_Q), str(engine_loop.START_EVAL), "standard", 7, 0, 2, 0.2, QUICK)
            info = engine_loop.chunk(task)
            self.assertEqual(info["games"], 2)
            data = engine_loop.load_games(games)
            self.assertEqual(list(data["games"]), [0, 1])
            self.assertEqual(len(data["x"]), info["decisions"])
            self.assertEqual(data["legal"].shape, (info["decisions"], engine_loop.OPTIONS))
            self.assertEqual(data["pos_x"].shape[1], 42)
            self.assertTrue(set(data["result"]) <= {0.0, 0.5, 1.0})
            self.assertEqual(int((data["bot"] != data["pick"]).sum()), info["changed"])
            # The same game again gives the same file: a resumed run plays exactly the games it skipped.
            pool, draw, q, model = engine_loop.world("standard", str(engine_loop.START_Q), str(engine_loop.START_EVAL))
            again = engine_loop.play(1, 7, q, model, pool, draw, 0.2, QUICK)
            self.assertEqual(len(again["decisions"]), int((data["game"] == 1).sum()))
            report = engine_loop.fit(here, data, engine_loop.START_Q, engine_loop.START_EVAL, seed=1)
            self.assertTrue((here / "q.npz").exists() and (here / "eval.npz").exists() and (here / "fit.json").exists())
            self.assertEqual(report["games"], 2)
            fitted = QNet.load(here / "q.npz")
            self.assertEqual({h: [p.shape for p in ps] for h, ps in fitted.params.items()},
                             {h: [p.shape for p in ps] for h, ps in QNet.load(engine_loop.START_Q).params.items()})
            for head, entry in report["q"].items():
                if entry["replayed"] is not None:
                    self.assertGreater(entry["replayed"], 0.99, head)

            class Args:
                field, chunk, sample, workers = "standard", 2, 0.2, 1
            Args.games = 2
            with patch.object(engine_loop, "SETTINGS", QUICK), patch("multiprocessing.get_context") as spawn:
                engine_loop.selfplay(here, engine_loop.START_Q, engine_loop.START_EVAL, 7, Args)
            spawn.assert_not_called()  # every part saved: nothing to play


class VersusNetworks(unittest.TestCase):
    def test_q_path_setting(self):
        engine_versus.setup()
        path = "runs/general-decide/q.npz"
        settings = engine_versus.parse(f"samples=2,q={path}")
        self.assertEqual(settings["q"], path)
        player = engine_versus.pilot(settings, 1)
        website = engine_versus._state["net"]
        self.assertIsNot(player.q, website)
        np.testing.assert_array_equal(player.q.params["throw"][0], website.params["throw"][0])
        self.assertIs(engine_versus.pilot(engine_versus.parse("samples=2,q=" + path), 2).q, player.q)  # loaded once
        self.assertIs(engine_versus.pilot(engine_versus.parse("samples=2"), 3).q, website)


if __name__ == "__main__":
    unittest.main()
