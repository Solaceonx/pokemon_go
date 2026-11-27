"""What the names under the buttons showed paid for holds until we throw (Player.note_paid / paid_floor_now): our
energy falls only when we throw. 2026-11-26, 170435: Body Slam's name showed at 123.2 s, then neither the names nor the
fill read in the gaps between Minior's Power Gems, and Snorlax fainted at 154 s with the move unthrown."""
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

COSTS = [40, 65]  # Snorlax: Body Slam, Earthquake


def player(active=2, changed_at=-1.0):
    p = object.__new__(pa.Player)
    p.active, p.switching, p.active_changed_at = active, None, changed_at
    p.t0 = time.time() - 100.0  # 100 s into the battle
    p.names_seen = p._names_raw = None
    p.names_blocked_until = 0.0
    return p


class PaidFloor(unittest.TestCase):
    def setUp(self):
        self._was, pa.PAID_FLOOR = pa.PAID_FLOOR, True  # off by default since 2026-11-27; these test the memory itself

    def tearDown(self):
        pa.PAID_FLOOR = self._was

    def test_off_by_default_reads_zero(self):
        pa.PAID_FLOOR = False
        p = player()
        p.note_paid([True, False], COSTS)
        self.assertEqual(p.paid_floor_now(), 0)

    def test_kept_after_the_names_go(self):
        p = player()
        p.note_paid([True, False], COSTS)
        self.assertEqual(p.paid_floor_now(), 40)
        p.names_seen = None  # the names unread for seconds
        self.assertEqual(p.paid_floor_now(), 40)

    def test_whole_energy(self):
        # 2026-11-26: a floor of 65.0 put into the tracker's count made the engine's searches fail ("'float' object
        # cannot be interpreted as an integer"), four times in a dry run
        p = player()
        p.note_paid([False, True], COSTS)
        self.assertIsInstance(p.paid_floor_now(), int)

    def test_only_ever_raised(self):
        p = player()
        p.note_paid([True, True], COSTS)
        p.note_paid([True, False], COSTS)  # a frame with Earthquake's name missing does not lower it
        self.assertEqual(p.paid_floor_now(), 65)

    def test_not_just_after_a_change_of_who_is_out(self):
        p = player(changed_at=99.6)  # changed 0.4 s ago: the names may be the last one's
        p.note_paid([True, False], COSTS)
        self.assertEqual(p.paid_floor_now(), 0)
        p = player()
        p.switching = (1, time.time(), None, None, None)
        p.note_paid([True, False], COSTS)
        self.assertEqual(p.paid_floor_now(), 0)

    def test_each_pokemon_its_own(self):
        p = player(active=2)
        p.note_paid([True, False], COSTS)
        p.active = 1
        self.assertEqual(p.paid_floor_now(), 0)
        p.active = 2  # back in: its energy was kept on the bench
        self.assertEqual(p.paid_floor_now(), 40)

    def test_gone_once_the_move_is_thrown(self):
        p = player()
        p.note_paid([True, False], COSTS)
        p._minigame = lambda k, move, since: None  # the swipe itself is not under test
        p.minigame(0, None, time.time())
        self.assertEqual(p.paid_floor_now(), 0)


if __name__ == "__main__":
    unittest.main()
