from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/recording'))
from fast_controls_v6 import gain_count


class FastControlGainTests(unittest.TestCase):
    def test_named_cost_bank_counts_gain_without_reset(self):
        result = gain_count(32, 8, 40, 8)
        self.assertEqual(result['count'], 2)
        self.assertEqual(result['status'], 'measured_aggregate_gain')

    def test_possible_cap_withholds_exact_count(self):
        result = gain_count(32, 8, 40, 8, possible_cap=True)
        self.assertIsNone(result['count'])
        self.assertEqual(result['minimum_count'], 2)

    def test_negative_or_nonintegral_gain_is_contradiction(self):
        self.assertEqual(gain_count(32, 8, 0, 8)['status'], 'contradictory')
        self.assertEqual(gain_count(0, 7, 0, 8)['status'], 'contradictory')


if __name__ == '__main__': unittest.main()
