"""Player.countdown_is_theirs (scripts/live/play_android.py): the countdown disc is their throw only with no shield
of ours left and no throw of ours in the last 18 s; after ours it is them choosing whether to shield (2026-11-22: 57
of 62 countdowns had no move of theirs after, and each put their energy at nothing)."""
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


def theirs(shields, ours_ago, prompt_ago=60.0):
    p = object.__new__(pa.Player)
    now = time.time()
    p.pending_theirs = False
    p.prompt_seen, p.their_throw_at, p.my_throw_at = now - prompt_ago, now - prompt_ago, now - ours_ago
    p.tracker = types.SimpleNamespace(me=types.SimpleNamespace(shields=shields))
    return p.countdown_is_theirs()


class CountdownTheirs(unittest.TestCase):
    def test_theirs_with_no_shields_and_no_throw_of_ours(self):
        self.assertTrue(theirs(shields=0, ours_ago=30.0))

    def test_not_after_a_throw_of_ours(self):
        self.assertFalse(theirs(shields=0, ours_ago=8.0))

    def test_not_with_a_shield_left(self):
        self.assertFalse(theirs(shields=1, ours_ago=30.0))

    def test_not_twice_for_one_throw(self):
        self.assertFalse(theirs(shields=0, ours_ago=30.0, prompt_ago=4.0))


if __name__ == "__main__":
    unittest.main()
