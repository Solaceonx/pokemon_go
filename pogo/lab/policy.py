"""Learned policies over the trained bot's decisions: a probability for each option, not a value (lab-learn).

The trained bot (pogo.learner.QNet) rates each option of a decision by its chance of winning and plays the best one
when it beats the rulebook's advice by a margin. A PolicyNet instead gives a probability for each option, fitted by
cross-entropy to the choices of a player we want to copy:

- the website engine's own picks (task 39's self-play games of E_0): a model of the engine as an opponent, so a search
  can imagine the opponent it actually meets instead of the trained bot (pogo.lab.engines.ModelledEngine);
- people's choices (the owner's website games, replayed exactly): an anchor for piKL-style play, the bot's values plus
  lam x the log-probability that a person makes the choice, so where the values are close the bot keeps to moves
  people make (harder for people to read and exploit, Jacob et al. 2022, "Modeling strong and human-like gameplay
  with KL-regularized search").

Inputs are the trained bot's own 45 (pogo.learner.describe and the rulebook's advice); with `bot_input`, also the
trained bot's pick (three more, one-hot), so a model of a player who mostly agrees with the bot only has to learn where
it departs. A policy can also be played as it is: drawn from (a mixed strategy with fitted probabilities) or its most
likely option taken.

    net = PolicyNet.new(inputs=48, bot_input=True)
    net.fit("throw", x, mask, target)          # target: the option chosen in each row (or rows of probabilities)
    net.probabilities("throw", x, mask)
    net.save(path); PolicyNet.load(path)

    PolicyPlayer(pnet=net, q=q, sample=True)    # plays the policy, drawing each choice
    PolicyPlayer(anchor=net, lam=0.05, q=q)     # piKL: q's values + lam x log anchor; lam 0 plays as the trained bot
"""
from __future__ import annotations

import json
import math
import random
from pathlib import Path

import numpy as np

from pogo.learner import N_FEATURES, Learner, QNet, describe

ROOT = Path(__file__).resolve().parent.parent.parent
POLICY_HEADS = {"shield": 2, "throw": 3, "swap": 3, "replace": 2}  # options as the bot decides them (learner.HEADS)


def bot_values(q: QNet, head: str, x) -> list[float]:
    """The trained bot's value for each option of a decision, as Learner._decide reads them (holding is worth the
    best of its three hold lengths)."""
    v = q.values(head, np.asarray(x[:q.params[head][0].shape[0]], float))
    if head == "throw":
        return [max(v[0], v[3], v[4]), v[1], v[2]]
    return [float(a) for a in v]


def bot_pick(values: list[float], legal: list[int], advice: int, margin: float) -> int:
    """The trained bot's choice: its best legal option when that beats the rulebook's advice by the margin."""
    best = max(legal, key=lambda k: values[k])
    return best if values[best] - values[advice] > margin else advice


class PolicyNet:
    """Per decision kind: inputs -> one layer of rectifiers -> softmax over that kind's options."""

    def __init__(self, params: dict[str, list[np.ndarray]], bot_input: bool = False, meta: dict | None = None):
        self.params, self.bot_input, self.meta = params, bot_input, meta or {}

    @classmethod
    def new(cls, inputs: int = N_FEATURES, hidden: int = 64, seed: int = 0, bot_input: bool = False,
            heads: dict | None = None) -> PolicyNet:
        rng = np.random.default_rng(seed)
        params = {head: [rng.normal(0, np.sqrt(2 / inputs), (inputs, hidden)), np.zeros(hidden),
                         rng.normal(0, 0.01, (hidden, n)), np.zeros(n)]
                  for head, n in (heads or POLICY_HEADS).items()}
        return cls(params, bot_input)

    def inputs(self, head: str) -> int:
        return self.params[head][0].shape[0]

    def logits(self, head: str, x) -> tuple[np.ndarray, np.ndarray]:
        w1, b1, w2, b2 = self.params[head]
        h = np.maximum(np.asarray(x, float) @ w1 + b1, 0.0)
        return h @ w2 + b2, h

    def probabilities(self, head: str, x, mask) -> np.ndarray:
        """A probability for each option of each row (one row: a vector), zero for illegal ones."""
        z, _ = self.logits(head, x)
        mask = np.asarray(mask, bool)[..., :z.shape[-1]]
        z = np.where(mask, z, -np.inf)
        z = z - z.max(axis=-1, keepdims=True)
        p = np.exp(z)
        return p / p.sum(axis=-1, keepdims=True)

    def fit(self, head: str, x, mask, target, weight=None, epochs: int = 20, batch: int = 512, rate: float = 2e-3,
            decay: float = 1e-4, seed: int = 0) -> None:
        """Adam on the cross-entropy of the chosen option (target: an index per row, or rows of probabilities),
        rows weighted by `weight`, with an L2 penalty `decay` on the weights."""
        x = np.asarray(x, float)
        n = self.params[head][2].shape[1]
        mask = np.asarray(mask, bool)[:, :n]
        target = np.asarray(target)
        if target.ndim == 1:
            t = np.zeros((len(x), n))
            t[np.arange(len(x)), target.astype(int)] = 1.0
        else:
            t = np.asarray(target, float)[:, :n]
        w = np.ones(len(x)) if weight is None else np.asarray(weight, float)
        rng = np.random.default_rng(seed)
        params = self.params[head]
        m, v, step = [np.zeros_like(p) for p in params], [np.zeros_like(p) for p in params], 0
        for _ in range(epochs):
            order = rng.permutation(len(x))
            for start in range(0, len(x), batch):
                rows = order[start:start + batch]
                w1, b1, w2, b2 = params
                h = np.maximum(x[rows] @ w1 + b1, 0.0)
                z = np.where(mask[rows], h @ w2 + b2, -np.inf)
                z = z - z.max(axis=1, keepdims=True)
                p = np.exp(z)
                p /= p.sum(axis=1, keepdims=True)
                g = w[rows, None] * (p - t[rows]) / max(w[rows].sum(), 1e-9)
                g = np.where(mask[rows], g, 0.0)
                dh = (g @ w2.T) * (h > 0)
                grads = [x[rows].T @ dh + decay * w1, dh.sum(axis=0), h.T @ g + decay * w2, g.sum(axis=0)]
                step += 1
                for k, gr in enumerate(grads):
                    m[k] = 0.9 * m[k] + 0.1 * gr
                    v[k] = 0.999 * v[k] + 0.001 * gr * gr
                    params[k] = params[k] - rate * (m[k] / (1 - 0.9 ** step)) / (np.sqrt(v[k] / (1 - 0.999 ** step)) + 1e-8)

    def log_loss(self, head: str, x, mask, target) -> float:
        p = self.probabilities(head, x, mask)
        return float(-np.log(np.clip(p[np.arange(len(p)), np.asarray(target, int)], 1e-12, 1.0)).mean())

    def save(self, path, **meta) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(path, bot_input=np.array(self.bot_input), meta=np.array(json.dumps({**self.meta, **meta})),
                 **{f"{head}.{k}": p for head, ps in self.params.items() for k, p in enumerate(ps)})

    @classmethod
    def load(cls, path) -> PolicyNet:
        path = Path(path)
        d = np.load(path if path.is_absolute() else ROOT / path)
        heads = sorted({k.split(".")[0] for k in d.files if "." in k})
        meta = json.loads(str(d["meta"])) if "meta" in d.files else {}
        return cls({h: [d[f"{h}.{k}"] for k in range(4)] for h in heads}, bool(d["bot_input"]), meta)


_loaded: dict = {}


def cached(path) -> PolicyNet:
    """One copy per path, shared by every player that uses it (the weights never change in play)."""
    if str(path) not in _loaded:
        _loaded[str(path)] = PolicyNet.load(path)
    return _loaded[str(path)]


class PolicyPlayer(Learner):
    """The trained bot, with its shield, throw, swap and replacement choices from a learned policy.

    pnet: play the policy, drawing from its probabilities (sample=True; a mixed strategy) or taking the likeliest
    option. anchor (piKL): each option's value from q plus lam x the log of the anchor's probability for it, the best
    taken when it beats the rulebook's advice by the margin, as the trained bot does (lam 0 plays exactly as the
    trained bot); with temperature > 0, drawn from the softmax of those scores / temperature instead. Kinds of
    decision the network has no head for, and everything mechanical, stay the trained bot's. Draws use their own
    generator, so the rest of the player's dice are the trained bot's.
    """

    def __init__(self, pnet: PolicyNet | None = None, anchor: PolicyNet | None = None, lam: float = 0.0,
                 sample: bool = False, temperature: float = 0.0, **settings):
        super().__init__(**settings)
        self.pnet, self.anchor, self.lam, self.sample, self.temperature = pnet, anchor, lam, sample, temperature
        self._draw = random.Random(hash(self.rng.getstate()))
        self.off_bot = 0  # decisions made other than the trained bot would

    def clone(self) -> PolicyPlayer:
        twin = super().clone()
        twin._draw = random.Random()
        twin._draw.setstate(self._draw.getstate())
        return twin

    def _pick(self, p: np.ndarray, legal: list[int], sample: bool) -> int:
        if not sample:
            return max(legal, key=lambda k: p[k])
        r, total = self._draw.random() * sum(p[k] for k in legal), 0.0
        for k in legal:
            total += p[k]
            if r < total:
                return k
        return legal[-1]

    def _decide(self, head: str, view, mask: tuple, planner_choice, foe_energy: int | None = None) -> int:
        net = self.anchor if self.anchor is not None else self.pnet
        if head in self.forced or net is None or head not in net.params:
            return super()._decide(head, view, mask, planner_choice, foe_energy)
        advice = planner_choice()
        x = describe(self, view, foe_energy) + [float(advice == k) for k in range(3)]
        legal = [k for k in range(len(mask)) if mask[k]]
        values, bot = None, advice
        margin = self._head_margin(head, view)
        if self.q is not None and head in self.q.params:
            values = bot_values(self.q, head, x)
            bot = bot_pick(values, legal, advice, margin)
            if head == "shield" and self.shield_toward and advice:
                bot = advice
        p = net.probabilities(head, x + ([float(bot == k) for k in range(3)] if net.bot_input else []), mask)
        if self.anchor is None:
            choice = self._pick(p, legal, self.sample)
        elif values is None:
            choice = bot
        else:
            score = {k: values[k] + self.lam * math.log(max(float(p[k]), 1e-6)) for k in legal}
            if self.temperature > 0:
                top = max(score.values())
                weights = np.array([math.exp((score[k] - top) / self.temperature) if k in score else 0.0
                                    for k in range(len(mask))])
                choice = self._pick(weights / weights.sum(), legal, True)
            else:
                best = max(legal, key=lambda k: (score[k], k == advice))
                choice = best if score[best] - score[advice] > margin else advice
            if head == "shield" and self.shield_toward and advice:
                choice = advice
        if choice != bot:
            self.off_bot += 1
            self.departures[head, bot, choice] = self.departures.get((head, bot, choice), 0) + 1
        if self.log is not None:
            self.log.append((head, x, mask, choice))
        return choice
