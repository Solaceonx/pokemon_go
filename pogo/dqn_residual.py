"""Training-only reference-anchored paired-return objective. No inference rules or hidden inputs."""
import numpy as np


def centered_residual_loss(logits, mask, reference, returns=None, step=.25):
    """Fit C(q_new - q_old) to step*C(returns), where C centers legal options per position.

    Equal sampled returns preserve the old relative scores instead of forcing tied new scores. Every
    position, including positions without an outcome difference, constrains drift from the reference.
    With returns=None this is a reference-logit anchor for ordinary demonstration states.
    """
    count = mask.sum(axis=1, keepdims=True)
    if len(logits) == 0 or np.any(count == 0) or step < 0:
        raise ValueError('Need nonempty legal options and a nonnegative residual step')
    difference = np.where(mask, logits - reference, 0.)
    error = difference - difference.sum(axis=1, keepdims=True, dtype=np.float64) / count
    if returns is not None:
        values = np.where(mask, returns, 0.)
        centered = values - values.sum(axis=1, keepdims=True, dtype=np.float64) / count
        error -= step * centered
    error = np.where(mask, error, 0.)
    weights = mask / (count * len(logits))
    loss = float(np.sum(np.where(abs(error) <= 1, .5 * error ** 2, abs(error) - .5) * weights))
    derivative = np.clip(error, -1, 1) * weights
    derivative -= np.where(mask, derivative.sum(axis=1, keepdims=True) / count, 0.)
    return loss, derivative
