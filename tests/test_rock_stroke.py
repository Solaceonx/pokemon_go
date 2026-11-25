"""The minigame stroke for Rock (play_android.PREDICTED_FIRST): the learnt icons are chased and the icons the detector
finds are not (2026-11-24: Stone Edge's rocks fly in from the left edge, and the finger chasing where a frame 0.1 to
0.2 s old had them came in behind them, 3 Great in 8); other types still chase what is found."""
import importlib.util
import math
import sys
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

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

SEEN, LEARNT = (0.92, 0.15), (0.20, 0.75)  # a detected icon (outside the rock sweep box) and a learnt one


class Phone:
    def __init__(self):
        self.sent = []

    def frame(self):
        return np.zeros((40, 20, 3), np.uint8), time.time()

    def _send(self, kind, x, y):
        self.sent.append((x, y))


def stroke(move_type):
    phone, trace = Phone(), []
    with patch.object(pa.screen, "shield_prompt", return_value=False), \
            patch.object(pa, "find_icons", return_value=[SEEN]), \
            patch.object(pa, "has_template", return_value=False):
        pa.minigame_stroke(phone, seconds=0.7, zone=((0.5, 0.6), (0.3, 0.2)), move_type=move_type, trace=trace,
                           predicted=[(0.0, 5.0, LEARNT[0], LEARNT[1], 0.9)], ready_at=time.time() - 1.2,
                           move_id="")
    near = lambda p: min(math.hypot(x - p[0], (y - p[1]) * 2.2) for x, y in phone.sent)  # every touch sent
    return near(SEEN), near(LEARNT)


class RockStroke(unittest.TestCase):
    def test_rock_goes_to_the_learnt_icon_not_the_seen_one(self):
        seen, learnt = stroke("rock")
        self.assertLess(learnt, 0.03)
        self.assertGreater(seen, 0.2)

    def test_other_types_chase_what_is_seen(self):
        seen, _ = stroke("fire")
        self.assertLess(seen, 0.03)


if __name__ == "__main__":
    unittest.main()
