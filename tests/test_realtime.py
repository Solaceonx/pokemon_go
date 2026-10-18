"""pogo.realtime: the engine with a deadline on each search."""
import random
import unittest
from pathlib import Path

from pogo.battle import FAST, Battle
from pogo.engine import Engine
from pogo.evaluation import Evaluator
from pogo.gamedata import GameData
from pogo.learner import QNet
from pogo.realtime import PREDICTED, RealTime

ROOT = Path(__file__).resolve().parent.parent


class FastOnly:
    """An opponent that only fast-moves and never switches."""

    def act(self, view):
        return FAST

    def shield(self, view, energy, *move):
        return False

    def replace(self, view):
        return view.me.bench()[0]


class Ticking:
    """A clock that moves on a whole second each time it is read: no search ever has time for a round."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        self.now += 1.0
        return self.now


class RealTimeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gd = GameData()
        cls.pool = cls.gd.meta(50)
        cls.net = QNet.load(str(ROOT / "runs" / "general-decide" / "q.npz"))
        cls.ev = Evaluator.load(ROOT / "runs" / "eval" / "eval.npz")
        rng = random.Random(5)
        cls.teams = [(rng.sample(cls.pool, 3), rng.sample(cls.pool, 3)) for _ in range(3)]

    def player(self, cls, **kwargs):
        return cls(self.ev, self.pool, horizon=8, samples=2, edge=0.03, rollout="quick", q=self.net, margin=0.02,
                   seed=11, **kwargs)

    def test_without_a_deadline_it_plays_as_the_engine(self):
        big = dict(turn_ms=1e9, unforeseen_ms=1e9, after_charged_ms=1e9, after_faint_ms=1e9, replace_ms=1e9, start_ms=1e9)
        for mine, theirs in self.teams[:2]:
            a, b = Battle(mine, theirs, self.player(Engine), FastOnly(), seed=3, record=True), None
            a.run()
            rt = self.player(RealTime, **big)
            b = Battle(mine, theirs, rt, FastOnly(), seed=3, record=True)
            b.run()
            self.assertEqual(a.log, b.log)
            self.assertFalse(any(row[5] or row[6] for row in rt.rows))

    def test_prediction_holds_when_they_only_fast_move(self):
        for mine, theirs in self.teams:
            rt = self.player(RealTime)
            Battle(mine, theirs, rt, FastOnly(), seed=4).run()
            causes = {row[0] for row in rt.rows}
            self.assertTrue(any(row[1] == PREDICTED for row in rt.rows))
            self.assertFalse(causes & {"mispredicted", "they switched", "a charged move came"}, causes)

    def test_no_time_plays_the_trained_bots_pick(self):
        rt = self.player(RealTime, clock=Ticking())
        mine, theirs = self.teams[0]
        Battle(mine, theirs, rt, FastOnly(), seed=6).run()
        self.assertTrue(rt.rows)
        self.assertTrue(all(row[6] for row in rt.rows))
        self.assertEqual(rt.changed, 0)


if __name__ == "__main__":
    unittest.main()
