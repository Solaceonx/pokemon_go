import random
import unittest
from pathlib import Path

from pogo.battle import Battle
from pogo.gamedata import GameData
from pogo.learner import N_FEATURES, N_FORMS, Learner, QNet, form_state

MODEL = Path(__file__).resolve().parent.parent / "runs" / "general-decide" / "q.npz"


class FormInputsTest(unittest.TestCase):
    def test_form_state(self):
        gd = GameData()
        battle = Battle([gd.default("mimikyu")], [gd.default("cramorant")], Learner(), Learner(), seed=0)
        x = form_state(battle.views[0])
        self.assertEqual(x[:3], [0.0, 1.0, 0.0])  # our Mimikyu: home form, disguise up
        self.assertEqual(x[3:], [0.0, 0.0, 0.0])  # their Cramorant: nothing in its mouth yet
        plain = Battle([gd.default("melmetal")], [gd.default("azumarill")], Learner(), Learner(), seed=0)
        self.assertEqual(form_state(plain.views[0]), [0.0] * N_FORMS)

    @unittest.skipUnless(MODEL.exists(), "needs the trained model")
    def test_widened_model_plays_the_same(self):
        gd = GameData()
        old = QNet.load(MODEL)
        new = old.widened(N_FEATURES + N_FORMS)
        self.assertTrue(new.forms and not new.wide and not old.forms)
        pool = gd.meta(50, forms=True)
        for n in range(4):
            rng = random.Random(n)
            a, b = rng.sample(pool, 3), rng.sample(pool, 3)
            logs = []
            for q in (old, new):
                battle = Battle(a, b, Learner(q=q, margin=0.02, seed=1), Learner(q=q, margin=0.02, seed=2), seed=3)
                logs.append((battle.run(), battle.turn))
            self.assertEqual(logs[0], logs[1])


if __name__ == "__main__":
    unittest.main()
