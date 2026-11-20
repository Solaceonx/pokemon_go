import importlib.util
from pathlib import Path
import sys
import unittest

DIRECTORY = Path(__file__).resolve().parents[1] / 'scripts/recording'
sys.path.insert(0, str(DIRECTORY))
spec = importlib.util.spec_from_file_location('energy_bounds_v4', DIRECTORY / 'energy_bounds_v4.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def context():
    return dict(initial_zero_at=0, initial_zero_verified=True, fast_only_interval=[0, 5],
        moves={'mine': dict(gain=8, turns=2), 'theirs': dict(gain=4, turns=1)}, charged_releases=[])


class EnergyBoundsV4Tests(unittest.TestCase):
    def test_no_damage_observed_does_not_prove_no_attacks(self):
        result = module.estimate(context(), 'theirs', 4)
        self.assertFalse(result['exact'])
        self.assertIn([32, 32], result['integer_ranges'])
        self.assertFalse(result['hp_drop_count_used'])

    def test_charged_animation_adds_no_optional_gains(self):
        c = context(); c['charged_releases'] = [dict(side='mine', t=10, cost=40)]
        a, b = module.estimate(c, 'mine', 10), module.estimate(c, 'mine', 20)
        self.assertEqual(a['integer_ranges'], b['integer_ranges'])
        self.assertNotEqual(a['integer_ranges'], [[0, 0]])

    def test_cap_and_legal_charge_affordability(self):
        c = context(); c['fast_only_interval'] = [0, 100]
        c['charged_releases'] = [dict(side='mine', t=100, cost=40)]
        result = module.estimate(c, 'mine', 100)
        self.assertTrue(all(0 <= lo <= hi <= 60 for lo, hi in result['integer_ranges']))

    def test_unknown_initial_balance_not_zero(self):
        c = context(); c['initial_zero_verified'] = False
        self.assertEqual(module.estimate(c, 'mine', 0)['integer_ranges'], [[0, 100]])

    def test_ambiguous_icon_fill_rejected(self):
        disc = dict(status='observed', white_rim_fraction=.3,
            measurement=dict(present=True, rim=1, lopsided=0, fill=.5))
        self.assertIsNone(module.button_values(disc, 40))

    def test_fresh_unready_disc_gives_integer_candidates(self):
        disc = dict(status='observed', white_rim_fraction=0,
            measurement=dict(present=True, rim=1, lopsided=0, fill=.4))
        self.assertIn(16, module.button_values(disc, 40))
        self.assertNotIn(56, module.button_values(disc, 40))

    def test_query_delay_allows_optional_completion(self):
        self.assertEqual(module.optional_completions({16}, .08, gain=8, period=1), {16, 24})

    def test_bench_interval_does_not_reset_or_add_energy(self):
        c = context(); c['fighting_intervals'] = [[0, 2], [10, 12]]
        self.assertEqual(module.estimate(c, 'mine', 2)['integer_ranges'],
                         module.estimate(c, 'mine', 8)['integer_ranges'])


if __name__ == '__main__': unittest.main()
