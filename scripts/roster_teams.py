#!/usr/bin/env python3
"""Find the best teams the owner can field from their own Pokémon.

    python3 scripts/roster_teams.py [--pool 100] [--stages 150:500,600:50,3000:12] [--finals 6000] [--workers 3]

The owner's Pokémon come from data/owner_team.json and data/owner_roster.json, with their own IVs and moves.
Every legal line-up (a lead and two others) is a candidate. Opponents bring a random legal three from the top
--pool Pokémon: every such team is equally likely, so the score estimates the win rate over all of them
without playing each one. Opposing players are the usual crowd; ours is the best bot.

All candidates play the same battles. Each stage adds battles and keeps the best so far ("150:500" = 150
battles each, keep 500). The survivors of the last stage then play fresh battles, and only those are
reported: the best of thousands in the rounds that picked them is flattered by luck.
Results also go to data/roster_teams.json.
"""
from __future__ import annotations

import argparse
import itertools
import json
import multiprocessing
import os
import sys
import time
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_v] = "1"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pogo.agents import Planner, varied  # noqa: E402
from pogo.arena import field_results, mean_and_margin  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.roster import builds  # noqa: E402

MODEL = ROOT / "runs" / "general-decide" / "q.npz"
_state: dict = {}


def setup(pool_size: int) -> None:
    os.nice(10)
    gd = GameData()
    pool = gd.meta(pool_size)
    dex = {b.species_id: gd.species[b.species_id]["dex"] for b in pool}
    if MODEL.exists():
        from pogo.learner import Learner, QNet
        net = QNet.load(str(MODEL))
        pilot = lambda: Learner(q=net, margin=0.02)  # noqa: E731
    else:
        pilot = Planner

    def draw(rng):
        while True:
            team = rng.sample(pool, 3)
            if len({dex[b.species_id] for b in team}) == 3:  # the game does not allow a species twice
                return team

    _state.update(pool=pool, mine=builds(gd), pilot=pilot, draw=draw)


def play(job):
    lineup, battles, seed, keep_all = job
    s = _state
    points = field_results([s["mine"][sp] for sp in lineup], s["pool"], s["pilot"], lambda rng: varied(rng, s["pool"]),
                           battles, seed, draw=s["draw"])
    return lineup, (points if keep_all else sum(points))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pool", type=int, default=100, help="opponents draw from this many top-ranked Pokémon")
    parser.add_argument("--stages", default="150:500,600:50,3000:12", help="battles:keep for each stage")
    parser.add_argument("--finals", type=int, default=6000)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--show", type=int, default=12)
    args = parser.parse_args()
    gd = GameData()
    mine = builds(gd)
    dex = {sid: gd.species[sid]["dex"] for sid in mine}
    current = tuple(builds(gd, files=(ROOT / "data" / "owner_team.json",)))
    lineups = [(lead, *rest) for three in itertools.combinations(mine, 3) if len({dex[sp] for sp in three}) == 3
               for lead in three for rest in [tuple(sp for sp in three if sp != lead)]]
    print(f"{len(mine)} Pokémon, {len(lineups)} line-ups; opponents: random legal threes from the top {args.pool}; "
          f"pilot: {'the trained bot' if MODEL.exists() else 'the Planner'}", flush=True)

    played, total = 0, {t: 0.0 for t in lineups}
    alive = list(lineups)
    with multiprocessing.get_context("spawn").Pool(args.workers, initializer=setup, initargs=(args.pool,)) as workers:
        for number, stage in enumerate(args.stages.split(","), start=1):
            battles, keep = (int(v) for v in stage.split(":"))
            t0 = time.time()
            for lineup, points in workers.imap_unordered(play, [(t, battles, args.seed + number, False) for t in alive], chunksize=4):
                total[lineup] += points
            played += battles
            alive.sort(key=lambda t: -total[t])
            scores = [100 * total[t] / played for t in alive]
            print(f"stage {number}: {len(alive)} line-ups, {played} battles each so far, {(time.time() - t0) / 60:.0f} min; "
                  f"best {scores[0]:.1f}%, middle {scores[len(scores) // 2]:.1f}%, worst {scores[-1]:.1f}%", flush=True)
            alive = alive[:keep]
        finalists = alive + [t for t in lineups if set(t) == set(current) and t not in alive]
        final = dict(workers.imap_unordered(play, [(t, args.finals, args.seed + 1000, True) for t in finalists], chunksize=1))

    ranked = sorted(finalists, key=lambda t: -sum(final[t]))
    best = final[ranked[0]]
    rows = []
    print(f"\nfresh battles, {args.finals} each, the same for every line-up (lead first):")
    for t in ranked:
        mean, margin = mean_and_margin(final[t])
        diff, dm = mean_and_margin([a - b for a, b in zip(final[t], best)])
        mark = "   <- the current three" if set(t) == set(current) else ""
        rows.append({"team": list(t), "score": round(mean, 4), "margin": round(margin, 4), "behind_best": round(-diff, 4), "behind_margin": round(dm, 4)})
        if len(rows) <= args.show or mark:
            print(f"  {' / '.join(t):48s} {100 * mean:5.1f}% ± {100 * margin:.1f}   {100 * diff:+5.1f} ± {100 * dm:.1f} against the top line{mark}")
    count: dict = {}
    for t in alive:
        for sp in t:
            count[sp] = count.get(sp, 0) + 1
    print(f"how often each Pokémon is in the {len(alive)} survivors: " + ", ".join(f"{sp} {n}" for sp, n in sorted(count.items(), key=lambda kv: -kv[1])))
    out = ROOT / "data" / "roster_teams.json"
    out.write_text(json.dumps({"about": "Best line-ups from the owner's own Pokémon (scripts/roster_teams.py). score: share of battles won on fresh battles "
                               f"against random legal teams from the top {args.pool}; margin: 95% range; behind_best: gap to the top line on the same battles.",
                               "pool": args.pool, "battles": args.finals, "teams": rows}, indent=1) + "\n")
    print(f"written: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
