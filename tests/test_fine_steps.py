"""FineSteps (scripts/live/play_android.py): their fast moves landing on our bar, a fall of 1 pixel or more held
0.07 s, timed at its first reading; flicker of a pixel on single readings is not a hit."""
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


def hits(series):
    f, out = pa.FineSteps(), []
    for t, px in series:
        if f.add(t, px) is not None:
            out.append(round(f.at, 3))
    return out


class FineSteps(unittest.TestCase):
    def test_small_steps_a_second_apart(self):
        # 1.5 px a hit every 1.0 s, read 30 times a second
        series = [(k / 30, 100.0 - 1.5 * int(k / 30)) for k in range(30 * 4)]
        got = hits(series)
        self.assertEqual(len(got), 3)
        self.assertTrue(all(abs(b - a - 1.0) < 0.05 for a, b in zip(got, got[1:])))

    def test_single_frame_flicker_is_no_hit(self):
        series = [(k / 30, 100.0 - (1.5 if k % 9 == 0 else 0.0)) for k in range(90)]
        self.assertEqual(hits(series), [])

    def test_half_the_frames_still_counts(self):
        series = [(k / 15, 100.0 - 2.0 * int(k / 15)) for k in range(15 * 4)]
        self.assertEqual(len(hits(series)), 3)



class LabelMove(unittest.TestCase):
    """Player.label_move: a button read as Normal's grey says nothing (it is also a button not lit up)."""

    def test_normal_says_nothing(self):
        from pogo.gamedata import GameData
        gd = GameData(league=2500)
        p = object.__new__(pa.Player)
        p.team = pa.load_team(gd, ROOT / "data" / "team_owner_ul.json")
        old = pa.screen.paid_type
        try:
            pa.screen.paid_type = lambda rgb, k: "normal"
            self.assertIsNone(p.label_move(None, 1))
            pa.screen.paid_type = lambda rgb, k: "water"
            self.assertIsNotNone(p.label_move(None, 0))
        finally:
            pa.screen.paid_type = old


class ReplaceCards(unittest.TestCase):
    """Player.replace_cards: the replacement prompt's two cards, left to right, by their names."""

    def player(self, words):
        import numpy as np
        from pogo.gamedata import GameData
        gd = GameData(league=2500)
        p = object.__new__(pa.Player)
        p.team = pa.load_team(gd, ROOT / "data" / "team_owner_ul.json")
        p.names = types.SimpleNamespace(ocr=lambda crop: ([[[[x, 0], [x + 10, 0], [x + 10, 5], [x, 5]], w, 0.9] for x, w in words], None))
        return p, np.zeros((1200, 540, 3), np.uint8)

    def test_two_names_read(self):
        p, a = self.player([(300, "Blastoise"), (40, "Melmetal")])
        self.assertEqual(p.replace_cards(a), [0, 1])  # Melmetal left, Blastoise right

    def test_nicknames_say_nothing(self):
        p, a = self.player([(40, "UL #3"), (300, "UL #1")])
        self.assertIsNone(p.replace_cards(a))


if __name__ == "__main__":
    unittest.main()
