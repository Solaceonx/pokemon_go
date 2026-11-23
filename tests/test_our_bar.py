"""Our health from our bar and their named moves (2026-11-22: after their throws, our tracked health was over 20% off
the next bar reading at 46 of 153; now 17)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pogo.battle import damage  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.tracker import Observation, Tracker  # noqa: E402

GD = GameData()


def look(tr, t, **kw):
    tr.update(Observation(t=t, my_species="melmetal", foe_species="stunfisk_galarian", my_left=3, foe_left=3,
                          my_shields=2, foe_shields=2, **kw))


def battle():
    tr = Tracker(GD, [GD.default("melmetal"), GD.default("altaria"), GD.default("jellicent")])
    for k in range(20):
        look(tr, k * 0.5, my_hp=1.0)
    tr.foe.lo = tr.foe.hi = tr.foe.mon.energy = 100  # both their moves paid for: which one went is not known
    return tr


class OurBar(unittest.TestCase):
    def test_a_bar_filling_as_ours_comes_in_is_doubted(self):
        tr = battle()
        look(tr, 10.0, my_hp=0.07)  # far below what their fast moves could do in half a second
        self.assertEqual(tr.me.mon.hp, tr.me.mon.build.hp)
        look(tr, 10.5, my_hp=0.9)
        self.assertEqual(tr.me.mon.hp, round(0.9 * tr.me.mon.build.hp))

    def test_a_drop_read_twice_is_believed(self):
        tr = battle()
        look(tr, 10.0, my_hp=0.3)
        look(tr, 10.5, my_hp=0.3)
        self.assertEqual(tr.me.mon.hp, round(0.3 * tr.me.mon.build.hp))

    def test_their_move_named_after_a_bar_not_caught_up(self):
        tr = battle()
        full = tr.me.mon.hp
        look(tr, 10.0, my_hp=1.0, foe_charged=True)  # the bar from before the hit; the move not named yet
        self.assertEqual(tr.me.mon.hp, full)
        move = tr.foe.mon.build.charged[0]
        tr.their_move_named(10.3, move.id)
        self.assertEqual(tr.me.mon.hp, max(1, full - damage(tr.foe.mon, move, tr.me.mon)))


if __name__ == "__main__":
    unittest.main()
