"""Training from both players' decisions in battles of the learner against itself (decide.py --both-sides)."""
import random
import unittest

import numpy as np

from pogo.agents import Planner
from pogo.battle import DRAW, Battle
from pogo.gamedata import GameData
from pogo.learner import N_FEATURES, Learner
from scripts.decide import collect, play_out

GD = GameData()


def points(winner, side):
    return 1.0 if winner == side else 0.5 if winner == DRAW else 0.0


class BothSides(unittest.TestCase):
    def test_replaying_either_players_own_choice_gives_the_real_result(self):
        pool = GD.meta(50)
        rng = random.Random(3)
        logs = ([], [])
        me, them = (Learner(log=logs[i], seed=11 + i) for i in range(2))
        battle = Battle(rng.sample(pool, 3), rng.sample(pool, 3), me, them, seed=5)
        checks = []
        while battle.winner is None:
            snapshot = (battle.clone(None, None), me.clone(), them.clone())
            seen = [len(log) for log in logs]
            battle.step()
            for side in (0, 1):
                for head, _, _, choice in logs[side][seen[side]:]:
                    checks.append((side, play_out(snapshot, head, choice, side=side)))
        self.assertTrue(any(side == 1 for side, _ in checks))
        for side, result in checks:
            self.assertEqual(result, points(battle.winner, side))

    def test_collect_keeps_both_players_decisions(self):
        pool = GD.meta(50)
        data, battles, _ = collect(None, pool, None, 0.03, lambda rng: Planner(), 3.0, 1, lambda rng: rng.sample(pool, 3),
                                   both_sides=1.0)
        self.assertGreater(battles, 0)
        for x, y in data.values():
            self.assertEqual(x.shape[1], N_FEATURES)
            known = y[~np.isnan(y)]
            self.assertTrue(set(np.unique(known)) <= {0.0, 0.5, 1.0})
        self.assertGreater(len(data["shield"][0]), 0)


if __name__ == "__main__":
    unittest.main()
