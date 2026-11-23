"""Player.owner_prefers (scripts/live/play_android.py): the team file's preferred charged move replaces the engine's
other one when paid for, unless not very effective on the one out (the owner, 2026-11-22: Hydro Cannon over Skull
Bash)."""
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
from pogo.battle import CHARGED  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402

GD = GameData(league=2500)
BLASTOISE = GD.build("blastoise", ["WATER_GUN", "HYDRO_CANNON", "SKULL_BASH"])


def player(energy):
    p = object.__new__(pa.Player)
    p.team, p.active = [BLASTOISE], 0
    p.tracker = types.SimpleNamespace(foe=object(), me=types.SimpleNamespace(mon=types.SimpleNamespace(energy=energy)))
    p.energy = lambda: energy
    p.paid_bounds = lambda: None
    p.logged = []
    p.log = lambda kind, t, **kw: p.logged.append(kind)
    p.decision = CHARGED[1]  # Skull Bash
    return p


def view(foe):
    return types.SimpleNamespace(foe=types.SimpleNamespace(build=GD.default(foe)))


class OwnerPrefers(unittest.TestCase):
    def setUp(self):
        pa.PREFER["blastoise"] = "HYDRO_CANNON"

    def tearDown(self):
        pa.PREFER.pop("blastoise", None)

    def test_hydro_cannon_on_a_neutral_target(self):
        p = player(75)
        p.owner_prefers(1.0, view("cresselia"))
        self.assertEqual(p.decision, CHARGED[0])
        self.assertIn("owner_prefers", p.logged)

    def test_skull_bash_kept_when_hydro_cannon_is_resisted(self):
        p = player(75)
        p.owner_prefers(1.0, view("poliwrath"))
        self.assertEqual(p.decision, CHARGED[1])

    def test_not_when_hydro_cannon_is_not_paid_for(self):
        p = player(35)
        p.owner_prefers(1.0, view("cresselia"))
        self.assertEqual(p.decision, CHARGED[1])


if __name__ == "__main__":
    unittest.main()
