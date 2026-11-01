import gzip
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
import bench  # noqa: E402


class FrozenEndgames(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        bench.setup()
        with gzip.open(bench.ENDGAMES, "rt") as f:
            cls.rows = [json.loads(line) for line in f]

    def test_values_are_consistent(self):
        """Against the opponent's optimal mix no action beats the position's value, and the best one reaches it."""
        for row in self.rows:
            if row["kind"] == "act":
                best = max(row["worth"].values())
                self.assertAlmostEqual(best, row["value"], delta=0.01, msg=str(row["worth"]))

    def test_positions_restore_exactly(self):
        """Including Pokémon in another form, which must keep all their forms to change back."""
        forms = 0
        for row in self.rows:
            again = bench.dump(bench.restore(row["state"]))
            for side, saved in zip(again["sides"], row["state"]["sides"]):
                self.assertEqual((side["active"], side["shields"], side["switch_wait"], side["busy"]),
                                 (saved["active"], saved["shields"], saved["switch_wait"], saved["busy"]))
                for mon, want in zip(side["team"], saved["team"]):
                    self.assertEqual((mon["id"], mon["moves"], mon["hp"], mon["energy"]), (want["id"], want["moves"], want["hp"], want["energy"]))
                    forms += mon["id"] in bench.HOME
        self.assertGreater(forms, 0)

    def test_broken_bot_is_broken(self):
        row = next(r for r in self.rows if r["kind"] == "shield" and r["worth"]["yes"] > r["worth"]["no"])
        view = bench.restore(row["state"]).views[row["side"]]
        self.assertFalse(bench.BUILDS["no_shields"](1).shield(view, row["foe_energy"]))


if __name__ == "__main__":
    unittest.main()
