import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts/recording'))
from native_health import measure_frame, header_panels


class PhysicalPixels(unittest.TestCase):
    def setUp(self):
        try:
            import cv2
            import numpy as np
            if not hasattr(cv2, 'cvtColor'):
                self.skipTest('optional video dependencies unavailable')
        except ImportError:
            self.skipTest('optional video dependencies unavailable')
        self.cv2, self.np = cv2, np

    def frame(self):
        return self.np.zeros((1080, 508, 3), dtype=self.np.uint8)

    def bar(self, image, live, orange=0):
        self.cv2.rectangle(image, (30, 600), (183, 613), (255, 255, 255), 2)
        image[603:611, 33:181] = 0
        image[603:611, 33:33+live] = [0, 240, 170]
        image[603:611, 33+live:33+live+orange] = [255, 145, 0]

    def test_actual_width_retains_the_last_live_pixels(self):
        image = self.frame(); self.bar(image, 3)
        mine = measure_frame(image)['mine']
        self.assertEqual(mine['status'], 'observed')
        self.assertGreater(mine['bar']['live_pixels'], 0)
        lo, hi = mine['bar']['fraction_interval']
        self.assertLessEqual(lo, 3/148)
        self.assertGreaterEqual(hi, 3/148)

    def test_orange_damage_does_not_become_live_hp(self):
        image = self.frame(); self.bar(image, 50, 30)
        mine = measure_frame(image)['mine']
        self.assertEqual(mine['status'], 'observed')
        self.assertLess(mine['bar']['fraction'], .4)
        self.assertGreater(mine['bar']['damage_pixels'], 20)

    def test_missing_outline_is_unknown_not_zero(self):
        image = self.frame()
        image[603:611, 33:80] = [0, 240, 170]
        self.assertEqual(measure_frame(image)['mine']['status'], 'not_visible')

    def test_empty_bar_preserves_pixel_uncertainty(self):
        image = self.frame(); self.bar(image, 0)
        bar = measure_frame(image)['mine']['bar']
        self.assertEqual(bar['fraction_interval'][0], 0)
        self.assertGreater(bar['fraction_interval'][1], 0)

    def test_shifted_header_is_found_without_fixed_icon_positions(self):
        image = self.frame()
        self.cv2.rectangle(image, (18, 100), (218, 154), (225, 225, 225), -1)
        for x, color in zip([40, 68, 96, 124, 152],
                            [(255, 0, 0)]*2+[(80, 80, 80)]+[(225, 110, 220)]*2):
            self.cv2.circle(image, (x, 141), 6, color, -1)
        panels = header_panels(image)
        self.assertEqual(len(panels), 1)
        self.assertEqual(len(panels[0]['glyphs']), 5)
        self.assertGreater(panels[0]['glyphs'][0]['red_pixels'], 0)
        self.assertEqual(panels[0]['glyphs'][2]['red_pixels'], 0)

    def test_cloud_merged_panel_still_requires_actual_opposite_glyphs(self):
        from creator_observations import classify_headers
        image=self.frame()
        self.cv2.rectangle(image,(6,70),(205,130),(230,230,230),-1)
        self.cv2.rectangle(image,(300,0),(507,130),(230,230,230),-1)
        for x in [25,52,79,426,454,482]:
            self.cv2.circle(image,(x,112),7,(255,0,0),-1)
        for x in [117,141,366,390]:
            self.cv2.circle(image,(x,112),7,(225,110,220),-1)
        measured=classify_headers(header_panels(image))
        self.assertEqual(measured['theirs']['party']['value'],3)
        self.assertEqual(measured['theirs']['shields']['value'],2)
        image[100:125,300:508]=(230,230,230)
        self.assertIsNone(classify_headers(header_panels(image))['theirs']['party']['value'])


if __name__ == '__main__':
    unittest.main()
