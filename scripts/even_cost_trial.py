#!/usr/bin/env python3
"""Two charged moves of the same cost into a shield: the one listed first (the old rule), or the better one? (the owner:
Empoleon threw resisted Hydro Cannon at Jellicent over Drill Peck, both 40 energy)

    python3 scripts/even_cost_trial.py [--field mixed|usual] [--pairings 2000] [--focus 2000] [--crowd 3000] [--pvpoke 1500]
                                       [--workers 3] [--seed 4501]

On the mixed field (pogo.teamshape.mixed_field; --field usual: the top 50 and the good-team list), the trained bot with `even_cost="best"` (Planner: the move that leaves
it better off, shielded or not as the opponent is likely to) against the trained bot with `even_cost="first"`: head
to head, each pair of teams both ways; head to head on teams that each hold a Pokémon with two same-cost moves
(Empoleon, Annihilape, Malamar, ...), where the rule can matter; and against the crowd and PvPoke's AI, the same
battles for both.
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
from pogo.battle import DRAW, Battle  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.learner import Learner, QNet  # noqa: E402
from pogo.pvpoke_ai import PvpokeAI  # noqa: E402
from pogo.teamlist import drawer  # noqa: E402
from pogo.teamshape import mixed_field  # noqa: E402

_s: dict = {}


def setup(field):
    low_priority()
    gd = GameData()
    if field == "mixed":
        pool, draw = mixed_field(gd)
    else:
        pool = gd.meta(50)
        draw = drawer(gd, pool)

    def focused(rng):
        """A team from the field holding a Pokémon with two charged moves of the same cost."""
        while True:
            team = draw(rng)
            if any(len(b.charged) == 2 and b.charged[0].energy == b.charged[1].energy for b in team):
                return team

    _s.update(pool=pool, draw=draw, focused=focused, net=QNet.load(str(ROOT / "runs" / "general-decide" / "q.npz")))


def bot(r, rule):
    return Learner(q=_s["net"], margin=0.02, seed=r.getrandbits(30), even_cost=rule)


def job(task):
    kind, seed, n = task
    r = random.Random(seed)
    if kind in ("h2h", "focus"):
        draw = _s["draw"] if kind == "h2h" else _s["focused"]
        return kind, [compare(lambda: bot(r, "best"), lambda: bot(r, "first"), _s["pool"], pairings=n, seed=seed, draw=draw).score]
    out = []
    for rule in ("best", "first"):
        rr = random.Random(seed + 1)
        if kind == "crowd":
            out.append(field_results(None, _s["pool"], lambda: bot(rr, rule), lambda rng: varied(rng, _s["pool"]), n, seed, draw=_s["draw"]))
        else:
            rng, pts = random.Random(seed), []
            for _ in range(n):
                a, b = _s["draw"](rng), _s["draw"](rng)
                w = Battle(a, b, bot(rr, rule), PvpokeAI(), seed=rng.getrandbits(32)).run()
                pts.append(1.0 if w == 0 else 0.5 if w == DRAW else 0.0)
            out.append(pts)
    return kind, out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--field", choices=("mixed", "usual"), default="mixed")
    parser.add_argument("--pairings", type=int, default=2000)
    parser.add_argument("--focus", type=int, default=2000)
    parser.add_argument("--crowd", type=int, default=3000)
    parser.add_argument("--pvpoke", type=int, default=1500)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--seed", type=int, default=4501)
    args = parser.parse_args()
    chunk = 50
    tasks = ([("focus", args.seed * 3000 + k, chunk) for k in range(args.focus // chunk)]
             + [("h2h", args.seed * 1000 + k, chunk) for k in range(args.pairings // chunk)]
             + [("crowd", args.seed * 7000 + k, chunk) for k in range(args.crowd // chunk)]
             + [("pvpoke", args.seed * 9000 + k, chunk) for k in range(args.pvpoke // chunk)])
    got = {"h2h": [], "focus": [], "crowd": [], "pvpoke": []}
    with multiprocessing.get_context("spawn").Pool(args.workers, initializer=setup, initargs=(args.field,)) as pool:
        for kind, out in pool.imap_unordered(job, tasks):
            got[kind].append(out)
    for kind, what in (("h2h", "the whole field"), ("focus", "teams holding a same-cost Pokémon")):
        m, e = mean_and_margin([x[0] for x in got[kind]])
        print(f"{args.field} field; same-cost moves by the better one against the first listed, head to head on {what} "
              f"({getattr(args, 'pairings' if kind == 'h2h' else 'focus')} pairings both ways): {100 * m:.1f}% ± {100 * e:.1f}")
    for kind in ("crowd", "pvpoke"):
        a = [x for o in got[kind] for x in o[0]]
        b = [x for o in got[kind] for x in o[1]]
        d, de = mean_and_margin([x - y for x, y in zip(a, b)])
        print(f"against the {'crowd' if kind == 'crowd' else 'PvPoke AI'} ({len(a)} battles, the same for both): better one "
              f"{100 * sum(a) / len(a):.1f}%, first listed {100 * sum(b) / len(b):.1f}%, difference {100 * d:+.1f} ± {100 * de:.1f} points")


if __name__ == "__main__":
    main()
