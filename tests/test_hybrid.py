import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pogo.agents import Planner  # noqa: E402
from pogo.battle import Battle  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.hybrid import EndgameThrows  # noqa: E402
from pogo.pvpoke_ai import PvpokeAI  # noqa: E402

GD = GameData()
POOL = GD.meta(6)


class Endgame(unittest.TestCase):
    def test_before_the_final_one_on_one_the_player_decides(self):
        b = Battle(POOL[:3], POOL[3:6], EndgameThrows(Planner()), Planner(), seed=1)
        self.assertFalse(EndgameThrows.final(b.views[0]))
        self.assertEqual(b.agents[0].act(b.views[0]), Planner().act(b.views[0]))

    def test_in_the_final_one_on_one_pvpoke_decides(self):
        b = Battle(POOL[:1], POOL[1:2], EndgameThrows(Planner()), Planner(), seed=1)
        self.assertTrue(EndgameThrows.final(b.views[0]))
        self.assertEqual(b.agents[0].act(b.views[0]), PvpokeAI().act(b.views[0]))

    def test_plays_whole_battles(self):
        for seed in range(5):
            Battle(POOL[:3], POOL[3:6], EndgameThrows(Planner()), Planner(), seed=seed).run()


if __name__ == "__main__":
    unittest.main()
