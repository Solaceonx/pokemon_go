#!/usr/bin/env python3
"""Find teams that should beat a given team, for the browser game to play against it (scripts/play.py --counters).

    python3 scripts/counters.py [melmetal altaria jellicent] [--keep 20] [--workers 3]

Our team is lead first and built as the browser game builds it (the owner's own IVs and moves); without names,
the browser game's default team. Candidates: every team in the good-team list (data/teams.json) with each of its
three leading, and random legal threes from the top 50. Each is scored by its win chance against ours with both
sides played by the trained bot with shifted habits (pogo.lineup), in stages that keep the better ones; the
survivors are scored again on fresh battles, and those whose chance is above --least are saved, best first, to
data/counters/<our team>.json.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import random
import sys
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_v] = "1"
ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
from pogo.gamedata import GameData  # noqa: E402
from pogo.learner import QNet  # noqa: E402
from pogo.lineup import win_chance  # noqa: E402

FOLDER = ROOT / "data" / "counters"
_state: dict = {}


def path_for(species: list) -> Path:
    return FOLDER / ("-".join(species) + ".json")


def setup(mine: list) -> None:
    os.nice(10)
    import play
    gd = GameData()
    owned = play.owner_builds(gd)
    _state.update(gd=gd, pool=gd.meta(50), net=QNet.load(str(ROOT / "runs" / "general-decide" / "q.npz")),
                  mine=[play.species_build(gd, s, owned) for s in mine])


def score(job):
    team, battles, seed = job
    s = _state
    theirs = [s["gd"].default(sid) for sid in team]
    chance, _ = win_chance(s["net"], s["pool"], theirs, s["mine"], battles, seed)  # the candidate's side
    return team, chance, battles


def main() -> None:
    import play
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mine", nargs="*", metavar="OURS")
    parser.add_argument("--random", type=int, default=300, help="random legal threes from the top 50 to try as well")
    parser.add_argument("--stages", default="30:80,150:25", help="battles:keep for each stage")
    parser.add_argument("--final", type=int, default=300, help="fresh battles for each survivor")
    parser.add_argument("--least", type=float, default=0.55, help="save only teams whose win chance is above this")
    parser.add_argument("--most", type=float, default=1.0,
                        help="save only teams whose win chance is at most this (for counters that are unfavourable but winnable)")
    parser.add_argument("--keep", type=int, default=20)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--seed", type=int, default=5)
    args = parser.parse_args()
    gd = GameData()
    owned = play.owner_builds(gd)
    mine = [play.species_build(gd, s, owned).species_id for s in args.mine] if args.mine \
        else [b.species_id for b in list(owned.values())[:3]]
    pool = gd.meta(50)
    dex = lambda sid: gd.species[sid]["dex"]  # noqa: E731
    candidates = set()
    for entry in json.loads((ROOT / "data" / "teams.json").read_text())["teams"]:
        t = entry["team"]
        candidates.update(tuple(t[k:] + t[:k]) for k in range(3))
    rng = random.Random(args.seed)
    while len(candidates) < 243 + args.random:
        t = tuple(b.species_id for b in rng.sample(pool, 3))
        if len({dex(s) for s in t}) == 3:
            candidates.add(t)
    alive = sorted(candidates)
    print(f"our team: {' / '.join(mine)}; {len(alive)} candidate teams (lead first)", flush=True)
    totals = {t: [0.0, 0] for t in alive}
    with multiprocessing.get_context("spawn").Pool(args.workers, initializer=setup, initargs=(mine,)) as workers:
        for number, stage in enumerate(args.stages.split(","), start=1):
            battles, keep = (int(v) for v in stage.split(":"))
            for team, chance, n in workers.imap_unordered(score, [(t, battles, args.seed + number) for t in alive], chunksize=4):
                totals[team][0] += chance * n
                totals[team][1] += n
            alive.sort(key=lambda t: -totals[t][0] / totals[t][1])
            alive = alive[:keep]
            print(f"stage {number}: kept {len(alive)}, best so far {100 * totals[alive[0]][0] / totals[alive[0]][1]:.0f}%", flush=True)
        final = list(workers.imap_unordered(score, [(t, args.final, args.seed + 1000) for t in alive], chunksize=1))
    final.sort(key=lambda r: -r[1])
    saved = [{"team": list(t), "win_chance": round(c, 3)} for t, c, _ in final if args.least < c <= args.most][:args.keep]
    FOLDER.mkdir(parents=True, exist_ok=True)
    out = path_for(mine)
    out.write_text(json.dumps({"about": f"Teams that should beat {' / '.join(mine)}: their win chance against it with both sides "
                               "played by the trained bot (scripts/counters.py), on fresh battles.", "against": mine,
                               "battles": args.final, "teams": saved}, indent=1) + "\n")
    print(f"\nfresh battles, {args.final} each (their win chance against ours):")
    for t, c, _ in final:
        print(f"  {' / '.join(t):50s} {100 * c:.0f}%")
    print(f"saved {len(saved)} teams above {100 * args.least:.0f}% to {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
