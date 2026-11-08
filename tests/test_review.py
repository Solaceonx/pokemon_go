"""pogo/review.py: either player's decisions replay from a saved game and are judged; the per-player score."""
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from pogo import review  # noqa: E402
from pogo.agents import Planner  # noqa: E402
from pogo.battle import CHARGED, Battle  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.learner import QNet  # noqa: E402

TEAMS = (["azumarill", "medicham", "registeel"], ["swampert", "skarmory", "galvantula"])


class Recorder:
    """A player that writes down its choices the way the browser game writes down a person's."""

    def __init__(self, inner):
        self.inner, self.choices = inner, []

    def act(self, view):
        action = self.inner.act(view)
        if action != 0:
            self.choices.append([view.turn, 0, action])
        return action

    def shield(self, view, energy, *move):
        if view.me.shields == 0:
            return False
        answer = bool(self.inner.shield(view, energy))
        self.choices.append([view.turn, 0, f"shield:{answer}"])
        return answer

    def replace(self, view):
        slot = self.inner.replace(view)
        if len(view.me.bench()) > 1:
            self.choices.append([view.turn, 0, f"replace:{slot}"])
        return slot


class Review(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import play
        cls.gd = GameData()
        cls.net = QNet.load(str(ROOT / "runs" / "general-decide" / "q.npz"))
        teams = [[cls.gd.default(s) for s in t] for t in TEAMS]
        person = Recorder(Planner(seed=3))
        battle = Battle(teams[0], teams[1], person, Planner(seed=4), seed=11, record=True)
        battle.run()
        cls.record = {"seed": 11, "my_choices": person.choices, "log": [list(e) for e in battle.log],
                      "teams": [[play.describe(m.build) for m in side.team] for side in battle.sides]}

    def test_both_players_replay(self):
        for side in (0, 1):
            game = review.decisions(self.record, self.gd, side=side)
            with self.subTest(side=side):
                self.assertEqual(game["side"], side)
                self.assertTrue(game["items"])

    def test_bot_throws_are_the_logged_ones(self):
        game = review.decisions(self.record, self.gd, side=1)
        throws = {(t, text.split(" throws ", 1)[1].split(":")[0]) for t, s, text in self.record["log"] if s == 1 and " throws " in text}
        seen = [(turn, snap.views[1].me.mon.build.charged[CHARGED.index(choice)].name)
                for snap, turn, kind, choice, _ in game["items"] if kind == "act" and choice in CHARGED]
        self.assertTrue(seen)
        self.assertTrue(set(seen) <= throws)

    def test_judging_the_bot(self):
        game = review.decisions(self.record, self.gd, side=1)
        out = review.judge(game, game["items"][0], self.net, self.gd.meta(50), seed=1, screen=2, confirm=2)
        self.assertTrue(0 <= out["mine"] <= 1 and 0 <= out["best"] <= 1)
        self.assertGreaterEqual(out["cost"], 0)
        self.assertEqual(out["mon"], game["items"][0][0].views[1].me.mon.build.name)

    def test_accuracy(self):
        def judged(*costs):
            return [{"cost": c, "label": next((n for limit, n in review.LABELS if c >= limit), None)} for c in costs]
        self.assertEqual(review.accuracy([])["accuracy"], None)
        self.assertEqual(review.accuracy(judged(0, 0.05, 0.07))["accuracy"], 100.0)  # under the inaccuracy line
        self.assertAlmostEqual(review.decision_score(0.08), 69.7, places=1)
        self.assertAlmostEqual(review.decision_score(0.25), 31.6, places=1)
        score = review.accuracy(judged(0, 0, 0.25))
        a = review.decision_score(0.25)
        self.assertAlmostEqual(score["accuracy"], round(((200 + a) / 3 + 3 / (2 / 100 + 1 / a)) / 2, 1))
        self.assertEqual((score["blunder"], score["mistake"], score["given_away"]), (1, 0, 0.25))
        self.assertTrue(math.isclose(review.accuracy(judged(0.15, 0.15))["accuracy"], review.decision_score(0.15), abs_tol=0.05))


if __name__ == "__main__":
    unittest.main()
