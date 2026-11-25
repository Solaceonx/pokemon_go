"""A team holds three: a fourth species read for theirs is a misreading and changes nothing (2026-11-25, 120840:
"Aron" read off "Lucario used Aura Sphere!", and the engine failed on 42 decisions with four of theirs)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pogo.gamedata import GameData  # noqa: E402
from pogo.tracker import Observation, Tracker  # noqa: E402

GD = GameData()


class FourthFoe(unittest.TestCase):
    def test_a_fourth_name_is_ignored(self):
        tr = Tracker(GD, [GD.default("clodsire"), GD.default("snorlax"), GD.default("azumarill")])
        t = 0.0
        for sp in ("toxicroak", "lucario", "dragalge", "aron", "lucario"):
            for _ in range(4):
                tr.update(Observation(t=t, my_species="clodsire", foe_species=sp, my_left=3, foe_left=3))
                t += 0.5
            if sp == "aron":
                self.assertEqual(tr.foe.mon.build.species_id, "dragalge")  # the one out stays out
        self.assertEqual(sorted(tr.foes), ["dragalge", "lucario", "toxicroak"])
        self.assertEqual(len(tr.view().foe_shown), 3)


if __name__ == "__main__":
    unittest.main()
