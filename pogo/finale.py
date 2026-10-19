"""The last Pokémon against the last Pokémon, solved as a guessing game of plans (scripts/mirror.py; the owner: "if I
bait once and they shield, I outpace them").

When both sides are down to their last Pokémon nothing is left to switch to, so what is left is when and what to
throw and when to shield. A plan says, for each of our next `depth` charged moves while they still have a shield:
the cheaper move as soon as it is affordable (C), the cheaper move once the dearer one is affordable too (B, the bait
their energy count cannot tell from the real thing), or the dearer move (D); and for each of the next `depth` charged
moves thrown at us while we have a shield: shield (S), take it (N), or shield only if the dearer move was affordable
(?). Beyond that a plan throws the dearer move when it can, takes a knockout with the cheapest move that does it, and
shields only a hit that would knock it out. Every plan is played against every plan from the position as it stands
(Battle.clone: the simulator is the rules), the table of win shares is solved for both sides' best mixes
(pogo.sixes.solve), and `Finale` plays a plan drawn from ours, solving again after every charged move.
"""
from __future__ import annotations

import itertools
import random

import numpy as np

from .battle import CHARGED, DRAW, FAST, damage
from .sixes import solve


class Plan:
    """One plan for the rest of a last-Pokémon fight (see the module's notes)."""

    def __init__(self, throws: str, shields: str):
        self.throws, self.shields, self.thrown, self.faced = throws, shields, 0, 0

    def act(self, view):
        mon, foe = view.me.mon, view.foe
        moves = mon.build.charged
        if not moves:
            return FAST
        cheap = min(range(len(moves)), key=lambda k: moves[k].energy)
        dear = max(range(len(moves)), key=lambda k: moves[k].energy)
        ready = [k for k in range(len(moves)) if mon.energy >= moves[k].energy]
        if view.foe_shields == 0:
            lethal = [k for k in ready if damage(mon, moves[k], foe) >= foe.hp]
            if lethal:
                return self._throw(min(lethal, key=lambda k: moves[k].energy))
            return self._throw(dear) if dear in ready else FAST
        want = self.throws[self.thrown] if self.thrown < len(self.throws) else "D"
        if want == "B":
            return self._throw(cheap) if dear in ready else FAST
        k = cheap if want == "C" else dear
        return self._throw(k) if k in ready else FAST

    def _throw(self, k):
        self.thrown += 1
        return CHARGED[k]

    def shield(self, view, energy, *move):
        mon, foe = view.me.mon, view.foe
        j, self.faced = self.faced, self.faced + 1
        rule = self.shields[j] if j < len(self.shields) else "K"
        if rule == "S":
            return True
        if rule == "N":
            return False
        if rule == "?":
            return energy >= max(m.energy for m in foe.build.charged)
        return any(damage(foe, m, mon) >= mon.hp for m in foe.build.charged if m.energy <= energy)

    def replace(self, view):
        return view.me.bench()[0]

    def clone(self):
        twin = Plan(self.throws, self.shields)
        twin.thrown, twin.faced = self.thrown, self.faced
        return twin


def plans(depth: int = 2) -> list[tuple[str, str]]:
    return [("".join(t), "".join(s)) for t in itertools.product("CBD", repeat=depth)
            for s in itertools.product("SN?", repeat=depth)]


_CACHE: dict = {}


def solve_finale(battle, side: int, depth: int = 2, rounds: int = 20_000):
    """(value, our mix, plan list) for the last-Pokémon fight from this position, for `side`."""
    a, b = battle.sides[side], battle.sides[1 - side]
    key = (side, depth, battle.turn % 2, tuple(
        (s.mon.build.uid, s.mon.hp, s.mon.energy, s.mon.atk_stage, s.mon.def_stage, s.shields, s.busy) for s in (a, b)))
    if key in _CACHE:
        return _CACHE[key]
    options = plans(depth)
    table = np.zeros((len(options), len(options)))
    for i, mine in enumerate(options):
        for j, theirs in enumerate(options):
            agents = [None, None]
            agents[side], agents[1 - side] = Plan(*mine), Plan(*theirs)
            winner = battle.clone(*agents).run()
            table[i, j] = 1.0 if winner == side else 0.5 if winner == DRAW else 0.0
    value, p, _ = solve(table, rounds)
    if len(_CACHE) > 20_000:
        _CACHE.clear()
    _CACHE[key] = (value, p, options)
    return _CACHE[key]


class Finale:
    """Plays as `inner` until both sides are on their last Pokémon, then by a plan drawn from the solved mix, solving
    again after every charged move. With `fixed`, plays that one plan in every last-Pokémon fight instead (a test
    opponent: ("BDD", "??") always opens with the bait at full energy)."""

    def __init__(self, inner, rng: random.Random | None = None, depth: int = 2, fixed: tuple[str, str] | None = None):
        self.inner, self.rng, self.depth, self.fixed = inner, rng or random.Random(0), depth, fixed
        self.plan, self.stale, self.solves = None, True, 0
        self.sees_move = getattr(inner, "sees_move", False)

    def saw_throw(self, view, move, foe_energy, could_shield):
        self.stale = True
        if hasattr(self.inner, "saw_throw"):
            self.inner.saw_throw(view, move, foe_energy, could_shield)

    def saw_shield(self, view, shielded):
        if hasattr(self.inner, "saw_shield"):
            self.inner.saw_shield(view, shielded)

    def _last(self, view) -> bool:
        return view.me.left() == 1 and view.foe_left == 1 and view.me.mon.hp > 0 and view.foe.hp > 0

    def act(self, view):
        if not self._last(view):
            return self.inner.act(view)
        if self.plan is None or self.stale:
            if self.fixed:
                self.plan = Plan(*self.fixed) if self.plan is None else self.plan
            else:
                battle = view._battle
                _, p, options = solve_finale(battle, battle.sides.index(view.me), self.depth)
                self.plan = Plan(*options[self.rng.choices(range(len(options)), p)[0]])
                self.solves += 1
            self.stale = False
        action = self.plan.act(view)
        if action in CHARGED:
            self.stale = True
        self.inner.act(view)  # its own bookkeeping goes on (what it has seen; its timers)
        return action

    def shield(self, view, energy, *move):
        if not self._last(view):
            return self.inner.shield(view, energy, *move)
        if self.plan is None:
            self.plan = Plan(*(self.fixed or ("D" * self.depth, "?" * self.depth)))
        return self.plan.shield(view, energy, *move)

    def replace(self, view):
        return self.inner.replace(view)

    def clone(self):
        twin = Finale(self.inner.clone(), random.Random(self.rng.random()), self.depth, self.fixed)
        twin.plan = self.plan.clone() if self.plan else None
        twin.stale = self.stale
        return twin
