"""A search at the bot's judgement calls, the way a chess engine searches: look ahead, judge the positions reached.

At a decision (throw a charged move or keep fast-moving, swap or stay, which replacement), the `Engine` rebuilds
the battle from what it can see, with what it cannot (the opponent's unseen Pokémon) drawn at random, plays each
option `horizon` turns ahead several times with the same dice for every option, and judges where it ends up with
an evaluation (pogo.evaluation; a battle that ends inside the horizon is scored by pogo.arena.decisive). It takes
the best option if it beats the trained bot's own pick by `edge`; otherwise it plays as the trained bot.

Both sides are played inside the look-ahead by the quick rollout player (pogo.agents._rollout), so a look costs
little. Shield decisions are left to the trained bot: the defender does not know which move is coming.
"""
from __future__ import annotations

import random

from .agents import _rollout
from .arena import decisive
from .battle import CHARGED, FAST, SWITCH, Battle, Mon, View
from .learner import Learner


class _First:
    """A player whose first action is fixed; after that, `inner` plays."""

    def __init__(self, inner, action):
        self.inner, self.action = inner, action

    def act(self, view):
        if self.action is not None:
            action, self.action = self.action, None
            if action in view.legal():
                return action
        return self.inner.act(view)

    def shield(self, view, energy, *move):
        return self.inner.shield(view, energy)

    def replace(self, view):
        return self.inner.replace(view)


def imagine(view: View, rng: random.Random, pool: list, me_agent, foe_agent) -> Battle:
    """A battle standing where this view stands, with the opponent's unseen Pokémon drawn from the pool."""
    me = view.me
    mine = [m.copy() for m in me.team]
    seen = view.foe_shown
    theirs = [m.copy() for m in seen]
    unseen = max(0, view.foe_left - sum(m.hp > 0 for m in seen))
    taken = {m.build.species_id for m in seen}
    theirs += [Mon(b) for b in rng.sample([b for b in pool if b.species_id not in taken], unseen)]
    battle = Battle(mine, theirs, me_agent, foe_agent, seed=rng.getrandbits(32),
                    shields=(me.shields, view.foe_shields), switch_wait=(me.switch_wait, view.foe_switch_wait))
    ours, foes = battle.sides
    ours.active, ours.busy, ours.shown = me.active, me.busy, list(me.shown)
    foes.active = next(i for i, m in enumerate(seen) if m is view.foe)
    foes.busy, foes.shown = view.foe_busy, list(range(len(seen)))
    battle.turn = view.turn
    return battle


class Engine(Learner):
    def __init__(self, evaluator, pool: list, horizon: int = 20, samples: int = 6, edge: float = 0.0,
                 heads: tuple = ("throw", "swap", "mid_swap", "replace"), rollout: str = "quick", **settings):
        super().__init__(**settings)
        self.evaluator, self.pool = evaluator, pool
        self.horizon, self.samples, self.edge, self.heads = horizon, samples, edge, heads
        # Who plays inside the look-ahead: "quick", the cheap rollout player, or "bot", the trained bot itself.
        self.rollout = rollout
        self.looks = 0  # decisions searched
        self.changed = 0  # of those, how many went against the trained bot's pick

    def clone(self) -> Engine:
        return super().clone()

    def _decide(self, head: str, view: View, mask: tuple, planner_choice, foe_energy: int | None = None) -> int:
        if head in self.forced or head not in self.heads:
            return super()._decide(head, view, mask, planner_choice, foe_energy)
        options = [k for k in range(len(mask)) if mask[k]]
        pick = super()._decide(head, view, mask, planner_choice, foe_energy)  # the trained bot's choice
        if len(options) < 2:
            return pick
        seeds = [self.rng.getrandbits(32) for _ in range(self.samples)]
        worth = {k: sum(self._look(view, head, k, s) for s in seeds) / len(seeds) for k in options}
        self.looks += 1
        best = max(options, key=lambda k: (worth[k], k == pick))
        if worth[best] - worth[pick] > self.edge:
            self.changed += best != pick
            return best
        return pick

    def _look(self, view: View, head: str, option: int, seed: int) -> float:
        """Play one option `horizon` turns ahead in one imagined battle; judge the position reached."""
        rng = random.Random(seed)
        others = [j for j in range(3) if j != view.me.active]
        first = None
        if head == "throw":
            first = FAST if option == 0 else CHARGED[option - 1]
        elif head in ("swap", "mid_swap"):
            first = None if option == 0 else SWITCH[others[option - 1]]
        if self.rollout == "bot":
            us, them = (Learner(q=self.q, margin=self.margin, seed=rng.getrandbits(32)) for _ in range(2))
        else:
            us, them = _rollout(), _rollout()
        battle = imagine(view, rng, self.pool, _First(us, first), them)
        if head == "replace":
            battle.sides[0].active = others[option]
            if others[option] not in battle.sides[0].shown:
                battle.sides[0].shown.append(others[option])
        foes = battle.sides[1]
        if foes.mon.hp <= 0:  # they fainted on the same turn: they send in someone too
            if not foes.bench():
                return decisive(battle, 0) if battle.winner is not None else 0.5
            foes.active = foes.bench()[0]
            foes.shown.append(foes.active)
        for _ in range(self.horizon):
            if battle.winner is not None:
                return decisive(battle, 0)
            battle.step()
        if battle.winner is not None:
            return decisive(battle, 0)
        return self.evaluator(battle.views[0])
