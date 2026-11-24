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
    p.reading_new_at, p.reading_base = 0.0, 0.0
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


def asking(p, answer):
    asked = []
    p.engine = types.SimpleNamespace(act=lambda view: asked.append(1) or answer, cap_ms=150)
    p.engine_sees = lambda: __import__("contextlib").nullcontext()
    p.view = lambda: None
    p.engine_calls = 0
    p.name = lambda d: str(d)
    return asked


class NotArmedAtALanding(unittest.TestCase):
    """2026-11-23, 235319, 70.8 s: armed for Shadow Ball at the very reading (18 to 37) that showed Incinerate
    landing; the taps before it were the landed move's, the hold stopped the rest, and Skeledirge stood 2.9 s."""

    def test_not_with_the_reading_just_risen(self):
        p = player()
        now = time.time()
        p.energy_read, p.reading_new_at, p.last_fast_tap = (36.9, now), now - 0.1, now - 0.05
        asked = asking(p, pa.CHARGED[0])
        p.look_ahead(70.8, None)
        self.assertEqual(asked, [])
        self.assertIsNone(p.armed)
        self.assertIsNone(p.slow_pause)

    def test_armed_with_a_tap_a_turn_after(self):
        p = player()
        now = time.time()
        p.energy_read, p.reading_new_at, p.last_fast_tap = (36.9, now), now - 0.7, now - 0.1
        asked = asking(p, pa.CHARGED[0])
        p.look_ahead(71.4, None)
        self.assertEqual(asked, [1])
        self.assertIsNotNone(p.armed)
        self.assertEqual(p.armed[0], 0)

    def test_short_fast_moves_unchanged(self):
        p = player()
        p.team = [GD.build("blastoise", ["WATER_GUN", "HYDRO_CANNON", "SKULL_BASH"])]
        now = time.time()
        p.energy_read, p.reading_new_at, p.last_fast_tap = (38.0, now), now - 0.1, now - 0.05  # Water Gun: +3 to 41
        asked = asking(p, pa.FAST)
        p.look_ahead(1.0, None)
        self.assertEqual(asked, [1])


class ReadingNewAt(unittest.TestCase):
    def reading(self, p, e, when):
        from unittest import mock
        with mock.patch.object(pa.screen, "my_energy", lambda a, c: e), \
                mock.patch.object(pa.screen, "button_labels", lambda a: [None, None]), \
                mock.patch.object(pa.screen, "button_rim", lambda a, k: 20.0):
            p.read_energy(None, when)

    def player(self):
        p = player()
        p.energy_read, p._energy_raw, p.t0, p.names_blocked_until = None, None, 0.0, 0.0
        return p

    def test_a_landing_and_a_steady_reading(self):
        p, t = self.player(), 1000.0
        self.reading(p, 18.2, t)
        self.reading(p, 18.2, t + 0.1)
        self.assertEqual(p.reading_new_at, t + 0.1)  # the first reading
        self.reading(p, 18.2, t + 0.3)
        self.assertEqual(p.reading_new_at, t + 0.1)  # unchanged: not new
        self.reading(p, 36.9, t + 0.5)
        self.reading(p, 36.9, t + 0.6)
        self.assertEqual(p.reading_new_at, t + 0.6)  # Incinerate landed: 18 to 37

    def test_a_landing_whose_fill_rises_in_steps(self):
        # 235319, 70.8 s: the fill rose 18 to 37 over a few frames, each step within 5 of the last
        p, t = self.player(), 1000.0
        for i, e in enumerate([18.2, 18.2, 18.2, 22.0, 25.5, 29.0, 32.5, 36.9, 36.9]):
            self.reading(p, e, t + 0.05 * i)
        self.assertEqual(p.reading_new_at, t + 0.05 * 5)  # 29.0: half an Incinerate over 18.2
        self.reading(p, 36.9, t + 0.5)
        self.assertEqual(p.reading_new_at, t + 0.05 * 5)  # 36.9 is under 10 over 29: the same landing

    def test_back_after_a_close_up(self):
        p, t = self.player(), 1000.0
        for dt in (0.0, 0.1):
            self.reading(p, 36.9, t + dt)
        for dt in (2.6, 2.7):
            self.reading(p, 36.9, t + dt)
        self.assertEqual(p.reading_new_at, t + 2.7)  # the same energy, but unread for 2.6 s


if __name__ == "__main__":
    unittest.main()
