"""A small neural network that estimates the chance of winning from a position.

Plain numpy, so it trains in seconds and needs nothing installed. The inputs
are built by agents.position_features.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np


class ValueModel:
    def __init__(self, layers: list[tuple[np.ndarray, np.ndarray]]):
        self.layers = layers

    def predict(self, x: np.ndarray) -> np.ndarray:
        """Win chance for each row of x."""
        h = np.asarray(x, dtype=np.float64)
        for w, b in self.layers[:-1]:
            h = np.maximum(h @ w + b, 0.0)
        w, b = self.layers[-1]
        return 1.0 / (1.0 + np.exp(-(h @ w + b)[..., 0]))

    def __call__(self, features: list[float]) -> float:
        return float(self.predict(np.asarray(features)[None, :])[0])

    def save(self, path: Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        np.savez(path, **{f"{kind}{i}": arr for i, (w, b) in enumerate(self.layers) for kind, arr in (("w", w), ("b", b))})

    @classmethod
    def load(cls, path: Path) -> ValueModel:
        data = np.load(path)
        return cls([(data[f"w{i}"], data[f"b{i}"]) for i in range(len(data.files) // 2)])

    @classmethod
    def train(cls, x: np.ndarray, y: np.ndarray, hidden: tuple[int, ...] = (48, 24), epochs: int = 40,
              batch: int = 256, rate: float = 2e-3, decay: float = 1e-5, seed: int = 0) -> ValueModel:
        """Fit to outcomes y in [0, 1] (1 win, 0 loss, 0.5 draw) by gradient descent with Adam."""
        rng = np.random.default_rng(seed)
        sizes = [x.shape[1], *hidden, 1]
        params = []
        for n_in, n_out in zip(sizes, sizes[1:]):
            params += [rng.normal(0, np.sqrt(2.0 / n_in), (n_in, n_out)), np.zeros(n_out)]
        m = [np.zeros_like(p) for p in params]
        v = [np.zeros_like(p) for p in params]
        step = 0
        for _ in range(epochs):
            order = rng.permutation(len(x))
            for start in range(0, len(x), batch):
                rows = order[start:start + batch]
                acts = [x[rows]]
                for k in range(0, len(params) - 2, 2):
                    acts.append(np.maximum(acts[-1] @ params[k] + params[k + 1], 0.0))
                out = 1.0 / (1.0 + np.exp(-(acts[-1] @ params[-2] + params[-1])[:, 0]))
                grad = ((out - y[rows]) / len(rows))[:, None]  # gradient of the log loss at the output
                grads = [None] * len(params)
                for k in range(len(params) - 2, -1, -2):
                    grads[k] = acts[k // 2].T @ grad + decay * params[k]
                    grads[k + 1] = grad.sum(axis=0)
                    if k:
                        grad = (grad @ params[k].T) * (acts[k // 2] > 0)
                step += 1
                for k, g in enumerate(grads):
                    m[k] = 0.9 * m[k] + 0.1 * g
                    v[k] = 0.999 * v[k] + 0.001 * g * g
                    params[k] -= rate * (m[k] / (1 - 0.9 ** step)) / (np.sqrt(v[k] / (1 - 0.999 ** step)) + 1e-8)
        return cls([(params[k], params[k + 1]) for k in range(0, len(params), 2)])


def log_loss(p: np.ndarray, y: np.ndarray) -> float:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())
