"""Holds of the fast taps for a long fast move (Skeledirge's Incinerate, 2.5 s), 2026-11-23, 232848: the taps stopped
3 s at 83 s (the hit that paid ignored as a flame's) and 3.5 s at 93 s (held on the count, the fight not back after
Giratina's Ominous Wind, for a move never begun)."""
import importlib.util
import sys
import time
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
from pogo.tracker import Observation, Tracker  # noqa: E402

GD = GameData()


def player():
    p = object.__new__(pa.Player)
    p.logged = []
    p.log = lambda kind, t, **kw: p.logged.append(kind)
    sk = GD.build("skeledirge", ["INCINERATE", "SHADOW_BALL", "TORCH_SONG"])
    p.team, p.active = [sk], 0
    p.tracker = Tracker(GD, [sk, GD.default("melmetal"), GD.default("altaria")])
    p.tracker.update(Observation(t=0.0, my_species="skeledirge", foe_species="giratina_origin", my_left=3, foe_left=3))
    p.tracker.me.mon.energy = 37
    p.names_seen = None
    p.slow_pause = p.armed = None
    p.hold_ended_at = 0.0
    p.last_fast_tap = time.time() - 0.1
    p.engine = types.SimpleNamespace(act=lambda view: (_ for _ in ()).throw(AssertionError("engine asked")), cap_ms=150)
    return p


class CountStandsIn(unittest.TestCase):
    def test_not_with_the_buttons_unread_since_a_charged_move(self):
        p = player()
        p.energy_read = (37.0, time.time() - 6.0)  # last read before their charged move
        p.look_ahead(1.0, None)
        self.assertIsNone(p.slow_pause)
        self.assertIsNone(p.armed)

    def test_with_the_buttons_read_just_now(self):
        p = player()
        p.energy_read = (37.0, time.time() - 0.6)  # read a moment ago; none this instant
        asked = []
        p.engine = types.SimpleNamespace(act=lambda view: asked.append(1) or pa.FAST, cap_ms=150)
        p.engine_sees = lambda: __import__("contextlib").nullcontext()
        p.view = lambda: None
        p.engine_calls = 0
        p.name = lambda d: str(d)
        p.look_ahead(1.0, None)
        self.assertEqual(asked, [1])
        self.assertIsNotNone(p.slow_pause)


if __name__ == "__main__":
    unittest.main()
