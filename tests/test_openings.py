"""pogo.openings: a plan is carried out exactly, and the bot is in charge outside it."""
import unittest

from pogo.agents import Masher
from pogo.battle import FAST, SWITCH, Battle
from pogo.gamedata import GameData
from pogo.openings import Booked


class Swapper(Masher):
    """Wants to switch to slot 2 at every chance: the book must hold it back."""

    def act(self, view):
        return SWITCH[2] if view.me.switch_wait == 0 and 2 in view.me.bench() else FAST


class Openings(unittest.TestCase):
    def setUp(self):
        gd = GameData()
        self.mine = [gd.default(s) for s in ("melmetal", "altaria", "jellicent")]
        self.theirs = [gd.default(s) for s in ("corviknight", "tinkaton", "mandibuzz")]

    def first_switch(self, book, inner):
        battle = Battle(self.mine, self.theirs, Booked(inner, book), Masher(), seed=1, record=True)
        while battle.winner is None:
            battle.step()
            entered = [(t, text) for t, side, text in battle.log if side == 0 and "sends in" in text]
            if entered:
                return entered[0]
        return None

    def test_swap_after_fast_moves(self):
        t, text = self.first_switch({"corviknight": {"swap": 1, "after_fast": 4}}, Masher())
        self.assertIn("Altaria", text)
        fast = self.mine[0].fast.turns
        self.assertEqual(t, 4 * fast)  # four fast moves of Thunder Shock, then the switch

    def test_no_early_switch_and_stay_means_the_bot(self):
        t, text = self.first_switch({"corviknight": {"swap": 1, "after_fast": 2}}, Swapper())
        self.assertIn("Altaria", text)  # the plan's slot, not the one the inner player kept asking for
        t, text = self.first_switch({}, Swapper())
        self.assertEqual(t, 0)  # no plan for this lead: the inner player switches at once, as it wants
        self.assertIn("Jellicent", text)


if __name__ == "__main__":
    unittest.main()
