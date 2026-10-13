"""The decisiveness score: any win above any loss, and by how much from the winner's health and shields."""
import unittest

from pogo.agents import Masher
from pogo.arena import decisive, left_over
from pogo.battle import DRAW, Battle, Mon
from pogo.gamedata import GameData

GD = GameData()


class Decisive(unittest.TestCase):
    def finished(self, winner, hp_share, shields):
        team = [Mon(GD.default("medicham")), Mon(GD.default("azumarill")), Mon(GD.default("registeel"))]
        for m in team:
            m.hp = round(hp_share * m.build.hp)
        battle = Battle(team, [GD.default("swampert")], Masher(), Masher(), shields=(shields, 0))
        battle.sides[1].team[0].hp = 0
        battle.winner = winner
        return battle

    def test_flawless_win_and_loss(self):
        self.assertAlmostEqual(left_over(self.finished(0, 1.0, 2).sides[0]), 1.0)
        self.assertAlmostEqual(decisive(self.finished(0, 1.0, 2)), 1.0)
        self.assertAlmostEqual(decisive(self.finished(0, 1.0, 2), side=1), 0.0)

    def test_any_win_beats_any_loss(self):
        narrow = decisive(self.finished(0, 0.01, 0))
        self.assertGreater(narrow, 0.75)
        self.assertLess(narrow, 0.76)
        self.assertLess(decisive(self.finished(0, 0.01, 0), side=1), 0.25)

    def test_more_left_scores_higher(self):
        self.assertGreater(decisive(self.finished(0, 0.6, 1)), decisive(self.finished(0, 0.3, 1)))
        self.assertGreater(decisive(self.finished(0, 0.3, 2)), decisive(self.finished(0, 0.3, 0)))

    def test_draw_and_plain_results(self):
        self.assertEqual(decisive(self.finished(DRAW, 0.5, 1)), 0.5)
        self.assertEqual(decisive(self.finished(0, 0.2, 0), bare=1.0), 1.0)
        self.assertEqual(decisive(self.finished(0, 0.2, 0), side=1, bare=1.0), 0.0)


if __name__ == "__main__":
    unittest.main()
