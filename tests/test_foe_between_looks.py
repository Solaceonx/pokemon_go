"""A new name of theirs read between looks (2026-11-22: 7 of 154 changes reached the tracker 7 to 11 s late, read
just before a charged move and handed over only at the look after it).

Tracker.their_active_seen takes the change at once, with the Pokémon's own stored count, and leaves the turns to the
next look, which credits them as a look given the change would have. Player.throw drops a move decided on the one
that has gone, unless ours is low (stick)."""
import importlib.util
import sys
import types
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts" / "live"))
_stub = "cv2" not in sys.modules and importlib.util.find_spec("cv2") is None
if _stub:
    sys.modules["cv2"] = types.ModuleType("cv2")
try:
    import play_android as pa  # noqa: E402
finally:
    if _stub:
        del sys.modules["cv2"]
from pogo.gamedata import GameData  # noqa: E402
from pogo.tracker import Observation, Tracker  # noqa: E402

GD = GameData()


def look(tr, t, foe, **kw):
    tr.update(Observation(t=t, my_species="melmetal", foe_species=foe, my_left=3, foe_left=3, **kw))


def stunfisk_azumarill_stunfisk():
    """Stunfisk 0-5 s, Azumarill 5.5-10 s (its count kept when it leaves), Stunfisk again 10.5-12 s."""
    tr = Tracker(GD, [GD.default("melmetal"), GD.default("altaria"), GD.default("jellicent")])
    for k in range(25):
        look(tr, k * 0.5, "stunfisk" if k <= 10 or k >= 21 else "azumarill")
    return tr


class TrackerBetweenLooks(unittest.TestCase):
    def test_the_one_named_is_out_with_its_own_count(self):
        tr = stunfisk_azumarill_stunfisk()
        stored = tr.foes["azumarill"].hi
        self.assertEqual(tr.their_active_seen(12.2, "azumarill", out_for=0.1), "switch")
        self.assertEqual(tr.foe.mon.build.species_id, "azumarill")
        self.assertEqual(tr.foe.hi, stored)  # what a shield call now sees, not Stunfisk's count
        self.assertGreater(tr.foe_switch_at, 12.2)

    def test_the_next_look_counts_as_a_look_told_of_the_change(self):
        between = stunfisk_azumarill_stunfisk()
        between.their_active_seen(12.2, "azumarill", out_for=0.1)
        told = stunfisk_azumarill_stunfisk()
        look(told, 12.5, "azumarill", foe_out_for=0.4)  # the same reading, at the look
        look(between, 12.5, "azumarill")
        for tr in (between, told):
            for k in range(26, 31):
                look(tr, k * 0.5, "azumarill")
        self.assertEqual({s: (f.lo, f.hi) for s, f in between.foes.items()},
                         {s: (f.lo, f.hi) for s, f in told.foes.items()})

    def test_the_same_one_changes_nothing(self):
        tr = stunfisk_azumarill_stunfisk()
        self.assertIsNone(tr.their_active_seen(12.2, "stunfisk"))
        self.assertEqual(tr.foe.mon.build.species_id, "stunfisk")


class Stop(Exception):
    pass


def player(species_read, seen="stunfisk"):
    """A player whose tracker was last told `seen`, with `species_read` the latest name read."""
    p = object.__new__(pa.Player)
    p.logged, p.touched = [], []
    p.log = lambda kind, t, **kw: p.logged.append((kind, kw))
    p.now = lambda: 1.0
    p.names = types.SimpleNamespace(species=species_read, read_at=0.9, offer=lambda rgb, t: None)
    p.foe_seen_species = seen
    p.tracker = Tracker(GD, [GD.default("melmetal"), GD.default("altaria"), GD.default("jellicent")])
    look(p.tracker, 0.0, seen)
    p.queued, p.practised, p.tapping, p.active = None, {}, True, 0
    p.team = [GD.default("melmetal")]
    p.label_move = lambda rgb, k: None
    p.header_says = lambda: 0
    p.clear_of_fast_taps = lambda: None
    p.t0, p.frame_t, p.off_time, p.fight_frame_t = 0.0, None, 0.0, 0.0
    black = np.zeros((2400, 1080, 3), dtype=np.uint8)
    p.phone = types.SimpleNamespace(frame=lambda: (black, 0.0), next_frame=lambda last, timeout=0.3: (black, last + 0.05))
    return p


class ThrowOnTheOneOut(unittest.TestCase):
    def test_not_tapped_when_theirs_changed_since_the_decision(self):
        p = player("azumarill")
        p.touch = lambda point, note: p.touched.append(note)
        p.throw(1.0, 0, p.team[0].charged[0])
        self.assertEqual(p.touched, [])
        self.assertEqual(p.logged[-1][0], "throw_cancelled")

    def test_tapped_anyway_when_ours_is_low(self):
        p = player("azumarill")

        def touch(point, note):
            raise Stop
        p.touch = touch
        with self.assertRaises(Stop):
            p.throw(1.0, 0, p.team[0].charged[0], stick=True)

    def test_taps_stop_when_theirs_changes_while_ours_waits(self):
        p = player("stunfisk")

        def touch(point, note):
            p.touched.append(note)
            p.names.species = "azumarill"  # read on the frames after the tap
        p.touch = touch
        p.throw(1.0, 0, p.team[0].charged[0])
        self.assertEqual(len(p.touched), 1)
        self.assertEqual(p.logged[-1][0], "throw_dropped")
        self.assertIsNotNone(p.queued)  # a move that goes anyway is still swiped
        self.assertTrue(p.queued_retapped)  # and not tapped again

    def test_handed_to_the_tracker_at_once(self):
        p = player("azumarill")
        self.assertTrue(p.foe_now(1.0, "shield prompt"))
        self.assertEqual(p.tracker.foe.mon.build.species_id, "azumarill")
        self.assertFalse(p.foe_name_new())
        self.assertFalse(p.foe_now(1.1, "shield prompt"))


class TellCorrection(unittest.TestCase):
    """Player.tell_correction: how a change of ours the player found came about, told to the tracker."""

    def kind(self, switch_ago=60.0, replace_ago=60.0, alive=(True, True, True), low=False, throw_ago=60.0):
        import time
        p = object.__new__(pa.Player)
        p.switching, p.active = None, 0
        p.switch_last_tap, p.replace_tapped = time.time() - switch_ago, time.time() - replace_ago
        p.team = [GD.default("melmetal"), GD.default("altaria"), GD.default("jellicent")]
        p.tracker = Tracker(GD, list(p.team))
        p.their_throw_at = time.time() - throw_ago
        for m, up in zip(p.tracker.me.team, alive):
            m.hp = m.hp if up else 0
        if low:
            p.tracker.me.team[0].hp = 10
        return p.tell_correction()

    def test_our_switch_is_left_to_the_tracker(self):
        self.assertIsNone(self.kind(switch_ago=2.0))

    def test_after_a_replacement_tap_no_faint(self):
        self.assertEqual(self.kind(replace_ago=5.0), "none")

    def test_our_last_sent_in(self):
        self.assertEqual(self.kind(alive=(True, False, True), low=True), "faint")
        self.assertEqual(self.kind(alive=(True, False, True), throw_ago=3.0), "faint")

    def test_no_faint_where_none_was_likely(self):
        self.assertEqual(self.kind(alive=(True, False, True)), "unsure")

    def test_two_others_alive_left_to_the_counter(self):
        self.assertEqual(self.kind(), "unsure")


class TypesGuard(unittest.TestCase):
    """Player.check_active: our header's type icons do not bring back one the tracker has fainted (2026-11-22, 151353:
    misread icons put Feraligatr, fainted, back out for 3 s, and Virizion's bar was put to it)."""

    def setup(self, left):
        import threading
        p = object.__new__(pa.Player)
        p.my_left_seen = left
        p.logged = []
        p.log = lambda kind, t, **kw: p.logged.append(kind)
        p.switching, p.active, p._last_active, p.active_changed_at = None, 0, 0, 0.0
        p.names = types.SimpleNamespace(my_name_at=None, labels_at=None, _lock=threading.Lock(), _mine_sig=None,
                                        _label_sig=None, my_name="", labels=[])
        p.header_checked = p.types_checked = p.labels_checked = None
        p.header_says = lambda: None
        p.header_confirmed_at = 0.0
        p.team = [GD.default("melmetal"), GD.default("altaria"), GD.default("jellicent")]
        p.tracker = Tracker(GD, list(p.team))
        p.tracker.me.team[2].hp = 0
        p.types_seen = (2, 5.0)
        p.tell_correction = lambda: None
        p.check_active(5.5)
        return p

    def test_a_fainted_one_is_not_taken_for_out(self):
        p = self.setup(left=2)  # the count of ours left shows the faint
        self.assertEqual(p.active, 0)
        self.assertIn("types_ignored", p.logged)

    def test_unless_the_count_does_not_show_the_faint(self):
        p = self.setup(left=3)  # 2026-11-23, 205934: a faint from a false prompt
        self.assertEqual(p.active, 2)
        self.assertNotIn("types_ignored", p.logged)


class NewcomersBar(unittest.TestCase):
    """give_look: soon after a switch tap, a bar far over the one believed out is the newcomer's (health does not come
    back), not credited to it (2026-11-22, 191031: Skeledirge's full bar put to Melmetal on 24%)."""

    def test_not_credited(self):
        import time
        p = player("stunfisk")
        p.tracker.me.team[0].hp = round(0.24 * p.tracker.me.team[0].build.hp)
        p.switching, p.switch_last_tap = None, time.time() - 2.0
        bar = 0.997
        believed = p.tracker.me.team[p.active]
        self.assertTrue(time.time() - p.switch_last_tap < 6.0 and bar > believed.hp / believed.build.hp + 0.25)


if __name__ == "__main__":
    unittest.main()
