"""The browser game's human player: queued actions, and prompts that time out."""
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import play  # noqa: E402
from pogo.agents import Masher  # noqa: E402
from pogo.battle import CHARGED, FAST, SWITCH, Mon  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402

GD = GameData()


class HumanPlayer(unittest.TestCase):
    def game(self, energy=0):
        mine = [Mon(GD.default("medicham"), energy=energy), GD.default("azumarill"), GD.default("registeel")]
        return play.Game(GD, mine, [GD.default("swampert")], Masher(), "test", charged_pause=0.0)

    def test_fast_moves_unless_told_and_only_legal_choices(self):
        game = self.game(energy=0)
        view = game.battle.views[0]
        self.assertEqual(game.human.act(view), FAST)
        game.queue(CHARGED[0])  # not enough energy: ignored
        self.assertEqual(game.human.act(view), FAST)
        game.queue(SWITCH[1])
        self.assertEqual(game.human.act(view), SWITCH[1])

    def test_unanswered_shield_prompt_means_no_shield(self):
        game = self.game()
        play_ask = game.ask
        game.ask = lambda kind, seconds, default, **details: play_ask(kind, 0.05, default, **details)
        self.assertFalse(game.human.shield(game.battle.views[0], 50))

    def test_answered_prompt(self):
        game = self.game()
        threading.Timer(0.05, lambda: game.reply(True)).start()
        self.assertTrue(game.ask("shield", 2.0, False))

    def test_sprite_names(self):
        self.assertEqual(play.sprite(GD, GD.default("ninetales_alolan"))["showdown"], "ninetales-alola")
        self.assertEqual(play.sprite(GD, GD.default("quagsire_shadow"))["showdown"], "quagsire")


if __name__ == "__main__":
    unittest.main()
