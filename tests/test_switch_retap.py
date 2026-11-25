"""Player.check_switch taps a switch again every 0.2 s until it shows (scripts/live/play_android.py, SPAM_SWITCH),
only while the bench strip looks as it did at the tap, and for SWITCH_SPAM_S of fight on screen at most (close-ups and
charged moves do not count: 2026-11-24, the window ran out in the close-up after our own throw)."""
import importlib.util
import sys
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "live"))
# check_switch uses no OpenCV; where it is not installed (the Mac) a stand-in lets the module load, and is taken out
# of sys.modules again so that nothing else imports it
_stub = "cv2" not in sys.modules and importlib.util.find_spec("cv2") is None
if _stub:
    sys.modules["cv2"] = types.ModuleType("cv2")
try:
    import play_android as pa  # noqa: E402
finally:
    if _stub:
        del sys.modules["cv2"]


def player(before):
    p = object.__new__(pa.Player)
    mon = types.SimpleNamespace(name="Stunfisk", charged=[types.SimpleNamespace(energy=40)])
    other = types.SimpleNamespace(name="Jellicent", charged=[types.SimpleNamespace(energy=45)])
    p.team, p.active, p.t0 = [other, mon], 0, None
    p.switching = (1, time.time(), before, None, 0)
    p.switch_point, p.switch_last_tap = pa.BENCH[0], time.time() - 1.0
    p.switch_fight_s, p.switch_fight_last = 0.0, time.time()
    p._switch_fits, p.switch_retried, p.switch_wanted = [], False, None
    p.hold_taps_until, p.switch_ready_at, p.energy_read, p._energy_raw = 0.0, 0.0, None, None
    p.names = types.SimpleNamespace(labels_at=None, my_name_at=None)
    p.labels_say = lambda: None
    p.header_says = lambda: None
    p.taps, p.logged = [], []
    p.touch = lambda point, note: p.taps.append((point, note))
    p.log = lambda kind, t, **kw: p.logged.append(kind)
    return p


class SwitchRetap(unittest.TestCase):
    def setUp(self):
        self.before = np.zeros((4, 4, 3), np.int16)

    def check(self, p, strip):
        with patch.object(pa.screen, "my_energy", return_value=None), \
                patch.object(pa.screen, "bench_strip", return_value=strip):
            p.check_switch(1.0, None)

    def test_tapped_again_while_the_strip_is_unchanged(self):
        p = player(self.before)
        self.check(p, self.before + 20)  # an ignored tap leaves the strip within 17 to 31
        self.assertEqual(len(p.taps), 1)
        self.assertEqual(p.taps[0][0], pa.BENCH[0])
        self.assertIn("switch_retap", p.logged)
        self.assertGreater(p.hold_taps_until, time.time() + 1.0)  # fast taps held after it
        self.check(p, self.before + 20)  # within 0.2 s of that tap: not again
        self.assertEqual(len(p.taps), 1)

    def test_not_tapped_once_the_strip_has_changed(self):
        p = player(self.before)
        self.check(p, self.before + 70)  # a switch moves it 60 to 75; a camera cut too
        self.assertEqual(p.taps, [])

    def test_not_tapped_after_the_spam_window(self):
        p = player(self.before)
        p.switch_fight_s = pa.SWITCH_SPAM_S + 0.1
        self.check(p, self.before + 20)
        self.assertEqual(p.taps, [])

    def test_window_counts_the_fight_not_the_clock(self):
        # 174318, 111 s: tapped 0.3 s after Stone Edge's minigame, ignored; the fight back 3 s later after the close-up
        p = player(self.before)
        slot, _, before, since, looked = p.switching
        p.switching = (slot, time.time() - 4.0, before, since, looked)  # 4 s on the clock
        p.switch_fight_s, p.switch_fight_last = 1.0, time.time() - 2.5  # 1 s of fight, then 2.5 s off the screen
        p.switch_last_tap = time.time() - 3.0
        self.check(p, self.before + 20)
        self.assertEqual(len(p.taps), 1)  # tapped again now the fight is back
        self.assertLess(p.switch_fight_s, 1.3)  # the close-up added at most a frame's worth
        self.assertIsNotNone(p.switching)

    def test_strip_taken_afresh_when_the_fight_is_back(self):
        # tapped in Stone Edge's animation, the strip then unlike the fight's: compared with the fight's once it is back
        p = player(self.before)
        p.switch_fight_s, p.switch_fight_last = 1.0, time.time() - 2.5
        p.switch_last_tap = time.time() - 3.0
        self.check(p, self.before + 70)  # 70 from the strip at the tap
        self.assertEqual(len(p.taps), 1)
        p.switch_last_tap = time.time() - 0.3
        self.check(p, self.before + 70)  # the same strip again: still the same, tapped again
        self.assertEqual(len(p.taps), 2)
        p.switch_last_tap = time.time() - 0.3
        self.check(p, self.before + 140)  # now it moves: the switch has gone, or the camera cut
        self.assertEqual(len(p.taps), 2)

    def test_header_waits_for_the_window(self):
        # the header still naming the one out 1.5 s after the tap does not end the switch while re-taps remain
        p = player(self.before)
        slot, _, before, since, looked = p.switching
        p.switching = (slot, time.time() - 4.0, before, since, looked)
        p.switch_fight_s = 1.0
        p.names.my_name_at = 10.0
        p.header_says = lambda: 0
        self.check(p, self.before + 20)
        self.assertNotIn("switch_not_taken", p.logged)
        p.switch_fight_s = pa.SWITCH_SPAM_S
        self.check(p, self.before + 20)
        self.assertIn("switch_not_taken", p.logged)
        self.assertEqual(p.switch_wanted, 1)  # tried once more

    def test_given_up_after_five_seconds_of_fight(self):
        p = player(self.before)
        p.switch_fight_s = 5.0
        self.check(p, self.before + 20)
        self.assertIn("switch_not_taken", p.logged)
        self.assertIsNone(p.switching)

    def test_off_with_the_setting(self):
        p = player(self.before)
        with patch.object(pa, "SPAM_SWITCH", False):
            self.check(p, self.before + 20)
        self.assertEqual(p.taps, [])


class SwitchWentLate(unittest.TestCase):
    """173951: Snorlax tapped at 112.9 s, judged not taken, named by the header at 124.7 s: the timer from the tap."""

    def player(self, ago):
        p = player(np.zeros((4, 4, 3), np.int16))
        p.switching, p.switch_tapped_to, p.switch_last_tap = None, 1, time.time() - ago
        return p

    def test_timer_from_the_tap(self):
        p = self.player(11.8)
        p.switch_went_late(124.7, 1)
        self.assertAlmostEqual(p.switch_ready_at, p.switch_last_tap + 45, places=3)
        self.assertIn("switch_seen_late", p.logged)

    def test_not_for_another_or_an_old_tap(self):
        p = self.player(11.8)
        p.switch_went_late(124.7, 0)
        p2 = self.player(50.0)
        p2.switch_went_late(124.7, 1)
        self.assertEqual((p.switch_ready_at, p2.switch_ready_at), (0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
