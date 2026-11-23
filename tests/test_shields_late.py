"""Shield counters in the header lag the shield by a look to 5 s (2026-11-22: 341 of 342 shields of ours not yet
counted at the look that brought their move; in November 215 of 222 of theirs counted 0.5 to 5 s after our throw was
handed over, at our minigame's end, before they chose)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pogo.gamedata import GameData  # noqa: E402
from pogo.tracker import Observation, Tracker  # noqa: E402

GD = GameData()


def battle():
    tr = Tracker(GD, [GD.default("melmetal"), GD.default("altaria"), GD.default("jellicent")])
    for k in range(20):
        look(tr, k * 0.5, my_hp=1.0, foe_hp=1.0)
    return tr


def look(tr, t, my_shields=2, foe_shields=2, **kw):
    tr.update(Observation(t=t, my_species="melmetal", foe_species="stunfisk_galarian", my_left=3, foe_left=3,
                          my_shields=my_shields, foe_shields=foe_shields, **kw))


class OurShield(unittest.TestCase):
    def test_told_by_the_player_not_the_header(self):
        tr = battle()
        tr.foe.lo = tr.foe.hi = 100
        hp = tr.me.mon.hp
        tr.my_shield_used()
        look(tr, 10.5, foe_charged=True, foe_move=tr.foe.mon.build.charged[0].id)  # the header still says 2
        self.assertEqual(tr.me.shields, 1)
        self.assertGreaterEqual(tr.me.mon.hp, hp - 1)  # blocked: not the move's damage
        look(tr, 12.0)  # the header still lagging
        self.assertEqual(tr.me.shields, 1)
        look(tr, 30.0)  # long after: the header is believed
        self.assertEqual(tr.me.shields, 2)


class TheirShield(unittest.TestCase):
    def test_their_counter_late_gives_the_health_back(self):
        tr = battle()
        tr.me.mon.energy = 100
        before = tr.foe.mon.hp
        look(tr, 10.5, my_charged=0)  # our minigame over; their counter not yet down
        self.assertLess(tr.foe.mon.hp, before - 1)  # the hit taken off by the rules
        look(tr, 13.0, foe_shields=1)
        self.assertEqual(tr.foe.mon.hp, before - 1)

    def test_their_bar_read_first_is_the_witness(self):
        tr = battle()
        tr.me.mon.energy = 100
        look(tr, 10.5, my_charged=0)
        look(tr, 12.0, foe_hp=0.5)
        look(tr, 12.5, foe_hp=0.5)  # a drop past the count, believed on a second reading
        look(tr, 13.0, foe_shields=1)
        self.assertEqual(tr.foe.mon.hp, round(0.5 * tr.foe.mon.build.hp))


if __name__ == "__main__":
    unittest.main()
