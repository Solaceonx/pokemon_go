"""A wide evaluation (scripts/train_eval.py --wide) reads their Pokemon seen and off the field; a narrow one cannot."""
import unittest

import numpy as np

from pogo.battle import Battle
from pogo.evaluation import N_INPUTS, Evaluator
from pogo.gamedata import GameData
from pogo.learner import N_KNOWN, Learner, describe
from pogo.value import ValueModel


def model(inputs: int, seed: int = 0) -> ValueModel:
    rng = np.random.default_rng(seed)
    return ValueModel([(rng.normal(size=(inputs, 8)), np.zeros(8)), (rng.normal(size=(8, 1)), np.zeros(1))])


class WideEvaluation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        gd = GameData()
        pool = gd.meta(6)
        cls.battle = Battle(pool[:3], pool[3:6], None, None, seed=1)
        foes = cls.battle.sides[1]
        foes.shown = [0, 1]  # their first two seen, the second now in play: the first is off the field
        foes.active = 1

    def test_sizes(self):
        view = self.battle.views[0]
        self.assertEqual(len(describe(Learner(), view)), N_INPUTS)
        narrow, wide = Evaluator(model(N_INPUTS)), Evaluator(model(N_INPUTS + N_KNOWN))
        self.assertFalse(narrow.wide)
        self.assertTrue(wide.wide)
        self.assertFalse(Evaluator().wide)
        self.assertEqual(len(wide.features(view)), N_INPUTS + N_KNOWN)

    def test_only_the_wide_one_sees_the_bench(self):
        narrow, wide = Evaluator(model(N_INPUTS)), Evaluator(model(N_INPUTS + N_KNOWN))
        benched = self.battle.sides[1].team[0]
        before = narrow(self.battle.views[0]), wide(self.battle.views[0])
        hp = benched.hp
        try:
            benched.hp = 1
            after = narrow(self.battle.views[0]), wide(self.battle.views[0])
        finally:
            benched.hp = hp
        self.assertEqual(before[0], after[0])
        self.assertNotEqual(before[1], after[1])


if __name__ == "__main__":
    unittest.main()
