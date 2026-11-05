#!/usr/bin/env python3
"""Choose a capacity candidate only after a positive paired validation interval.

This allocates further training; it never claims final strength or opens a test.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

for _key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_key] = "1"
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pogo.rl_experiment import atomic_json, digest
from pogo.standalone_rl_v2 import ActorCritic
from scripts.monte_carlo_rl import sources


def paired_difference(control, candidate, *, seed=41003):
    if [r["index"] for r in control] != [r["index"] for r in candidate] or len(control) < 2:
        raise ValueError("paired validation cases differ")
    a, b = (np.array([r["score"] for r in group], dtype=float) for group in (control, candidate))
    if not all(np.isfinite(x).all() and ((x >= 0) & (x <= 1)).all() for x in (a, b)):
        raise ValueError("invalid pairing scores")
    d = b-a
    rng = np.random.default_rng(seed)
    draws = d[rng.integers(len(d), size=(10000, len(d)))].mean(axis=1)
    return {"paired_change": float(d.mean()), "ci95": np.quantile(draws, [.025, .975]).tolist(),
            "pairings": len(d), "bootstrap_seed": seed}


def load_selection(name):
    if Path(name).name != name or name in (".", ".."):
        raise ValueError("run must be one directory name")
    folder = ROOT / "runs/standalone-rl" / name
    config = json.loads((folder / "experiment.json").read_text(encoding="utf-8"))
    if config["sources"] != sources():
        raise ValueError("registered policy source changed")
    model, meta = ActorCritic.load(folder / "best.npz")
    state = meta["state"]
    mode = "greedy" if state["best_greedy"] else "stochastic"
    log = folder / f"validation_{state['best_round']:05d}_{mode}.jsonl"
    records = [json.loads(s) for s in log.read_text(encoding="utf-8").splitlines()]
    header, rows = records[0], records[1:]
    fingerprint = hashlib.sha256(b"".join(model.params[k].tobytes() for k in sorted(model.params))).hexdigest()
    if fingerprint != header["weights_sha256"] or len(rows) != 128 or header["samples"] != 32:
        raise ValueError("selected policy is not bound to complete full-engine validation")
    value = float(np.mean([r["score"] for r in rows]))
    if not np.isclose(value, state["best_validation"]):
        raise ValueError("selected score differs from its pairing records")
    return {"run": name, "score": value, "round": state["best_round"], "mode": mode,
            "checkpoint_sha256": digest(folder / "best.npz"), "frozen_commit": config["commit"],
            "schedule_sha256": header["schedule_sha256"]}, rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--candidates", nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    baseline, rows = load_selection(args.baseline)
    selected, comparisons = baseline, []
    for name in args.candidates:
        candidate, other = load_selection(name)
        if any(candidate[k] != baseline[k] for k in ("schedule_sha256", "frozen_commit")):
            raise ValueError("capacity candidate has a different frozen opponent or validation schedule")
        difference = paired_difference(rows, other)
        eligible = difference["ci95"][0] > 0 and candidate["score"] > baseline["score"]
        comparisons.append({**candidate, **difference, "eligible_for_promotion": eligible})
        if eligible and candidate["score"] > selected["score"]:
            selected = candidate
    report = {"baseline": baseline, "selected": selected, "comparisons": comparisons,
              "promoted": selected["run"] != baseline["run"],
              "selector_sha256": hashlib.sha256(Path(__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
              "scope": "Exploratory validation allocation only; no final strength claim or final test data."}
    atomic_json(args.output, report)
    print(json.dumps(report))


if __name__ == "__main__":
    main()
