"""Small distributions for the engine lab. No global dice or learned weights."""
import math
import random

from pogo.agents import solve_2x2
from pogo.battle import damage


def private_rng(rng: random.Random) -> random.Random:
    """A process-stable private stream without advancing the player's search dice."""
    copy = random.Random()
    copy.setstate(rng.getstate())
    return random.Random(copy.getrandbits(128))


def bait_pair(view) -> tuple[int, int] | None:
    """Cheap/dear move indices for a real bait, as defined by the creator report."""
    mon, foe = view.me.mon, view.foe
    moves = mon.build.charged
    if len(moves) != 2 or view.foe_shields <= 0 or any(mon.energy < m.energy for m in moves):
        return None
    cheap, dear = sorted(range(2), key=lambda k: moves[k].energy)
    low, high = damage(mon, moves[cheap], foe), damage(mon, moves[dear], foe)
    if moves[cheap].energy == moves[dear].energy or low >= foe.hp or high < 1.3 * low:
        return None
    return cheap, dear


def validate_mixing(**settings) -> None:
    """Legacy random paths precede the lab paths; reject active combinations instead of ignoring a key."""
    lab = [k for k in ("shield_mix", "throw_mix") if settings.get(k) is not None]
    lab += [k for k in ("shield_floor", "equilibrium") if settings.get(k)]
    legacy = [k for k in ("temperature", "mix", "mix_shield", "mix_switch") if settings.get(k)]
    if lab and legacy:
        raise ValueError(f"legacy mixing options ({', '.join(legacy)}) cannot be combined with "
                         f"lab options ({', '.join(lab)})")


def logit(worth: dict, pick: int, edge: float, tau: float) -> dict:
    """Softmax of searched values with the usual edge bonus for the bot's pick.

    At zero, preserve the engine's strict edge test and its tie preference exactly.
    """
    if tau == 0:
        best = max(worth, key=lambda k: (worth[k], k == pick))
        choice = best if worth[best] - worth[pick] > edge else pick
        return {k: float(k == choice) for k in worth}
    scores = {k: v + (edge if k == pick else 0.0) for k, v in worth.items()}
    top = max(scores.values())
    weights = {k: math.exp((v - top) / tau) for k, v in scores.items()}
    total = sum(weights.values())
    return {k: w / total for k, w in weights.items()}


def shield_floor(probabilities: dict, worth: dict, edge: float, floor: float) -> dict:
    """Bound P(shield) only when the unadjusted values are within the search edge."""
    if floor and abs(worth[1] - worth[0]) <= edge:
        p = min(1 - floor, max(floor, probabilities[1]))
        return {0: 1 - p, 1: p}
    return probabilities


def equilibrium(table: list) -> list:
    """Exact maximin row distribution of a 2x2 zero-sum payoff table."""
    p = solve_2x2(*table[0], *table[1])
    return [p, 1 - p]
