#!/usr/bin/env python3
"""The engine in real time (pogo.realtime): how its time is spent, and whether it plays as well as unhurried.

    python3 scripts/realtime_trial.py --timing 200                 where the time goes (minutes on three cores)
    python3 scripts/realtime_trial.py --pairings 600 --crowd 1000  is it as good (hours: hand to another machine)

Both default to the engine's confirmed settings (the trained bot inside the look-ahead, 4 imagined battles per
option, 20 turns, edge 0.03). --samples, --horizon and --edge measure other settings, and --settings takes any setting
in engine_versus.py's form (for example --settings "mix=1"). Pause lengths are options (milliseconds); the defaults
are cautious guesses. --save writes a compact timing summary with 95% intervals obtained by resampling
whole battles.

--timing: the real-time engine plays the usual crowd. For every searched decision: what came before it, the time
it had, the time it took, how often the deadline cut the search short or left no complete round (then it plays
the trained bot's pick), and the wait at the moment of decision (nil when the search was done ahead or during a
pause, the search time when the decision was unforeseen).

--pairings: head to head, the real-time engine against the unhurried engine (each pair of teams both ways round).
--crowd: the real-time engine, the unhurried engine and the trained bot against the crowd on the same battles.
Search time defaults to this process's CPU time, so a busy machine does not shorten the searches. --clock wall
uses elapsed time for both deadlines and measurements, as in live play.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_var] = "1"

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
from engine_versus import parse  # noqa: E402

PAUSES = ("turn_ms", "see_and_tap_ms", "unforeseen_ms", "after_charged_ms", "after_faint_ms", "replace_ms", "start_ms",
          "cap_ms")


def points(winner: int, side: int) -> float:
    return 1.0 if winner == side else 0.5 if winner == DRAW else 0.0


def job(task) -> dict:
    mode, pauses, settings, clock, start, count, seed = task
    low_priority()
    gd = GameData()
    pool = gd.meta(50)
    draw = drawer(gd, pool)
    net = QNet.load(str(ROOT / "runs" / "general-decide" / "q.npz"))
    confirmed = dict(settings)
    ev = Evaluator.load(confirmed.pop("eval", ROOT / "runs" / "eval" / "eval.npz"))
    confirmed.setdefault("margin", 0.02)
    confirmed.update(rollout="bot", q=net)

    def realtime(s):
        timer = time.perf_counter if clock == "wall" else time.process_time
        return RealTime(Evaluator(ev.model), pool, seed=s, clock=timer, **confirmed, **pauses)

    def engine(s):
        return Engine(Evaluator(ev.model), pool, seed=s, **confirmed)

    out = {"rows": [], "head": [], "rt": [], "engine": [], "bot": [], "timing_games": []}
    for n in range(start, start + count):
        rng = random.Random(seed * 1_000_003 + n)
        if mode == "timing":
            rt = realtime(rng.getrandbits(32))
            Battle(draw(rng), draw(rng), rt, varied(rng, pool), seed=rng.getrandbits(32)).run()
            out["rows"] += rt.rows
            out["timing_games"].append(rt.rows)
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


def run(mode, battles, workers, seed, pauses, settings, clock) -> dict:
    per = -(-battles // workers)
    tasks = [(mode, pauses, settings, clock, w * per, min(per, battles - w * per), seed)
             for w in range(workers) if w * per < battles]
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


def timing_intervals(games, seed):
    """95% bootstrap intervals, resampling whole battles rather than correlated decisions."""
    def measures(rows):
        a = np.asarray([[r[3], r[4], r[5], r[6]] for r in rows])
        return np.array([np.median(a[:, 0]), np.percentile(a[:, 0], 99),
                         100 * np.mean(a[:, 2]), 100 * np.mean(a[:, 3]),
                         100 * np.mean(a[:, 1] > 0)])

    estimate = measures([r for game in games for r in game])
    rng = np.random.default_rng(seed)
    samples = np.array([measures([r for i in rng.integers(len(games), size=len(games)) for r in games[i]])
                        for _ in range(1000)])
    low, high = np.percentile(samples, [2.5, 97.5], axis=0)
    names = ("median_ms", "p99_ms", "cut_percent", "fallback_percent", "wait_percent")
    result = {name: {"estimate": float(v), "low95": float(lo), "high95": float(hi)}
              for name, v, lo, hi in zip(names, estimate, low, high)}
    # A bootstrap of zero events is always zero; it cannot bound the unseen risk.
    # Use independent battles for the exact one-sided zero-event bound instead.
    for name, column in (("cut_percent", 5), ("fallback_percent", 6), ("wait_percent", 4)):
        if not any(r[column] > 0 for game in games for r in game):
            result[name]["battle_risk_upper95_percent"] = 100 * (1 - 0.05 ** (1 / len(games)))
    print("\n95% intervals (whole-battle bootstrap; observed worst is a sample maximum):")
    for name, v in result.items():
        print(f"  {name}: {v['estimate']:.2f} [{v['low95']:.2f}, {v['high95']:.2f}]")
        if "battle_risk_upper95_percent" in v:
            print(f"    no events observed; one-sided 95% upper bound on battles affected: "
                  f"{v['battle_risk_upper95_percent']:.2f}%")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--timing", type=int, default=0, help="battles against the crowd, for the timing table")
    parser.add_argument("--pairings", type=int, default=0, help="team pairings, each both ways, real-time against unhurried")
    parser.add_argument("--crowd", type=int, default=0, help="battles against the crowd for real-time, unhurried and the bot")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--seed", type=int, default=2301)
    parser.add_argument("--samples", type=int, default=None, help="imagined battles per option (default 4)")
    parser.add_argument("--horizon", type=int, default=None, help="turns ahead (default 20)")
    parser.add_argument("--edge", type=float, default=None, help="default 0.03")
    parser.add_argument("--settings", default="", help="engine settings, as in engine_versus.py (e.g. mix=1)")
    parser.add_argument("--clock", choices=("cpu", "wall"), default="cpu")
    parser.add_argument("--save", type=Path, help="write the timing summary as small JSON")
    for name in PAUSES:
        parser.add_argument("--" + name.replace("_", "-"), type=float, default=None)
    args = parser.parse_args()
    settings = parse(args.settings)
    if settings is None:
        parser.error("--settings must describe an engine, not 'bot'")
    for key in ("samples", "horizon", "edge"):
        if getattr(args, key) is not None:
            settings[key] = getattr(args, key)
    if settings["samples"] < 1 or settings["horizon"] < 1 or args.workers < 1:
        parser.error("samples, horizon and workers must be positive")
    pauses = {name: getattr(args, name) for name in PAUSES if getattr(args, name) is not None}
    print(f"real-time engine, settings: {settings}, clock: {args.clock}, "
          f"pauses: {pauses or 'defaults (pogo/realtime.py)'}")
    if args.timing:
        print(f"\n--- timing: {args.timing} battles against the crowd")
        got = run("timing", args.timing, args.workers, args.seed, pauses, settings, args.clock)
        timing_table(got["rows"])
        intervals = timing_intervals(got["timing_games"], args.seed)
        if args.save:
            args.save.parent.mkdir(parents=True, exist_ok=True)
            args.save.write_text(json.dumps(dict(settings=settings, seed=args.seed, battles=args.timing,
                searched_decisions=len(got["rows"]), intervals=intervals,
                worst_ms=max(r[3] for r in got["rows"]), worst_wait_ms=max(r[4] for r in got["rows"])), indent=2) + "\n")
    if args.pairings:
        got = run("pairings", args.pairings, args.workers, args.seed + 1, pauses, settings, args.clock)
        m, h = mean_and_margin(got["head"])
        print(f"\n--- head to head, real-time engine against the unhurried engine, {len(got['head'])} pairings both ways: "
              f"{100 * m:.1f}% ± {100 * h:.1f}")
        timing_table(got["rows"])
    if args.crowd:
        got = run("crowd", args.crowd, args.workers, args.seed + 2, pauses, settings, args.clock)
        print(f"\n--- against the crowd, {args.crowd} battles, the same for all three")
        for name, label in (("rt", "real-time engine"), ("engine", "unhurried engine"), ("bot", "trained bot")):
            m, h = mean_and_margin(got[name])
            print(f"  {label:18} {100 * m:.1f}% ± {100 * h:.1f}")
        for a, b in (("rt", "bot"), ("rt", "engine")):
            m, h = mean_and_margin([x - y for x, y in zip(got[a], got[b])])
            print(f"  {a} minus {b}: {100 * m:+.1f} ± {100 * h:.1f} points")


if __name__ == "__main__":
    main()
