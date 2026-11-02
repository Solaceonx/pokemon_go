"""Shared matchup encoder for public-observation Double DQN; NumPy only.

Each own/observed-foe pair uses the same encoder. Pooling and shared bench heads make bench labels
equivariant by construction. Active-role flags retain the distinction between the current matchup
and the bench. No tactical rule, search player or hidden field is used.
"""
import copy
import json
from pathlib import Path

import numpy as np

from .dqn import N_FEATURES, N_MON

ARCHITECTURE = 'shared-matchup-v1'
GLOBAL_ACTIONS = [0, 1, 2, 5, 6]


class Network:
    def __init__(self, seed=0, hidden=64):
        if hidden < 4 or hidden % 2:
            raise ValueError('Use an even hidden width of at least four')
        self.hidden, self.embedding = hidden, hidden // 2
        h, e = hidden, self.embedding
        shapes = [(122, h), (h,), (h, e), (e,), (13 + 2 * e, h), (h,), (h, 5), (5,),
                  (13 + 3 * e, h), (h,), (h, 2), (2,)]
        rng = np.random.default_rng(seed)
        self.p = [(rng.normal(0, np.sqrt(2 / s[0]), s) if len(s) == 2 else np.zeros(s)).astype(np.float32)
                  for s in shapes]
        self.p[6] *= .01
        self.p[10] *= .01
        self.m, self.v = [np.zeros_like(p) for p in self.p], [np.zeros_like(p) for p in self.p]
        self.steps = 0

    def forward(self, x):
        x = np.asarray(x, dtype=self.p[0].dtype)
        if x.ndim != 2 or x.shape[1] != N_FEATURES:
            raise ValueError('Expected a batch of 400 public features')
        b, e = len(x), self.embedding
        g, mons = x[:, :13], x[:, 13:13 + 6 * N_MON].reshape(b, 6, N_MON)
        pairs = x[:, 13 + 6 * N_MON:].reshape(b, 3, 3, 11)
        own = np.broadcast_to(mons[:, :3, None], (b, 3, 3, N_MON))
        foe = np.broadcast_to(mons[:, None, 3:], (b, 3, 3, N_MON))
        global_x = np.broadcast_to(g[:, None, None], (b, 3, 3, 13))
        role = np.array([1, 0, 0], dtype=x.dtype)
        own_role = np.broadcast_to(role[None, :, None, None], (b, 3, 3, 1))
        foe_role = np.broadcast_to(role[None, None, :, None], (b, 3, 3, 1))
        pair_x = np.concatenate([own, foe, pairs, global_x, own_role, foe_role], axis=-1).reshape(-1, 122)
        a = np.maximum(pair_x @ self.p[0] + self.p[1], 0)
        encoded = np.maximum(a @ self.p[2] + self.p[3], 0)
        present = mons[:, 3:, 0]
        weights = present / np.maximum(present.sum(axis=1, keepdims=True), 1)
        embeddings = (encoded.reshape(b, 3, 3, e) * weights[:, None, :, None]).sum(axis=2)
        context = np.concatenate([g, embeddings[:, 0], embeddings.mean(axis=1)], axis=1)
        global_h = np.maximum(context @ self.p[4] + self.p[5], 0)
        global_q = global_h @ self.p[6] + self.p[7]
        bench_x = np.concatenate([np.broadcast_to(context[:, None], (b, 2, context.shape[1])),
                                  embeddings[:, 1:]], axis=-1).reshape(b * 2, -1)
        bench_h = np.maximum(bench_x @ self.p[8] + self.p[9], 0)
        bench_q = (bench_h @ self.p[10] + self.p[11]).reshape(b, 2, 2)
        q = np.empty((b, 9), dtype=x.dtype)
        q[:, GLOBAL_ACTIONS] = global_q
        q[:, 3:5], q[:, 7:9] = bench_q[:, :, 0], bench_q[:, :, 1]
        cache = (pair_x, a, encoded, weights, context, global_h, bench_x, bench_h)
        return q, cache

    def predict(self, x):
        x = np.asarray(x)
        if x.ndim not in (1, 2) or x.shape[-1] != N_FEATURES:
            raise ValueError('Expected 400 public features, singly or as a batch')
        single = x.ndim == 1
        q, _ = self.forward(x.reshape(-1, N_FEATURES))
        return q[0] if single else q

    def backward(self, cache, dq):
        pair_x, a, encoded, weights, context, global_h, bench_x, bench_h = cache
        b, e, c = len(dq), self.embedding, context.shape[1]
        grads = [None] * 12
        dbq = np.stack([dq[:, 3:5], dq[:, 7:9]], axis=-1).reshape(b * 2, 2)
        grads[10], grads[11] = bench_h.T @ dbq, dbq.sum(axis=0)
        dbh = (dbq @ self.p[10].T) * (bench_h > 0)
        grads[8], grads[9] = bench_x.T @ dbh, dbh.sum(axis=0)
        dbx = (dbh @ self.p[8].T).reshape(b, 2, -1)
        dc = dbx[:, :, :c].sum(axis=1)
        de = np.zeros((b, 3, e), dtype=dq.dtype)
        de[:, 1:] = dbx[:, :, c:]
        dgq = dq[:, GLOBAL_ACTIONS]
        grads[6], grads[7] = global_h.T @ dgq, dgq.sum(axis=0)
        dgh = (dgq @ self.p[6].T) * (global_h > 0)
        grads[4], grads[5] = context.T @ dgh, dgh.sum(axis=0)
        dc += dgh @ self.p[4].T
        de[:, 0] += dc[:, 13:13 + e]
        de += dc[:, 13 + e:][:, None] / 3
        dz = (de[:, :, None] * weights[:, None, :, None]).reshape(b * 9, e) * (encoded > 0)
        grads[2], grads[3] = a.T @ dz, dz.sum(axis=0)
        da = (dz @ self.p[2].T) * (a > 0)
        grads[0], grads[1] = pair_x.T @ da, da.sum(axis=0)
        return grads

    def apply(self, grads, rate):
        norm = np.sqrt(sum(float((g * g).sum()) for g in grads))
        if not np.isfinite(norm):
            raise ValueError('Non-finite relational-network gradient')
        scale = min(1., 10 / max(norm, 1e-10))
        self.steps += 1
        for p, m, v, g in zip(self.p, self.m, self.v, grads):
            g = g * scale
            m *= .9
            m += .1 * g
            v *= .999
            v += .001 * g * g
            p -= rate * (m / (1 - .9 ** self.steps)) / (np.sqrt(v / (1 - .999 ** self.steps)) + 1e-8)

    def imitate(self, x, masks, actions, weights=None, rate=.0001):
        from .counterfactual import classification_loss
        q, cache = self.forward(x)
        loss, dq = classification_loss(q, masks, actions, weights)
        self.apply(self.backward(cache, dq), rate)
        return loss

    def update(self, x, actions, targets, masks=None, imitation=0., rate=.0003, weights=None):
        """The same TD/large-margin output objective as the original Double DQN, with a shared encoder."""
        q, cache = self.forward(x)
        rows = np.arange(len(x))
        error = q[rows, actions] - targets
        weights = np.ones(len(x), np.float32) if weights is None else weights
        dq = np.zeros_like(q)
        dq[rows, actions] = np.clip(error, -1, 1) * weights / len(x)
        loss = float(np.mean(np.where(abs(error) <= 1, .5 * error ** 2, abs(error) - .5) * weights))
        if imitation:
            margin = np.where(masks, .2, -1e6)
            margin[rows, actions] = 0
            rivals = np.argmax(q + margin, axis=1)
            active = q[rows, rivals] + margin[rows, rivals] > q[rows, actions]
            dq[rows, rivals] += imitation * active / len(x)
            dq[rows, actions] -= imitation * active / len(x)
        self.apply(self.backward(cache, dq), rate)
        return loss, abs(error)

    def save(self, path, metadata=None, target=None):
        arrays = {f'{name}{i}': a for name, values in (('p', self.p), ('m', self.m), ('v', self.v))
                  for i, a in enumerate(values)}
        arrays.update(architecture=np.array(ARCHITECTURE), steps=np.array(self.steps),
                      metadata=np.array(json.dumps(metadata or {})))
        if target is not None:
            arrays.update({f'target{i}': p for i, p in enumerate(target.p)})
        path = Path(path)
        temp = path.with_name(path.name + '.tmp')
        with temp.open('wb') as file:
            np.savez_compressed(file, **arrays)
        temp.replace(path)

    @classmethod
    def load(cls, path):
        with np.load(path, allow_pickle=False) as data:
            if 'architecture' not in data or str(data['architecture']) != ARCHITECTURE:
                raise ValueError('Checkpoint is not a shared matchup network')
            net = cls(hidden=data['p0'].shape[1])
            shapes = [p.shape for p in net.p]
            for name in ('p', 'm', 'v'):
                arrays = [data[f'{name}{i}'].copy() for i in range(12)]
                if [a.shape for a in arrays] != shapes:
                    raise ValueError('Relational checkpoint parameter schema differs')
                setattr(net, name, arrays)
            net.steps = int(data['steps'])
            metadata = json.loads(str(data['metadata']))
            target = copy.deepcopy(net)
            if 'target0' in data:
                target.p = [data[f'target{i}'].copy() for i in range(12)]
                if [p.shape for p in target.p] != shapes:
                    raise ValueError('Relational target schema differs')
        return net, metadata, target
