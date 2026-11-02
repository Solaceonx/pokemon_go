"""Standalone public-observation Double DQN. No Planner or Engine is called by the policy.

Actions: fast, charged 0/1, relative bench 0/1; take/shield; replacement bench 0/1.
Team slots are ordered active first, then bench in team order. Unknown opponents are zeros.
"""
from __future__ import annotations

import copy
import json
import random
from pathlib import Path

import numpy as np

from .battle import damage

N_ACTIONS = 9
TYPES = ('normal', 'fire', 'water', 'electric', 'grass', 'ice', 'fighting', 'poison', 'ground',
         'flying', 'psychic', 'bug', 'rock', 'ghost', 'dragon', 'dark', 'steel', 'fairy')
N_MON = 46
N_FEATURES = 13 + 6 * N_MON + 9 * 9


def ordered(view):
    me = view.me
    slots = [me.active] + [j for j in range(len(me.team)) if j != me.active]
    ours = [me.team[j] for j in slots]
    foes = [view.foe] + [m for m in view.foe_shown if m is not view.foe]
    return slots, (ours + [None] * 3)[:3], (foes + [None] * 3)[:3]


def mon_features(mon):
    if mon is None:
        return [0.] * N_MON
    b = mon.build
    rule = b.rule or {}
    x = [1., float(mon.hp > 0), max(0, mon.hp) / b.hp, mon.energy / 100,
         mon.atk_stage / 4, mon.def_stage / 4, b.atk / 200, b.defense / 200, b.hp / 250,
         b.cmp_atk / 200, b.fast.turns / 5, b.fast.energy_gain / 20,
         float(bool(b.forms)), float(rule.get('effect') == 'protect'), float(b.gulp is not None),
         float(b.forms is not None and b.species_id != b.home)]
    x += [float(t in b.types) for t in TYPES]
    x += [(b.charged[k].energy / 100 if k < len(b.charged) else 1.) for k in range(2)]
    for k in range(2):
        if k < len(b.charged):
            m = b.charged[k]
            x += [m.buff_chance] + [s / 4 for s in (*m.self_buffs, *m.foe_buffs)]
        else:
            x += [0.] * 5
    return x


def pair_features(a, b):
    if a is None or b is None:
        return [0.] * 9
    x = [min(damage(a, a.build.fast, b) / max(b.hp, 1), 2),
         min(damage(b, b.build.fast, a) / max(a.hp, 1), 2),
         float(a.build.cmp_atk > b.build.cmp_atk)]
    for user, target in ((a, b), (b, a)):
        for k in range(2):
            x.append(min(damage(user, user.build.charged[k], target) / max(target.hp, 1), 2)
                     if k < len(user.build.charged) else 0.)
        moves = user.build.charged
        x.append(min((max(0, m.energy - user.energy) / max(user.build.fast.energy_gain, 1)
                      for m in moves), default=10) / 10)
    return x


def observation(view, kind='act', foe_energy=None):
    """Read public fields only; never view._battle or view._foe."""
    slots, ours, foes = ordered(view)
    # shield() receives pre-spend energy; do not infer which incoming move was selected.
    if foe_energy is not None:
        foes[0] = foes[0].copy()
        foes[0].energy = foe_energy
    x = [view.turn / 480, view.me.shields / 2, view.foe_shields / 2,
         view.me.switch_wait / 90, view.foe_switch_wait / 90, view.me.busy / 5, view.foe_busy / 5,
         view.me.left() / 3, view.foe_left / 3, len(view.foe_shown) / 3,
         float(kind == 'act'), float(kind == 'shield'), float(kind == 'replace')]
    for mon in ours + foes:
        x += mon_features(mon)
    for a in ours:
        for b in foes:
            x += pair_features(a, b)
    mask = np.zeros(N_ACTIONS, dtype=bool)
    if kind == 'act':
        mask[0] = True
        for k, move in enumerate(view.me.mon.build.charged[:2]):
            mask[k + 1] = view.me.mon.energy >= move.energy
        if view.me.switch_wait == 0:
            for k, j in enumerate(slots[1:]):
                mask[3 + k] = view.me.team[j].hp > 0
    elif kind == 'shield':
        mask[5] = True
        mask[6] = view.me.shields > 0
    elif kind == 'replace':
        for k, j in enumerate(slots[1:]):
            mask[7 + k] = view.me.team[j].hp > 0
    else:
        raise ValueError(kind)
    return np.asarray(x, dtype=np.float32), mask


def potential(view):
    ours = sum(max(0, m.hp) / m.build.hp for m in view.me.team) + .35 * view.me.shields
    shown = view.foe_shown
    theirs = (sum(max(0, m.hp) / m.build.hp for m in shown)
              + max(0, view.foe_left - sum(m.hp > 0 for m in shown)) + .35 * view.foe_shields)
    return .25 * (ours - theirs) / 3.7


class Network:
    """Two ReLU layers, linear Q heads, Adam; optimizer state is checkpointed."""
    def __init__(self, seed=0, hidden=128):
        rng = np.random.default_rng(seed)
        shapes = [(N_FEATURES, hidden), (hidden,), (hidden, hidden), (hidden,), (hidden, N_ACTIONS), (N_ACTIONS,)]
        self.p = [(rng.normal(0, (2 / s[0]) ** .5, s) if len(s) == 2 else np.zeros(s)).astype(np.float32)
                  for s in shapes]
        self.p[-2] *= .01
        self.m = [np.zeros_like(p) for p in self.p]
        self.v = [np.zeros_like(p) for p in self.p]
        self.steps = 0

    def predict(self, x):
        a = np.maximum(x @ self.p[0] + self.p[1], 0)
        b = np.maximum(a @ self.p[2] + self.p[3], 0)
        return b @ self.p[4] + self.p[5]

    def update(self, x, actions, targets, masks=None, imitation=0., rate=3e-4, weights=None):
        a = np.maximum(x @ self.p[0] + self.p[1], 0)
        b = np.maximum(a @ self.p[2] + self.p[3], 0)
        q = b @ self.p[4] + self.p[5]
        rows = np.arange(len(x))
        error = q[rows, actions] - targets
        weights = np.ones(len(x), dtype=np.float32) if weights is None else weights
        dq = np.zeros_like(q)
        dq[rows, actions] = np.clip(error, -1, 1) * weights / len(x)
        loss = float(np.mean(np.where(abs(error) <= 1, .5 * error ** 2, abs(error) - .5) * weights))
        if imitation:
            # Demo large-margin classification: maintain action ordering while fitting returns.
            margin = np.where(masks, .2, -1e6)
            margin[rows, actions] = 0
            rivals = np.argmax(q + margin, axis=1)
            active = q[rows, rivals] + margin[rows, rivals] > q[rows, actions]
            dq[rows, rivals] += imitation * active / len(x)
            dq[rows, actions] -= imitation * active / len(x)
        grads = [None] * 6
        grads[4], grads[5] = b.T @ dq, dq.sum(axis=0)
        db = (dq @ self.p[4].T) * (b > 0)
        grads[2], grads[3] = a.T @ db, db.sum(axis=0)
        da = (db @ self.p[2].T) * (a > 0)
        grads[0], grads[1] = x.T @ da, da.sum(axis=0)
        norm = sum(float((g * g).sum()) for g in grads) ** .5
        scale = min(1., 10 / max(norm, 1e-10))
        self.steps += 1
        for p, m, v, g in zip(self.p, self.m, self.v, grads):
            g = g * scale
            m *= .9
            m += .1 * g
            v *= .999
            v += .001 * g * g
            p -= rate * (m / (1 - .9 ** self.steps)) / (np.sqrt(v / (1 - .999 ** self.steps)) + 1e-8)
        return loss, abs(error)

    def save(self, path, metadata=None, target=None):
        data = {f'{name}{i}': a for name, arrays in [('p', self.p), ('m', self.m), ('v', self.v)]
                for i, a in enumerate(arrays)}
        data['steps'] = np.array(self.steps)
        data['metadata'] = np.array(json.dumps(metadata or {}))
        if target is not None:
            data.update({f'target{i}': p for i, p in enumerate(target.p)})
        path = Path(path)
        temp = path.with_name(path.name + '.tmp')
        with temp.open('wb') as f:
            np.savez_compressed(f, **data)
        temp.replace(path)

    @classmethod
    def load(cls, path):
        with np.load(path, allow_pickle=False) as data:
            if data['p0'].shape[0] != N_FEATURES or data['p5'].shape != (N_ACTIONS,):
                raise ValueError('Checkpoint observation/action schema differs from this policy')
            net = cls(hidden=data['p0'].shape[1])
            for name in ('p', 'm', 'v'):
                setattr(net, name, [data[f'{name}{i}'].copy() for i in range(6)])
            net.steps = int(data['steps'])
            metadata = json.loads(str(data['metadata']))
            target = copy.deepcopy(net)
            if 'target0' in data:
                target.p = [data[f'target{i}'].copy() for i in range(6)]
        return net, metadata, target


def double_targets(online, target, next_x, next_masks, rewards, discounts):
    choices = np.where(next_masks, online.predict(next_x), -np.inf).argmax(axis=1)
    values = target.predict(next_x)[np.arange(len(next_x)), choices]
    return rewards + discounts * values


class Agent:
    """Independent policy. Teacher is optional and used only to collect demonstrations."""
    def __init__(self, net, seed=0, epsilon=0., teacher=None, record=False):
        self.net, self.rng, self.epsilon = net, random.Random(seed), epsilon
        self.teacher, self.record, self.log = teacher, record, []

    def clone(self):
        twin = copy.copy(self)
        twin.rng = random.Random()
        twin.rng.setstate(self.rng.getstate())
        twin.log, twin.record = [], False
        twin.teacher = self.teacher.clone() if self.teacher else None
        return twin

    def choose(self, view, kind, foe_energy=None):
        x, mask = observation(view, kind, foe_energy)
        slots = ordered(view)[0]
        legal = np.flatnonzero(mask)
        if not len(legal):
            raise ValueError(f'No legal {kind} action')
        if self.teacher is not None:
            if kind == 'act':
                action = self.teacher.act(view)
                pick = action if action < 3 else 3 + slots[1:].index(action - 3)
            elif kind == 'shield':
                pick = 5 + int(self.teacher.shield(view, foe_energy))
            else:
                pick = 7 + slots[1:].index(self.teacher.replace(view))
        elif len(legal) == 1:
            pick = int(legal[0])
        elif self.rng.random() < self.epsilon:
            pick = int(self.rng.choice(legal))
        else:
            pick = int(np.where(mask, self.net.predict(x), -np.inf).argmax())
        if not mask[pick]:
            raise ValueError(f'Illegal teacher action {pick}')
        if self.record and len(legal) > 1:
            self.log.append((x, mask, pick, potential(view)))
        if kind == 'act':
            return pick if pick < 3 else 3 + slots[pick - 2]
        if kind == 'shield':
            return pick == 6
        return slots[pick - 6]

    def act(self, view):
        # Forced fast moves do not require feature extraction or a neural decision.
        mon = view.me.mon
        if (view.me.switch_wait > 0 or not view.me.bench()) and not any(mon.energy >= m.energy for m in mon.build.charged):
            return self.teacher.act(view) if self.teacher is not None else 0
        return self.choose(view, 'act')

    def shield(self, view, foe_energy):
        return self.choose(view, 'shield', foe_energy)

    def replace(self, view):
        return self.choose(view, 'replace')

    def saw_throw(self, *args):
        if self.teacher is not None:
            self.teacher.saw_throw(*args)

    def saw_shield(self, *args):
        if self.teacher is not None:
            self.teacher.saw_shield(*args)


def transitions(log, result, nstep=8):
    """Undiscounted n-step returns with telescoping public-state potential shaping.

    Each step is the next non-forced policy decision, including shield/replacement callbacks.
    Terminal potential is zero; total return differs from the win reward by -initial potential.
    """
    for i, (x, mask, action, phi) in enumerate(log):
        j = min(i + nstep, len(log))
        terminal = j == len(log)
        next_x, next_mask = (np.zeros_like(x), np.ones_like(mask)) if terminal else log[j][:2]
        reward = result - phi if terminal else log[j][3] - phi
        yield x, mask, action, reward, next_x, next_mask, float(not terminal), result - phi


class Replay:
    def __init__(self, capacity=50000):
        self.capacity, self.size, self.cursor = capacity, 0, 0
        self.x = np.zeros((capacity, N_FEATURES), np.float32)
        self.mask = np.zeros((capacity, N_ACTIONS), bool)
        self.action = np.zeros(capacity, np.int64)
        self.reward = np.zeros(capacity, np.float32)
        self.next_x = np.zeros_like(self.x)
        self.next_mask = np.zeros_like(self.mask)
        self.discount = np.zeros(capacity, np.float32)
        self.mc = np.zeros(capacity, np.float32)
        self.priority = np.ones(capacity, np.float32)

    def add(self, rows):
        for row in rows:
            i = self.cursor
            for name, value in zip(('x', 'mask', 'action', 'reward', 'next_x', 'next_mask', 'discount', 'mc'), row):
                getattr(self, name)[i] = value
            self.priority[i] = max(float(self.priority[:self.size].max()) if self.size else 1., .01)
            self.cursor = (i + 1) % self.capacity
            self.size = min(self.capacity, self.size + 1)

    def sample(self, rng, n):
        probs = (self.priority[:self.size] + .01) ** .6
        probs /= probs.sum()
        ids = rng.choice(self.size, n, replace=True, p=probs)
        weights = (self.size * probs[ids]) ** -.4
        return ids, weights / weights.max()

    def save(self, path):
        data = {k: v[:self.size] for k, v in vars(self).items() if isinstance(v, np.ndarray)}
        data.update(capacity=self.capacity, size=self.size, cursor=self.cursor)
        temp = Path(str(path) + '.tmp')
        with temp.open('wb') as f:
            np.savez_compressed(f, **data)
        temp.replace(path)

    @classmethod
    def load(cls, path):
        with np.load(path, allow_pickle=False) as data:
            replay = cls(int(data['capacity']))
            replay.size, replay.cursor = int(data['size']), int(data['cursor'])
            for k, v in vars(replay).items():
                if isinstance(v, np.ndarray):
                    v[:replay.size] = data[k]
        return replay
