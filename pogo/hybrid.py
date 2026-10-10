"""Our players with PvPoke's charged-move choice in the final one-on-one.

PvPoke's single-matchup AI chooses fast and charged moves better than the Planner once both
sides are on their last Pokémon, and worse before that, because it does not save energy for
a later matchup. EndgameThrows keeps the given player for everything (switches, replacements,
shields, and throws earlier in the battle) and hands only the fast/charged choice in the
final one-on-one to PvPoke. Measured by scripts/check_endgame_throws.py.
"""
from __future__ import annotations

from pogo.pvpoke_ai import PvpokeAI


class EndgameThrows:
    def __init__(self, player):
        self.player = player
        self.pvpoke = PvpokeAI()

    @staticmethod
    def final(view) -> bool:
        return view.me.left() == 1 and view.foe_left == 1

    def act(self, view):
        return self.pvpoke.act(view) if self.final(view) else self.player.act(view)

    def shield(self, view, energy):
        return self.player.shield(view, energy)

    def replace(self, view):
        return self.player.replace(view)

    # The Planner learns how the opponent plays from these (bait="read" uses them).
    def saw_throw(self, *args):
        if hasattr(self.player, "saw_throw"):
            self.player.saw_throw(*args)

    def saw_shield(self, *args):
        if hasattr(self.player, "saw_shield"):
            self.player.saw_shield(*args)

    def clone(self) -> EndgameThrows:
        # PvpokeAI keys its matchup cache on the battle's Pokémon, so a fresh one is equivalent.
        return EndgameThrows(self.player.clone())
