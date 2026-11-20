import importlib.util
from pathlib import Path
import sys
import unittest

DIRECTORY = Path(__file__).resolve().parents[1] / 'scripts/recording'
sys.path.insert(0, str(DIRECTORY))
spec = importlib.util.spec_from_file_location('energy_reference_six', DIRECTORY / 'energy_reference_six.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def point(truth, *, useful=False, exact=False, within=False, overlap=False):
    return dict(side='mine', truth=truth, useful=useful, exact_correct=exact,
                prediction_within_reference=within, overlaps=overlap)


def record(source, points):
    return dict(source_vod=source, before_points=points, after_points=points)


class SixReferenceScoringTests(unittest.TestCase):
    def test_unknown_truth_retained_in_attempted_coverage(self):
        reports = [record('vod-a', [point([16, 16], useful=True, exact=True, within=True, overlap=True)]),
                   record('vod-b', [point(None)])]
        result = module.summarize(reports, 'after')['both']
        self.assertEqual(result['attempted_windows'], 2)
        self.assertEqual(result['evaluable_numeric_windows'], 1)
        self.assertEqual(result['unscorable_windows'], 1)
        self.assertEqual(result['useful_coverage_all_attempts'], .5)
        self.assertEqual(result['useful_coverage_evaluable'], 1)

    def test_false_confident_interval_failure_visible(self):
        reports = [record('vod-a', [point([32, 36], useful=True)])]
        result = module.summarize(reports, 'after')['both']
        self.assertEqual(result['covered_source_bound_denominator'], 1)
        self.assertEqual(result['covered_predictions_within_source_bounds'], 0)
        self.assertEqual(len(result['false_confident_predictions']), 1)
        self.assertEqual(result['scalar_numeric_targets'], 0)

    def test_two_clips_same_vod_are_one_bootstrap_group(self):
        reports = [record('same-vod', [point([16, 16], useful=True)]),
                   record('same-vod', [point([24, 24])])]
        groups = module.grouped_counts(reports, 'after', 'both', lambda p: p['useful'], lambda p: True)
        self.assertEqual(groups, [[1, 2]])
        self.assertIsNone(module.summarize(reports, 'after')['both']['coverage_source_bootstrap']['interval_95'])

    def test_interval_compatibility_never_becomes_exact_scalar_truth(self):
        reports = [record('a', [point([40, 48], useful=True, within=True, overlap=True)])]
        result = module.summarize(reports, 'after')['both']
        self.assertEqual(result['scalar_numeric_targets'], 0)
        self.assertEqual(result['covered_predictions_within_source_bounds'], 1)


if __name__ == '__main__': unittest.main()
