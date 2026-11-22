"""Player.check_switch taps a switch again every 0.2 s until it shows (scripts/live/play_android.py, SPAM_SWITCH),
only while the bench strip looks as it did at the tap, and for SWITCH_SPAM_S at most."""
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
        slot, _, before, since, looked = p.switching
        p.switching = (slot, time.time() - pa.SWITCH_SPAM_S - 0.1, before, since, looked)
        self.check(p, self.before + 20)
        self.assertEqual(p.taps, [])

    def test_off_with_the_setting(self):
        p = player(self.before)
        with patch.object(pa, "SPAM_SWITCH", False):
            self.check(p, self.before + 20)
        self.assertEqual(p.taps, [])


if __name__ == "__main__":
    unittest.main()
