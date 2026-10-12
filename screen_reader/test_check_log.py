import unittest
from check_log import compare


class ComparisonTests(unittest.TestCase):
    def observation(self, fraction, width=138, time=1.0):
        side = {"health_bar": {"value": None if fraction is None else {"fraction": fraction, "pixel_resolution_fraction": 1/width}},
                "cp": {"value": 1495, "status": "observed"}}
        return {"timestamp_seconds": time, "mine": side, "opponent": side}

    def test_unknown_health_does_not_pass(self):
        report = compare([self.observation(None)], [{"timestamp_seconds": 1, "mine": {"hp": 80, "max_hp": 100}}])
        self.assertEqual(report["summary"], {"unreadable": 1})

    def test_one_hp_requirement_is_flagged_when_pixels_are_too_coarse(self):
        report = compare([self.observation(0.8)], [{"timestamp_seconds": 1, "mine": {"hp": 160, "max_hp": 200}}])
        self.assertEqual(report["summary"], {"resolution_limited": 1})

    def test_health_mismatch_is_reported(self):
        report = compare([self.observation(0.6)], [{"timestamp_seconds": 1, "mine": {"health_fraction": 0.8}}])
        self.assertEqual(report["summary"], {"mismatch": 1})

    def test_out_of_range_timestamp_does_not_match_distant_frame(self):
        report = compare([self.observation(0.8, time=1)], [{"timestamp_seconds": 2, "mine": {"cp": 1495}}])
        self.assertEqual(report["summary"], {"no_matching_frame": 1})

    def test_integer_hp_comparison_with_sufficient_resolution(self):
        report = compare([self.observation(0.8, width=300)], [{"timestamp_seconds": 1, "mine": {"hp": 160, "max_hp": 200}}])
        self.assertEqual(report["summary"], {"pass": 1})


if __name__ == "__main__":
    unittest.main()
