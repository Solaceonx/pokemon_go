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

    def test_yellow_transition_after_green_does_not_extend_live_prefix(self):
        from native_health import palette
        image=self.frame();self.bar(image,50)
        image[603:611,83:91]=[255,240,0]
        bar=palette(image,[30,600,184,614])
        self.assertLessEqual(bar['live_pixels'],51)

    def test_warm_live_bar_still_reads_yellow_health(self):
        from native_health import palette
        image=self.frame();self.bar(image,50)
        image[603:611,33:83]=[255,240,0]
        bar=palette(image,[30,600,184,614])
        self.assertGreaterEqual(bar['live_pixels'],49)

    def test_saturated_damage_edge_is_not_a_vertical_outline(self):
        from native_health import rectangle
        image=self.frame();self.bar(image,130,10)
        image[599:615,160:166]=[255,230,0]
        self.assertIsNone(rectangle(image,[30,600,164,614],'closed_physical_contour'))

    def test_empty_bar_preserves_pixel_uncertainty(self):
        image = self.frame(); self.bar(image, 0)
        bar = measure_frame(image)['mine']['bar']
        self.assertEqual(bar['fraction_interval'][0], 0)
        self.assertGreater(bar['fraction_interval'][1], 0)

    def test_washed_out_yellow_fill_is_live_health(self):
        from native_health import palette
        image=self.frame(); self.bar(image, 50)
        image[603:611, 33:83]=[230, 225, 170]
        bar=palette(image, [30,600,184,614])
        self.assertIsNotNone(bar)
        self.assertAlmostEqual(bar['fraction'], 50/148, places=5)

    def test_dim_four_rail_outline_recovers_only_positive_profile_width_bar(self):
        from native_health import rectangle, dim_rectangle
        image=self.frame(); self.bar(image, 50)
        image[(image == 255).all(axis=2)]=[120,120,120]
        self.assertIsNone(rectangle(image,[30,600,184,614],'test'))
        self.assertIsNotNone(dim_rectangle(image,[30,600,184,614],154))
        self.assertIsNone(dim_rectangle(image,[30,600,184,614],144))
        image[603:611,33:181]=0
        self.assertIsNone(dim_rectangle(image,[30,600,184,614],154))

    def test_dim_outline_cannot_be_unoutlined_black_background(self):
        from native_health import dim_rectangle
        image=self.frame(); image[603:611,33:83]=[0,240,170]
        self.assertIsNone(dim_rectangle(image,[30,600,184,614],154))

    def test_dim_outline_needs_all_four_matching_rails(self):
        from native_health import dim_rectangle
        image=self.frame(); self.bar(image,50)
        image[(image == 255).all(axis=2)]=[120,120,120]
        image[598:616,181:187]=[255,145,0]
        self.assertIsNone(dim_rectangle(image,[30,600,184,614],154))

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

    def test_weather_icons_cannot_extend_an_otherwise_valid_header_component(self):
        from creator_observations import classify_headers
        image=self.frame()
        for x in [6,301]:
            self.cv2.rectangle(image,(x,70),(x+198,130),(230,230,230),-1)
            self.cv2.circle(image,(x+20,55),12,(230,230,230),-1)
        for x in [25,52,79,426,454,482]:
            self.cv2.circle(image,(x,112),7,(255,0,0),-1)
        for x in [117,141,366,390]:
            self.cv2.circle(image,(x,112),7,(225,110,220),-1)
        measured=classify_headers(header_panels(image))
        for side in ['mine','theirs']:
            self.assertEqual(measured[side]['party']['value'],3)
            self.assertEqual(measured[side]['shields']['value'],2)


if __name__ == '__main__':
    unittest.main()
