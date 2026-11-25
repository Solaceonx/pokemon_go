"""Rock's minigame follows the owner's own swipe (play_android.owner_path, data/minigame/android/owner_type_rock.json:
a narrow tilted oval looped mid-screen, Excellent 4 of 4 on 2026-11-24), whatever icons are seen. Below it, two ways
of stroking tried for Stone Edge and left off (they did not beat chasing what is seen): a lane
swept up and down with only icons past it chased (play_android.LANE, CHASE_FROM_X), and the lead that aims at where
an icon will be (LEAD_TYPES). Both checked here as written, switched on for the test."""
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
                patch.object(pa, "LANE", {}), patch.object(pa, "owner_path", return_value=None):
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
                patch.object(pa, "find_icons", return_value=seen), patch.object(pa, "has_template", return_value=False), \
                patch.object(pa, "LANE", {"rock": ((0.12, 0.22), (0.12, 0.78))}), \
                patch.object(pa, "CHASE_FROM_X", {"rock": 0.26}), patch.object(pa, "owner_path", return_value=None):
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


class OwnerPath(unittest.TestCase):
    def test_the_owners_swipe_followed_not_the_icons(self):
        path = pa.owner_path("rock")
        self.assertIsNotNone(path)
        sent, t0 = [], time.time()

        class Phone:
            def frame(self_):
                return np.zeros((40, 20, 3), np.uint8), time.time()

            def _send(self_, kind, x, y):
                sent.append((time.time() - t0, x, y))

        with patch.object(pa.screen, "shield_prompt", return_value=False), \
                patch.object(pa, "find_icons", return_value=[(0.10, 0.30)]), \
                patch.object(pa, "has_template", return_value=False):
            pa.minigame_stroke(Phone(), seconds=1.0, zone=((0.5, 0.6), (0.3, 0.2)), move_type="rock")
        moves = sent[1:-2]  # the touch down, then the lift on the open field
        off = [math.hypot(x - pa.owner_point(path, t)[0], (y - pa.owner_point(path, t)[1]) * 2.2) for t, x, y in moves]
        self.assertLess(sorted(off)[int(0.9 * len(off))], 0.05)  # on the owner's path, give or take a step
        self.assertGreater(min(math.hypot(x - 0.10, (y - 0.30) * 2.2) for _, x, y in moves), 0.15)  # not the icon

    def test_round_again(self):
        path = [[0.0, 0.1, 0.1], [1.0, 0.9, 0.1]]
        self.assertAlmostEqual(pa.owner_point(path, 0.5)[0], 0.5)
        self.assertAlmostEqual(pa.owner_point(path, 1.25)[0], 0.3)

    def test_none_for_other_types(self):
        self.assertIsNone(pa.owner_path("fire"))


if __name__ == "__main__":
    unittest.main()
