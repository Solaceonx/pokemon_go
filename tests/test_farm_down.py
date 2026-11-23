"""Player.farm_down (scripts/live/play_android.py): a paid charged move is held to finish their Pokémon with fast
moves only while no charged move of theirs can come first, whatever our shields, their energy taken as the top of the
count plus one fast move (2026-11-22: 9 of 10 holds that went wrong had their move counted in reach, a shield up)."""
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
from pogo.battle import Mon  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402

GD = GameData(league=2500)
MELMETAL = GD.build("melmetal", ["THUNDER_SHOCK", "DOUBLE_IRON_BASH", "DYNAMIC_PUNCH"])
FLORGES = GD.build("florges", ["FAIRY_WIND", "CHILLING_WATER", "DISARMING_VOICE"])  # both 45, 9 a Fairy Wind


def farms(lo, hi, shields):
    p = object.__new__(pa.Player)
    p.tracker = types.SimpleNamespace(foe=types.SimpleNamespace(lo=lo, hi=hi))
    p.farm_for, p.farm_since, p.farm_checked = None, 0.0, 0.0
    p.logged = []
    p.log = lambda kind, t, **kw: p.logged.append(kind)
    p.now = lambda: 1.0
    view = types.SimpleNamespace(foe=Mon(FLORGES, hp=6), me=types.SimpleNamespace(mon=Mon(MELMETAL), shields=shields))
    return p.farm_down(view, MELMETAL, 40, 1.0, MELMETAL.charged[0])


class FarmDown(unittest.TestCase):
    def test_farmed_when_their_move_is_far_off(self):
        self.assertTrue(farms(0, 0, shields=2))

    def test_not_farmed_with_their_move_in_reach_and_a_shield_up(self):
        self.assertFalse(farms(20, 20, shields=2))  # 20 + 3 Fairy Winds = 47 ≥ 45

    def test_the_top_of_the_count_not_the_bottom(self):
        self.assertFalse(farms(0, 20, shields=0))


if __name__ == "__main__":
    unittest.main()
