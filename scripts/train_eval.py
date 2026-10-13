#!/usr/bin/env python3
"""Train the engine's evaluation of a position (pogo.evaluation) and test it against the plain count.

    python3 scripts/train_eval.py --battles 10000 --workers 4          writes runs/eval/eval.npz and report.json

Battles: the trained bot against the varied crowd and against itself, teams half from data/teams.json and half
random threes from the top 50. At random moments in each battle both players' views are recorded, each with how
the battle ended for that player (pogo.arena.decisive: any win above any loss, and by how much). A tenth of the
battles are kept back, whole, for testing.

Reported on the battles kept back: how often each evaluation points to the eventual winner, early in a battle
(its first third), in the middle and late; how far it is from the final decisiveness on average; and whether it
is calibrated (of positions rated 0.6 to 0.7, how many were won).
"""
from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import random
import sys
import time
from pathlib import Path

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pogo.agents import varied  # noqa: E402
from pogo.arena import decisive, low_priority  # noqa: E402
from pogo.battle import Battle  # noqa: E402
from pogo.evaluation import Evaluator, material  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.learner import Learner, QNet  # noqa: E402
from pogo.teamlist import drawer  # noqa: E402
from pogo.value import ValueModel, log_loss  # noqa: E402

MODEL = ROOT / "runs" / "general-decide" / "q.npz"


def positions(job) -> dict:
    """Play `count` battles; return the positions seen, with both sides' features and how each battle ended."""
    seed, count, sample = job
    low_priority()
    gd = GameData()
    pool = gd.meta(50)
    draw = drawer(gd, pool)
    net = QNet.load(str(MODEL))
    rng = random.Random(seed)
    evaluator = Evaluator()
    xs, labels, phases, counts, battles = [], [], [], [], []
    for n in range(count):
        bot = Learner(q=net, margin=0.02, seed=rng.getrandbits(32))
        rival = Learner(q=net, margin=0.02, seed=rng.getrandbits(32)) if rng.random() < 0.5 else varied(rng, pool)
        battle = Battle(draw(rng), draw(rng), bot, rival, seed=rng.getrandbits(32))
        seen = []
        while battle.winner is None:
            if rng.random() < sample:
                for side in (0, 1):
                    view = battle.views[side]
                    if view.me.mon.hp > 0 and view.foe.hp > 0:
                        seen.append((side, battle.turn, evaluator.features(view), material(view)))
            battle.step()
        for side, turn, x, plain in seen:
            xs.append(x)
            labels.append(decisive(battle, side))
            phases.append(turn / max(battle.turn, 1))
            counts.append(plain)
            battles.append(seed * 100_000 + n)
    return {"x": np.array(xs, dtype=np.float32), "y": np.array(labels), "phase": np.array(phases),
            "material": np.array(counts), "battle": np.array(battles)}


def report(name: str, predicted: np.ndarray, y: np.ndarray, phase: np.ndarray) -> dict:
    won = y > 0.5
    decided = y != 0.5
    out = {"mean error": float(np.abs(predicted - y).mean()), "log loss": log_loss(predicted, y)}
    for label, lo, hi in (("early", 0.0, 1 / 3), ("middle", 1 / 3, 2 / 3), ("late", 2 / 3, 1.01), ("all", 0.0, 1.01)):
        rows = decided & (phase >= lo) & (phase < hi)
        out[f"picks the winner, {label}"] = float(((predicted[rows] > 0.5) == won[rows]).mean())
    line = f"{name:>22}: picks the winner " + ", ".join(f"{k.split(', ')[1]} {100 * v:.1f}%" for k, v in out.items() if k.startswith("picks")) \
        + f" | off by {out['mean error']:.3f} on average"
    print(line, flush=True)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--battles", type=int, default=10000)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--sample", type=float, default=0.1, help="chance of recording the position on any one turn")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", default=str(ROOT / "runs" / "eval" / "eval.npz"))
    args = parser.parse_args()
    started = time.time()
    per = -(-args.battles // args.workers)
    jobs = [(args.seed * 1000 + w + 1, per, args.sample) for w in range(args.workers)]
    with multiprocessing.get_context("spawn").Pool(args.workers) as pool:
        parts = pool.map(positions, jobs)
    data = {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}
    print(f"{len(data['y'])} positions from {len(np.unique(data['battle']))} battles in {(time.time() - started) / 60:.1f} min", flush=True)

    ids = np.unique(data["battle"])
    held = set(np.random.default_rng(args.seed).choice(ids, len(ids) // 10, replace=False).tolist())
    test = np.array([b in held for b in data["battle"]])
    train = ~test
    model = ValueModel.train(data["x"][train].astype(np.float64), data["y"][train], hidden=(64, 32), epochs=30, seed=args.seed)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    model.save(args.out)

    y, phase = data["y"][test], data["phase"][test]
    print(f"\nheld-out battles: {len(held)}, positions: {int(test.sum())}")
    results = {
        "learned evaluation": report("learned evaluation", model.predict(data["x"][test].astype(np.float64)), y, phase),
        "material count": report("material count", data["material"][test], y, phase),
    }
    learned = model.predict(data["x"][test].astype(np.float64))
    calibration = []
    for lo in np.arange(0.0, 1.0, 0.1):
        rows = (learned >= lo) & (learned < lo + 0.1)
        if rows.sum() >= 50:
            calibration.append({"rated": f"{lo:.1f}-{lo + 0.1:.1f}", "positions": int(rows.sum()),
                                "won": float((y[rows] > 0.5).mean()), "mean outcome": float(y[rows].mean())})
    print("calibration (learned): " + "; ".join(f"rated {c['rated']}: won {100 * c['won']:.0f}% of {c['positions']}" for c in calibration))
    (Path(args.out).parent / "report.json").write_text(json.dumps(
        {"battles": args.battles, "positions": int(len(data["y"])), "held_out_battles": len(held), "results": results,
         "calibration": calibration, "minutes": round((time.time() - started) / 60, 1)}, indent=1) + "\n")
    print(f"model: {args.out}")


if __name__ == "__main__":
    main()
