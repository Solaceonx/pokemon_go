"""NameReader: a form told apart by both type icons is kept when a later reading shows only one icon (2026-11-23,
231509: Galarian Weezing named plain "weezing" at two looks and two shield prompts as the icons faded in)."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pogo.android_screen import NameReader  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402

GD = GameData()


def reader():
    r = object.__new__(NameReader)
    NameReader.__init__(r, GD)
    r.ocr = lambda img: ([(None, "Weezing", 0.99)], None)
    return r


class FormIcons(unittest.TestCase):
    def read(self, r, types):
        r._busy = True
        r._read(np.zeros((4, 4, 3), np.uint8), 0.0, types)
        return r.species

    def test_two_icons_then_one_keeps_the_form(self):
        r = reader()
        self.assertEqual(self.read(r, ["fairy", "poison"]), "weezing_galarian")
        self.assertEqual(self.read(r, ["fairy"]), "weezing_galarian")
        self.assertEqual(self.read(r, []), "weezing_galarian")

    def test_one_icon_that_fits_a_form_does_not_undo_two(self):
        r = reader()
        self.read(r, ["fairy", "poison"])
        self.assertEqual(self.read(r, ["poison"]), "weezing_galarian")

    def test_the_usual_form_when_its_icon_shows(self):
        r = reader()
        self.assertEqual(self.read(r, ["poison"]), "weezing")


if __name__ == "__main__":
    unittest.main()
