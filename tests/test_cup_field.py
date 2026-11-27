"""A cup's field for the engines (play_android.cup_field, POGO_FIELD): the species met twice or more as builds with
the moves seen (Minior is not in the open rankings that give default moves), only teams whose species all build, and
the open top 50 without a field."""
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
FIELD = ROOT / "data" / "fields" / "mega_catch_cup.json"


class CupField(unittest.TestCase):
    def test_none_is_the_open_top_50(self):
        pool, teams, builds = pa.cup_field(GD, "")
        self.assertEqual([b.species_id for b in pool], [b.species_id for b in GD.meta(50)])
        self.assertIsNone(teams)

    @unittest.skipUnless(FIELD.exists(), "needs data/fields/mega_catch_cup.json")
    def test_the_mega_catch_cup(self):
        pool, teams, builds = pa.cup_field(GD, str(FIELD))
        ids = [b.species_id for b in pool]
        self.assertIn("minior_core", ids)
        self.assertEqual(builds["minior_core"].fast.id, "ROLLOUT")
        self.assertNotIn("cramorant", builds)  # form-changing: left out, as in GameData.meta
        self.assertTrue(teams and all(all(sp in builds for sp in t) for _, t in teams))
        self.assertTrue(all(w > 0 for w, _ in teams))


if __name__ == "__main__":
    unittest.main()
