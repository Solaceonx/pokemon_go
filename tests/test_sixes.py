"""pogo.sixes: the choices from six, and the solver of a simultaneous zero-sum table."""
import unittest

import numpy as np

from pogo.sixes import choices, gap, solve


class SixesTest(unittest.TestCase):
    def test_sixty_choices_each_three_once_per_lead(self):
        c = choices(list("abcdef"))
        self.assertEqual(len(c), 60)
        self.assertEqual(len({(x[0], frozenset(x)) for x in c}), 60)

    def test_rock_paper_scissors(self):
        table = np.array([[0.5, 0, 1], [1, 0.5, 0], [0, 1, 0.5]])
        value, p, q = solve(table, 20000)
        self.assertAlmostEqual(value, 0.5, places=3)
        np.testing.assert_allclose(p, [1 / 3] * 3, atol=0.01)
        np.testing.assert_allclose(q, [1 / 3] * 3, atol=0.01)

    def test_dominant_choice_is_found(self):
        table = np.array([[0.9, 0.8], [0.2, 0.1]])  # row 0 is better whatever they do; column 1 is their best
        value, p, q = solve(table, 5000)
        self.assertAlmostEqual(value, 0.8, places=2)
        self.assertGreater(p[0], 0.99)
        self.assertGreater(q[1], 0.99)
        self.assertLess(gap(table, p, q), 0.01)


if __name__ == "__main__":
    unittest.main()
