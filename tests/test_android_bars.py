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


class PaleYellow(unittest.TestCase):
    """The phone's yellow at a third of the bar or so, (253, 249, 122): blue over 120 (2026-11-22: Venusaur on 36% read
    0.013); a gold Pokémon is that colour too, so only at a yellow bar's length, and after a bar of the usual colours."""
    PALE = (253, 249, 122)

    def setUp(self):
        screen._HINTS.clear()
        screen._ACCEPTED.clear()
        screen._DROPS.clear()

    def test_read_at_a_yellow_bars_length(self):
        got = screen.bar_places(frame(0.36, colour=self.PALE))
        self.assertAlmostEqual(got["mine"][0], 0.36, delta=0.02)

    def test_not_at_a_length_no_yellow_bar_has(self):
        self.assertNotIn("mine", screen.bar_places(frame(0.07, colour=self.PALE)))
        self.assertNotIn("mine", screen.bar_places(frame(0.9, colour=self.PALE)))

    def test_a_green_bar_before_a_pale_one(self):
        a = frame(0.5, y=780)
        b = frame(0.3, colour=self.PALE, y=600)
        a[590:615] = b[590:615]
        a[597:612, 30:33] = (245, 245, 245)
        got = screen.bar_places(a)
        self.assertAlmostEqual(got["mine"][0], 0.5, delta=0.02)


class CreamBorderOverGold(unittest.TestCase):
    """Our bar over Melmetal (2026-11-23): its cream border is low in blue, read by its mean, and the bar, closed at its
    right end, is found; a run with no right end and no sharp border is not."""

    def setUp(self):
        screen._HINTS.clear()
        screen._ACCEPTED.clear()
        screen._DROPS.clear()

    def bar(self, share, right_end=True):
        a = frame(share)
        y, x0, full = 780, 34, int(screen.BAR_INSIDE)
        a[y - 30:y + 40, 0:540] = (170, 130, 50)  # gold behind
        a[y - 3:y + 11, x0 - 4:x0 + full + 4] = (240, 215, 165) if right_end else (170, 130, 50)
        a[y - 3:y, x0 - 4:x0 + full] = (240, 215, 165)  # the top border
        a[y - 3:y + 11, x0 - 4:x0] = (230, 170, 140)  # the left border: blue under 150, its mean over
        a[y:y + 8, x0:x0 + full] = (100, 70, 30)  # the see-through empty part, darkened gold
        a[y:y + 8, x0:x0 + int(round(share * screen.BAR_INSIDE))] = GREEN
        return a

    def test_found(self):
        got = screen.bar_places(self.bar(0.85))
        self.assertAlmostEqual(got["mine"][0], 0.85, delta=0.02)

    def test_not_without_its_right_end(self):
        self.assertNotIn("mine", screen.bar_places(self.bar(0.85, right_end=False)))


if __name__ == "__main__":
    unittest.main()


class Countdown(unittest.TestCase):
    """Their charged move's countdown at the top centre (2026-11-09): a slate disc there, the sky otherwise."""

    def frame(self, disc: bool):
        a = np.zeros((1200, 540, 3), np.uint8)
        a[:] = (200, 235, 247)  # sky
        if disc:
            yy, xx = np.mgrid[0:1200, 0:540]
            a[(xx - 270) ** 2 + (yy - 95) ** 2 <= 44 ** 2] = (100, 115, 122)
            a[(xx - 270) ** 2 + (yy - 95) ** 2 <= 8 ** 2] = (255, 255, 255)  # the number
        return a

    def test_disc_is_a_countdown(self):
        self.assertTrue(screen.countdown(self.frame(True)))

    def test_sky_is_not(self):
        self.assertFalse(screen.countdown(self.frame(False)))


class OneButtonEnergy(unittest.TestCase):
    """my_energy_one reads nothing where no buttons are drawn (a plain frame: no rims)."""

    def test_no_buttons_no_reading(self):
        a = np.zeros((1200, 540, 3), np.uint8)
        a[:] = (90, 140, 70)  # grass
        self.assertIsNone(screen.my_energy_one(a, [40, 65]))
