import importlib.util
from pathlib import Path
import sys
import unittest

DIRECTORY = Path(__file__).resolve().parents[1] / 'scripts/recording'
sys.path.insert(0, str(DIRECTORY))
spec = importlib.util.spec_from_file_location('energy_bounds_v5', DIRECTORY / 'energy_bounds_v5.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def context():
    return dict(initial_zero_at=0, initial_zero_verified=True, fast_only_interval=[0, 2],
        moves={'mine': dict(gain=8, turns=2), 'theirs': dict(gain=4, turns=1)},
        charged_releases=[], charge_button_costs=[40, 40])


def row(t, fill=.2):
    return dict(t=t, controls=dict(discs=[dict(status='observed', white_rim_fraction=0,
        measurement=dict(fill=fill, present=True, rim=1, lopsided=0)) for _ in range(2)]))


class EnergyTransportV5Tests(unittest.TestCase):
    def test_old_anchor_expands_instead_of_carrying_exact_energy(self):
        result = module.estimate(context(), 'mine', .8, [row(0), row(.1667)])
        self.assertEqual(result['integer_ranges'], [[8, 8], [16, 16]])
        self.assertFalse(result['exact'])
        self.assertFalse(result['transported_energy_is_current_exact_observation'])

    def test_anchor_not_used_past_declared_horizon(self):
        result = module.estimate(context(), 'mine', 2, [row(0), row(.1667)])
        self.assertIsNone(result['anchor_at'])

    def test_cap_before_cost_does_not_erase_possible_late_credit(self):
        c = context(); c['fast_only_interval'] = [0, 0]
        c['charged_releases'] = [dict(side='mine', t=1, cost=40)]
        self.assertEqual(module.bank_from({100}, c, 'mine', 0, 1, boundary_allowance=False), {60, 68})

    def test_no_periodic_gain_during_held_animation(self):
        c = context(); c['charged_releases'] = [dict(side='mine', t=3, cost=16)]
        self.assertEqual(module.estimate(c, 'mine', 3)['integer_ranges'],
                         module.estimate(c, 'mine', 20)['integer_ranges'])

    def test_unknown_initial_is_not_zero(self):
        c = context(); c['initial_zero_verified'] = False
        self.assertEqual(module.estimate(c, 'mine', 0)['integer_ranges'], [[0, 100]])

    def test_opponent_has_no_fictional_own_button_readout(self):
        result = module.estimate(context(), 'theirs', .8, [row(0), row(.1667)])
        self.assertIsNone(result['anchor_at'])
        self.assertFalse(result['hp_drop_count_used'])
