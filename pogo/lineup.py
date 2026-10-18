"""The chance that one team beats another, both known, before the first turn.

Both sides are played by the trained bot with its habits shifted a little in each battle (as in the training
crowd), so the number is how these two teams do in the hands of two equally good players, not one fixed game.
"""
from __future__ import annotations

import random

from .agents import varied_settings
from .arena import mean_and_margin
from .battle import DRAW, Battle
from .learner import Learner


def win_chance(net, pool: list, mine: list, theirs: list, battles: int = 200, seed: int = 0) -> tuple[float, float]:
    """(chance, 95% margin) that `mine` beats `theirs`, each lead first."""
    rng = random.Random(seed)
    points = []
    for _ in range(battles):
        ours = Learner(q=net, margin=rng.choice((0.02, 0.05)), **varied_settings(rng, pool))
        foes = Learner(q=net, margin=rng.choice((0.02, 0.05)), **varied_settings(rng, pool))
        winner = Battle(mine, theirs, ours, foes, seed=rng.getrandbits(32)).run()
        points.append(1.0 if winner == 0 else 0.5 if winner == DRAW else 0.0)
    return mean_and_margin(points)
