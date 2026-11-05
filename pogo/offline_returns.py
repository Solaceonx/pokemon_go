"""Conservative per-action regression on recorded terminal returns.

Uses the CQL log-sum-exp penalty, with observed complete-game returns rather
than bootstrapped Bellman targets. This does not inherit CQL's theoretical
guarantees. Greedy inference uses the unchanged standalone neural player.
"""
import numpy as np

from .standalone_rl import HEADS


def initialize_q(model, scale=.1):
    if not 0 < scale <= 1:
        raise ValueError("positive head scale at most one required")
    for head in HEADS:
        model.params[head + ".out_w"] *= scale
        model.params[head + ".out_b"] *= scale
    model.m = {k: np.zeros_like(v) for k, v in model.params.items()}
    model.v = {k: np.zeros_like(v) for k, v in model.params.items()}
    model.steps, model.updates = {k: 0 for k in model.params}, 0


def objective(q, mask, actions, returns, alpha=.1):
    n = len(q)
    if not n or q.shape != mask.shape or len(actions) != n or len(returns) != n or not np.isfinite(alpha) or alpha < 0:
        raise ValueError("invalid conservative-return batch")
    row = np.arange(n)
    if not np.isfinite(q).all() or not np.isfinite(returns).all() or np.any(np.abs(returns) > 1):
        raise ValueError("finite Q values and bounded terminal returns required")
    if np.any(actions < 0) or np.any(actions >= q.shape[1]) or not mask[row, actions].all():
        raise ValueError("recorded actions must be legal")
    z = np.where(mask, q, -1e9)
    peak = z.max(axis=1, keepdims=True)
    exp = np.exp(z - peak)
    probs = exp / exp.sum(axis=1, keepdims=True)
    logsum = peak[:, 0] + np.log(exp.sum(axis=1))
    chosen = q[row, actions]
    error = chosen - returns
    mse = float(np.mean(error * error))
    conservative = float(np.mean(logsum - chosen))
    gradient = alpha * probs
    gradient[row, actions] += error - alpha
    gradient = np.where(mask, gradient / n, 0.)
    return .5 * mse + alpha * conservative, gradient, dict(mse=mse, conservative=conservative)


def update(model, head, x, mask, actions, returns, *, alpha=.1, rate=2e-4):
    q, cache = model._branch(x, head)
    loss, gradient, metrics = objective(q, mask, actions, returns, alpha)
    norm = model._adam(model._backward(x, head, cache, gradient), rate)
    model.updates += 1
    return dict(loss=loss, grad_norm=float(norm), **metrics)
