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
        screen._ACCEPTED.clear()
        screen._DROPS.clear()

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
        self.assertIn("mine", screen.bars_held(hidden, 8.0))  # still kept 7 s on (a charged move's length)
        self.assertNotIn("mine", screen.bars_held(hidden, 20.0))  # too old by then

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


class WholeReader(unittest.TestCase):
    def test_read_runs_on_a_frame(self):
        """screen.read uses every part of the reader (bars, buttons, prompts, the header's counts)."""
        screen._HINTS.clear(); screen._ACCEPTED.clear(); screen._DROPS.clear()
        look = screen.read(frame(0.5), 0.0)
        self.assertTrue(look.header)
        self.assertAlmostEqual(look.bars["mine"], 0.5, delta=0.02)
        self.assertIsNone(screen.my_energy(frame(0.5), [40, 45]))  # no buttons drawn: no reading


class Drops(unittest.TestCase):
    """A big drop is given out only once it repeats; a rise (a Pokémon coming in) at once."""

    def setUp(self):
        screen._HINTS.clear()
        screen._ACCEPTED.clear()
        screen._DROPS.clear()

    def test_a_single_frame_drop_is_held_back(self):
        self.assertAlmostEqual(screen.bars_held(frame(0.95), 0.0)["mine"], 0.95, delta=0.01)
        self.assertNotIn("mine", screen.bars_held(frame(0.03), 0.05))  # one frame at 3%: not given out
        self.assertAlmostEqual(screen.bars_held(frame(0.94), 0.1)["mine"], 0.94, delta=0.01)

    def test_a_drop_that_lasts_is_given_out(self):
        screen.bars_held(frame(0.95), 0.0)
        got = [screen.bars_held(frame(0.4), 0.05 * k).get("mine") for k in range(1, 5)]
        self.assertEqual(got[:2], [None, None])
        self.assertAlmostEqual(got[2], 0.4, delta=0.01)  # the third reading in a row confirms it
        self.assertAlmostEqual(got[3], 0.4, delta=0.01)

    def test_a_rise_is_given_out_at_once(self):
        screen.bars_held(frame(0.1), 0.0)
        self.assertAlmostEqual(screen.bars_held(frame(1.0), 0.05)["mine"], 1.0, delta=0.01)


if __name__ == "__main__":
    unittest.main()
