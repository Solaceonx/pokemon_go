"""A hit on ours taken off by the rules (our bar unread) leaves it at 1 HP at least: their stats are guessed, and only
the game says ours fainted (2026-11-22, 191734: Melmetal, put at 0 by Tinkaton's Bulldoze, lived on 1%, and was
left off the bench at the next replacement prompt)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pogo.gamedata import GameData  # noqa: E402
from pogo.tracker import Observation, Tracker  # noqa: E402

GD = GameData()


class OurHealthFloor(unittest.TestCase):
    def test_a_hit_by_the_rules_does_not_faint_ours(self):
        tr = Tracker(GD, [GD.default("melmetal"), GD.default("altaria"), GD.default("jellicent")])
        for k in range(20):
            tr.update(Observation(t=k * 0.5, my_species="melmetal", foe_species="stunfisk_galarian", my_left=3,
                                  foe_left=3, my_shields=2, foe_shields=2))
        move = tr.foe.mon.build.charged[0]
        tr.foe.lo = tr.foe.hi = 100
        tr.me.mon.hp = 5
        tr.update(Observation(t=10.5, my_species="melmetal", foe_species="stunfisk_galarian", my_left=3, foe_left=3,
                              my_shields=2, foe_shields=2, foe_charged=True, foe_move=move.id))
        self.assertEqual(tr.me.mon.hp, 1)

    def test_a_reading_of_nothing_still_counts(self):
        tr = Tracker(GD, [GD.default("melmetal"), GD.default("altaria"), GD.default("jellicent")])
        tr.update(Observation(t=0.0, my_species="melmetal", foe_species="stunfisk_galarian", my_left=3, foe_left=3))
        tr.update(Observation(t=0.5, my_species="melmetal", foe_species="stunfisk_galarian", my_left=3, foe_left=3,
                              my_hp=0.0))
        self.assertEqual(tr.me.mon.hp, 0)


if __name__ == "__main__":
    unittest.main()
