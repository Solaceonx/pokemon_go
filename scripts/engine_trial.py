#!/usr/bin/env python3
"""The engine (pogo.engine: look ahead at each judgement call, judge with an evaluation) against the trained bot.

    python3 scripts/engine_trial.py [--eval runs/eval/eval.npz | --material] [--horizon 20] [--samples 6]
                                    [--edge 0.0] [--battles 2000] [--seed 51] [--workers 4]

Head to head against the trained bot (runs/general-decide/q.npz, margin 0.02) on random teams, every pair played
both ways round, and both against the usual crowd on the same battles. The engine plays as the trained bot except
where its look-ahead rates another option higher by more than --edge.
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

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pogo.agents import varied  # noqa: E402
from pogo.arena import low_priority, mean_and_margin  # noqa: E402
from pogo.battle import DRAW, Battle  # noqa: E402
from pogo.engine import Engine  # noqa: E402
from pogo.evaluation import Evaluator  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.learner import Learner, QNet  # noqa: E402
from pogo.teamlist import drawer  # noqa: E402

MODEL = ROOT / "runs" / "general-decide" / "q.npz"


def points(winner: int, side: int) -> float:
    return 1.0 if winner == side else 0.5 if winner == DRAW else 0.0


def job(task) -> dict:
    """One worker's share: pairings head to head (both ways round), and crowd battles for both pilots."""
    settings, start, count, seed = task
    low_priority()
    gd = GameData()
    pool = gd.meta(50)
    draw = drawer(gd, pool)
    net = QNet.load(str(MODEL))
    evaluator = Evaluator.load(settings["eval"]) if settings["eval"] else Evaluator()

    def engine(s):
        return Engine(evaluator, pool, horizon=settings["horizon"], samples=settings["samples"], edge=settings["edge"],
                      heads=settings["heads"], rollout=settings["rollout"], q=net, margin=0.02, seed=s)

    def bot(s):
        return Learner(q=net, margin=0.02, seed=s)

    head, crowd_engine, crowd_bot, looks, changed = [], [], [], 0, 0
    for n in range(start, start + count):
        rng = random.Random(seed * 1_000_003 + n)
        a, b = draw(rng), draw(rng)
        dice = rng.getrandbits(32)
        pair = []
        for ours, theirs in ((a, b), (b, a)):
            e = engine(rng.getrandbits(32))
            pair.append(points(Battle(ours, theirs, e, bot(rng.getrandbits(32)), seed=dice).run(), 0))
            looks, changed = looks + e.looks, changed + e.changed
        head.append(sum(pair) / 2)
        # Against the crowd: the same teams, opponent and dice for the engine and for the trained bot.
        crowd_rng = random.Random(seed * 7 + n)
        mine, theirs = draw(crowd_rng), draw(crowd_rng)
        opponent_seed, dice = crowd_rng.getrandbits(32), crowd_rng.getrandbits(32)
        e = engine(dice)
        crowd_engine.append(points(Battle(mine, theirs, e, varied(random.Random(opponent_seed), pool), seed=dice).run(), 0))
        crowd_bot.append(points(Battle(mine, theirs, bot(dice), varied(random.Random(opponent_seed), pool), seed=dice).run(), 0))
        looks, changed = looks + e.looks, changed + e.changed
    return {"head": head, "engine": crowd_engine, "bot": crowd_bot, "looks": looks, "changed": changed}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--eval", default=str(ROOT / "runs" / "eval" / "eval.npz"))
    parser.add_argument("--material", action="store_true", help="judge with the plain count of health and shields instead")
    parser.add_argument("--horizon", type=int, default=20, help="turns looked ahead")
    parser.add_argument("--samples", type=int, default=6, help="imagined battles per option")
    parser.add_argument("--edge", type=float, default=0.0)
    parser.add_argument("--heads", default="throw,swap,mid_swap,replace", help="which decisions to search")
    parser.add_argument("--rollout", choices=("quick", "bot"), default="quick", help="who plays inside the look-ahead")
    parser.add_argument("--battles", type=int, default=2000, help="team pairings (each played both ways) and crowd battles")
    parser.add_argument("--seed", type=int, default=51)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    settings = {"eval": None if args.material else args.eval, "horizon": args.horizon, "samples": args.samples, "edge": args.edge,
                "heads": tuple(args.heads.split(",")), "rollout": args.rollout}
    per = -(-args.battles // args.workers)
    tasks = [(settings, w * per, min(per, args.battles - w * per), args.seed) for w in range(args.workers)]
    with multiprocessing.get_context("spawn").Pool(args.workers) as pool:
        parts = pool.map(job, tasks)
    head = [x for p in parts for x in p["head"]]
    engine = [x for p in parts for x in p["engine"]]
    bot = [x for p in parts for x in p["bot"]]
    looks, changed = sum(p["looks"] for p in parts), sum(p["changed"] for p in parts)
    judge = "plain count" if args.material else Path(args.eval).name
    print(f"engine (judged by {judge}, {args.horizon} turns ahead, {args.samples} samples, edge {args.edge}, "
          f"searching {args.heads}, {args.rollout} play inside) against the trained bot")
    m, h = mean_and_margin(head)
    print(f"  head to head, {len(head)} pairings both ways: {100 * m:.1f}% ± {100 * h:.1f}")
    for name, values in (("engine", engine), ("trained bot", bot)):
        m, h = mean_and_margin(values)
        print(f"  {name} against the crowd: {100 * m:.1f}% ± {100 * h:.1f}")
    m, h = mean_and_margin([a - b for a, b in zip(engine, bot)])
    print(f"  difference against the crowd, same battles: {100 * m:+.1f} ± {100 * h:.1f} points")
    print(f"  decisions searched: {looks}; changed from the trained bot's pick: {changed} ({100 * changed / max(looks, 1):.0f}%)")


if __name__ == "__main__":
    main()
