#!/usr/bin/env python3
"""Function-preserving capacity expansion of an independent standalone policy.

Duplicate tanh units, split outgoing weights, and add balanced perturbations
whose sum across identical units is zero. The initial policy/value functions
are preserved to floating-point precision; gradients can break the symmetry.
This is an initialization operation, not training or a strength measurement.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
from pathlib import Path

for _name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_name] = "1"

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pogo.rl_experiment import atomic_json
from pogo.standalone_rl import HEADS, N_FEATURES
from pogo.standalone_rl_v2 import ActorCritic


def widen(model, *, factor=4, seed=41002, jitter=.01):
    if factor < 2 or not isinstance(factor, int) or not np.isfinite(jitter) or jitter < 0:
        raise ValueError("need an integer expansion factor >= 2 and finite nonnegative jitter")
    old = model.params["act.w1"].shape[1]
    new, rng = old * factor, np.random.default_rng(seed)
    grown = ActorCritic(seed=seed, hidden=new)
    for head in (*HEADS, "critic"):
        p, q = model.params, grown.params
        q[head + ".w1"] = np.repeat(p[head + ".w1"], factor, axis=1)
        q[head + ".b1"] = np.repeat(p[head + ".b1"], factor)
        q[head + ".w2"] = np.repeat(np.repeat(p[head + ".w2"], factor, axis=0), factor, axis=1) / factor
        noise = rng.normal(0., jitter, (old, factor, new)).astype(np.float32)
        noise -= noise.mean(axis=1, keepdims=True)
        q[head + ".w2"] += noise.reshape(new, new)
        q[head + ".b2"] = np.repeat(p[head + ".b2"], factor)
        q[head + ".out_w"] = np.repeat(p[head + ".out_w"], factor, axis=0) / factor
        width = p[head + ".out_w"].shape[1]
        noise = rng.normal(0., jitter, (old, factor, width)).astype(np.float32)
        noise -= noise.mean(axis=1, keepdims=True)
        q[head + ".out_w"] += noise.reshape(new, width)
        q[head + ".out_b"] = p[head + ".out_b"].copy()
    # Optimizer state is deliberately fresh for the new parameterization.
    return grown


def transfer_check(old, new, seed=41002):
    rng = np.random.default_rng(seed)
    x = rng.normal(size=(64, N_FEATURES)).astype(np.float32)
    errors = {}
    for head, width in HEADS.items():
        mask = rng.random((len(x), width)) > .3
        mask[:, 0] = True
        a, va, _ = old.forward(x, head, mask)
        b, vb, _ = new.forward(x, head, mask)
        errors[head] = {"max_probability_error": float(np.abs(a-b).max()),
                        "max_value_error": float(np.abs(va-vb).max()),
                        "changed_greedy_actions": int(np.count_nonzero(a.argmax(axis=1) != b.argmax(axis=1)))}
        if not np.allclose(a, b, atol=2e-6, rtol=2e-6) or not np.allclose(va, vb, atol=2e-6, rtol=2e-6):
            raise ValueError("capacity expansion did not preserve the policy/value functions")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--factor", type=int, default=4)
    parser.add_argument("--seed", type=int, default=41002)
    parser.add_argument("--jitter", type=float, default=.01)
    args = parser.parse_args()
    parent = args.output.with_suffix(".parent.npz")
    report_path = args.output.with_suffix(".transfer.json")
    if any(p.exists() for p in (args.output, parent, report_path)):
        parser.error("use new output paths; existing checkpoints will not be overwritten")
    # Snapshot a potentially live best checkpoint once, binding bytes and hash.
    raw = args.start.read_bytes()
    original, metadata = ActorCritic.load(io.BytesIO(raw))
    grown = widen(original, factor=args.factor, seed=args.seed, jitter=args.jitter)
    errors = transfer_check(original, grown, args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    parent.write_bytes(raw)
    record = {"source_checkpoint": str(args.start), "parent_snapshot": str(parent),
              "parent_sha256": hashlib.sha256(raw).hexdigest(), "factor": args.factor,
              "seed": args.seed, "jitter": args.jitter,
              "old_hidden": original.params["act.w1"].shape[1],
              "new_hidden": grown.params["act.w1"].shape[1],
              "source_sha256": hashlib.sha256(Path(__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
              "optimizer_reset_for_architecture_change": True, "checks": errors,
              "scope": "Initialization transfer only; no strength result or checkpoint selection."}
    grown.save(args.output, {"initialization": metadata, "capacity_transfer": record,
                            "selection_required": "validation only"})
    atomic_json(report_path, record)
    print(json.dumps(record))


if __name__ == "__main__":
    main()
