"""Player.header_now: the counts of Pokémon left and of shields, the most common of the last five readings, but a fall
read twice in a row taken at once (the counts only fall)."""
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


def counts(readings):
    p = object.__new__(pa.Player)
    p.history = []
    got = None
    for r in readings:
        got = p.header_now(types.SimpleNamespace(header=True, my_left=r[0], foe_left=r[1], my_shields=r[2], foe_shields=r[3]))
    return got


class HeaderCounts(unittest.TestCase):
    def test_a_fall_read_twice_is_taken(self):
        self.assertEqual(counts([(3, 3, 2, 2)] * 3 + [(3, 3, 2, 1)] * 2)[3], 1)

    def test_a_single_misread_is_not(self):
        self.assertEqual(counts([(3, 3, 2, 2)] * 4 + [(3, 3, 2, 1)])[3], 2)

    def test_a_rise_needs_the_majority(self):
        self.assertEqual(counts([(3, 3, 2, 1)] * 3 + [(3, 3, 2, 2)] * 2)[3], 1)


if __name__ == "__main__":
    unittest.main()
