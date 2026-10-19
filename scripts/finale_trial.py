#!/usr/bin/env python3
"""Does solving the last-Pokémon fight as a game (pogo.finale) beat the bot's own endgame? (the owner)

    python3 scripts/finale_trial.py [--pairings 2000] [--crowd 3000] [--baiter 2000] [--workers 3] [--seed 4401]

On the mixed field (pogo.teamshape.mixed_field), the trained bot with `Finale` (its last-Pokémon fights solved)
against: the trained bot as it is, head to head (each pair of teams both ways); the crowd, on the same battles as
the bot as it is; and a baiter (the bot, but in every last-Pokémon fight it opens with the cheaper move at the dearer
move's energy, then the dearer), where both the solver and the bot as it is play the same pairings, so the two can
be compared. The bot as it is always shields on its last Pokémon, which the baiter is built to punish.
"""
from __future__ import annotations

import argparse
import multiprocessing
import os
import random
import sys
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_v] = "1"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pogo.agents import varied  # noqa: E402
from pogo.arena import compare, field_results, low_priority, mean_and_margin  # noqa: E402
from pogo.finale import Finale  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.learner import Learner, QNet  # noqa: E402
from pogo.teamshape import mixed_field  # noqa: E402

_s: dict = {}


def setup():
    low_priority()
    gd = GameData()
    pool, draw = mixed_field(gd)
    _s.update(pool=pool, draw=draw, net=QNet.load(str(ROOT / "runs" / "general-decide" / "q.npz")))


def bot(r):
    return Learner(q=_s["net"], margin=0.02, seed=r.getrandbits(30))


def solver(r):
    return Finale(bot(r), random.Random(r.getrandbits(30)))


def baiter(r):
    return Finale(bot(r), fixed=("BD", "??"))


def job(task):
    kind, seed, n = task
    r = random.Random(seed)
    if kind == "h2h":
        return kind, [compare(lambda: solver(r), lambda: bot(r), _s["pool"], pairings=n, seed=seed, draw=_s["draw"]).score]
    if kind == "crowd":
        out = []
        for make in (solver, bot):
            rr = random.Random(seed + 1)
            out.append(field_results(None, _s["pool"], lambda: make(rr), lambda rng: varied(rng, _s["pool"]), n, seed, draw=_s["draw"]))
        return kind, out
    out = []
    for make in (solver, bot):
        rr = random.Random(seed + 2)
        out.append(compare(lambda: make(rr), lambda: baiter(rr), _s["pool"], pairings=n, seed=seed, draw=_s["draw"]).score)
    return kind, out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pairings", type=int, default=2000)
    parser.add_argument("--crowd", type=int, default=3000)
    parser.add_argument("--baiter", type=int, default=2000)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--seed", type=int, default=4401)
    args = parser.parse_args()
    chunk = 50
    tasks = ([("h2h", args.seed * 1000 + k, chunk) for k in range(args.pairings // chunk)]
             + [("crowd", args.seed * 7000 + k, chunk) for k in range(args.crowd // chunk)]
             + [("baiter", args.seed * 9000 + k, chunk) for k in range(args.baiter // chunk)])
    got = {"h2h": [], "crowd": [], "baiter": []}
    with multiprocessing.get_context("spawn").Pool(args.workers, initializer=setup) as pool:
        for kind, out in pool.imap_unordered(job, tasks):
            got[kind].append(out)
    h = [x[0] for x in got["h2h"]]
    m, e = mean_and_margin(h)
    print(f"mixed field; solved last-Pokémon fights against the bot as it is, head to head ({args.pairings} pairings both ways): "
          f"{100 * m:.1f}% ± {100 * e:.1f} (margin over chunks of {chunk} pairings)")
    a = [x for o in got["crowd"] for x in o[0]]
    b = [x for o in got["crowd"] for x in o[1]]
    (ma, ea), (mb, eb) = mean_and_margin(a), mean_and_margin(b)
    d, de = mean_and_margin([x - y for x, y in zip(a, b)])
    print(f"against the crowd ({len(a)} battles, the same for both): solved {100 * ma:.1f}% ± {100 * ea:.1f}, as it is "
          f"{100 * mb:.1f}% ± {100 * eb:.1f}, difference {100 * d:+.1f} ± {100 * de:.1f} points")
    s = [o[0] for o in got["baiter"]]
    t = [o[1] for o in got["baiter"]]
    (ms, es), (mt, et) = mean_and_margin(s), mean_and_margin(t)
    d, de = mean_and_margin([x - y for x, y in zip(s, t)])
    print(f"against the baiter ({args.baiter} pairings both ways, the same for both): solved {100 * ms:.1f}% ± {100 * es:.1f}, "
          f"as it is {100 * mt:.1f}% ± {100 * et:.1f}, difference {100 * d:+.1f} ± {100 * de:.1f} points")


if __name__ == "__main__":
    main()
