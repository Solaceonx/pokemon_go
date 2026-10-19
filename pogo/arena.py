"""Play many simulated battles between two kinds of player and report who wins."""
from __future__ import annotations

import math
import os
import random
from dataclasses import dataclass

from .battle import DRAW, SHIELDS, Battle
from .gamedata import Build

SHIELD_WORTH = 0.35  # an unused shield, in units of one full Pokémon, as the Planner's lookahead counts it


def left_over(side, shield_worth: float = SHIELD_WORTH) -> float:
    """What one side has left, from 0 (nothing) to 1 (every Pokémon at full health and both shields unused)."""
    have = sum(max(m.hp, 0) / m.build.hp for m in side.team) + shield_worth * side.shields
    return have / (len(side.team) + shield_worth * SHIELDS)


def decisive(battle: Battle, side: int = 0, bare: float = 0.5) -> float:
    """How well a finished battle went for `side`, from 0 to 1, counting by how much it was won (the owner's
    idea): the winner's health and shields left. A win scores from 0.5 + bare / 2 (won with next to nothing
    left) up to 1 (won without losing anything); a loss mirrors that from the winner's side; a draw is 0.5.
    So any win scores above any loss. bare = 1 gives back plain win / draw / loss (1, 0.5, 0)."""
    if battle.winner == DRAW:
        return 0.5
    edge = bare + (1 - bare) * left_over(battle.sides[battle.winner])
    return 0.5 + 0.5 * edge if battle.winner == side else 0.5 - 0.5 * edge


def low_priority() -> None:
    """Lower batch-job priority, or retain an already-low inherited sandbox priority. On Windows (no os.nice), the
    below-normal priority class, so a PC running a job stays usable."""
    if not hasattr(os, "nice"):
        try:
            import ctypes
            kernel = ctypes.windll.kernel32
            kernel.SetPriorityClass(kernel.GetCurrentProcess(), 0x00004000)  # BELOW_NORMAL_PRIORITY_CLASS
        except (AttributeError, OSError):
            pass
        return
    try:
        os.nice(10)
    except PermissionError:
        priority = os.getpriority(os.PRIO_PROCESS, 0)
        if priority <= 0:
            raise
        print(f"priority: retaining inherited nice={priority} (sandbox denied lowering it further)", flush=True)


@dataclass
class Result:
    games: int
    wins: int
    draws: int
    losses: int
    score: float  # wins plus half the draws, as a share of games
    margin: float  # 95% half-width, from the spread across team pairings
    turns: float  # mean battle length in turns

    def __str__(self) -> str:
        return (f"{100 * self.score:5.1f}% ± {100 * self.margin:.1f}  "
                f"({self.wins} won, {self.losses} lost, {self.draws} drawn of {self.games})")


def compare(make_x, make_y, pool: list[Build], pairings: int = 500, seed: int = 0, team_size: int = 3,
            draw=None) -> Result:
    """Score player X against player Y over random teams drawn from the pool (or by draw(rng), e.g. a field).

    Each pairing of teams is played twice with the teams swapped, so neither
    player gains from being dealt the stronger team.
    """
    rng = random.Random(seed)
    wins = draws = losses = turns = 0
    pair_scores = []
    for _ in range(pairings):
        team_a, team_b = (draw(rng), draw(rng)) if draw else (rng.sample(pool, team_size), rng.sample(pool, team_size))
        pair = 0.0
        for mine, theirs in ((team_a, team_b), (team_b, team_a)):
            battle = Battle(mine, theirs, make_x(), make_y(), seed=rng.getrandbits(32))
            winner = battle.run()
            turns += battle.turn
            if winner == 0:
                wins += 1
                pair += 0.5
            elif winner == DRAW:
                draws += 1
                pair += 0.25
            else:
                losses += 1
        pair_scores.append(pair)
    mean = sum(pair_scores) / pairings
    spread = math.sqrt(sum((s - mean) ** 2 for s in pair_scores) / max(pairings - 1, 1))
    return Result(games=2 * pairings, wins=wins, draws=draws, losses=losses,
                  score=mean, margin=1.96 * spread / math.sqrt(pairings), turns=turns / (2 * pairings))


def field_results(team, pool, make_pilot, make_opponent, battles: int, seed: int, draw=None) -> list[float]:
    """One point per battle (1 win, 0.5 draw, 0 loss) for this team and pilot against random
    threes from the pool. With team None, our team is a random three as well. make_opponent(rng)
    gives each opposing pilot. The same seed gives the same teams and opponents, so two pilots
    can be compared battle by battle."""
    rng = random.Random(seed)
    points = []
    for _ in range(battles):
        mine = team or (draw(rng) if draw else rng.sample(pool, 3))
        theirs = draw(rng) if draw else rng.sample(pool, 3)  # draw: a function giving teams, e.g. teamlist.drawer
        opponent = make_opponent(rng)
        winner = Battle(mine, theirs, make_pilot(), opponent, seed=rng.getrandbits(32)).run()
        points.append(1.0 if winner == 0 else 0.5 if winner == DRAW else 0.0)
    return points


def mean_and_margin(values: list[float]) -> tuple[float, float]:
    n = len(values)
    mean = sum(values) / n
    return mean, 1.96 * math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1) / n)
