"""The owner's rule 5, out of a bad lead to the safe swap (play_android.safe_swap): 2026-11-24, Clodsire kept in
against Empoleon lost the battle; against Machamp Clodsire is the one to keep in."""
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
TEAM = [GD.build("clodsire", ["POISON_STING", "STONE_EDGE", "EARTHQUAKE"]),
        GD.build("thievul", ["SUCKER_PUNCH", "NIGHT_SLASH", "PLAY_ROUGH"]),
        GD.build("snorlax", ["PSYWAVE", "BODY_SLAM", "EARTHQUAKE"])]


class SafeSwap(unittest.TestCase):
    def test_out_of_empoleon_to_snorlax(self):
        to, scores = pa.safe_swap(TEAM, 0, GD.default("empoleon"))
        self.assertEqual(to, 2)
        self.assertLess(scores[0], pa.LEAD_BAD)

    def test_kept_in_against_machamp(self):
        to, _ = pa.safe_swap(TEAM, 0, GD.default("machamp"))
        self.assertIsNone(to)


if __name__ == "__main__":
    unittest.main()
