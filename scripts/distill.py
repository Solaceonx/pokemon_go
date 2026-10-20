#!/usr/bin/env python3
"""Teach the trained bot the engine's judgement (distillation), so it plays more like the engine at its own speed.

    python3 scripts/distill.py collect [--battles 6000] [--workers 3] [--seed 301]
    python3 scripts/distill.py fit [--from runs/general-decide/q.npz] [--fresh] [--epochs 20] [--out runs/distill/q.npz]

collect: the engine (pogo.engine, the trained bot inside its look-ahead, 4 imagined battles per option, 20 turns)
plays the crowd training uses (Planner variations, half of them with the trained bot's decisions) on teams drawn
half from data/teams.json. At every throw, swap and replacement decision with a choice, it writes down what the
trained bot's networks see and the look-ahead's worth of every option. Saved to runs/distill/labels.npz.

fit: refits the throw, swap and replacement networks to those worths, starting from the trained bot's (or from
scratch with --fresh); the shield network is kept. A worth judged by the look-ahead is far less noisy than a single
play-out's result, which is what training otherwise learns from. Holding for 4 or 10 turns (the throw network's
last two options) is given the worth of holding, the only kind of hold the look-ahead tries.
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
from pogo.agents import Planner, varied_settings  # noqa: E402
from pogo.arena import low_priority  # noqa: E402
from pogo.battle import Battle  # noqa: E402
from pogo.engine import Engine  # noqa: E402
from pogo.evaluation import Evaluator  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.learner import Q_HEADS, Learner, QNet, describe  # noqa: E402
from pogo.teamlist import drawer  # noqa: E402

MODEL = ROOT / "runs" / "general-decide" / "q.npz"
FOLDER = ROOT / "runs" / "distill"
HEADS = ("throw", "swap", "replace")


class Labeller(Engine):
    """The engine, writing down the networks' inputs and the look-ahead's worth of each option."""

    def _decide(self, head, view, mask, planner_choice, foe_energy=None):
        if head in self.forced or head not in self.heads or self.labels is None:
            return super()._decide(head, view, mask, planner_choice, foe_energy)
        advice = []

        def once():  # the Planner's pick can be random: ask it once and use the same answer twice
            if not advice:
                advice.append(planner_choice())
            return advice[0]

        options = [k for k in range(len(mask)) if mask[k]]
        pick = Learner._decide(self, head, view, mask, once, foe_energy)
        if len(options) < 2:
            return pick
        x = describe(self, view, foe_energy) + [float(once() == k) for k in range(3)]
        seeds = [self.rng.getrandbits(32) for _ in range(self.samples)]
        worth = {k: sum(self._look(view, head, k, s) for s in seeds) / len(seeds) for k in options}
        y = [worth.get(k, float("nan")) for k in range(len(mask))]
        if head == "throw":
            y += [y[0], y[0]]  # hold 4 and hold 10: the look-ahead only tries holding for a turn
        self.labels.append((head, x, y))
        best = max(options, key=lambda k: (worth[k], k == pick))
        return best if worth[best] - worth[pick] > self.edge else pick


def collect_job(task) -> list:
    seed, count = task
    low_priority()
    gd = GameData()
    pool = gd.meta(50)
    draw = drawer(gd, pool, ROOT / "data" / "teams.json")
    net = QNet.load(str(MODEL))
    ev = Evaluator.load(ROOT / "runs" / "eval" / "eval.npz")
    rng = random.Random(seed)
    labels = []
    for _ in range(count):
        # a fresh evaluation cache per engine, the weights shared (task 27's fix)
        engine = Labeller(Evaluator(ev.model), pool, rollout="bot", samples=4, edge=0.03, q=net, margin=0.02, seed=rng.getrandbits(32))
        engine.labels = labels
        settings = varied_settings(rng, pool)
        if rng.random() < 0.5:
            rival = Learner(q=net, margin=rng.choice((0.02, 0.05, 0.1)), **settings)
        else:
            rival = Planner(**settings)
        Battle(draw(rng), draw(rng), engine, rival, seed=rng.getrandbits(32)).run()
    return labels


def collect(args) -> None:
    per = -(-args.battles // args.workers)
    with multiprocessing.get_context("spawn").Pool(args.workers) as pool:
        parts = pool.map(collect_job, [(args.seed * 1000 + w, per) for w in range(args.workers)])
    labels = [row for part in parts for row in part]
    FOLDER.mkdir(parents=True, exist_ok=True)
    out = {}
    for head in HEADS:
        rows = [(x, y) for h, x, y in labels if h == head]
        out[f"{head}_x"] = np.array([x for x, _ in rows], dtype=float).reshape(len(rows), -1)
        out[f"{head}_y"] = np.array([y for _, y in rows], dtype=float).reshape(len(rows), Q_HEADS[head])
        print(f"{head}: {len(rows)} decisions labelled")
    path = FOLDER / f"labels_{args.seed}.npz"
    np.savez_compressed(path, **out)
    print(f"saved {path}")


def fit(args) -> None:
    files = sorted(FOLDER.glob("labels_*.npz"))
    if not files:
        sys.exit("no labels yet: run collect first")
    data = [np.load(f) for f in files]
    q = QNet.load(args.start)
    fresh = QNet(seed=args.seed)
    rng = np.random.default_rng(args.seed)
    for head in HEADS:
        x = np.vstack([d[f"{head}_x"] for d in data])
        y = np.vstack([d[f"{head}_y"] for d in data])
        if args.fresh:
            q.params[head] = fresh.params[head]
        order = rng.permutation(len(x))
        held = order[:len(x) // 10]
        train = order[len(x) // 10:]
        before = error(q, head, x[held], y[held])
        q.fit(head, x[train], y[train], epochs=args.epochs, seed=args.seed)
        print(f"{head}: {len(train)} to fit, {len(held)} held out; held-out error in the look-ahead's worth "
              f"{before:.4f} before, {error(q, head, x[held], y[held]):.4f} after")
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    q.save(Path(args.out))
    print(f"saved {args.out}")


def error(q: QNet, head: str, x: np.ndarray, y: np.ndarray) -> float:
    """Root mean square difference between the network's values and the look-ahead's, over the options it tried."""
    if not len(x):
        return float("nan")
    v = q.values(head, x)
    known = ~np.isnan(y)
    return float(np.sqrt(np.mean((v[known] - y[known]) ** 2)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("step", choices=("collect", "fit"))
    parser.add_argument("--battles", type=int, default=6000)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--seed", type=int, default=301)
    parser.add_argument("--start", default=str(MODEL), help="fit: the networks to start from")
    parser.add_argument("--fresh", action="store_true", help="fit: start the throw, swap and replacement networks from scratch")
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--out", default=str(FOLDER / "q.npz"))
    args = parser.parse_args()
    collect(args) if args.step == "collect" else fit(args)


if __name__ == "__main__":
    main()
