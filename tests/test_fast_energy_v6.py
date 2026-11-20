from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/recording'))
from fast_energy_v6 import counted_hypothesis


def context():
    return dict(initial_zero_verified=True, moves={'theirs': dict(gain=8)}, charged_releases=[])


class CountedDiagnosticTests(unittest.TestCase):
    def test_absent_vfx_never_fabricates_exact_opponent_zero(self):
        r = counted_hypothesis(context(), 'theirs', 10, [], initial_sequence_assumed_complete=True)
        self.assertIsNone(r['value'])
        self.assertFalse(r['usable_for_fullstate'])

    def test_incomplete_prefix_withholds_value(self):
        r = counted_hypothesis(context(), 'theirs', 10, [dict(t=1, side='theirs')], initial_sequence_assumed_complete=False)
        self.assertIsNone(r['value'])

    def test_charge_subtracts_bank_not_reset(self):
        c = context(); c['charged_releases'] = [dict(t=9, side='theirs', cost=40)]
        r = counted_hypothesis(c, 'theirs', 10, [dict(t=i, side='theirs') for i in range(1, 7)], initial_sequence_assumed_complete=True)
        self.assertEqual(r['value'], 8)
        self.assertFalse(r['usable_for_fullstate'])

    def test_future_vfx_not_counted(self):
        r = counted_hypothesis(context(), 'theirs', 10, [dict(t=11, side='theirs')], initial_sequence_assumed_complete=True)
        self.assertIsNone(r['value'])

    def test_unverified_initial_energy_withholds_even_with_complete_prefix(self):
        c = context(); c['initial_zero_verified'] = False
        r = counted_hypothesis(c, 'theirs', 10, [dict(t=1, side='theirs')], initial_sequence_assumed_complete=True)
        self.assertIsNone(r['value'])
        self.assertFalse(r['usable_for_fullstate'])


if __name__ == '__main__': unittest.main()
