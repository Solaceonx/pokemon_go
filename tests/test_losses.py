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
