"""Inference-only averaging over equivalent own-team slot representations.

Runtime needs the neural policy and public observations only. Physical action
numbers are restored before averaging; the weights and game rules are untouched.
"""
from __future__ import annotations

import itertools
import numpy as np

from .standalone_rl import (
    HEADS, MON_FEATURES, PAIR_FEATURES, N_FEATURES, StandaloneAgent, encode, mask_for,
)

PERMUTATIONS = tuple(itertools.permutations(range(3)))
OWN_BEGIN = 12
OWN_END = OWN_BEGIN + 3 * MON_FEATURES
PAIR_BEGIN = OWN_BEGIN + 6 * MON_FEATURES


def action_order(head, permutation):
    """Permuted output index -> physical output index."""
    if head == "act":
        return (0, 1, 2, *(3 + j for j in permutation))
    if head == "replace":
        return tuple(permutation)
    if head == "shield":
        return (0, 1)
    raise ValueError(f"unknown policy head {head!r}")


def permute_features(x, permutation):
    """Relabel own slots, including every own/foe pair interaction."""
    x = np.asarray(x, dtype=np.float32)
    if x.ndim != 2 or x.shape[1] != N_FEATURES or tuple(sorted(permutation)) != (0, 1, 2):
        raise ValueError("expected a feature batch and a three-slot permutation")
    n = len(x)
    out = x.copy()
    out[:, OWN_BEGIN:OWN_END] = x[:, OWN_BEGIN:OWN_END].reshape(n, 3, MON_FEATURES)[:, permutation, :].reshape(n, -1)
    out[:, PAIR_BEGIN:] = x[:, PAIR_BEGIN:].reshape(n, 3, 3, PAIR_FEATURES)[:, permutation, :, :].reshape(n, -1)
    return out


def probabilities(model, x, head, mask):
    """Mean masked probability in physical action coordinates, for one state."""
    x, mask = np.asarray(x, np.float32), np.asarray(mask, bool)
    if x.shape != (N_FEATURES,) or mask.shape != (HEADS[head],) or not mask.any():
        raise ValueError("invalid public features or action mask")
    orders = [action_order(head, p) for p in PERMUTATIONS]
    xs = np.stack([permute_features(x[None], p)[0] for p in PERMUTATIONS])
    masks = np.stack([mask[list(order)] for order in orders])
    p = model.forward(xs, head, masks)[0]
    physical = np.empty_like(p)
    for row, order in enumerate(orders):
        physical[row, list(order)] = p[row]
    mean = np.where(mask, physical.mean(axis=0, dtype=np.float64), 0.)
    if not np.isfinite(mean).all() or (mean < 0).any() or mean.sum() <= 0:
        raise FloatingPointError("invalid ensemble probabilities")
    return mean / mean.sum()


class SlotEnsembleAgent(StandaloneAgent):
    def __init__(self, model, *, seed=0, greedy=True, log=None):
        if log is not None:
            raise ValueError("slot ensemble is inference-only; ordinary PPO cannot train its mixture")
        super().__init__(model, seed=seed, greedy=greedy)
        self.ensemble_decisions = 0

    def choose(self, view, head, energy=None):
        mask = mask_for(view, head)
        if mask.sum() == 1:
            return int(np.flatnonzero(mask)[0])
        p = probabilities(self.model, encode(view, energy), head, mask)
        self.ensemble_decisions += 1
        return int(p.argmax()) if self.greedy else int(self.rng.choice(len(p), p=p))


def load_agent(checkpoint, *, seed=0, greedy=True):
    from .standalone_rl_v2 import ActorCritic
    return SlotEnsembleAgent(ActorCritic.load(checkpoint)[0], seed=seed, greedy=greedy)
