#!/usr/bin/env python3
"""The engine in real time (pogo.realtime): how its time is spent, and whether it plays as well as unhurried.

    python3 scripts/realtime_trial.py --timing 200                 where the time goes (minutes on three cores)
    python3 scripts/realtime_trial.py --timing 200 --heads throw+swap+mid_swap+replace+shield
    python3 scripts/realtime_trial.py --pairings 600 --crowd 1000  is it as good (hours: hand to another machine)

Both use the engine's confirmed settings (the trained bot inside the look-ahead, 4 imagined battles per option,
20 turns, edge 0.03). Pause lengths are options (milliseconds); the defaults are cautious guesses.

--timing: the real-time engine plays the usual crowd. For every searched decision: what came before it, the time
it had, the time it took, how often the deadline cut the search short or left no complete round (then it plays
the trained bot's pick), and the wait at the moment of decision (nil when the search was done ahead or during a
pause, the search time when the decision was unforeseen).

--pairings: head to head, the real-time engine against the unhurried engine (each pair of teams both ways round).
--crowd: the real-time engine, the unhurried engine and the trained bot against the crowd on the same battles.
Search time is measured as this process's CPU time, so a busy machine does not shorten the searches.
"""
from __future__ import annotations

import argparse
import multiprocessing
import os
import random
import sys
from collections import defaultdict
from pathlib import Path

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pogo.agents import varied  # noqa: E402
from pogo.arena import low_priority, mean_and_margin  # noqa: E402
from pogo.battle import DRAW, Battle  # noqa: E402
from pogo.engine import Engine  # noqa: E402
from pogo.evaluation import Evaluator  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.learner import Learner, QNet  # noqa: E402
from pogo.realtime import RealTime  # noqa: E402
from pogo.teamlist import drawer  # noqa: E402

PAUSES = ("turn_ms", "see_and_tap_ms", "unforeseen_ms", "after_charged_ms", "after_faint_ms", "replace_ms", "start_ms")


def points(winner: int, side: int) -> float:
    return 1.0 if winner == side else 0.5 if winner == DRAW else 0.0


def job(task) -> dict:
    mode, pauses, start, count, seed, heads = task
    low_priority()
    gd = GameData()
    pool = gd.meta(50)
    draw = drawer(gd, pool)
    net = QNet.load(str(ROOT / "runs" / "general-decide" / "q.npz"))
    ev = Evaluator.load(ROOT / "runs" / "eval" / "eval.npz")
    confirmed = dict(rollout="bot", samples=4, edge=0.03, q=net, margin=0.02)
    if heads is not None:
        confirmed["heads"] = heads

    def realtime(s):
        return RealTime(ev, pool, seed=s, **confirmed, **pauses)

    def engine(s):
        return Engine(ev, pool, seed=s, **confirmed)

    out = {"rows": [], "head": [], "rt": [], "engine": [], "bot": []}
    for n in range(start, start + count):
        rng = random.Random(seed * 1_000_003 + n)
        if mode == "timing":
            rt = realtime(rng.getrandbits(32))
            Battle(draw(rng), draw(rng), rt, varied(rng, pool), seed=rng.getrandbits(32)).run()
            out["rows"] += rt.rows
        elif mode == "pairings":
            a, b = draw(rng), draw(rng)
            dice = rng.getrandbits(32)
            pair = []
            for ours, theirs in ((a, b), (b, a)):
                rt = realtime(rng.getrandbits(32))
                pair.append(points(Battle(ours, theirs, rt, engine(rng.getrandbits(32)), seed=dice).run(), 0))
                out["rows"] += rt.rows
            out["head"].append(sum(pair) / 2)
        else:
            mine, theirs = draw(rng), draw(rng)
            opponent_seed, dice = rng.getrandbits(32), rng.getrandbits(32)
            for name, pilot in (("rt", realtime(dice)), ("engine", engine(dice)), ("bot", Learner(q=net, margin=0.02, seed=dice))):
                won = Battle(mine, theirs, pilot, varied(random.Random(opponent_seed), pool), seed=dice).run()
                out[name].append(points(won, 0))
                if name == "rt":
                    out["rows"] += pilot.rows
    return out


def run(mode, battles, workers, seed, pauses, heads=None) -> dict:
    per = -(-battles // workers)
    tasks = [(mode, pauses, w * per, min(per, battles - w * per), seed, heads) for w in range(workers) if w * per < battles]
    with multiprocessing.get_context("spawn").Pool(len(tasks)) as pool:
        parts = pool.map(job, tasks)
    return {k: [x for p in parts for x in p[k]] for k in parts[0]}


def timing_table(rows) -> None:
    by = defaultdict(list)
    for row in rows:
        by[row[0]].append(row)
    spent = np.array([r[3] for r in rows])
    wait = np.array([r[4] for r in rows])
    print(f"{len(rows)} searched decisions; search time median {np.median(spent):.0f} ms, 99th percentile "
          f"{np.percentile(spent, 99):.0f}, worst {spent.max():.0f}")
    print(f"cut short by the deadline {100 * np.mean([r[5] for r in rows]):.1f}%, no complete round (trained bot's pick) "
          f"{100 * np.mean([r[6] for r in rows]):.1f}%")
    print(f"wait at the moment of decision: median {np.median(wait):.0f} ms, 99th percentile {np.percentile(wait, 99):.0f}, "
          f"worst {wait.max():.0f}; decisions with any wait {100 * np.mean(wait > 0):.1f}%\n")
    print(f"{'what came before the decision':30} | kind       | share | time had | median | 99th | worst | cut short | bot's pick")
    for cause, rs in sorted(by.items(), key=lambda kv: -len(kv[1])):
        s = np.array([r[3] for r in rs])
        print(f"{cause:30} | {rs[0][1]:10} | {100 * len(rs) / len(rows):4.0f}% | {rs[0][2]:6.0f}ms | {np.median(s):6.0f} | "
              f"{np.percentile(s, 99):4.0f} | {s.max():5.0f} | {100 * np.mean([r[5] for r in rs]):8.1f}% | {100 * np.mean([r[6] for r in rs]):9.1f}%")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--timing", type=int, default=0, help="battles against the crowd, for the timing table")
    parser.add_argument("--pairings", type=int, default=0, help="team pairings, each both ways, real-time against unhurried")
    parser.add_argument("--crowd", type=int, default=0, help="battles against the crowd for real-time, unhurried and the bot")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--seed", type=int, default=2301)
    parser.add_argument("--heads", help="searched decisions joined by '+', e.g. throw+swap+mid_swap+replace+shield")
    for name in PAUSES:
        parser.add_argument("--" + name.replace("_", "-"), type=float, default=None)
    args = parser.parse_args()
    heads = tuple(args.heads.split("+")) if args.heads is not None else None
    if heads is not None and (not heads or set(heads) - {"throw", "swap", "mid_swap", "replace", "shield"}):
        parser.error("--heads must contain search heads joined by '+'")
    pauses = {name: getattr(args, name) for name in PAUSES if getattr(args, name) is not None}
    print(f"real-time engine, pauses: {pauses or 'defaults (pogo/realtime.py)'}")
    if heads is not None:
        print(f"searched heads: {'+'.join(heads)}")
    if args.timing:
        print(f"\n--- timing: {args.timing} battles against the crowd")
        timing_table(run("timing", args.timing, args.workers, args.seed, pauses, heads)["rows"])
    if args.pairings:
        got = run("pairings", args.pairings, args.workers, args.seed + 1, pauses, heads)
        m, h = mean_and_margin(got["head"])
        print(f"\n--- head to head, real-time engine against the unhurried engine, {len(got['head'])} pairings both ways: "
              f"{100 * m:.1f}% ± {100 * h:.1f}")
        timing_table(got["rows"])
    if args.crowd:
        got = run("crowd", args.crowd, args.workers, args.seed + 2, pauses, heads)
        print(f"\n--- against the crowd, {args.crowd} battles, the same for all three")
        for name, label in (("rt", "real-time engine"), ("engine", "unhurried engine"), ("bot", "trained bot")):
            m, h = mean_and_margin(got[name])
            print(f"  {label:18} {100 * m:.1f}% ± {100 * h:.1f}")
        for a, b in (("rt", "bot"), ("rt", "engine")):
            m, h = mean_and_margin([x - y for x, y in zip(got[a], got[b])])
            print(f"  {a} minus {b}: {100 * m:+.1f} ± {100 * h:.1f} points")


if __name__ == "__main__":
    main()
