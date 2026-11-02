"""Independent complete-battle rollout improvement of learned RL policies.

Uses public observations, the rules simulator and two frozen neural policies.
The search player, Planner and Learner are not dependencies. Unseen opponents
are sampled from a supplied public pool. No weights change during inference.
"""
from __future__ import annotations

import copy
import random

import numpy as np

from .battle import Battle, Mon
from .standalone_rl import StandaloneAgent, encode, mask_for


def _copy_mon(mon):
    # Public Views can belong to an independently imported frozen rules package.
    # Construct our simulator's Mon explicitly rather than relying on isinstance.
    twin = Mon(mon.build, hp=mon.hp, energy=mon.energy)
    twin.atk_stage, twin.def_stage = mon.atk_stage, mon.def_stage
    return twin


def public_world(view, pool, ours, theirs, rng):
    """Reconstruct a pre-step world without accessing a View's private fields."""
    seen = view.foe_shown
    mine, enemies = [_copy_mon(m) for m in view.me.team], [_copy_mon(m) for m in seen]
    unseen = max(0, view.foe_left - sum(m.hp > 0 for m in seen))
    taken = {m.build.home or m.build.species_id for m in seen}
    available = {}
    for build in pool:
        identity = build.home or build.species_id
        if identity not in taken:
            available.setdefault(identity, build)
    if unseen > len(available):
        raise ValueError("public pool cannot supply distinct unseen teammates")
    enemies.extend(Mon(build) for build in rng.sample(list(available.values()), unseen))
    world = Battle(mine, enemies, ours, theirs, seed=rng.getrandbits(64),
                   shields=(view.me.shields, view.foe_shields),
                   switch_wait=(view.me.switch_wait, view.foe_switch_wait))
    a, b = world.sides
    a.active, a.busy, a.shown = view.me.active, view.me.busy, list(view.me.shown)
    b.active = next(i for i, mon in enumerate(seen) if mon is view.foe)
    b.busy, b.shown = view.foe_busy, list(range(len(seen)))
    world.turn = view.turn
    return world


class FirstAction:
    def __init__(self, inner, action):
        self.inner, self.action = inner, action

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def act(self, view):
        normal = self.inner.act(view)
        if self.action is None:
            return normal
        action, self.action = self.action, None
        if action not in view.legal():
            raise ValueError("illegal root action")
        return action


class PlanningAgent(StandaloneAgent):
    """Neural auxiliary decisions; terminal-return rollout physical actions.

    A fixed confidence gate avoids simulating already decisive neural choices.
    Each scenario supplies all legal actions with identical world/policy dice.
    Equal rollout returns are resolved by the learned policy's probabilities.
    """
    def __init__(self, model, opponent_model, pool, *, seed=0, samples=4, confidence=.98,
                 stochastic_opponent=True):
        if samples < 0 or not 0. <= confidence <= 1.:
            raise ValueError("invalid rollout budget or confidence")
        super().__init__(model, seed=seed, greedy=True)
        self.opponent_model, self.pool = opponent_model, tuple(pool)
        self.samples, self.confidence = samples, confidence
        self.stochastic_opponent = stochastic_opponent
        self.search_rng = random.Random(seed)
        self.searches = self.rollouts = self.simulated_turns = 0

    def clone(self):
        twin = super().clone()
        twin.search_rng = copy.deepcopy(self.search_rng)
        return twin

    def act(self, view):
        mask = mask_for(view, "act")
        if mask.sum() == 1 or not self.samples:
            return self.choose(view, "act")
        probabilities = self.model.forward(encode(view)[None], "act", mask[None])[0][0]
        fallback = int(probabilities.argmax())
        if probabilities[fallback] >= self.confidence:
            return fallback
        options = np.flatnonzero(mask)
        totals = np.zeros(len(mask), dtype=np.float64)
        self.searches += 1
        for _ in range(self.samples):
            # Rollouts contain only ordinary standalone networks: no recursive
            # planning and no use of the frozen opponent's controller.
            ours = StandaloneAgent(self.model, seed=self.search_rng.getrandbits(64), greedy=True)
            theirs = StandaloneAgent(self.opponent_model, seed=self.search_rng.getrandbits(64),
                                     greedy=not self.stochastic_opponent)
            world = public_world(view, self.pool, ours, theirs, self.search_rng)
            for action in options:
                fork = world.clone(FirstAction(ours.clone(), int(action)), theirs.clone())
                winner = fork.run()
                totals[action] += .5 if winner == -1 else float(winner == 0)
                self.rollouts += 1
                self.simulated_turns += fork.turn - world.turn
        best = max(totals[options])
        tied = [int(a) for a in options if totals[a] == best]
        return max(tied, key=lambda a: probabilities[a])
