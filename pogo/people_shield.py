"""Shield calls copied from good players: a small network fitted on the shield decisions in task 46's creator
records (the creators and their opponents, our last Pokémon left out: that stays the rulebook's), from what a
player sees when the prompt comes up. Their energy is not among the inputs: the footage does not show it.

    people = PeopleShield.load("runs/people-shield/shield.npz")
    people(view)              # True: shield
    people.probability(view)  # how often players shield there

Fitted by scripts/people_shield.py (numpy only). The owner, 2026-11-22: "why don't you learn from the behavior of
the youtubers?"
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from pogo.battle import damage

ROOT = Path(__file__).resolve().parent.parent
FEATURES = ("hp_share", "hit_big", "hit_cheap", "ko_big", "ko_cheap", "shields", "their_shields", "left",
            "their_left", "two_moves")


def describe(hp: int, hp_max: int, hits: list, shields: int, their_shields: int, left: int, their_left: int) -> list:
    """The inputs: our health share, the hardest and the cheapest of their charged moves as shares of the health we
    have (capped at 3), whether each knocks us out, shields and Pokémon left on both sides, and whether their two
    moves differ in cost. `hits` is (cost, damage) for each of their charged moves."""
    hp = max(1, hp)
    hits = sorted(hits)
    big, cheap = max(h for _, h in hits), hits[0][1]
    return [hp / hp_max, min(3.0, big / hp), min(3.0, cheap / hp), float(big >= hp), float(cheap >= hp),
            float(shields), float(their_shields), float(left), float(their_left), float(len({e for e, _ in hits}) > 1)]


def view_features(view) -> list:
    me, foe = view.me.mon, view.foe
    hits = [(m.energy, damage(foe, m, me)) for m in foe.build.charged]
    return describe(me.hp, me.build.hp, hits, view.me.shields, view.foe_shields, view.me.left(), view.foe_left)


class PeopleShield:
    def __init__(self, mean, scale, w1, b1, w2, b2):
        self.mean, self.scale, self.w1, self.b1, self.w2, self.b2 = mean, scale, w1, b1, w2, b2

    @classmethod
    def load(cls, path: str | Path) -> PeopleShield:
        path = Path(path)
        d = np.load(path if path.is_absolute() else ROOT / path)
        return cls(*(d[k] for k in ("mean", "scale", "w1", "b1", "w2", "b2")))

    def save(self, path: Path) -> None:
        np.savez(path, mean=self.mean, scale=self.scale, w1=self.w1, b1=self.b1, w2=self.w2, b2=self.b2,
                 features=np.array(FEATURES))

    def probabilities(self, x) -> np.ndarray:
        z = (np.asarray(x, float) - self.mean) / self.scale
        h = np.maximum(0.0, z @ self.w1 + self.b1)
        return 1.0 / (1.0 + np.exp(-(h @ self.w2 + self.b2)))

    def probability(self, view) -> float:
        return float(self.probabilities([view_features(view)])[0])

    def __call__(self, view) -> bool:
        return self.probability(view) > 0.5


_loaded: dict = {}


def cached(path: str | Path) -> PeopleShield:
    """One copy of a fitted network per path, shared by every player that uses it (the weights are never changed)."""
    if str(path) not in _loaded:
        _loaded[str(path)] = PeopleShield.load(path)
    return _loaded[str(path)]


def fit(x, y, hidden: int = 16, l2: float = 3.0, steps: int = 1000, lr: float = 0.01, seed: int = 0) -> PeopleShield:
    """One hidden layer of rectifiers, logistic output, full-batch Adam with an L2 penalty (as scikit-learn's
    MLPClassifier; tuned battle-wise: 67 to 69% copied across step counts and penalties)."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    mean, scale = x.mean(0), x.std(0)
    scale[scale == 0] = 1.0
    z = (x - mean) / scale
    rng = np.random.default_rng(seed)
    n, d = z.shape
    params = [rng.normal(0, np.sqrt(2 / d), (d, hidden)), np.zeros(hidden), rng.normal(0, np.sqrt(1 / hidden), hidden),
              np.zeros(())]
    m = [np.zeros_like(p) for p in params]
    v = [np.zeros_like(p) for p in params]
    for t in range(1, steps + 1):
        w1, b1, w2, b2 = params
        a = z @ w1 + b1
        h = np.maximum(0.0, a)
        p = 1.0 / (1.0 + np.exp(-(h @ w2 + b2)))
        g = (p - y) / n
        gw2 = h.T @ g + l2 * w2 / n
        gb2 = g.sum()
        gh = np.outer(g, w2) * (a > 0)
        gw1 = z.T @ gh + l2 * w1 / n
        gb1 = gh.sum(0)
        for i, gr in enumerate((gw1, gb1, gw2, gb2)):
            m[i] = 0.9 * m[i] + 0.1 * gr
            v[i] = 0.999 * v[i] + 0.001 * gr * gr
            params[i] = params[i] - lr * (m[i] / (1 - 0.9 ** t)) / (np.sqrt(v[i] / (1 - 0.999 ** t)) + 1e-8)
    return PeopleShield(mean, scale, *params)
