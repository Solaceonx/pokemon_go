"""A standalone, masked actor-critic. Runtime: NumPy and public battle state only.

No Planner, Learner, engine search, teacher advice, or private simulator state is
used here. Training may imitate a teacher, then improve from battle rewards.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np

SCHEMA = 1
HEADS = {"act": 6, "shield": 2, "replace": 3}
TYPES = tuple("normal fire water electric grass ice fighting poison ground flying psychic bug rock ghost dragon dark steel fairy".split())
MON_FEATURES = 41
PAIR_FEATURES = 12
N_FEATURES = 12 + 6 * MON_FEATURES + 9 * PAIR_FEATURES


def damage(user, move, target) -> int:
    """Public damage calculation; no dependency on a player or battle engine."""
    base = user.build.base_damage(move, target.build)
    if user.atk_stage or target.def_stage:
        def stage(s):
            return (4 + s) / 4 if s >= 0 else 4 / (4 - s)
        base *= stage(user.atk_stage) / stage(target.def_stage)
    return int(base) + 1


def _mon(mon, active: bool) -> list[float]:
    if mon is None:
        return [0.] * MON_FEATURES
    b, rule = mon.build, mon.build.rule or {}
    x = [1., float(mon.hp > 0), float(active), max(mon.hp, 0) / b.hp,
         mon.energy / 100, mon.atk_stage / 4, mon.def_stage / 4,
         b.atk / 200, b.defense / 300, b.hp / 300,
         b.fast.turns / 5, b.fast.energy_gain / 20,
         float(b.forms is not None and b.species_id != b.home),
         float(rule.get("effect") == "protect"), float(b.gulp is not None)]
    x += [float(t in b.types) for t in TYPES]
    for k in range(2):
        if k < len(b.charged):
            m = b.charged[k]
            x += [m.energy / 100, m.power / 150,
                  sum(m.self_buffs) * m.buff_chance / 4,
                  sum(m.foe_buffs) * m.buff_chance / 4]
        else:
            x += [0.] * 4
    return x


def _pair(a, b) -> list[float]:
    if a is None or b is None:
        return [0.] * PAIR_FEATURES
    x = []
    for user, target in ((a, b), (b, a)):
        fast = user.build.fast
        x += [min(damage(user, fast, target) / max(1, target.hp), 2.),
              min(10 * damage(user, fast, target) / fast.turns / max(1, target.hp), 3.)]
        for k in range(2):
            if k < len(user.build.charged):
                move = user.build.charged[k]
                x += [min(damage(user, move, target) / max(1, target.hp), 3.),
                      max(-2., min(2., (user.energy - move.energy) / 50))]
            else:
                x += [0., 0.]
    return x


def encode(view, foe_energy: int | None = None) -> np.ndarray:
    """Only public properties. Unseen team members occupy all-zero slots.

    Own slots retain their simulator action numbering; opponent slot zero is
    active and the remaining revealed Pokemon retain first-sighting order.
    """
    me, foe = view.me, view.foe
    ours = [me.team[j] if j < len(me.team) else None for j in range(3)]
    theirs = [foe] + [m for m in view.foe_shown if m is not foe][:2]
    theirs += [None] * (3 - len(theirs))
    if foe_energy is not None:
        # Shield callbacks pass pre-spend energy; never expose the hidden move.
        theirs[0] = foe.copy()
        theirs[0].energy = foe_energy
    unseen = max(0, view.foe_left - sum(m.hp > 0 for m in view.foe_shown))
    x = [view.turn / 480, me.shields / 2, view.foe_shields / 2,
         me.switch_wait / 90, view.foe_switch_wait / 90,
         me.busy / 5, view.foe_busy / 5, me.left() / 3, view.foe_left / 3,
         unseen / 3, float(me.switch_wait == 0), float(view.foe_switch_wait == 0)]
    for j, mon in enumerate(ours):
        x += _mon(mon, j == me.active)
    for j, mon in enumerate(theirs):
        x += _mon(mon, j == 0)
    for a in ours:
        for b in theirs:
            x += _pair(a, b)
    return np.asarray(x, dtype=np.float32)


def mask_for(view, head: str) -> np.ndarray:
    mask = np.zeros(HEADS[head], dtype=bool)
    if head == "act":
        mask[view.legal()] = True
    elif head == "shield":
        mask[0], mask[1] = True, view.me.shields > 0
    else:
        mask[view.me.bench()] = True
    if not mask.any():
        raise ValueError(f"no legal {head} choices")
    return mask


class ActorCritic:
    """Two tanh layers, three masked policy heads, and a state-value head.

    Adam moments and update count are saved with weights for exact resumption.
    """
    def __init__(self, seed: int = 0, hidden: int = 128):
        rng = np.random.default_rng(seed)
        self.params = {
            "w1": (rng.normal(size=(N_FEATURES, hidden)) / np.sqrt(N_FEATURES)).astype(np.float32),
            "b1": np.zeros(hidden, np.float32),
            "w2": (rng.normal(size=(hidden, hidden)) / np.sqrt(hidden)).astype(np.float32),
            "b2": np.zeros(hidden, np.float32),
        }
        for head, count in {**HEADS, "value": 1}.items():
            self.params[head + ".w"] = rng.normal(0, .01, (hidden, count)).astype(np.float32)
            self.params[head + ".b"] = np.zeros(count, np.float32)
        self.m = {k: np.zeros_like(p) for k, p in self.params.items()}
        self.v = {k: np.zeros_like(p) for k, p in self.params.items()}
        self.updates = 0

    def forward(self, x, head: str, mask):
        h1 = np.tanh(np.asarray(x) @ self.params["w1"] + self.params["b1"])
        h2 = np.tanh(h1 @ self.params["w2"] + self.params["b2"])
        logits = np.where(mask, h2 @ self.params[head + ".w"] + self.params[head + ".b"], -1e9)
        logits -= logits.max(axis=-1, keepdims=True)
        p = np.exp(logits)
        p /= p.sum(axis=-1, keepdims=True)
        value = (h2 @ self.params["value.w"] + self.params["value.b"]).reshape(-1)
        return p, value, (h1, h2)

    def update(self, head, x, mask, actions, returns, *, advantages=None, old_logp=None,
               rate=3e-4, clip=.2, entropy=.01, imitation=False, teacher=None, anchor=.0):
        p, value, (h1, h2) = self.forward(x, head, mask)
        n, row = len(x), np.arange(len(x))
        logp = np.log(np.maximum(p, 1e-12))
        onehot = np.zeros_like(p)
        onehot[row, actions] = 1
        ent = -(p * logp).sum(axis=1)
        if imitation:
            dz = (p - onehot) / n
            policy_loss = float(-logp[row, actions].mean())
            kl = 0.
        else:
            ratio = np.exp(logp[row, actions] - old_logp)
            allowed = np.where(advantages >= 0, ratio <= 1 + clip, ratio >= 1 - clip)
            dz = (p - onehot) * (advantages * ratio * allowed)[:, None] / n
            dz += entropy * p * (logp + ent[:, None]) / n
            if teacher is not None and anchor:
                dz += anchor * (p - teacher) / n
            policy_loss = float(-np.minimum(ratio * advantages, np.clip(ratio, 1 - clip, 1 + clip) * advantages).mean())
            kl = float((np.exp(old_logp - logp[row, actions]) - 1 - (old_logp - logp[row, actions])).mean())
        dz = np.where(mask, dz, 0.)
        dv = (value - returns)[:, None] / n  # derivative of .5 * MSE
        grads = {k: np.zeros_like(v) for k, v in self.params.items()}
        grads[head + ".w"], grads[head + ".b"] = h2.T @ dz, dz.sum(axis=0)
        grads["value.w"], grads["value.b"] = h2.T @ dv, dv.sum(axis=0)
        dh2 = (dz @ self.params[head + ".w"].T + dv @ self.params["value.w"].T) * (1 - h2 * h2)
        grads["w2"], grads["b2"] = h1.T @ dh2, dh2.sum(axis=0)
        dh1 = (dh2 @ self.params["w2"].T) * (1 - h1 * h1)
        grads["w1"], grads["b1"] = np.asarray(x).T @ dh1, dh1.sum(axis=0)
        norm = np.sqrt(sum(float((g * g).sum()) for g in grads.values()))
        scale = min(1., .5 / max(norm, 1e-12))
        self.updates += 1
        for k, g in grads.items():
            g = g * scale
            self.m[k] = .9 * self.m[k] + .1 * g
            self.v[k] = .999 * self.v[k] + .001 * g * g
            self.params[k] -= rate * (self.m[k] / (1 - .9 ** self.updates)) / (np.sqrt(self.v[k] / (1 - .999 ** self.updates)) + 1e-8)
        return {"policy_loss": policy_loss, "value_mse": float(((value - returns) ** 2).mean()),
                "entropy": float(ent.mean()), "kl": kl, "grad_norm": float(norm)}

    def copy(self):
        return copy.deepcopy(self)

    def save(self, path, metadata: dict | None = None):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        arrays = {f"p:{k}": v for k, v in self.params.items()}
        arrays.update({f"m:{k}": v for k, v in self.m.items()})
        arrays.update({f"v:{k}": v for k, v in self.v.items()})
        arrays["meta"] = np.array(json.dumps({**(metadata or {}), "schema": SCHEMA, "features": N_FEATURES,
                                               "updates": self.updates}))
        with tmp.open("wb") as f:
            np.savez_compressed(f, **arrays)
        tmp.replace(path)

    @classmethod
    def load(cls, path):
        with np.load(path, allow_pickle=False) as data:
            meta = json.loads(str(data["meta"]))
            if meta["schema"] == 2:
                from .standalone_rl_v2 import ActorCritic as IndependentActorCritic
                return IndependentActorCritic.load(path)
            if meta["schema"] != SCHEMA or meta["features"] != N_FEATURES:
                raise ValueError("incompatible standalone RL feature schema")
            model = cls(hidden=data["p:w1"].shape[1])
            for prefix, target in (("p", model.params), ("m", model.m), ("v", model.v)):
                for k in target:
                    target[k] = data[f"{prefix}:{k}"].copy()
            model.updates = meta["updates"]
        return model, meta


class StandaloneAgent:
    """All choices come from the learned policy; illegal choices have zero mass."""
    sees_move = False

    def __init__(self, model: ActorCritic, seed: int = 0, greedy: bool = False, log: list | None = None):
        self.model, self.rng, self.greedy, self.log = model, np.random.default_rng(seed), greedy, log

    def choose(self, view, head: str, energy=None):
        mask = mask_for(view, head)
        # Forced choices cannot teach a policy and need no network evaluation.
        if mask.sum() == 1:
            return int(np.flatnonzero(mask)[0])
        x = encode(view, energy)
        p, value, _ = self.model.forward(x[None], head, mask[None])
        a = int(p[0].argmax()) if self.greedy else int(self.rng.choice(len(p[0]), p=p[0].astype(float) / p[0].sum(dtype=float)))
        if self.log is not None:
            self.log.append((head, x, mask, a, float(np.log(max(p[0, a], 1e-12))), float(value[0])))
        return a

    def act(self, view):
        return self.choose(view, "act")

    def shield(self, view, energy):
        return bool(self.choose(view, "shield", energy))

    def replace(self, view):
        return self.choose(view, "replace")

    def clone(self):
        twin = copy.copy(self)
        twin.rng, twin.log = copy.deepcopy(self.rng), None
        return twin
