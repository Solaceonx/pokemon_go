"""Reproducible, side-balanced battles shared by team search and roster comparison."""
from __future__ import annotations

import hashlib
import itertools
import os
import random

import numpy as np

from .arena import mean_and_margin
from .battle import DRAW, Battle
from .gamedata import GameData
from .learner import Learner, QNet
from .roster import builds

_state: dict = {}


def seed_for(seed: int, *parts) -> int:
    """Separate search, fitting and test streams, without Python's randomized hash()."""
    text = ":".join(map(str, (seed, *parts)))
    return int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")


def canonical(team) -> tuple:
    return (team[0], *sorted(team[1:]))


def leads(team) -> list[tuple]:
    return [canonical((lead, *(s for s in team if s != lead))) for lead in sorted(team)]


def legal(team, dex) -> bool:
    return len(team) == 3 and all(s in dex for s in team) and len({dex[s] for s in team}) == 3


def all_lineups(ids, dex) -> list[tuple]:
    return [t for three in itertools.combinations(sorted(ids), 3) if legal(three, dex) for t in leads(three)]


def schedule(teams, weights, ids, dex, pairs: int, seed: int, listed: float = 1.0) -> list:
    """Common uniforms for lists; independent seeds for pilots, engine and each pairing.

    Changing a list changes only its selected opponent. Random-team slots, battle dice
    and pilot seeds stay identical, even when random-team legality requires rejection.
    Each item is played on both sides and is one independent observation for margins.
    """
    rows = []
    for i in range(pairs):
        rng = random.Random(seed_for(seed, "opponent", i))
        if rng.random() < listed:
            foe = rng.choices(teams, weights=weights)[0]
        else:
            while True:
                foe = rng.sample(ids, 3)
                if legal(foe, dex):
                    break
        rows.append((tuple(foe), seed_for(seed, "battle", i),
                     seed_for(seed, "pilot-a", i), seed_for(seed, "pilot-b", i)))
    return rows


def setup(model: str, pool_size: int) -> None:
    try:
        os.nice(10)
    except OSError:  # some sandboxes deny even lowering priority; callers also use nice
        pass
    gd = GameData()
    _state.update(net=QNet.load(model), usual={b.species_id: b for b in gd.meta(pool_size)},
                  owner=builds(gd), gd=gd)


def play(job):
    team, rows, owner = job
    state = _state
    source = state["owner"] if owner else state["usual"]
    mine = [source[s] for s in team]
    points = []
    for foe, dice, a_seed, b_seed in rows:
        # Old lists may contain a supported species just outside a smaller test pool.
        for sid in foe:
            if sid not in state["usual"]:
                state["usual"][sid] = state["gd"].default(sid)
        theirs = [state["usual"][s] for s in foe]
        pair = 0.0
        for side in (0, 1):
            a = Learner(q=state["net"], margin=0.02, seed=a_seed)
            b = Learner(q=state["net"], margin=0.02, seed=b_seed)
            winner = (Battle(mine, theirs, a, b, seed=dice) if side == 0 else
                      Battle(theirs, mine, b, a, seed=dice)).run()
            pair += 0.5 if winner == side else 0.25 if winner == DRAW else 0.0
        points.append(pair)
    return tuple(team), points


def evaluate(workers, teams, rows, owner=False) -> dict:
    return dict(workers.imap_unordered(play, [(t, rows, owner) for t in teams], chunksize=1))


def estimate(points) -> dict:
    mean, margin = mean_and_margin(points)
    return {"score": mean, "margin": margin, "pairs": len(points), "battles": 2 * len(points)}


def equilibrium(payoff, iterations: int = 50000) -> np.ndarray:
    """Symmetric fictitious play for an antisymmetric, zero-sum payoff matrix.

    Remembering every past best response avoids cycling between counters. The average
    strategy is the opponent mix; this optimizes only the measured finite population.
    """
    a = np.asarray(payoff, dtype=float)
    if a.ndim != 2 or a.shape[0] != a.shape[1] or not np.allclose(a, -a.T):
        raise ValueError("payoff must be square and antisymmetric")
    counts = np.ones(len(a))
    totals = a @ counts
    for _ in range(iterations):
        best = int(totals.argmax())
        counts[best] += 1
        totals += a[:, best]
    return counts / counts.sum()
