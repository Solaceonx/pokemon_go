import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts/recording'))
from native_health import header_panels, header_row_panels
from creator_observations import classify_headers


class HeaderRows(unittest.TestCase):
    def setUp(self):
        try:
            import cv2
            import numpy as np
            if not hasattr(cv2, 'cvtColor'):
                self.skipTest('optional video dependencies unavailable')
        except ImportError:
            self.skipTest('optional video dependencies unavailable')
        self.cv2, self.np = cv2, np

    def frame(self, color=(245,245,245), icons=5):
        image=self.np.full((1080,508,3),color,dtype=self.np.uint8)
        for i,x in enumerate([22,55,88,128,155][:icons]):
            rgb=(35,35,35) if i==0 else (215,20,30) if i<3 else (200,110,245)
            self.cv2.circle(image,(x,145),8,rgb,-1)
        return image

    def test_cloud_connected_panel_recovers_measured_dark_party_and_colored_shields(self):
        image=self.frame()
        panels=header_panels(image)
        values=classify_headers(panels)['mine']
        self.assertEqual(values['party']['value'],2)
        self.assertEqual(values['shields']['value'],2)
        self.assertTrue(any(p['geometry_source']=='fresh_five_glyph_header_row' for p in panels))

    def test_four_icons_do_not_manufacture_fifth_or_a_counter(self):
        self.assertEqual(header_row_panels(self.frame(icons=4)),[])

    def test_color_shapes_without_pale_header_background_are_rejected(self):
        self.assertEqual(header_row_panels(self.frame(color=(30,50,70))),[])

    def test_icons_on_different_rows_cannot_form_one_header(self):
        image=self.frame(icons=4)
        self.cv2.circle(image,(155,180),8,(200,110,245),-1)
        self.assertEqual(header_row_panels(image),[])

    def test_readable_physical_panel_keeps_priority(self):
        image=self.np.zeros((1080,508,3),dtype=self.np.uint8)
        image[90:171,:200]=self.frame()[90:171,:200]
        panels=header_panels(image)
        self.assertTrue(any(p['geometry_source']=='pale_component' for p in panels))
        self.assertFalse(any(p['geometry_source']=='fresh_five_glyph_header_row' for p in panels))
