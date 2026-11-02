#!/usr/bin/env python3
"""Can real decisions be predicted from real games, and would more games help? (docs/benchmarking.md; the VOD question)

    python3 scripts/people_model.py [--workers 3] [--splits 40]

The owner's decisions in the website games (scripts/exam_positions.py's shadow: each version of the bot says what it would
do at each decision) go into a small model, a conditional logit over the options of a decision: what each version chose, and
plain facts of the position (damage, health, energy, shields, matchups). Trained on some games, it is tested on games it has
not seen, with growing numbers of training games: if the score is still climbing with the last games added, more games
help; if flat, they do not, for this model and this player. Scored as the geometric mean of the chance it gave what the
player did, and how often its top choice was right, beside each version of the bot taken as the prediction.
"""
from __future__ import annotations

import argparse
import glob
import gzip
import json
import multiprocessing
import os
import random
import sys
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_v] = "1"
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
ROWS = ROOT / "runs" / "bench" / "people_rows.jsonl.gz"
VERSIONS = ("rulebook", "trained", "engine", "matching")


def collect(workers: int) -> list:
    import exam_positions as E
    games = sorted(p for p in glob.glob(str(ROOT / "games" / "played" / "*-web.json")) if not json.loads(Path(p).read_text()).get("player"))
    rows = []
    with multiprocessing.get_context("spawn").Pool(workers, initializer=E.setup) as pool:
        for name, same, got in pool.imap_unordered(E.shadow_job, games):
            rows += [r for r in got if r["side"] == 0]
    rows.sort(key=lambda r: (r["game"], r["turn"], r["kind"]))
    with gzip.open(ROWS, "wt") as f:
        for r in rows:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
    return rows


def features(row: dict, key: str) -> list:
    """Facts of one option of one decision, the same list for every kind of decision."""
    p = row["position"]
    you, foe = p["you"], p["foe"]
    me, them = you["active"], foe["active"]
    health = me["hp"] / me["hp_max"]
    foe_health = them["hp"] / them["hp_max"]
    ready = [c for c in them["charged"] if them["energy"] >= c["cost"]]
    worst = max((c["dmg"] for c in ready), default=0)
    votes = [float(row["picks"].get(v) == key) for v in VERSIONS]
    shields, foe_shields = you["shields"] / 2, foe["shields"] / 2
    is_fast, is_throw, is_switch, is_shield, is_no, is_replace = key == "fast", key[0] == "c", key[0] == "s", key == "yes", key == "no", key[0] == "r"
    x = [float(is_fast), float(is_throw), float(is_switch), float(is_shield), float(is_replace)] + votes
    # fast move: how much is at stake in waiting
    x += [is_fast * health, is_fast * float(bool(ready)), is_fast * me["energy"] / 100, is_fast * min(1.0, worst / max(me["hp"], 1))]
    # a throw: damage against what is left, a knock-out, the dearer move, into shields
    if is_throw:
        c = me["charged"][int(key[1:])]
        other = [m["cost"] for m in me["charged"]]
        x += [min(1.0, c["dmg"] / max(them["hp"], 1)), float(c["dmg"] >= them["hp"]), float(c["cost"] == max(other) and len(set(other)) > 1), foe_shields, c["cost"] / 100]
    else:
        x += [0.0] * 5
    # a switch or a send-in: the Pokémon coming in, against this one
    if is_switch or is_replace:
        slot = int(key[1:])
        names = [m["name"] for m in you["bench"]]
        options = [o for o in p["options"] if o["key"] == key]
        name = options[0]["label"].split(" to ")[-1].replace("Send in ", "") if options else ""
        b = you["bench"][names.index(name)] if name in names else None
        if b:
            deals = max(m["dmg"] for m in b["charged"]) / max(them["hp"], 1)
            takes = max(b["taken"]) / max(b["hp"], 1)
            x += [b["hp"] / b["hp_max"], min(1.0, deals), min(1.0, takes), is_switch * health, is_switch * shields]
        else:
            x += [0.0] * 5
    else:
        x += [0.0] * 5
    # a shield call
    x += [is_shield * health, is_shield * shields, is_shield * min(1.0, worst / max(me["hp"], 1)), is_shield * foe_health, is_shield * float(worst >= me["hp"])]
    return x


def encode(rows: list) -> list:
    return [(np.array([features(r, o["key"]) for o in r["position"]["options"]]),
             next((i for i, o in enumerate(r["position"]["options"]) if o["key"] == r["played"]), None)) for r in rows]


def fit(data: list, l2: float = 1.0, steps: int = 200) -> np.ndarray:
    """L2-regularised conditional logit, by Newton's method."""
    w = np.zeros(data[0][0].shape[1])
    for _ in range(steps):
        grad, hess = l2 * w, l2 * np.eye(len(w))
        for x, y in data:
            s = x @ w
            p = np.exp(s - s.max())
            p /= p.sum()
            mean = p @ x
            grad -= x[y] - mean
            d = x - mean
            hess += (d * p[:, None]).T @ d
        step = np.linalg.solve(hess, grad)
        w -= step
        if np.abs(step).max() < 1e-4:
            break
    return w


def score(data: list, w: np.ndarray) -> tuple:
    logs, right = [], []
    for x, y in data:
        s = x @ w
        p = np.exp(s - s.max())
        p /= p.sum()
        logs.append(np.log(max(p[y], 1e-6)))
        right.append(float(np.argmax(p) == y))
    return logs, right


def split_job(task):
    games, by_game, k, seed = task
    r = random.Random(seed)
    order = list(games)
    r.shuffle(order)
    test, train = order[:5], order[5:5 + k]
    w = fit([d for g in train for d in by_game[g]])
    logs, right = score([d for g in test for d in by_game[g]], w)
    return k, float(np.mean(logs)), float(np.mean(right))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--splits", type=int, default=40)
    parser.add_argument("--fresh", action="store_true", help="shadow the games again")
    args = parser.parse_args()
    if ROWS.exists() and not args.fresh:
        with gzip.open(ROWS, "rt") as f:
            rows = [json.loads(line) for line in f]
    else:
        ROWS.parent.mkdir(parents=True, exist_ok=True)
        rows = collect(args.workers)
    rows = [r for r in rows if any(o["key"] == r["played"] for o in r["position"]["options"])]
    by_kind = {}
    for r in rows:
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
    games = sorted({r["game"] for r in rows})
    print(f"{len(rows)} of the owner's decisions in {len(games)} games: {by_kind}")
    by_game = {g: encode([r for r in rows if r["game"] == g]) for g in games}

    print("\nEach version of the bot as the prediction, the chosen option given 90% and the rest sharing 10%:")
    print("  chance per decision / top choice right")
    for v in VERSIONS:
        logs = [np.log(0.9 if r["picks"].get(v) == r["played"] else 0.1 / max(1, len(r["position"]["options"]) - 1)) for r in rows]
        right = [r["picks"].get(v) == r["played"] for r in rows]
        print(f"  {v:10s} {100 * np.exp(np.mean(logs)):5.1f}% / {100 * np.mean(right):5.1f}%")
    logs = [-np.log(len(r["position"]["options"])) for r in rows]
    print(f"  {'all equal':10s} {100 * np.exp(np.mean(logs)):5.1f}%")

    print("\nThe model on 5 games it has not seen, by games trained on (mean of random splits):")
    print("  games trained on   chance per decision   top choice right")
    sizes = [k for k in (2, 5, 10, 15, 20, 25) if k + 5 <= len(games)]
    tasks = [(games, by_game, k, 1000 * k + s) for k in sizes for s in range(args.splits)]
    with multiprocessing.get_context("spawn").Pool(args.workers) as pool:
        out = pool.map(split_job, tasks, chunksize=1)
    for k in sizes:
        these = [o for o in out if o[0] == k]
        logs, right = [t[1] for t in these], [t[2] for t in these]
        err = 196 * float(np.std(right)) / len(right) ** 0.5
        print(f"  {k:16d}   {100 * np.exp(np.mean(logs)):18.1f}%   {100 * np.mean(right):13.1f}% ± {err:.1f}")


if __name__ == "__main__":
    main()
