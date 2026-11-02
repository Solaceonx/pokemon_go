"""Pairing integrity and conservative resource allocation for capacity tests."""
import unittest
from scripts.select_capacity_candidate import paired_difference


class CapacitySelection(unittest.TestCase):
    def rows(self, values):
        return [{"index": i, "score": v} for i, v in enumerate(values)]

    def test_equal_policies_cannot_have_a_positive_difference_interval(self):
        a = self.rows([0., .5, 1., 0.] * 8)
        result = paired_difference(a, a)
        self.assertEqual(result["paired_change"], 0.)
        self.assertEqual(result["ci95"], [0., 0.])

    def test_consistent_improvement_has_a_positive_interval_and_repeats(self):
        a, b = self.rows([0.] * 32), self.rows([.5] * 32)
        self.assertEqual(paired_difference(a, b), paired_difference(a, b))
        self.assertEqual(paired_difference(a, b)["ci95"], [.5, .5])

    def test_mismatched_cases_or_invalid_scores_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "cases differ"):
            paired_difference(self.rows([0., 1.]), self.rows([0.]))
        with self.assertRaisesRegex(ValueError, "scores"):
            paired_difference(self.rows([0., 1.]), self.rows([0., 2.]))


if __name__ == "__main__":
    unittest.main()
