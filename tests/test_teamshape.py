import random
import unittest

from pogo.gamedata import GameData
from pogo.teamshape import PVPOKE_WEIGHTS, Shapes, pvpoke_usage, shaped_drawer


class Stub(Shapes):
    """Letters given outright: a and b alike, c and d alike."""

    def __init__(self):
        self.counters = {}
        self._same = {}

    def same(self, a, b):
        return {a, b} in ({"a", "b"}, {"c", "d"}) or a == b


class TeamShapeTest(unittest.TestCase):
    def test_shapes(self):
        s = Stub()
        self.assertEqual(s.shape(["a", "c", "e"]), "ABC")
        self.assertEqual(s.shape(["e", "c", "d"]), "ABB")
        self.assertEqual(s.shape(["a", "b", "c"]), "AAB")
        self.assertEqual(s.shape(["c", "a", "d"]), "AAB")

    def test_usage_drawer(self):
        gd = GameData()
        usage = pvpoke_usage()
        self.assertAlmostEqual(sum(usage.values()), 0.79, delta=0.03)
        draw = shaped_drawer(gd, gd.meta(50, forms=True), PVPOKE_WEIGHTS, usage=usage)
        rng = random.Random(0)
        for _ in range(50):
            team = draw(rng)
            self.assertEqual(len({gd.species[b.species_id]["dex"] for b in team}), 3)


if __name__ == "__main__":
    unittest.main()
