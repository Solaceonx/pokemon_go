"""The phone's health-bar reader (pogo/android_screen.py): a bar found anywhere with all its checks, and the held
fallback where one was just read, on drawn frames of the phone's size (540 x 1200)."""
import unittest

import numpy as np

from pogo import android_screen as screen

GREEN, RED, DARK, LIGHT = (44, 249, 188), (235, 100, 105), (40, 60, 90), (245, 245, 245)


def frame(share: float, colour=GREEN, x0: int = 34, y: int = 780, borders: bool = True, over_empty=None,
          header: bool = True):
    """A night-blue frame with one health bar: light frame round it, the fill from x0, the dark empty part after;
    with the header's two light boxes (the fight view) unless header is False."""
    a = np.zeros((1200, 540, 3), np.uint8)
    a[:] = (30, 50, 110)
    if header:
        for x, yy in screen.HEADER_PATCHES:
            a[yy - 6:yy + 7, x - 20:x + 21] = (235, 238, 240)
    full = int(screen.BAR_INSIDE)
    a[y - 3:y + 11, x0 - 4:x0 + full + 4] = LIGHT if borders else (30, 50, 110)
    a[y:y + 8, x0:x0 + full] = DARK
    a[y:y + 8, x0:x0 + int(round(share * screen.BAR_INSIDE))] = colour
    if over_empty is not None:
        a[y:y + 8, x0 + int(share * full) + 4:x0 + full] = over_empty
    return a


class Bars(unittest.TestCase):
    def setUp(self):
        screen._HINTS.clear()

    def test_a_bar_with_its_borders_is_found(self):
        got = screen.bar_places(frame(0.62))
        self.assertIn("mine", got)
        self.assertAlmostEqual(got["mine"][0], 0.62, delta=0.02)
        self.assertEqual(got["mine"][2], 34)

    def test_borders_hidden_found_only_where_one_was_just_read(self):
        hidden = frame(0.6, borders=False)
        self.assertNotIn("mine", screen.bars(hidden))
        self.assertNotIn("mine", screen.bars_held(hidden, 0.0))  # nothing read before: no place to look
        screen.bars_held(frame(0.62), 1.0)
        self.assertAlmostEqual(screen.bars_held(hidden, 1.5)["mine"], 0.6, delta=0.02)
        self.assertNotIn("mine", screen.bars_held(hidden, 5.0))  # the place is too old by then

    def test_a_red_sliver_at_low_health(self):
        screen.bars_held(frame(0.1, RED), 0.0)
        got = screen.bars_held(frame(0.04, RED, borders=False), 0.5)
        self.assertAlmostEqual(got["mine"], 0.04, delta=0.015)

    def test_not_higher_than_the_last_reading(self):
        screen.bars_held(frame(0.3), 0.0)
        self.assertNotIn("mine", screen.bars_held(frame(0.8, borders=False), 0.5))

    def test_not_when_the_empty_part_is_covered(self):
        screen.bars_held(frame(1.0), 0.0)
        covered = frame(0.55, borders=False, over_empty=LIGHT)  # "GO!" over the bar
        self.assertNotIn("mine", screen.bars_held(covered, 0.5))

    def test_no_place_taken_from_a_camera_pan(self):
        screen.bars_held(frame(0.62, header=False), 1.0)  # the header down: a pan or a close-up
        self.assertNotIn("mine", screen.bars_held(frame(0.6, borders=False), 1.5))

    def test_not_a_pixel_or_two(self):
        screen.bars_held(frame(0.35), 0.0)
        self.assertNotIn("mine", screen.bars_held(frame(0.007, borders=False), 0.5))


if __name__ == "__main__":
    unittest.main()
