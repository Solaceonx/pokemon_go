"""Independent policy trunks and critic, with per-parameter Adam clocks.

The public feature schema and agent interface are shared with standalone_rl.
No player, search or private simulator API is used by this module.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np

from .standalone_rl import HEADS, N_FEATURES

SCHEMA = 2


class ActorCritic:
    def __init__(self, seed=0, hidden=128):
        rng = np.random.default_rng(seed)
        self.params = {}
        for head, outputs in {**HEADS, "critic": 1}.items():
            self.params.update({
                head + ".w1": (rng.normal(size=(N_FEATURES, hidden)) / np.sqrt(N_FEATURES)).astype(np.float32),
                head + ".b1": np.zeros(hidden, np.float32),
                head + ".w2": (rng.normal(size=(hidden, hidden)) / np.sqrt(hidden)).astype(np.float32),
                head + ".b2": np.zeros(hidden, np.float32),
                head + ".out_w": rng.normal(0, .01, (hidden, outputs)).astype(np.float32),
                head + ".out_b": np.zeros(outputs, np.float32)})
        self.m = {k: np.zeros_like(p) for k, p in self.params.items()}
        self.v = {k: np.zeros_like(p) for k, p in self.params.items()}
        self.steps = {k: 0 for k in self.params}
        self.updates = 0

    def _branch(self, x, head):
        p = self.params
        h1 = np.tanh(x @ p[head + ".w1"] + p[head + ".b1"])
        h2 = np.tanh(h1 @ p[head + ".w2"] + p[head + ".b2"])
        return h2 @ p[head + ".out_w"] + p[head + ".out_b"], (h1, h2)

    def forward(self, x, head, mask):
        x = np.asarray(x)
        logits, actor = self._branch(x, head)
        value, critic = self._branch(x, "critic")
        z = np.where(mask, logits, -1e9)
        z -= z.max(axis=-1, keepdims=True)
        p = np.exp(z)
        p /= p.sum(axis=-1, keepdims=True)
        return p, value.reshape(-1), (actor, critic)

    def _backward(self, x, head, cache, dz):
        h1, h2 = cache
        p = self.params
        dh2 = (dz @ p[head + ".out_w"].T) * (1 - h2 * h2)
        dh1 = (dh2 @ p[head + ".w2"].T) * (1 - h1 * h1)
        return {head + ".out_w": h2.T @ dz, head + ".out_b": dz.sum(axis=0),
                head + ".w2": h1.T @ dh2, head + ".b2": dh2.sum(axis=0),
                head + ".w1": np.asarray(x).T @ dh1, head + ".b1": dh1.sum(axis=0)}

    def _adam(self, grads, rate):
        norm = np.sqrt(sum(float((g * g).sum()) for g in grads.values()))
        scale = min(1., .5 / max(norm, 1e-12))
        for k, g in grads.items():
            g = g * scale
            self.steps[k] += 1
            t = self.steps[k]
            self.m[k] = .9 * self.m[k] + .1 * g
            self.v[k] = .999 * self.v[k] + .001 * g * g
            self.params[k] -= rate * (self.m[k] / (1 - .9 ** t)) / (np.sqrt(self.v[k] / (1 - .999 ** t)) + 1e-8)
        return norm

    def update(self, head, x, mask, actions, returns, *, advantages=None, old_logp=None,
               rate=3e-4, clip=.2, entropy=.01, imitation=False, teacher=None, anchor=0.,
               demo_x=None, demo_mask=None, demo_actions=None, demo_weight=0.):
        p, value, (actor, critic) = self.forward(x, head, mask)
        n, row = len(x), np.arange(len(x))
        logp = np.log(np.maximum(p, 1e-12))
        onehot = np.zeros_like(p)
        onehot[row, actions] = 1
        ent = -(p * logp).sum(axis=1)
        if imitation:
            dz = (p - onehot) / n
            policy_loss, kl = float(-logp[row, actions].mean()), 0.
        else:
            logratio = logp[row, actions] - old_logp
            ratio = np.exp(np.clip(logratio, -20, 20))
            allowed = np.where(advantages >= 0, ratio <= 1 + clip, ratio >= 1 - clip)
            dz = (p - onehot) * (advantages * ratio * allowed)[:, None] / n
            dz += entropy * p * (logp + ent[:, None]) / n
            if teacher is not None and anchor:
                dz += anchor * (p - teacher) / n
            policy_loss = float(-np.minimum(ratio * advantages, np.clip(ratio, 1 - clip, 1 + clip) * advantages).mean())
            kl = float((ratio - 1 - logratio).mean())
        dz = np.where(mask, dz, 0.)
        # Separate gradient clipping prevents a newly adapting critic from
        # suppressing the policy gradient. Unused heads receive no Adam step.
        actor_grads = self._backward(x, head, actor, dz)
        demo_loss = 0.
        if demo_x is not None and demo_weight:
            logits, cache = self._branch(demo_x, head)
            logits = np.where(demo_mask, logits, -1e9)
            logits -= logits.max(axis=-1, keepdims=True)
            dp = np.exp(logits)
            dp /= dp.sum(axis=-1, keepdims=True)
            demo_loss = float(-np.log(np.maximum(dp[np.arange(len(dp)), demo_actions], 1e-12)).mean())
            dp[np.arange(len(dp)), demo_actions] -= 1
            dg = self._backward(demo_x, head, cache, demo_weight * dp / len(dp))
            actor_grads = {k: g + dg[k] for k, g in actor_grads.items()}
        actor_norm = self._adam(actor_grads, rate)
        critic_norm = self._adam(self._backward(x, "critic", critic, (value - returns)[:, None] / n), rate * 2)
        self.updates += 1
        return {"policy_loss": policy_loss, "value_mse": float(((value - returns) ** 2).mean()),
                "entropy": float(ent.mean()), "kl": kl, "grad_norm": float(actor_norm),
                "critic_grad_norm": float(critic_norm), "demo_loss": demo_loss}

    def copy(self):
        return copy.deepcopy(self)

    def save(self, path, metadata=None):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        arrays = {f"p:{k}": v for k, v in self.params.items()}
        arrays.update({f"m:{k}": v for k, v in self.m.items()})
        arrays.update({f"v:{k}": v for k, v in self.v.items()})
        arrays["meta"] = np.array(json.dumps({**(metadata or {}), "schema": SCHEMA, "features": N_FEATURES,
                                               "updates": self.updates, "adam_steps": self.steps}))
        with tmp.open("wb") as f:
            np.savez_compressed(f, **arrays)
        tmp.replace(path)

    @classmethod
    def load(cls, path):
        with np.load(path, allow_pickle=False) as data:
            meta = json.loads(str(data["meta"]))
            if meta["features"] != N_FEATURES:
                raise ValueError("incompatible standalone RL feature schema")
            if meta["schema"] == 1:
                # Exact policy/value transfer from the first experiment. New
                # optimization starts with zero moments, explicitly recorded.
                model = cls(hidden=data["p:w1"].shape[1])
                for head in (*HEADS, "critic"):
                    for part in ("w1", "b1", "w2", "b2"):
                        model.params[head + "." + part] = data["p:" + part].copy()
                    original = "value" if head == "critic" else head
                    model.params[head + ".out_w"] = data["p:" + original + ".w"].copy()
                    model.params[head + ".out_b"] = data["p:" + original + ".b"].copy()
                meta = {"schema": SCHEMA, "features": N_FEATURES, "migrated_from": meta,
                        "optimizer_reset_for_migration": True}
            elif meta["schema"] == SCHEMA:
                model = cls(hidden=data["p:act.w1"].shape[1])
                for prefix, target in (("p", model.params), ("m", model.m), ("v", model.v)):
                    for k in target:
                        target[k] = data[f"{prefix}:{k}"].copy()
                model.steps, model.updates = meta["adam_steps"], meta["updates"]
            else:
                raise ValueError("unsupported standalone RL checkpoint schema")
        return model, meta
