#!/usr/bin/env python3
"""Task 28: compare existing human-style knobs on development recordings only.

Henry's fifteen clips select a setting; the owner's four recordings check its
agreement separately. Official footage is never loaded. This measures imitation,
not battle strength; engine_versus.py must measure any selected style in search.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import random
import sys
from pathlib import Path

for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[name] = "1"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from real_decisions import bot_choice, decisions, same_kind  # noqa: E402
from pogo.arena import low_priority  # noqa: E402
from pogo.battle import FAST  # noqa: E402
from pogo.engine import human_settings  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.learner import Learner, QNet  # noqa: E402
import numpy as np  # noqa: E402

# Only existing knobs for the owner's farming/holding rule; no new tactical rule.
SETTINGS = {"original": {}, "hold_cost=1.5": {"hold_cost": 1.5},
            "farm_cost=0.7": {"farm": True, "farm_cost": 0.7},
            "hold_cost=1.5,farm_cost=0.7": {"hold_cost": 1.5, "farm": True, "farm_cost": 0.7}}


def job(task):
    folder, repeats, seed = task
    low_priority()
    gd = GameData()
    pool = gd.meta(50)
    q = QNet.load(ROOT / "runs/general-decide/q.npz")
    ds = decisions(folder)
    out = {name: {kind: [] for kind in ("throw", "shield", "switch")} for name in SETTINGS}
    observed_holds = sum(d["kind"] == "throw" and d["human"] == FAST for d in ds)
    for n, d in enumerate(ds):
        for name, changes in SETTINGS.items():
            agreement, holds = 0, 0
            for repeat in range(repeats):
                def make_bot(s):
                    rng = random.Random(s)
                    margin = rng.choice((0.02, 0.05))
                    settings = human_settings(rng, pool)
                    settings.update(changes)
                    return Learner(q=q, margin=margin, **settings)

                rng = random.Random(seed * 1_000_003 + n * repeats + repeat)
                choice = bot_choice(gd, d, make_bot, pool, rng)
                agreement += same_kind(d, choice) == same_kind(d, d["human"])
                holds += choice == FAST
            out[name][d["kind"]].append([agreement / repeats, holds / repeats])
    return dict(game=folder.name, observed_holds=observed_holds, results=out)


def interval(games, name, kind, column=0, reference=None):
    # Resample games, preserving the within-game decision correlation and pairing.
    numerators, denominators = [], []
    for game in games:
        values = game["results"][name][kind]
        numerators.append(sum(v[column] for v in values) -
                          (sum(v[column] for v in game["results"][reference][kind]) if reference else 0))
        denominators.append(len(values))
    nums, dens = np.array(numerators), np.array(denominators)
    rng = np.random.default_rng(28028)
    indices = rng.integers(len(games), size=(4000, len(games)))
    samples = nums[indices].sum(axis=1) / np.maximum(dens[indices].sum(axis=1), 1)
    value = nums.sum() / max(dens.sum(), 1)
    low, high = np.percentile(samples, [2.5, 97.5])
    return {"percent": 100 * value, "margin95": 100 * max(value - low, high - value), "decisions": int(dens.sum())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--repeats", type=int, default=16)
    parser.add_argument("--seed", type=int, default=28028)
    parser.add_argument("--save", type=Path, default=ROOT / "runs/task28/human-style.json")
    args = parser.parse_args()
    saved = ROOT / "runs/real_decisions"
    folders = [ROOT / "games/twitch" / p.stem for p in sorted(saved.glob("tw-2894502346-pov-*.json"))]
    folders += [ROOT / "games" / p.stem for p in sorted(saved.glob("screenrecording-10-10-2026-*.json"))]
    with multiprocessing.get_context("spawn").Pool(args.workers) as workers:
        games = list(workers.imap(job, [(f, args.repeats, args.seed) for f in folders]))
    summary = {}
    for label, subset in (("Henry (selection)", [g for g in games if g["game"].startswith("tw-")]),
                          ("owner (check)", [g for g in games if g["game"].startswith("screenrecording")])):
        print(f"\n{label}: {len(subset)} games; 95% margins from whole-game bootstrap")
        summary[label] = {}
        for name in SETTINGS:
            summary[label][name] = {}
            for kind in ("throw", "shield", "switch"):
                rate = interval(subset, name, kind)
                diff = interval(subset, name, kind, reference="original")
                summary[label][name][kind] = dict(agreement=rate, difference=diff)
                print(f"{name:30s} {kind:6s}: agreement {rate['percent']:.1f}% ± {rate['margin95']:.1f}, "
                      f"change {diff['percent']:+.1f} ± {diff['margin95']:.1f} points ({rate['decisions']} decisions)")
            holds = interval(subset, name, "throw", column=1)
            summary[label][name]["holds"] = holds
            print(f"  predicted hold rate {holds['percent']:.1f}% ± {holds['margin95']:.1f}")
    args.save.parent.mkdir(parents=True, exist_ok=True)
    args.save.write_text(json.dumps(dict(settings=SETTINGS, seed=args.seed, repeats=args.repeats,
                                        summary=summary, games=games), indent=1) + "\n")
    print(f"\nresults: {args.save}")


if __name__ == "__main__":
    main()
