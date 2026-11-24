"""Who is out and who fainted, with the counters of Pokémon left lagging the names (2026-11-22: they fell a look to
10 s after the change; 20 of ours and 21 of theirs were put at 0 HP while alive and came back out with health)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pogo.gamedata import GameData  # noqa: E402
from pogo.tracker import Observation, Tracker  # noqa: E402

GD = GameData()


def tracker():
    return Tracker(GD, [GD.default("melmetal"), GD.default("altaria"), GD.default("jellicent")])


def look(tr, t, me="melmetal", foe="stunfisk", my_left=3, foe_left=3, **kw):
    tr.update(Observation(t=t, my_species=me, foe_species=foe, my_left=my_left, foe_left=foe_left, **kw))


def hp(tr, species):
    return next(m.hp for m in tr.me.team if m.build.species_id == species)


class OursAfterAReplacement(unittest.TestCase):
    def test_the_counter_catching_up_is_no_faint_to_come(self):
        # Melmetal faints at the prompt; Altaria comes in; the counter falls 2 s later; we switch Altaria out alive.
        tr = tracker()
        look(tr, 0.0)
        tr.my_fainted()
        look(tr, 1.0, me="altaria")
        look(tr, 3.0, me="altaria", my_left=2)
        look(tr, 20.0, me="jellicent", my_left=2)
        self.assertEqual(hp(tr, "melmetal"), 0)
        self.assertGreater(hp(tr, "altaria"), 0)
        self.assertGreater(tr.my_switch_at, 20.0)  # a switch: its timer runs

    def test_a_fall_nothing_explains_is_still_a_faint_to_come(self):
        tr = tracker()
        look(tr, 0.0)
        look(tr, 1.0, my_left=2)  # the counter before the header
        look(tr, 2.0, me="altaria", my_left=2)
        self.assertEqual(hp(tr, "melmetal"), 0)


class TheirsWithALateCounter(unittest.TestCase):
    def test_a_change_then_the_counter_within_3_s_was_a_faint(self):
        tr = tracker()
        look(tr, 0.0)
        look(tr, 1.0, foe="azumarill")  # taken for a switch: its timer starts
        self.assertGreater(tr.foe_switch_at, 1.0)
        look(tr, 1.5, foe="azumarill", foe_left=2)
        self.assertEqual(tr.foes["stunfisk"].mon.hp, 0)
        self.assertLessEqual(tr.foe_switch_at, 1.0)  # undone

    def test_a_switch_then_a_faint_much_later_is_the_one_out(self):
        tr = tracker()
        look(tr, 0.0)
        look(tr, 1.0, foe="azumarill")
        look(tr, 20.0, foe="azumarill", foe_left=2)  # the one out, before its replacement shows
        look(tr, 22.0, foe="medicham", foe_left=2)
        self.assertGreater(tr.foes["stunfisk"].mon.hp, 0)
        self.assertEqual(tr.foes["azumarill"].mon.hp, 0)


class OursCorrected(unittest.TestCase):
    def test_our_last_sent_in_unasked_fainted_the_one_believed_out(self):
        tr = tracker()
        look(tr, 0.0)
        tr.my_fainted()
        look(tr, 1.0, me="altaria", my_left=2)  # Melmetal fainted at the prompt
        tr.my_active_corrected("faint")  # Altaria fainted; the game sent Jellicent in
        look(tr, 30.0, me="jellicent", my_left=2)
        self.assertEqual(hp(tr, "altaria"), 0)
        self.assertLessEqual(tr.my_switch_at, 30.0)  # no switch timer
        look(tr, 40.0, me="jellicent", my_left=1)  # the counter, 10 s late: nothing more
        self.assertGreater(hp(tr, "jellicent"), 0)

    def test_another_than_the_one_chosen_at_the_prompt(self):
        tr = tracker()
        look(tr, 0.0)
        tr.my_fainted()
        look(tr, 1.0, me="altaria")  # chosen
        tr.my_active_corrected("none")  # the game sent in Jellicent
        look(tr, 2.0, me="jellicent")
        look(tr, 3.0, me="jellicent", my_left=2)
        self.assertGreater(hp(tr, "altaria"), 0)
        self.assertGreater(hp(tr, "jellicent"), 0)
        self.assertLessEqual(tr.my_switch_at, 2.0)

    def test_unsure_is_settled_by_the_counter_however_late(self):
        tr = tracker()
        look(tr, 0.0)
        tr.my_active_corrected("unsure")
        look(tr, 1.0, me="altaria")
        self.assertGreater(hp(tr, "melmetal"), 0)
        look(tr, 9.0, me="altaria", my_left=2)
        self.assertEqual(hp(tr, "melmetal"), 0)



class OurTappedSwitch(unittest.TestCase):
    def test_the_counter_after_our_switch_is_the_newcomer_fainting(self):
        # 2026-11-23, 214336: we switch Melmetal out for Altaria; Altaria faints 2.6 s later, the counter falls first
        tr = tracker()
        look(tr, 0.0)
        tr.my_switch_tapped(0.5)
        look(tr, 1.0, me="altaria")
        look(tr, 3.6, me="altaria", my_left=2)
        self.assertGreater(hp(tr, "melmetal"), 0)
        look(tr, 5.0, me="jellicent", my_left=2)
        self.assertEqual(hp(tr, "altaria"), 0)

    def test_an_untapped_change_then_the_counter_is_still_a_late_faint(self):
        tr = tracker()
        look(tr, 0.0)
        look(tr, 1.0, me="altaria")
        look(tr, 2.0, me="altaria", my_left=2)
        self.assertEqual(hp(tr, "melmetal"), 0)


if __name__ == "__main__":
    unittest.main()
