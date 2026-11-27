"""The low-health rules read only the one out's own health (Player.settled_out, Player.hp_now). 2026-11-27, 112647: the
moment the switch to Snorlax showed, throw_before_fainting read Clodsire's bar (12%) from the frame before and threw
Snorlax's Body Slam into Kingambit, with Earthquake a fast move away."""
import collections
import importlib.util
import sys
import types
import unittest
from pathlib import Path

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

GD = GameData()
TEAM = [GD.default("clodsire"), GD.default("araquanid"), GD.default("snorlax")]


def view_of(build, hp):
    mon = types.SimpleNamespace(build=build, hp=hp)
    return types.SimpleNamespace(me=types.SimpleNamespace(mon=mon))


def player(active, changed_at, bars):
    p = object.__new__(pa.Player)
    p.team, p.active, p.active_changed_at = TEAM, active, changed_at
    p.my_bar_seen = collections.deque(bars, maxlen=12)
    return p


class SettledOut(unittest.TestCase):
    def test_the_last_ones_view_is_not_settled(self):
        # Snorlax just seen in; the view (and the bar) still Clodsire's at 12%
        p = player(active=2, changed_at=190.0, bars=[(195.3, 0.12), (195.4, 0.12), (195.5, 0.12)])
        v = view_of(TEAM[0], 26)
        self.assertFalse(p.settled_out(195.6, v))
        self.assertEqual(p.hp_now(195.6, v), 1.0)

    def test_not_within_a_second_of_the_change(self):
        p = player(active=2, changed_at=195.6, bars=[(195.3, 0.12), (195.4, 0.12), (195.5, 0.12)])
        v = view_of(TEAM[2], 84)
        self.assertFalse(p.settled_out(196.2, v))
        # the bars from before the change are not Snorlax's: the view's health stands in
        self.assertAlmostEqual(p.hp_now(196.2, v), 84 / TEAM[2].hp)

    def test_settled_reads_its_own_bar(self):
        p = player(active=2, changed_at=195.6, bars=[(197.0, 0.30), (197.1, 0.30), (197.2, 0.31)])
        v = view_of(TEAM[2], 84)
        self.assertTrue(p.settled_out(197.3, v))
        self.assertAlmostEqual(p.hp_now(197.3, v), 0.30)


if __name__ == "__main__":
    unittest.main()
