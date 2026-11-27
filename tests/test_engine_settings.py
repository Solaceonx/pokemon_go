"""POGO_ENGINE: the live player's engine settings over the website's (play_android.engine_settings)."""
import importlib.util
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "live"))
_stub = "cv2" not in sys.modules and importlib.util.find_spec("cv2") is None
if _stub:
    sys.modules["cv2"] = types.ModuleType("cv2")
try:
    import play_android as pa  # noqa: E402
finally:
    if _stub:
        del sys.modules["cv2"]


class EngineSettings(unittest.TestCase):
    def test_parsed(self):
        self.assertEqual(pa.engine_settings("judge=turn,horizon=40,edge=0.05"),
                         {"judge": "turn", "horizon": 40, "edge": 0.05})

    def test_heads(self):
        self.assertEqual(pa.engine_settings("judge=end,heads=throw+swap+shield,opponents=people,samples=16"),
                         {"judge": "end", "heads": ("throw", "swap", "shield"), "opponents": "people", "samples": 16})

    def test_empty(self):
        self.assertEqual(pa.engine_settings(""), {})


if __name__ == "__main__":
    unittest.main()
