#!/usr/bin/env python3
"""Fit the bot's networks to a run's saved examples, the way scripts/decide.py fits them after a round.

    python3 scripts/fit_examples.py runs/wide/examples.npz runs/wide/q_fit.npz [--narrow] [--hidden 48] [--seed 0] [--check]

--narrow drops the inputs that describe their Pokémon seen off the field (pogo.learner.known_foes) from
examples made with decide.py --wide, so a model with and one without them can be fitted on exactly the same
positions and results. --check first fits on nine tenths and prints the error on the other tenth for each
decision; the saved model is always fitted on everything.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pogo.learner import N_FEATURES, Q_HEADS, QNet  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("examples")
    parser.add_argument("out")
    parser.add_argument("--narrow", action="store_true", help="use only the original inputs")
    parser.add_argument("--hidden", type=int, default=48)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--check", action="store_true", help="also report held-out error per decision")
    args = parser.parse_args()
    saved = np.load(args.examples)
    data = {}
    for head in Q_HEADS:
        if f"{head}_x" in saved and len(saved[f"{head}_x"]):
            x = saved[f"{head}_x"]
            data[head] = (x[:, :N_FEATURES] if args.narrow else x, saved[f"{head}_y"])
    inputs = next(iter(data.values()))[0].shape[1]
    print(f"{inputs} inputs: " + ", ".join(f"{len(x)} {h}" for h, (x, _) in data.items()), flush=True)
    if args.check:
        rng = np.random.default_rng(args.seed)
        trial = QNet(seed=args.seed, hidden=args.hidden, inputs=inputs)
        for head, (x, y) in data.items():
            order = rng.permutation(len(x))
            held, rest = order[:len(x) // 10], order[len(x) // 10:]
            trial.fit(head, x[rest], y[rest], seed=args.seed)
            v, t = trial.values(head, x[held]), y[held]
            known = ~np.isnan(t)
            print(f"  {head}: held-out squared error {np.mean((v[known] - t[known]) ** 2):.5f} on {len(held)}", flush=True)
    q = QNet(seed=args.seed, hidden=args.hidden, inputs=inputs)
    q.params = {h: ps for h, ps in q.params.items() if h in data}
    for head, (x, y) in data.items():
        q.fit(head, x, y, seed=args.seed)
    q.save(Path(args.out))
    print(f"saved {args.out}")


if __name__ == "__main__":
    main()
