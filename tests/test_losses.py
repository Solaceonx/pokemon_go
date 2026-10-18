"""scripts/losses.py: replaying the bot's own choice, with the opponent left as it was, repeats the battle."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import losses  # noqa: E402
from pogo.battle import DRAW  # noqa: E402


class ReplayRepeatsTheBattle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        losses.setup()
        cls.found = []  # (seed, battle, steps) for the first loss and the first win
        for seed in range(1, 60):
            battle, steps = losses.record(seed)
            if battle.winner == DRAW or any(f[1].winner == battle.winner for f in cls.found):
                continue
            cls.found.append((seed, battle, steps))
            if len(cls.found) == 2:
                break

    def test_found_a_loss_and_a_win(self):
        self.assertEqual(sorted(f[1].winner for f in self.found), [0, 1])

    def test_own_choice_unvaried_repeats_the_result(self):
        for seed, battle, steps in self.found:
            expected = 1.0 if battle.winner == 0 else 0.0
            picks = sorted({0, len(steps) // 3, 2 * len(steps) // 3, len(steps) - 1})
            for index in picks:
                snap, calls = steps[index]
                kind, chosen, _ = calls[0]
                with self.subTest(seed=seed, step=index, kind=kind):
                    self.assertEqual(losses.win_chance(snap, kind, chosen, 2, seed, vary=False), expected)

    def test_varied_play_outs_differ(self):
        seed, battle, steps = next(f for f in self.found if f[1].winner == 1)
        snap, calls = steps[0]
        kind, chosen, _ = calls[0]
        self.assertGreater(losses.win_chance(snap, kind, chosen, 12, seed), 0.0)  # not every play-out repeats the loss


if __name__ == "__main__":
    unittest.main()


class Logged:
    """A player that writes down its choices the way the browser game writes down a person's."""

    def __init__(self, inner):
        self.inner, self.choices, self.battle = inner, [], None

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


class PlayedGamesReplay(unittest.TestCase):
    """A game saved as scripts/play.py saves it (seeds, teams, the person's choices) replays exactly."""

    def test_saved_game_replays(self):
        import json
        import random
        import tempfile
        from pogo.agents import Planner
        from pogo.battle import Battle

        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
        import play  # noqa: F401  (describe, as the game uses it)
        losses.setup()
        s = losses._state
        rng = random.Random(8)
        for game in range(3):
            teams = [s["draw"](rng), s["draw"](rng)]
            person, seed, bot_seed = Logged(Planner(seed=rng.getrandbits(30))), rng.getrandbits(32), rng.getrandbits(30)
            battle = Battle(teams[0], teams[1], person, losses.bot(bot_seed), seed=seed, record=True)
            battle.run()
            saved = {"bot": "learner", "seed": seed, "bot_seed": bot_seed, "my_choices": person.choices,
                     "log": [list(e) for e in battle.log],
                     "teams": [[play.describe(m.build) for m in side.team] for side in battle.sides]}
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
                json.dump(saved, f)
            replayed, steps, _, same = losses.replay(f.name)
            with self.subTest(game=game):
                self.assertTrue(same)
                self.assertEqual(replayed.winner, battle.winner)
                self.assertTrue(steps)
