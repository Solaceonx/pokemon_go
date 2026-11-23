"""Tracker._maybe_shadow: their Pokémon taken for a shadow when two or more of its charged hits on ours, measured
by our bar before and after, came to 1.13 or more of the rules' damage by the median (a shadow does 1.2 times)."""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pogo.battle import damage  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.tracker import Observation, Tracker  # noqa: E402

GD = GameData(league=2500)


def battle(scale):
    tr = Tracker(GD, [GD.default("registeel"), GD.default("cresselia"), GD.default("giratina_altered")])
    t = 0.0

    def look(**kw):
        nonlocal t
        t += 0.5
        tr.update(Observation(t=t, my_species="registeel", foe_species="swampert", my_left=3, foe_left=3, **kw))

    for _ in range(4):
        look(my_hp=1.0)
    for _ in range(2):
        tr.foe.lo = tr.foe.hi = tr.foe.mon.energy = 100
        move = tr.foe.mon.build.charged[0]
        mine = tr.me.mon
        hp = mine.hp
        hurt = damage(tr.foe.mon, move, mine)
        look(my_hp=hp / mine.build.hp, foe_charged=True, foe_move=move.id)  # the bar from before the hit
        look(my_hp=(hp - round(scale * hurt)) / mine.build.hp)
        look(my_hp=(hp - round(scale * hurt)) / mine.build.hp)
    return tr


class ShadowByDamage(unittest.TestCase):
    def test_hits_a_fifth_harder_make_a_shadow(self):
        tr = battle(1.2)
        self.assertEqual(tr.foe.mon.build.species_id, "swampert_shadow")
        self.assertIn("swampert_shadow", tr.foes)
        tr.update(Observation(t=20.0, my_species="registeel", foe_species="swampert", my_left=3, foe_left=3))
        self.assertEqual(tr.foe.mon.build.species_id, "swampert_shadow")  # the plain name read still means it

    def test_hits_as_the_rules_say_leave_it_plain(self):
        self.assertEqual(battle(1.02).foe.mon.build.species_id, "swampert")


if __name__ == "__main__":
    unittest.main()
