"""How good a position is, the way a chess engine's evaluation says it: one number, from what one player can see.

An evaluation is the expected decisiveness (pogo.arena.decisive) of the battle from here, for the player whose
view it is: 1 a win without losing anything, 0.75 a narrow win, 0.5 even, 0.25 a narrow loss, 0 a rout. The
learned one (`Evaluator` with a model, trained by scripts/train_eval.py) reads the same 45 numbers as the trained
bot (pogo.learner.describe): both Pokémon out, their health, energy, stat changes and moves, the pace of the
matchup, shields, switch timers, the bench, unseen Pokémon and the clock.

`material` is the plain count, as a chess player counts pieces: health and shields left on each side, with an
opponent's unseen Pokémon taken as untouched. It is what the learned evaluation has to beat.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .arena import SHIELD_WORTH
from .battle import SHIELDS, View
from .learner import Learner, describe
from .value import ValueModel


def material(view: View, shield_worth: float = SHIELD_WORTH) -> float:
    """Health and shields left, ours against theirs, as an evaluation between 0 and 1 (0.5 is even)."""
    ours = sum(max(m.hp, 0) / m.build.hp for m in view.me.team) + shield_worth * view.me.shields
    seen = view.foe_shown
    unseen = max(0, view.foe_left - sum(m.hp > 0 for m in seen))
    theirs = sum(max(m.hp, 0) / m.build.hp for m in seen) + unseen + shield_worth * view.foe_shields
    full = 3 + shield_worth * SHIELDS
    return 0.5 + 0.5 * (ours - theirs) / full


class Evaluator:
    """The engine's evaluation of a position from one player's view: 0 to 1, 0.5 even (see the module notes)."""

    def __init__(self, model: ValueModel | None = None):
        self.model = model
        self._agent = Learner()  # only for its cached one-on-one outlooks, which describe() reads

    def features(self, view: View) -> list[float]:
        if len(self._agent._outlooks) > 50_000:
            self._agent._outlooks.clear()
        return describe(self._agent, view)

    def __call__(self, view: View) -> float:
        if self.model is None:
            return material(view)
        return self.model(self.features(view))

    def many(self, rows: np.ndarray) -> np.ndarray:
        """Evaluations for rows of features already worked out."""
        return self.model.predict(rows)

    @classmethod
    def load(cls, path: Path | str) -> Evaluator:
        return cls(ValueModel.load(path))

    def save(self, path: Path | str) -> None:
        self.model.save(path)


def as_score(evaluation: float) -> str:
    """An evaluation shown the way chess engines show theirs: +0.42 is well ahead, -0.10 a little behind."""
    return f"{2 * evaluation - 1:+.2f}"
