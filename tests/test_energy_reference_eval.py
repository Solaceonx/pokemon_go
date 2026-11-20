import importlib.util
from pathlib import Path
import sys
import unittest

DIRECTORY = Path(__file__).resolve().parents[1] / 'scripts/recording'
sys.path.insert(0, str(DIRECTORY))
spec = importlib.util.spec_from_file_location('energy_reference_eval', DIRECTORY / 'energy_reference_eval.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class EnergyReferenceScoringTests(unittest.TestCase):
    def test_broad_truth_overlap_is_not_useful_energy(self):
        p = module.point_score('mine', 1, set(range(101)), [16, 16], 8)
        self.assertTrue(p['truth_contained'])
        self.assertFalse(p['useful'])
        self.assertFalse(p['exact_correct'])
        self.assertFalse(p['within_one_fast_guaranteed'])

    def test_interval_target_does_not_claim_exact_accuracy(self):
        p = module.point_score('theirs', 1, {48}, [40, 48], 8)
        self.assertTrue(p['useful'])
        self.assertTrue(p['prediction_within_reference'])
        self.assertFalse(p['exact_correct'])
        self.assertFalse(p['truth_contained'])

    def test_one_fast_guarantee_checks_every_candidate(self):
        good = module.point_score('mine', 1, {8, 16, 24}, [16, 16], 8)
        bad = module.point_score('mine', 1, {8, 16, 24, 32}, [16, 16], 8)
        self.assertTrue(good['within_one_fast_guaranteed'])
        self.assertFalse(bad['within_one_fast_guaranteed'])

    def test_baseline_pending_and_unknown_stay_uncovered(self):
        field = dict(status='estimated', value=[40, 40], state_validity='pending_change')
        rows = [dict(t=1, game_state=dict(sides={'mine': dict(active='a', active_status='observed',
            pokemon={'a': {'energy': field}})}))]
        self.assertEqual(module.baseline(rows, 'mine', 1), set())
        field['state_validity'] = 'recent_reading'
        self.assertEqual(module.baseline(rows, 'mine', 1), {40})
        self.assertEqual(module.baseline(rows, 'mine', 2), set())

    def test_noncontiguous_baseline_candidates_preserved(self):
        field = dict(status='estimated', value=[8, 16], integer_ranges=[[8, 8], [16, 16]])
        rows = [dict(t=1, game_state=dict(sides={'opponent': dict(active='a', active_status='observed',
            pokemon={'a': {'energy': field}})}))]
        self.assertEqual(module.baseline(rows, 'theirs', 1), {8, 16})

    def test_unknown_cases_remain_in_denominator(self):
        points = [module.point_score('mine', 1, {16}, [16, 16], 8),
                  module.point_score('mine', 2, set(), [16, 16], 8)]
        result = module.score_points(points)['mine']
        self.assertEqual(result['total'], 2)
        self.assertEqual(result['useful'], 1)
        self.assertEqual(result['useful_coverage'], .5)
        self.assertIsNone(result['group_bootstrap_95'])


if __name__ == '__main__': unittest.main()
