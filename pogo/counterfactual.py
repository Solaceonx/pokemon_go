"""Training-only policy losses and isolated replay controls. Inference remains pogo.dqn.Agent."""
from __future__ import annotations

import copy
import numpy as np

from .dqn import observation, ordered


def forward(net, x):
    a = np.maximum(x @ net.p[0] + net.p[1], 0)
    b = np.maximum(a @ net.p[2] + net.p[3], 0)
    return a, b, b @ net.p[4] + net.p[5]


def backward(net, x, a, b, dq, rate):
    grads = [None] * 6
    grads[4], grads[5] = b.T @ dq, dq.sum(axis=0)
    db = (dq @ net.p[4].T) * (b > 0)
    grads[2], grads[3] = a.T @ db, db.sum(axis=0)
    da = (db @ net.p[2].T) * (a > 0)
    grads[0], grads[1] = x.T @ da, da.sum(axis=0)
    norm = sum(float((g * g).sum()) for g in grads) ** .5
    scale = min(1., 10 / max(norm, 1e-10))
    net.steps += 1
    for p, m, v, g in zip(net.p, net.m, net.v, grads):
        g = g * scale
        m *= .9
        m += .1 * g
        v *= .999
        v += .001 * g * g
        p -= rate * (m / (1 - .9 ** net.steps)) / (np.sqrt(v / (1 - .999 ** net.steps)) + 1e-8)


def classification_loss(logits, mask, actions, weights=None, temperature=.1):
    """Masked weighted CE and its exact output derivative; illegal actions receive zero gradient."""
    if temperature <= 0 or not np.all(mask[np.arange(len(actions)), actions]):
        raise ValueError('Invalid temperature or demonstration action')
    z = np.where(mask, logits / temperature, -np.inf)
    z -= z.max(axis=1, keepdims=True)
    probs = np.exp(z)
    probs /= probs.sum(axis=1, keepdims=True)
    weights = np.ones(len(actions)) if weights is None else np.asarray(weights)
    normalizer = max(float(weights.sum()), 1e-12)
    rows = np.arange(len(actions))
    loss = float(np.sum(-np.log(np.maximum(probs[rows, actions], 1e-30)) * weights) / normalizer)
    dq = probs.copy()
    dq[rows, actions] -= 1
    dq *= (weights / (normalizer * temperature))[:, None]
    return loss, dq


def imitate(net, x, mask, actions, weights=None, rate=1e-4, temperature=.1):
    a, b, q = forward(net, x)
    loss, dq = classification_loss(q, mask, actions, weights, temperature)
    backward(net, x, a, b, dq, rate)
    return loss


def advantage_loss(logits, mask, returns):
    """Fit paired full-game advantages; common return offsets cancel before fitting.

    Rows with identical returns for all options carry zero policy-improvement signal and zero gradient.
    Every position is sampled before seeing its outcome, including future wins and losses.
    """
    count = mask.sum(axis=1, keepdims=True)
    if np.any(count == 0):
        raise ValueError('Every position needs legal options')
    q = np.where(mask, logits, 0.)
    y = np.where(mask, returns, 0.)
    pred = q - q.sum(axis=1, keepdims=True) / count
    target = y - y.sum(axis=1, keepdims=True) / count
    signal = np.any(np.where(mask, abs(target), 0.) > 1e-8, axis=1)
    error = np.where(mask, pred - target, 0.)
    weights = signal[:, None] / count
    denominator = max(int(signal.sum()), 1)
    loss = float(np.sum(np.where(abs(error) <= 1, .5 * error ** 2, abs(error) - .5) * weights) / denominator)
    dq = np.clip(error, -1, 1) * weights / denominator
    dq -= np.where(mask, dq.sum(axis=1, keepdims=True) / count, 0.)
    return loss, dq


def improve(net, x, mask, returns, rate=1e-4):
    a, b, q = forward(net, x)
    loss, dq = advantage_loss(q, mask, returns)
    if np.any(dq):
        backward(net, x, a, b, dq, rate)
    return loss


def isolated_clone(agent):
    """Copy mutable per-game caches as well as player RNG; immutable weights/builds may be shared."""
    twin = agent.clone()
    if hasattr(agent, '_outlooks'):
        twin._outlooks = dict(agent._outlooks)
    if hasattr(agent, 'evaluator'):
        twin.evaluator = copy.copy(agent.evaluator)
        twin.evaluator._agent = isolated_clone(agent.evaluator._agent)
    # Engine.clone intentionally clears some bookkeeping; full counterfactual replay needs it intact.
    for name in ('_pending', '_pending_shield', '_their_throw'):
        if hasattr(agent, name):
            setattr(twin, name, copy.deepcopy(getattr(agent, name)))
    return twin


class ForcedDecision:
    """Override one indexed callback after replaying its prefix, including shield/replace inside a step."""
    def __init__(self, inner, index, choice):
        self.inner, self.index, self.choice = inner, index, choice
        self.seen, self.applied = 0, False

    def _choose(self, native):
        replace = self.seen == self.index and not self.applied
        self.seen += 1
        if replace:
            self.applied = True
            return self.choice
        return native

    def act(self, view):
        return self._choose(self.inner.act(view))

    def shield(self, view, energy):
        return bool(self._choose(self.inner.shield(view, energy)))

    def replace(self, view):
        return self._choose(self.inner.replace(view))

    def saw_throw(self, *args):
        self.inner.saw_throw(*args)

    def saw_shield(self, *args):
        self.inner.saw_shield(*args)


def native_action(index, kind, slots):
    if kind == 'act':
        return index if index < 3 else 3 + slots[index - 2]
    if kind == 'shield':
        return index == 6
    return slots[index - 6]


class StepRecorder:
    """Record public policy inputs and native choices; a training loop owns environment snapshots."""
    def __init__(self, inner):
        self.inner, self.calls = inner, []

    def choose(self, kind, view, energy=None):
        x, mask = observation(view, kind, energy)
        slots = ordered(view)[0]
        native = (self.inner.act(view) if kind == 'act' else self.inner.shield(view, energy)
                  if kind == 'shield' else self.inner.replace(view))
        choices = {int(i): native_action(int(i), kind, slots) for i in np.flatnonzero(mask)}
        chosen = next(i for i, value in choices.items() if value == native)
        self.calls.append({'kind': kind, 'x': x, 'mask': mask, 'choice': chosen,
                           'native': native, 'options': choices})
        return native

    def act(self, view):
        return self.choose('act', view)

    def shield(self, view, energy):
        return self.choose('shield', view, energy)

    def replace(self, view):
        return self.choose('replace', view)

    def saw_throw(self, *args):
        self.inner.saw_throw(*args)

    def saw_shield(self, *args):
        self.inner.saw_shield(*args)


def replay_choice(snapshot, callback_index, native_choice, side=0):
    battle, players = snapshot
    copies = [isolated_clone(agent) for agent in players]
    forced = ForcedDecision(copies[side], callback_index, native_choice)
    copies[side] = forced
    played = battle.clone(*copies)
    winner = played.run()
    if not forced.applied:
        raise RuntimeError('Counterfactual callback was not reached')
    return 0. if winner == -1 else 1. if winner == side else -1.
