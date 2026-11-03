"""Training-only output calibration using complete-game, single-decision counterfactual returns."""
import numpy as np


def statistics(q, mask, returns, chosen, offsets):
    actions = np.where(mask, q + offsets, -np.inf).argmax(axis=1)
    rows = np.arange(len(actions))
    gain = float(np.mean(returns[rows, actions] - returns[rows, chosen]))
    changed = float(np.mean(actions != chosen))
    return {'proxy_return_gain': gain, 'changed_fraction': changed}


def fit(q, mask, returns, chosen, seed=38701, per_scale=1000, penalties=(0., .25)):
    """Fit six identifiable bias differences; the policy's other parameters stay fixed.

    The proxy changes ONE callback then follows the reference policy, as in the collected labels.
    It is not a whole-policy strength estimate. Real games on fresh validation must follow fitting.
    Shared candidates make the two regularization settings comparable on the training proxy.
    """
    if (q.ndim != 2 or q.shape[1] != 9 or q.shape != mask.shape or q.shape != returns.shape
            or not len(q) or not mask.any(axis=1).all() or not np.isfinite(q).all()
            or chosen.shape != (len(q),) or not mask[np.arange(len(q)), chosen].all()
            or per_scale < 1 or any(p < 0 for p in penalties)):
        raise ValueError('Need finite scores, legal reference actions, positive search count and penalties')
    rng = np.random.default_rng(seed)
    # A common offset within act/shield/replace cannot change a choice. Set one score per group to zero.
    coordinates = [1, 2, 3, 4, 6, 8]
    candidates = [np.zeros((1, 9), np.float32)]
    for scale in (.025, .05, .1, .2, .4):
        offsets = np.zeros((per_scale, 9), np.float32)
        offsets[:, coordinates] = rng.normal(0, scale, size=(per_scale, 6))
        candidates.append(offsets)
    candidates = np.concatenate(candidates)
    best = {penalty: (None, None, None) for penalty in penalties}
    rows = np.arange(len(q))[None, :]
    reference_returns = returns[np.arange(len(q)), chosen]
    for start in range(0, len(candidates), 128):
        offsets = candidates[start:start + 128]
        choices = np.where(mask[None], q[None] + offsets[:, None], -np.inf).argmax(axis=2)
        gains = np.mean(returns[rows, choices] - reference_returns[None], axis=1)
        changes = np.mean(choices != chosen[None], axis=1)
        norms = np.linalg.norm(offsets, axis=1)
        for index in range(len(offsets)):
            for penalty in penalties:
                key = (float(gains[index] - penalty * changes[index]),
                       -float(changes[index]), -float(norms[index]))
                if best[penalty][0] is None or key > best[penalty][0]:
                    best[penalty] = (key, offsets[index].copy(), start + index)
    return {str(penalty): {'offsets': value[1].tolist(), 'candidate': value[2],
            'objective': value[0][0], 'penalty': penalty, 'candidates': len(candidates),
            **statistics(q, mask, returns, chosen, value[1])} for penalty, value in best.items()}
