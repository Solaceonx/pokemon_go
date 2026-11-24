"""Tracker._set_fast: a fast move refitted to one of the same length that charges slower (told apart only by the size
of its hits) keeps the top of their energy range where it was (2026-11-23, 224221: Walrein's Powder Snow refitted as
Frost Breath, its count put from 64 to 35 three seconds before its Earthquake, 65)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pogo.gamedata import GameData  # noqa: E402
from pogo.tracker import Observation, Tracker  # noqa: E402

GD = GameData(league=2500)


def walrein_counted():
    tr = Tracker(GD, [GD.default("blastoise"), GD.default("melmetal"), GD.default("skeledirge")])
    tr.update(Observation(t=0.0, my_species="blastoise", foe_species="walrein", my_left=3, foe_left=3))
    foe = tr.foe
    foe.mon.build = GD.build("walrein", ["POWDER_SNOW", *(m.id for m in foe.mon.build.charged)], allow_forms=True)
    foe.base, foe.clock = (0, 0), 16  # eight Powder Snows: 64
    foe.lo = foe.hi = 64
    return tr, foe


class RefitFast(unittest.TestCase):
    def test_same_length_slower_keeps_the_top(self):
        tr, foe = walrein_counted()
        tr._set_fast(5.0, foe, GD.moves["FROST_BREATH"])
        self.assertEqual(foe.lo, 40)  # eight Frost Breaths
        self.assertEqual(foe.hi, 64)

    def test_another_length_is_counted_afresh(self):
        tr, foe = walrein_counted()
        tr._set_fast(5.0, foe, GD.moves["WATERFALL"])  # 3 turns
        self.assertEqual(foe.hi, foe.lo)


if __name__ == "__main__":
    unittest.main()
