import importlib.util
from pathlib import Path
import sys
import unittest

DIRECTORY = Path(__file__).resolve().parents[1] / 'scripts/recording'
sys.path.insert(0, str(DIRECTORY))
spec = importlib.util.spec_from_file_location('energy_reference_batch', DIRECTORY / 'energy_reference_batch.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class EnergyClusterMarginTests(unittest.TestCase):
    def test_one_source_cannot_manufacture_precision(self):
        self.assertIsNone(module.cluster_margin([(4, 8)])['interval_95'])

    def test_group_resampling_preserves_nested_point_denominators(self):
        result = module.cluster_margin([(4, 8), (1, 2), (0, 2)])
        self.assertEqual(result['enumerated_resamples'], 27)
        self.assertEqual(result['interval_95'], [0, .5])

    def test_uncertain_source_does_not_drop_from_bootstrap(self):
        result = module.cluster_margin([(3, 7), (1, 1), (0, 1)])
        self.assertEqual(result['interval_95'], [0, 1])
        self.assertEqual(result['undefined_resamples'], 0)

    def test_unscorable_draws_reported_separately(self):
        result = module.cluster_margin([(1, 1), (0, 0)])
        self.assertEqual(result['enumerated_resamples'], 4)
        self.assertEqual(result['undefined_resamples'], 1)
        self.assertEqual(result['interval_95'], [1, 1])

    def test_interval_guarantee_covers_every_possible_truth_value(self):
        from energy_reference_eval import point_score
        wide = point_score('mine', 1, {50}, [0, 100], 8)
        narrow = point_score('mine', 2, {48}, [40, 48], 8)
        report = {'supplemental': {'before_points': [wide], 'after_points': [narrow]}}
        module.interval_guarantees(report, {'mine': {'gain': 8}})
        self.assertFalse(wide['within_one_fast_guaranteed'])
        self.assertTrue(narrow['within_one_fast_guaranteed'])


if __name__ == '__main__': unittest.main()
