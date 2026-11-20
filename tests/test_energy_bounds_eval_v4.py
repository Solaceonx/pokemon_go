import importlib.util
from pathlib import Path
import sys
import unittest

DIRECTORY = Path(__file__).resolve().parents[1] / 'scripts/recording'
sys.path.insert(0, str(DIRECTORY))
spec = importlib.util.spec_from_file_location('energy_bounds_eval_v4', DIRECTORY / 'energy_bounds_eval_v4.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class CandidateContainmentTests(unittest.TestCase):
    def test_valid_conservative_candidates_not_exact_or_wrong(self):
        result = module.compare({16, 24}, [16, 16])
        self.assertTrue(result['scalar_truth_contained'])
        self.assertFalse(result['exact_scalar_recovered'])
        self.assertFalse(result['disjoint_narrow'])
        self.assertFalse(result['prediction_within_reference'])

    def test_interval_overlap_is_not_full_containment(self):
        result = module.compare({40, 48}, [40, 48])
        self.assertTrue(result['overlap'])
        self.assertFalse(result['interval_fully_contained'])
        self.assertTrue(result['prediction_within_reference'])

    def test_disjoint_exact_zero_is_false_confidence(self):
        result = module.compare({0}, [32, 36])
        self.assertTrue(result['disjoint_narrow'])

    def test_unknown_truth_not_excluded_from_attempted_scope(self):
        result = module.compare(set(), None)
        self.assertFalse(result['scorable'])
        self.assertIsNone(result['scalar_truth_contained'])
        self.assertFalse(result['useful'])


if __name__ == '__main__': unittest.main()
