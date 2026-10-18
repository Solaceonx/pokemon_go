"""Form-changing Pokémon (task 10): PvPoke's battles reproduced, and what happens on switching out."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import check_pvpoke  # noqa: E402
from pogo.battle import Mon, change_form, leave_field  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402


class Forms(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gd = GameData()

    def test_pvpoke_form_battles(self):
        ids, moves, lines = check_pvpoke.load(check_pvpoke.FORMS)
        problems = [p for p in (check_pvpoke.check(self.gd, ids, moves, line) for line in lines) if p]
        self.assertEqual(problems, [])
        self.assertGreaterEqual(len(lines), 40)

    def test_switching_out(self):
        aegislash = Mon(self.gd.default("aegislash_shield"))
        change_form(aegislash, "aegislash_blade")
        self.assertEqual(aegislash.build.species_id, "aegislash_blade")
        leave_field(aegislash)
        self.assertEqual(aegislash.build.species_id, "aegislash_shield")
        mimikyu = Mon(self.gd.default("mimikyu"))
        change_form(mimikyu, "mimikyu_busted")
        leave_field(mimikyu)
        self.assertEqual((mimikyu.build.species_id, mimikyu.def_stage), ("mimikyu_busted", -1))

    def test_blade_stats_match_pvpoke(self):
        blade = self.gd.default("aegislash_shield").forms["aegislash_blade"]
        self.assertEqual((blade.level, blade.hp), (22, 139))
        self.assertAlmostEqual(blade.atk, 172.93, places=1)
        self.assertAlmostEqual(blade.defense, 69.55, places=1)

    def test_pools_unchanged(self):
        self.assertFalse(any(b.forms for b in self.gd.meta(50)))
        self.assertTrue(any(b.forms for b in self.gd.meta(60, forms=True)))


if __name__ == "__main__":
    unittest.main()
