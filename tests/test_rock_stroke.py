"""The minigame stroke for Rock: its lane swept up and down, only icons past it chased (play_android.LANE,
CHASE_FROM_X; Stone Edge's rocks come in from the left edge at up to 0.9 of the width a second), and the lead
(LEAD_TYPES, off since it made no difference live) that aims at where an icon will be."""
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


class LeadIcons(unittest.TestCase):
    def test_ahead_by_its_speed(self):
        led = pa.lead_icons([(0.30, 0.40)], [(0.25, 0.40)], 0.05, 0.2, (0.30, 0.40), 6.5)
        self.assertAlmostEqual(led[0][0], 0.50, places=3)  # 1.0 a second for 0.2 s
        self.assertAlmostEqual(led[0][1], 0.40, places=3)

    def test_as_seen_without_a_match(self):
        self.assertEqual(pa.lead_icons([(0.30, 0.40)], [(0.70, 0.80)], 0.05, 0.2, (0, 0), 6.5), [(0.30, 0.40)])
        self.assertEqual(pa.lead_icons([(0.30, 0.40)], [(0.25, 0.40)], 0.0, 0.2, (0, 0), 6.5), [(0.30, 0.40)])

    def test_capped(self):
        led = pa.lead_icons([(0.30, 0.40)], [(0.25, 0.40)], 0.05, 5.0, (0.30, 0.40), 6.5)
        self.assertAlmostEqual(led[0][0], 0.30 + pa.LEAD_MAX, places=3)


class StaleFrames(unittest.TestCase):
    """A rock moving right at 0.9 a second, on frames 0.15 s old: led, the finger reaches where it is; chased as
    seen (a type not led), it stays behind."""
    AGE, V = 0.15, 0.9

    def run_stroke(self, move_type):
        t0 = time.time()
        shown = {"t": t0}
        pos = lambda t: (0.10 + self.V * (t - t0), 0.50)
        sent = []

        class Phone:
            def frame(self_):
                shown["t"] = time.time() - StaleFrames.AGE
                return np.zeros((40, 20, 3), np.uint8), shown["t"]

            def _send(self_, kind, x, y):
                sent.append((time.time(), x, y))

        with patch.object(pa.screen, "shield_prompt", return_value=False), \
                patch.object(pa, "find_icons", side_effect=lambda *a, **k: [pos(shown["t"])]), \
                patch.object(pa, "has_template", return_value=False), patch.object(pa, "LEAD_LAG", 0.0), \
                patch.object(pa, "LEAD_TYPES", {"rock"}), patch.object(pa, "CHASE_FROM_X", {}), \
                patch.object(pa, "LANE", {}):
            pa.minigame_stroke(Phone(), seconds=0.5, zone=((0.5, 0.6), (0.3, 0.2)), move_type=move_type)
        late = [(t, x, y) for t, x, y in sent if t - t0 > 0.15]
        return min(math.hypot(x - pos(t)[0], (y - pos(t)[1]) * 2.2) for t, x, y in late)

    def test_rock_reaches_it(self):
        self.assertLess(self.run_stroke("rock"), 0.04)

    def test_not_led_stays_behind(self):
        self.assertGreater(self.run_stroke("fire"), 0.08)


class Lane(unittest.TestCase):
    def run_stroke(self, seen):
        sent = []

        class Phone:
            def frame(self_):
                return np.zeros((40, 20, 3), np.uint8), time.time()

            def _send(self_, kind, x, y):
                sent.append((x, y))

        with patch.object(pa.screen, "shield_prompt", return_value=False), \
                patch.object(pa, "find_icons", return_value=seen), patch.object(pa, "has_template", return_value=False):
            pa.minigame_stroke(Phone(), seconds=0.6, zone=((0.5, 0.6), (0.3, 0.2)), move_type="rock")
        return sent

    def test_the_lane_swept_with_nothing_past_it(self):
        sent = self.run_stroke([(0.15, 0.40)])  # an icon in the lane: left to the sweep
        self.assertLess(max(x for x, _ in sent[:-2]), 0.15)  # the last two: lifted on the open field
        ys = [y for _, y in sent]
        self.assertLess(min(ys), 0.25)
        self.assertGreater(max(ys), 0.75)  # up and down the rows

    def test_a_settled_one_chased(self):
        sent = self.run_stroke([(0.40, 0.40)])
        self.assertLess(min(math.hypot(x - 0.40, (y - 0.40) * 2.2) for x, y in sent), 0.03)


if __name__ == "__main__":
    unittest.main()
