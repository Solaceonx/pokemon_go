import copy
import importlib.util
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location('energy_rebuild', Path(__file__).resolve().parents[1] / 'scripts/recording/energy_rebuild.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def event(kind, t, side='mine', identity='a', **kwargs):
    return dict(kind=kind, t=t, side=side, identity=identity,
                proof=dict(basis='source_review', source_sha256='a' * 64), **kwargs)


class EnergyRebuildTests(unittest.TestCase):
    def test_charge_never_resets_to_zero(self):
        events = [event('anchor', 0, candidates=[48, 56]),
                  event('charged_release', 1, move_source_verified=True, cost=40)]
        self.assertEqual(module.rebuild(events)['events'][-1]['after_ranges'], [[8, 8], [16, 16]])

    def test_release_affordability_is_constraint_not_free_energy(self):
        result = module.rebuild([event('charged_release', 1, move_source_verified=True, cost=40)])
        self.assertEqual(result['events'][0]['after_ranges'], [[0, 60]])

    def test_cap_and_optional_queued_completion(self):
        result = module.rebuild([event('anchor', 0, candidates=[96]),
            event('fast_complete', 1, move_source_verified=True, measured_completion=True, gain=8, count_range=[0, 1])])
        self.assertEqual(result['events'][-1]['after_ranges'], [[96, 96], [100, 100]])

    def test_bench_and_both_sides_independent(self):
        result = module.rebuild([event('anchor', 0, candidates=[48]),
            event('switch', 1, identity='b'), event('anchor', 2, side='theirs', candidates=[80]),
            event('switch', 3), event('charged_release', 4, move_source_verified=True, cost=40)])
        self.assertEqual(result['events'][-1]['after_ranges'], [[8, 8]])
        self.assertIn(dict(side='theirs', identity='a', integer_ranges=[[80, 80]]), result['final'])

    def test_animation_holds_no_elapsed_gain(self):
        result = module.rebuild([event('anchor', 0, candidates=[24]), event('animation_hold', 20)])
        self.assertEqual(result['events'][-1]['after_ranges'], [[24, 24]])

    def test_missing_interval_does_not_keep_fake_precision(self):
        result = module.rebuild([event('anchor', 0, candidates=[24]), event('gap', 20)])
        self.assertEqual(result['events'][-1]['after_ranges'], [[0, 100]])

    def test_contradictions_sticky(self):
        result = module.rebuild([event('anchor', 0, candidates=[24]),
            event('charged_release', 1, move_source_verified=True, cost=40), event('gap', 2)])
        self.assertEqual(result['events'][-1]['status'], 'contradictory')
        self.assertEqual(result['events'][-1]['after_ranges'], [])

    def test_assumed_move_or_fitted_timing_rejected(self):
        for kwargs in [dict(move_source_verified=False, measured_completion=True),
                       dict(move_source_verified=True, measured_completion=False)]:
            with self.assertRaises(ValueError):
                module.rebuild([event('fast_complete', 1, gain=8, **kwargs)])
        e = event('animation_hold', 1); e['proof']['basis'] = 'fitted_clock'
        with self.assertRaises(ValueError): module.rebuild([e])

    def test_order_and_input_not_mutated(self):
        events = [event('anchor', 1, candidates=[40]), event('animation_hold', 2)]
        original = copy.deepcopy(events); module.rebuild(events)
        self.assertEqual(events, original)
        with self.assertRaises(ValueError): module.rebuild(list(reversed(events)))

    def test_clipped_entry_and_extra_meter_rejected(self):
        with self.assertRaises(ValueError): module.rebuild([event('segment_start', 0)])
        with self.assertRaises(ValueError): module.rebuild([event('charged_release', 1, move_source_verified=True, cost=40, meter='mega_unknown')])

    def test_pulse_detector_no_periodic_invention(self):
        rows = [dict(t=i / 12, health={'mine': dict(status='observed', bar=dict(
            outline_method='closed_physical_contour', fraction=1 - (i >= 12) * .05))}) for i in range(48)]
        result = module.measured_impacts(rows, damaged_side='mine', start=0, end=4, turns=2)
        self.assertEqual(len(result['impacts']), 1)
        self.assertFalse(result['manual_target_counts_used'])

    def test_boolean_energy_not_integer(self):
        with self.assertRaises(ValueError): module.rebuild([event('anchor', 0, candidates=[True])])

    def test_initial_damaged_plateau_is_censored_not_zero_completions(self):
        rows = [dict(t=.5 + i / 12, health={'mine': dict(status='observed', bar=dict(
            outline_method='closed_physical_contour', fraction=.95))}) for i in range(12)]
        result = module.measured_impacts(rows, damaged_side='mine', start=0, end=2, turns=2)
        self.assertEqual(result['impacts'], [])
        self.assertEqual(result['initial_unmeasured_completion_count_range'][0], 0)
        self.assertGreaterEqual(result['initial_unmeasured_completion_count_range'][1], 1)


if __name__ == '__main__': unittest.main()
