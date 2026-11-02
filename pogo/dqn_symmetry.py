"""Bench-slot permutations for data augmentation and invariant neural inference.

Active Pokémon remain first. Permuting our bench remaps swap/replacement actions; permuting the
opponent's revealed bench changes no action. No game strategy or hidden state is involved.
"""
from functools import lru_cache

import numpy as np

from .dqn import N_FEATURES, N_MON


@lru_cache(maxsize=4)
def feature_order(ours=False, foes=False):
    a = [0, 2, 1] if ours else [0, 1, 2]
    b = [0, 2, 1] if foes else [0, 1, 2]
    index = np.arange(N_FEATURES)
    start = 13 + 6 * N_MON
    mons = index[13:start].reshape(6, N_MON)
    pairs = index[start:].reshape(3, 3, 11)
    return np.concatenate([index[:13], mons[a].ravel(), mons[np.array(b) + 3].ravel(),
                           pairs[a][:, b].ravel()])


def action_order(ours=False):
    return np.array([0, 1, 2, 4, 3, 5, 6, 8, 7] if ours else range(9))


def permute(x, mask, actions, ours=False, foes=False):
    """Transform inputs and labels together. Every permutation here is its own inverse."""
    order = action_order(ours)
    return x[..., feature_order(ours, foes)], mask[..., order], order[actions]


def augment(x, mask, actions, rng):
    """Independent uniform bench permutations per example, with the same RNG saved by training."""
    out_x, out_mask, out_actions = x.copy(), mask.copy(), actions.copy()
    variants = rng.integers(0, 4, len(actions))
    for variant in range(1, 4):
        rows = variants == variant
        if rows.any():
            out_x[rows], out_mask[rows], out_actions[rows] = permute(
                x[rows], mask[rows], actions[rows], bool(variant & 1), bool(variant & 2))
    return out_x, out_mask, out_actions


class SymmetricPolicy:
    """Average all four transformed network predictions after mapping actions back."""
    def __init__(self, net):
        self.net = net

    def predict(self, x):
        x = np.asarray(x)
        single = x.ndim == 1
        batch = x.reshape(-1, N_FEATURES)
        variants = [(False, False), (True, False), (False, True), (True, True)]
        inputs = np.concatenate([batch[:, feature_order(a, b)] for a, b in variants])
        predictions = self.net.predict(inputs).reshape(4, len(batch), 9)
        aligned = [predictions[i][:, action_order(a)] for i, (a, _) in enumerate(variants)]
        result = np.mean(aligned, axis=0)
        return result[0] if single else result
