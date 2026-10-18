"""Six against six with open team sheets: which three to bring, and who leads.

In the Play! Pokémon GO format each player registers six, both see each other's six, and before each game each
picks three in secret, the first of them leading. That is a simultaneous zero-sum game: 20 threes times 3 leads is
60 choices a side. `table` simulates every choice of ours against every choice of theirs (pogo.lineup: both sides
the trained bot with shifted habits) and `solve` finds the best mix of choices for both sides (regret matching,
averaged), its value (our win chance when both choose well), and how far any single choice falls short.
"""
from __future__ import annotations

import itertools

import numpy as np


def choices(six: list) -> list[tuple]:
    """Every three from six with each of them leading: (lead, back, back), 60 in all."""
    out = []
    for three in itertools.combinations(six, 3):
        for lead in three:
            out.append((lead, *[sp for sp in three if sp != lead]))
    return out


def solve(table: np.ndarray, rounds: int = 200_000) -> tuple[float, np.ndarray, np.ndarray]:
    """The row player's value and both mixes for a zero-sum table of the row player's win chances.

    Regret matching+ with linearly weighted averages (as in CFR+); the gap between the two sides' best replies to
    the averages shrinks as rounds grow, and `gap` reports it.
    """
    rows, cols = table.shape
    r_reg, c_reg = np.zeros(rows), np.zeros(cols)
    r_avg, c_avg = np.zeros(rows), np.zeros(cols)

    def mix(regret):
        pos = np.maximum(regret, 0)
        return pos / pos.sum() if pos.sum() > 0 else np.full(len(regret), 1 / len(regret))

    for t in range(1, rounds + 1):
        p, q = mix(r_reg), mix(c_reg)
        row_values = table @ q                 # what each row choice wins against their mix
        col_values = p @ table                 # what we win against each of their choices (they want it low)
        r_reg = np.maximum(r_reg + row_values - p @ row_values, 0)
        c_reg = np.maximum(c_reg + (p @ row_values) - col_values, 0)
        r_avg += t * p
        c_avg += t * q
        if t % 20_000 == 0 and gap(table, r_avg / r_avg.sum(), c_avg / c_avg.sum()) < 1e-4:
            break
    p, q = r_avg / r_avg.sum(), c_avg / c_avg.sum()
    return float(p @ table @ q), p, q


def gap(table: np.ndarray, p: np.ndarray, q: np.ndarray) -> float:
    """How much either side could gain by switching to its best single choice: zero at the solution."""
    return float((table @ q).max() - (p @ table).min())
