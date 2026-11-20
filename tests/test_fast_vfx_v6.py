import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

DIRECTORY = Path(__file__).resolve().parents[1] / 'scripts/recording'
sys.path.insert(0, str(DIRECTORY))
import fast_vfx_v6 as vfx
from fast_vfx_eval_v6 import match_events


def rows(times, positive=True, visible=True):
    return [dict(t=t, signals={'x': dict(positive=positive, visible=visible)}) for t in times]


def model(**kwargs):
    return dict(id='x', side='theirs', move_id='PECK', merge_gap_seconds=.25,
                min_positive_samples=1, **kwargs)


class FastVfxV6Tests(unittest.TestCase):
    def test_multiple_subhits_are_one_gesture(self):
        result = vfx.gestures(rows([1, 1.067, 1.2, 1.267]), model())
        self.assertEqual(len(result['events']), 1)
        self.assertFalse(result['measured_energy_credit'])

    def test_known_gesture_spacing_merges_fragment_not_periodic_attack(self):
        result = vfx.gestures(rows([1, 1.3, 2]), model(minimum_distinct_gesture_spacing_seconds=.6))
        self.assertEqual(len(result['events']), 2)
        self.assertEqual(result['events'][0]['samples'], 2)

    def test_no_positive_pixels_does_not_generate_periodic_events(self):
        self.assertEqual(vfx.gestures(rows([0, 1, 2, 3], False), model())['events'], [])

    def test_occlusion_retained_as_gap(self):
        result = vfx.gestures(rows([0, .1], False, False), model())
        self.assertEqual(result['occluded_frame_seconds'], [0, .1])

    def test_one_prediction_cannot_match_two_source_events(self):
        truth = [dict(side='mine', onset_window=[1, 1.1]), dict(side='mine', onset_window=[1.1, 1.2])]
        result = match_events([dict(side='mine', t=1.1)], truth)
        self.assertEqual((result['tp'], result['fn']), (1, 1))

    def test_late_peak_not_called_precise_onset(self):
        result = match_events([dict(side='mine', t=1.5)],
            [dict(side='mine', onset_window=[1, 1.1], gesture_window=[1, 1.6])])
        self.assertEqual(result['tp'], 1)
        self.assertEqual(result['matched_onset_within_150ms'], 0)

    def test_native_hough_shapes_and_builtin_json(self):
        try:
            import cv2
            import numpy as np
        except ImportError:
            self.skipTest('Native recording dependencies unavailable')
        if not hasattr(cv2, 'HoughLinesP'):
            self.skipTest('Native recording dependencies unavailable')
        lines = np.array([[0, 60, 30, 30], [0, 80, 30, 50], [0, 100, 30, 70]], dtype=np.int32)
        for shape in [(3, 4), (3, 1, 4)]:
            with patch.object(cv2, 'HoughLinesP', return_value=lines.reshape(shape)):
                result = vfx.signal(np.zeros((120, 120, 3), dtype=np.uint8),
                    dict(kind='white_parallel_slashes', box=[0, 0, 120, 120]), {})
            self.assertTrue(result['positive'])
            self.assertIs(type(result['positive']), bool)
            json.dumps(result)

    def test_unknown_model_or_long_window_rejected_before_decoding(self):
        with self.assertRaises(ValueError):
            vfx.acquire(Path('missing.mp4'), [], {}, 0, 3, 15, Path('unused.gz'))
        with self.assertRaises(ValueError):
            vfx.acquire(Path('missing.mp4'), [model()], {}, 0, 100, 15, Path('unused.gz'))


if __name__ == '__main__': unittest.main()
