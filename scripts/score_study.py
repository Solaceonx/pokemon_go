#!/usr/bin/env python3
"""Which way of scoring a finished battle tells the most about a position? (For the decisiveness score's weights.)

    python3 scripts/score_study.py [--positions 400] [--playouts 30] [--workers 4]

Positions are taken at random moments of ordinary battles (the trained bot against the crowd). Each is played on
--playouts times with fresh dice, which gives its true chance of winning. A single play-out is what training
learns from, so a good score is one whose value after one play-out predicts that chance well. For each way of
scoring (plain win / draw / loss, and pogo.arena.decisive with various weights for a bare win and for a shield)
this reports how much of the spread in true chances one play-out's score explains (R squared of a straight-line
fit), and the same for the mean of four play-outs.
"""
from __future__ import annotations

import argparse
import multiprocessing
import os
import random
import sys
from pathlib import Path

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pogo.agents import varied  # noqa: E402
from pogo.arena import low_priority  # noqa: E402
from pogo.battle import DRAW, SHIELDS, Battle  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.learner import Learner, QNet  # noqa: E402
from pogo.teamlist import drawer  # noqa: E402

MODEL = ROOT / "runs" / "general-decide" / "q.npz"


def ends(job) -> list:
    """For each position: per play-out (winner, health share left on the winner's team, the winner's shields, team size)."""
    seed, count, playouts = job
    low_priority()
    gd = GameData()
    pool = gd.meta(50)
    draw = drawer(gd, pool)
    net = QNet.load(str(MODEL))
    rng = random.Random(seed)
    out = []
    while len(out) < count:
        bot, rival = Learner(q=net, margin=0.02, seed=rng.getrandbits(32)), varied(rng, pool)
        battle = Battle(draw(rng), draw(rng), bot, rival, seed=rng.getrandbits(32))
        stop = rng.randint(10, 300)
        while battle.winner is None and battle.turn < stop:
            battle.step()
        if battle.winner is not None:
            continue
        rows = []
        for _ in range(playouts):
            me, them = bot.clone(), rival.clone()
            me.rng.seed(rng.getrandbits(32))
            them.rng.seed(rng.getrandbits(32))
            twin = battle.clone(me, them)
            twin.rng.seed(rng.getrandbits(32))
            winner = twin.run()
            side = twin.sides[winner] if winner != DRAW else None
            rows.append((winner, sum(max(m.hp, 0) / m.build.hp for m in side.team) if side else 0.0,
                         side.shields if side else 0, len(side.team) if side else 3))
        out.append(rows)
    return out


def score(rows, bare: float, shield: float) -> np.ndarray:
    values = []
    for winner, health, shields, size in rows:
        if winner == DRAW:
            values.append(0.5)
            continue
        edge = bare + (1 - bare) * (health + shield * shields) / (size + shield * SHIELDS)
        values.append(0.5 + 0.5 * edge if winner == 0 else 0.5 - 0.5 * edge)
    return np.array(values)


def explained(x: np.ndarray, y: np.ndarray) -> float:
    """R squared of the best straight line from x to y."""
    if np.std(x) == 0:
        return 0.0
    r = np.corrcoef(x, y)[0, 1]
    return float(r * r)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--positions", type=int, default=400)
    parser.add_argument("--playouts", type=int, default=30)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    per = -(-args.positions // args.workers)
    with multiprocessing.get_context("spawn").Pool(args.workers) as pool:
        parts = pool.map(ends, [(args.seed * 100 + w, per, args.playouts) for w in range(args.workers)])
    positions = [p for part in parts for p in part]
    import json
    (ROOT / "runs" / "score_study.json").write_text(json.dumps(positions) + "\n")  # every play-out, for other cuts
    rng = np.random.default_rng(args.seed)
    # Truth for a position: its win chance over all its play-outs but the four used as the sample, so the sample and
    # the truth are independent. The same four for every way of scoring.
    orders = [rng.permutation(len(rows)) for rows in positions]
    print(f"{len(positions)} positions, {args.playouts} play-outs each\n")
    for title, keep in (("all positions", lambda p: True), ("contested positions (true chance 20% to 80%)", lambda p: 0.2 <= p <= 0.8)):
        table(title, keep, positions, orders)


def table(title, keep, positions, orders) -> None:
    print(f"\n{title}")
    print(f"{'score':>36} | one play-out explains | mean of four explains")
    for name, bare, shield in [("win / draw / loss", 1.0, 0.35)] + [
            (f"decisive, bare win {b}, shield {s}", b, s) for b in (0.25, 0.5, 0.75) for s in (0.0, 0.35, 0.7)]:
        one_x, one_y, four_x, four_y = [], [], [], []
        for rows, order in zip(positions, orders):
            truth_rows = [rows[k] for k in order[4:]]
            truth = float(np.mean([1.0 if w == 0 else 0.5 if w == DRAW else 0.0 for w, *_ in truth_rows]))
            if not keep(truth):
                continue
            sample = score([rows[k] for k in order[:4]], bare, shield)
            one_x.append(sample[0]); one_y.append(truth)
            four_x.append(sample.mean()); four_y.append(truth)
        print(f"{name:>36} | {100 * explained(np.array(one_x), np.array(one_y)):20.1f}% | {100 * explained(np.array(four_x), np.array(four_y)):20.1f}%"
              f"   ({len(one_x)} positions)")


if __name__ == "__main__":
    main()
