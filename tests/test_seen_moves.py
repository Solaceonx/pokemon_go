"""A charged move named after its throw is a move seen, kept when another is learned (pogo.tracker.Tracker,
their_move_named / _learn_move). 2026-11-27, 124932: Quagsire's Stone Edge, in the guessed build and named at 45.6 s,
was dropped when Drain Punch was learned at 67.6 s, and the shield call at 88.3 s let Stone Edge through."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pogo.gamedata import GameData  # noqa: E402
from pogo.tracker import Observation, Tracker  # noqa: E402

GD = GameData()


def look(tr, t, **kw):
    tr.update(Observation(t=t, my_species="araquanid", foe_species="quagsire", my_left=3, foe_left=3,
                          my_shields=2, foe_shields=2, **kw))


def battle():
    tr = Tracker(GD, [GD.default("araquanid"), GD.default("clodsire"), GD.default("snorlax")])
    for k in range(20):
        look(tr, k * 0.5, my_hp=1.0)
    return tr


class SeenMoves(unittest.TestCase):
    def test_a_named_guess_is_kept_when_another_move_is_learned(self):
        tr = battle()
        guessed = [m.id for m in tr.foe.mon.build.charged]
        named = guessed[1]  # the old code dropped the second guess (Stone Edge was second in Quagsire's)
        new = next(i for i in GD.species["quagsire"]["chargedMoves"] if i in GD.moves and i not in guessed)
        # a throw with both moves paid for, so which one went is not known at the prompt; then its name
        tr.foe.lo = tr.foe.hi = tr.foe.mon.energy = 100
        look(tr, 10.0, my_hp=1.0, foe_charged=True)
        tr.their_move_named(10.3, named)
        for k in range(10):
            look(tr, 11 + k * 0.5, my_hp=0.9)
        # a second throw, of a move not in the guessed build
        tr.foe.lo = tr.foe.hi = tr.foe.mon.energy = 100
        look(tr, 20.0, my_hp=0.9, foe_charged=True)
        tr.their_move_named(20.3, new)
        have = [m.id for m in tr.foe.mon.build.charged]
        self.assertIn(named, have)
        self.assertIn(new, have)

    def test_the_name_beats_the_counts_attribution(self):
        tr = battle()
        cheap, dear = sorted(tr.foe.mon.build.charged, key=lambda m: m.energy)
        # the count affords only the cheaper move, so the throw is put down to it; the name then says the dearer
        tr.foe.lo = tr.foe.hi = tr.foe.mon.energy = dear.energy - 1
        look(tr, 10.0, my_hp=1.0, foe_charged=True)
        self.assertEqual(tr.foe.used.get(cheap.id), 1)
        tr.their_move_named(10.3, dear.id)
        self.assertFalse(tr.foe.used.get(cheap.id))
        self.assertEqual(tr.foe.used.get(dear.id), 1)
        # so a move learned later replaces the cheaper guess, not the move named
        new = next(i for i in GD.species["quagsire"]["chargedMoves"]
                   if i in GD.moves and i not in (cheap.id, dear.id))
        for k in range(10):
            look(tr, 11 + k * 0.5, my_hp=0.9)
        tr.foe.lo = tr.foe.hi = tr.foe.mon.energy = 100
        look(tr, 20.0, my_hp=0.9, foe_charged=True)
        tr.their_move_named(20.3, new)
        self.assertEqual({m.id for m in tr.foe.mon.build.charged}, {dear.id, new})

    def test_a_throw_known_at_the_prompt_is_not_counted_twice(self):
        tr = battle()
        move = tr.foe.mon.build.charged[0]
        tr.foe.lo = tr.foe.hi = tr.foe.mon.energy = 100
        look(tr, 10.0, my_hp=1.0, foe_charged=True, foe_move=move.id)  # known at once
        tr.their_move_named(10.3, move.id)  # and named after
        self.assertEqual(tr.foe.used.get(move.id), 1)


if __name__ == "__main__":
    unittest.main()
