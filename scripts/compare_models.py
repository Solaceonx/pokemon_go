#!/usr/bin/env python3
"""Compare trained models on the same battles.

    python3 scripts/compare_models.py runs/general-decide/q.npz:0.02 runs/general-rules2/q.npz:0.05 [--battles 4000] [--workers 3]

Each model is given as FILE:MARGIN (how far ahead another option must be rated before the model overrules
the Planner). Every model, and the Planner alone, plays the same battles: teams drawn half from the good-team
list and half at random, against the usual crowd. Reported: each one's score, its gain over the Planner, and
its gain over the first model named, with margins.
"""
from __future__ import annotations

import argparse
import multiprocessing
import os
import sys
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_v] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pogo.agents import Planner, varied  # noqa: E402
from pogo.arena import field_results, mean_and_margin  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.learner import Learner, QNet  # noqa: E402
from pogo.teamlist import drawer  # noqa: E402


def play(job):
    spec, battles, seed = job
    os.nice(10)
    gd = GameData()
    pool = gd.meta(50)
    if spec is None:
        pilot = Planner
    else:
        path, _, margin = spec.rpartition(":")
        net = QNet.load(path)
        pilot = lambda: Learner(q=net, margin=float(margin))  # noqa: E731
    return spec, field_results(None, pool, pilot, lambda rng: varied(rng, pool), battles, seed, draw=drawer(gd, pool))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("models", nargs="+", metavar="FILE:MARGIN")
    parser.add_argument("--battles", type=int, default=4000)
    parser.add_argument("--seed", type=int, default=5)
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    jobs = [(spec, args.battles, args.seed) for spec in [None, *args.models]]
    with multiprocessing.get_context("spawn").Pool(min(args.workers, len(jobs))) as workers:
        got = dict(workers.map(play, jobs, chunksize=1))
    base, first = got[None], got[args.models[0]]
    mean, margin = mean_and_margin(base)
    print(f"same {args.battles} battles for all\n  {'Planner alone':44s} {100 * mean:.1f}% ± {100 * margin:.1f}")
    for spec in args.models:
        mean, margin = mean_and_margin(got[spec])
        gain, gm = mean_and_margin([a - b for a, b in zip(got[spec], base)])
        line = f"  {spec:44s} {100 * mean:.1f}% ± {100 * margin:.1f}   {100 * gain:+.1f} ± {100 * gm:.1f} over the Planner"
        if spec != args.models[0]:
            diff, dm = mean_and_margin([a - b for a, b in zip(got[spec], first)])
            line += f"   {100 * diff:+.1f} ± {100 * dm:.1f} against the first"
        print(line, flush=True)


if __name__ == "__main__":
    main()
