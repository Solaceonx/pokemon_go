"""Finite-horizon exact endgames, using Battle.step as the rules oracle.

Payoffs are win share (draw = .5). Numerical matrix games use vertex enumeration,
not rollout estimates. Shields do NOT see the pending move. Pure turn strategies
are contingent on observations, so simultaneous actions, baiting, CMP, buffs and
switches retain the engine's information rules. At most two living mons per side
means every forced replacement is unique. The clock makes the graph acyclic.
"""
from __future__ import annotations

import itertools
import time
from dataclasses import dataclass

import numpy as np

from .battle import Battle, DRAW
from .learner import Learner


class SolveLimit(RuntimeError):
    """No exact answer was obtained within the work/time budget."""


def state_key(b):
    return (b.turn, b.winner, tuple(
        (s.active, s.shields, s.switch_wait, s.busy, tuple(s.shown), tuple(
            (m.build.uid, max(0, m.hp), m.energy, m.atk_stage, m.def_stage)
            for m in s.team)) for s in b.sides))


def matrix_game(payoffs, tick=lambda: None):
    """Return value and both optimal mixtures, with a primal/dual certificate."""
    a = np.asarray(payoffs, dtype=float)

    def rows(a):
        m, n = a.shape
        best, policy = -float('inf'), None
        # Vertices of {p >= 0, sum p = 1, p A >= v}.
        for k in range(1, min(m, n) + 1):
            for support in itertools.combinations(range(m), k):
                for tight in itertools.combinations(range(n), k):
                    tick()
                    system = np.ones((k + 1, k + 1))
                    system[:k, :k] = a[np.ix_(support, tight)].T
                    system[:k, k] = -1
                    system[k, k] = 0
                    try:
                        x = np.linalg.solve(system, np.r_[np.zeros(k), 1.])
                    except np.linalg.LinAlgError:
                        continue
                    if min(x[:k]) < -1e-9:
                        continue
                    p = np.zeros(m)
                    p[list(support)] = np.maximum(0, x[:k])
                    p /= p.sum()
                    value = float(min(p @ a))
                    if value > best:
                        best, policy = value, p
        return best, policy

    low, high = a.min(axis=1), a.max(axis=0)
    i, j = int(low.argmax()), int(high.argmin())
    if high[j] - low[i] <= 1e-10:
        return float(low[i]), np.eye(1, len(low), i)[0], np.eye(1, len(high), j)[0]
    v, p = rows(a)
    w, q = rows(-a.T)
    if abs(v + w) > 1e-8:
        raise ArithmeticError('matrix game failed primal/dual agreement')
    return (v - w) / 2, p, q


class _Request(Exception):
    def __init__(self, key, choices):
        self.key, self.choices = key, choices


class _Tape:
    def __init__(self, answers, cuts):
        self.answers, self.cuts, self.offset = answers, cuts, 0
        self.own_actions = [None, None]

    def ask(self, key, choices):
        if self.offset == len(self.answers):
            raise _Request(key, choices)
        answer = self.answers[self.offset]
        self.offset += 1
        return answer

    def random(self):
        return self.ask(None, tuple(((a + b) / 2, b - a)
                                   for a, b in zip(self.cuts, self.cuts[1:])))


class _TurnPlayer:
    def __init__(self, side, tape):
        self.side, self.tape = side, tape

    def act(self, view):
        action = self.tape.ask((self.side, 'act'), tuple(view.legal()))
        self.tape.own_actions[self.side] = action
        return action

    def shield(self, view, energy):
        # No pending charged move, opposing action or random tape in this key.
        key = (self.side, 'shield', self.tape.own_actions[self.side],
               state_key(view._battle))
        return self.tape.ask(key, (False, True))

    def replace(self, view):
        bench = view.me.bench()
        assert len(bench) == 1
        return bench[0]


@dataclass
class Solution:
    value: float
    plans: tuple
    mixtures: tuple


class Solver:
    def __init__(self, max_nodes=20000, seconds=2., memo=True):
        self.max_nodes, self.seconds, self.memo = max_nodes, seconds, memo
        self.cache = {}
        self.nodes = self.work = 0
        self.deadline = 0.

    @staticmethod
    def qualifies(b):
        return all(0 < s.left() <= 2 and s.mon.hp > 0 and
                   all(j in s.shown for j, m in enumerate(s.team) if m.hp > 0)
                   for s in b.sides)

    def tick(self):
        self.work += 1
        if self.work > self.max_nodes * 100 or time.monotonic() > self.deadline:
            raise SolveLimit('work/time limit')

    def solve(self, battle):
        if battle.winner is None and not self.qualifies(battle):
            raise ValueError('requires revealed, living active mons and at most two alive per side')
        self.nodes = self.work = 0
        self.deadline = time.monotonic() + self.seconds
        try:
            return self._solve(battle)
        except (SolveLimit, RecursionError) as exc:
            raise SolveLimit(str(exc)) from exc

    def _solve(self, b):
        self.tick()
        if b.winner is not None:
            return Solution(.5 if b.winner == DRAW else float(b.winner == 0), (), ())
        key = state_key(b)
        if self.memo and key in self.cache:
            return self.cache[key]
        self.nodes += 1
        if self.nodes > self.max_nodes:
            raise SolveLimit('position limit')
        cuts = sorted({0., .5, 1.} | {move.buff_chance for s in b.sides
                      for m in s.team for move in m.build.charged if 0 < move.buff_chance < 1})

        def tree(answers):
            self.tick()
            tape = _Tape(answers, cuts)
            twin = b.clone(_TurnPlayer(0, tape), _TurnPlayer(1, tape))
            twin.rng = tape
            try:
                twin.step()
            except _Request as request:
                if request.key is None:
                    return (None, [(p, tree(answers + [x])) for x, p in request.choices])
                return (request.key, [(x, tree(answers + [x])) for x in request.choices])
            twin.rng = b.rng  # dice state is irrelevant; each future draw is integrated
            return self._solve(twin).value

        root = tree([])

        def plans(side):
            def missing(node, plan):
                self.tick()
                if isinstance(node, float):
                    return None
                info, children = node
                if info is not None and info[0] == side:
                    if info not in plan:
                        return info, [x for x, _ in children]
                    children = [(x, child) for x, child in children if x == plan[info]]
                for _, child in children:
                    found = missing(child, plan)
                    if found is not None:
                        return found
                return None

            def expand(plan):
                found = missing(root, plan)
                if found is None:
                    yield plan
                else:
                    info, choices = found
                    for choice in choices:
                        yield from expand(plan | {info: choice})
            return list(expand({}))

        strategies = (plans(0), plans(1))

        def payoff(node, p, q):
            self.tick()
            if isinstance(node, float):
                return node
            info, children = node
            if info is None:
                return sum(prob * payoff(child, p, q) for prob, child in children)
            choice = (p, q)[info[0]][info]
            return next(payoff(child, p, q) for x, child in children if x == choice)

        a = [[payoff(root, p, q) for q in strategies[1]] for p in strategies[0]]
        value, p, q = matrix_game(a, self.tick)
        result = Solution(value, strategies, (p, q))
        if self.memo:
            self.cache[key] = result
        return result


class EndgamePlayer(Learner):
    """Learner plus bounded exact solves; samples a complete contingent turn plan.

    Instantiate with q=QNet.load(...), margin=.02 for the current best fallback.
    No approximate search result is ever used. Busy turns can still need shields.
    """
    def __init__(self, *, max_nodes=1000, seconds=.05, **kwargs):
        super().__init__(**kwargs)
        self.solver = Solver(max_nodes, seconds)
        self._plan = None
        self._plan_turn = None
        self.solved = self.limited = 0

    def clone(self):
        twin = super().clone()
        twin.solver = Solver(self.solver.max_nodes, self.solver.seconds)
        twin._plan = None
        twin._plan_turn = None
        return twin

    def _prepare(self, view):
        b = view._battle
        if self._plan_turn == (id(b), b.turn):
            return
        self._plan_turn, self._plan = (id(b), b.turn), None
        if not self.solver.qualifies(b):
            return
        # Keep memory bounded between decisions; exact descendants can be large.
        self.solver.cache.clear()
        try:
            result = self.solver.solve(b)
        except SolveLimit:
            self.limited += 1
            return
        side = 0 if view.me is b.sides[0] else 1
        index = self.rng.choices(range(len(result.plans[side])), result.mixtures[side])[0]
        self._plan = result.plans[side][index]
        self.solved += 1

    def act(self, view):
        self._prepare(view)
        side = 0 if view.me is view._battle.sides[0] else 1
        if self._plan is not None:
            return self._plan[(side, 'act')]
        return super().act(view)

    def shield(self, view, foe_energy):
        # If busy at the start of this turn there was no act callback. Solving
        # from inside _throw would be a different position, so fall back then.
        b = view._battle
        side = 0 if view.me is b.sides[0] else 1
        if self._plan_turn == (id(b), b.turn) and self._plan is not None:
            action = self._plan.get((side, 'act'))
            key = (side, 'shield', action, state_key(b))
            if key in self._plan:
                return self._plan[key]
        return super().shield(view, foe_energy)
