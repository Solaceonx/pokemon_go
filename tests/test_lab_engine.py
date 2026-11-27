"""Marco's lab engine on the phone (POGO_LAB, play_android.lab_engine): built from its spec, with the live player's
turn length and 300 ms search cap."""
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
from pogo.realtime import RealTime  # noqa: E402


@unittest.skipUnless((ROOT / "runs" / "lab-pop-q.npz").exists(), "needs runs/lab-pop-q.npz (lab-best)")
class LabEngine(unittest.TestCase):
    def test_p_at_the_live_deadlines(self):
        engine = pa.lab_engine(GameData(), "P", 1)
        self.assertIsInstance(engine, RealTime)
        self.assertEqual((engine.turn_ms, engine.cap_ms), (500, 300))


if __name__ == "__main__":
    unittest.main()
