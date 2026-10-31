"""The engine-strength options (docs/tasks.md, 25 and 27-30): each takes effect, and the evolution helpers work."""
import random
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import evolve_rules  # noqa: E402
from pogo.agents import Planner  # noqa: E402
from pogo.battle import Battle  # noqa: E402
from pogo.engine import Engine  # noqa: E402
from pogo.evaluation import Evaluator  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.learner import Learner, QNet  # noqa: E402
from pogo.reader import Reader  # noqa: E402


class EngineOptions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gd = GameData()
        cls.pool = cls.gd.meta(50)
        cls.net = QNet.load(str(ROOT / "runs" / "general-decide" / "q.npz"))
        cls.ev = Evaluator.load(ROOT / "runs" / "eval" / "eval.npz")

    def engine(self, cls=Engine, **kw):
        return cls(self.ev, self.pool, rollout="bot", samples=2, horizon=8, edge=0.03, q=self.net, margin=0.02, seed=3, **kw)

    def play(self, a, b, games=3):
        for g in range(games):
            rng = random.Random(g)
            Battle(rng.sample(self.pool, 3), rng.sample(self.pool, 3), a, b, seed=g).run()

    def test_options_take_effect(self):
        e = self.engine(heads=("throw", "swap", "replace", "shield"), mix=True, opponents="mix", profile=True, unseen="teams")
        seen = []
        original = Engine._decide

        def counting(this, head, *args, **kwargs):
            if this is e and head in this.heads:
                seen.append(head)
            return original(this, head, *args, **kwargs)

        Engine._decide = counting
        try:
            self.play(e, Learner(q=self.net, margin=0.02, seed=9))
        finally:
            Engine._decide = original
        self.assertIn("shield", seen)
        self.assertGreater(e.mixed, 0)
        self.assertGreater(e._obs["shield"][1] + e._obs["bait"][1], 0)
        weights = e._style_weights()
        self.assertAlmostEqual(sum(weights.values()), 1.0, places=6)
        self.assertTrue(all(w > 0 for w in weights.values()))

    def test_judge_and_switch_settings(self):
        for judge in ("turn", "end"):
            e = self.engine(judge=judge)
            self.play(e, Learner(q=self.net, margin=0.02, seed=9), games=1)
            self.assertGreater(e.looks, 0)
        with self.assertRaises(ValueError):
            self.engine(judge="never")
        e = self.engine(stay_after_replace=True, switch_edge=0.1)
        for g in range(3):
            rng = random.Random(g)
            b = Battle(rng.sample(self.pool, 3), rng.sample(self.pool, 3), e, Learner(q=self.net, margin=0.02, seed=9),
                       seed=g, record=True)
            b.run()
            fainted = {t for t, side, text in b.log if side == 0 and text.endswith("faints")}
            sent = [t for t, side, text in b.log if side == 0 and text.startswith("sends in") and t in fainted]
            self.assertEqual(len(sent), len(set(sent)))  # no swap on the turn of a replacement

    def test_rollouts_do_not_nest_lookaheads(self):
        depth, deepest = [0], [0]
        original = Planner._after_throw

        def counting(this, *args):
            depth[0] += 1
            deepest[0] = max(deepest[0], depth[0])
            try:
                return original(this, *args)
            finally:
                depth[0] -= 1

        Planner._after_throw = counting
        try:
            same_cost = [self.gd.default(s) for s in ("empoleon", "malamar", "charjabug")]
            Battle(same_cost, same_cost, Planner(seed=1), Planner(seed=2), seed=5).run()
        finally:
            Planner._after_throw = original
        self.assertEqual(deepest[0], 1)

    def test_reader_reads(self):
        target = self.engine()
        reader = self.engine(cls=Reader)
        reader.target = target
        self.play(reader, target, games=2)
        self.assertGreater(reader.reads, 0)

    def test_genes_round_trip_and_cma(self):
        defaults = {g[0]: g[4] for g in evolve_rules.GENES}
        self.assertEqual(evolve_rules.decode(evolve_rules.GENES, evolve_rules.encode(evolve_rules.GENES)), defaults)
        es = evolve_rules.CMAES(np.full(6, 0.8), 0.2, 12)
        rng = np.random.default_rng(0)
        for _ in range(60):
            xs = es.ask(rng)
            es.tell(xs, -((xs - 0.3) ** 2).sum(axis=1))
        np.testing.assert_allclose(es.mean, 0.3, atol=0.01)


if __name__ == "__main__":
    unittest.main()
