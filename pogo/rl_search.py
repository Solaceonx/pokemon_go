"""Independent Monte Carlo control guided by learned policies, using public observations only.

No Planner, Learner, Engine or their decision rules are imported. Both rollout players use neural policies.
Unknown opposing team members are sampled from a public pool, never read from the live battle.
"""
from __future__ import annotations

import copy
import time
import numpy as np

from .battle import Battle, Mon
from .dqn import Agent, observation, ordered
from .counterfactual import ForcedDecision


def copy_public_mon(mon):
    out = Mon(mon.build, hp=mon.hp, energy=mon.energy)
    out.atk_stage, out.def_stage = mon.atk_stage, mon.def_stage
    return out


def public_world(view, pool, rng, mine, theirs):
    """An imagined world from public fields. All actual unseen state remains inaccessible."""
    ours = [copy_public_mon(m) for m in view.me.team]
    shown = list(view.foe_shown)
    foes = [copy_public_mon(m) for m in shown]
    unseen = max(0, view.foe_left - sum(m.hp > 0 for m in shown))
    family = lambda build: (build.home or build.species_id).removesuffix('_shadow')
    taken = {family(m.build) for m in shown}
    for _ in range(unseen):
        candidates = [b for b in pool if family(b) not in taken]
        if not candidates:
            raise ValueError('Public pool cannot fill the unseen team without duplicate species')
        build = rng.choice(candidates)
        foes.append(Mon(build))
        taken.add(family(build))
    battle = Battle(ours, foes, mine, theirs, seed=rng.getrandbits(32))
    a, b = battle.sides
    a.active, a.shields, a.switch_wait, a.busy = view.me.active, view.me.shields, view.me.switch_wait, view.me.busy
    a.shown = list(view.me.shown)
    b.active = next(i for i, mon in enumerate(shown) if mon is view.foe)
    b.shields, b.switch_wait, b.busy = view.foe_shields, view.foe_switch_wait, view.foe_busy
    b.shown = list(range(len(shown)))
    battle.turn = view.turn
    return battle


class RolloutAgent(Agent):
    """Root Monte Carlo action values, with neural continuation and an opponent-policy ensemble.

    Search cadence is a compute budget; the neural policy remains free to choose any legal action between
    searches. Every charged-ready decision and every changed matchup is searched.
    """
    def __init__(self, net, pool, opponent_nets=None, samples=8, edge=.03, stride=8, seed=0):
        super().__init__(net, seed=seed)
        self.pool, self.opponent_nets = tuple(pool), tuple(opponent_nets or [net])
        self.samples, self.edge, self.stride = samples, edge, stride
        self._matchup, self._searched_at = None, -1000
        self.stats = {'searches': 0, 'rollouts': 0, 'changed': 0, 'seconds': 0.}

    def clone(self):
        twin = super().clone()
        twin.stats = dict(self.stats)
        return twin

    def act(self, view):
        baseline = super().act(view)
        _, mask = observation(view)
        legal = np.flatnonzero(mask)
        matchup = (view.me.active, view.foe.build.home or view.foe.build.species_id)
        due = (mask[1:3].any() or matchup != self._matchup
               or view.turn - self._searched_at >= self.stride)
        if self.samples <= 0 or len(legal) < 2 or not due:
            return baseline
        start = time.process_time()
        slots = ordered(view)[0]
        actions = {int(i): int(i) if i < 3 else 3 + slots[int(i) - 2] for i in legal}
        base_option = next(i for i, native in actions.items() if native == baseline)
        points = {i: [] for i in actions}
        for _ in range(self.samples):
            opponent_net = self.rng.choice(self.opponent_nets)
            mine = Agent(self.net, seed=self.rng.getrandbits(32))
            theirs = Agent(opponent_net, seed=self.rng.getrandbits(32))
            world = public_world(view, self.pool, self.rng, mine, theirs)
            for i, native in actions.items():
                forced = ForcedDecision(mine.clone(), 0, native)
                played = world.clone(forced, theirs.clone())
                winner = played.run()
                points[i].append(1. if winner == 0 else .5 if winner == -1 else 0.)
                self.stats['rollouts'] += 1
        means = {i: float(np.mean(values)) for i, values in points.items()}
        best = max(actions, key=lambda i: (means[i], i == base_option))
        choice = best if means[best] - means[base_option] > self.edge else base_option
        self.stats['searches'] += 1
        self.stats['changed'] += int(choice != base_option)
        self.stats['seconds'] += time.process_time() - start
        self._matchup, self._searched_at = matchup, view.turn
        return actions[choice]
