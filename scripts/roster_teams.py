#!/usr/bin/env python3
"""Find the best teams the owner can field from their own Pokémon.

    python3 scripts/roster_teams.py [--pool 100] [--stages 150:500,600:50,3000:12] [--finals 6000] [--workers 3]

The owner's Pokémon come from data/owner_team.json and data/owner_roster.json, with their own IVs and moves.
Every legal line-up (a lead and two others) is a candidate. Ours is piloted by the best bot.

Who the opponents are decides what the scores mean:
  --field mixed    (the default) teams as PvPoke's usage data has them three times in four, the usual draw otherwise
                   (pogo.teamshape.mixed_field: Cramorant and Mimikyu included, balanced teams); --listed and --pool
                   then do not apply. --field standard is the old draw below
  --listed SHARE   this share of opposing teams comes from the good-team list (--teams, data/teams.json), better
                   teams more often; the rest are random legal threes from the top --pool Pokémon
  --rival bot      the opponent is piloted by the same bot as ours (equal skill); "crowd" is the usual, weaker,
                   crowd of Planner variations
Random teams and the crowd flatter every line-up: on the ladder the opponents are as good as we are.
--recheck plays only the line-ups already in data/roster_teams.json, straight to the fresh battles.

All candidates play the same battles. Each stage adds battles and keeps the best so far ("150:500" = 150
battles each, keep 500). The survivors of the last stage then play fresh battles, and only those are
reported: the best of thousands in the rounds that picked them is flattered by luck.
Results also go to data/roster_teams.json.

--compare-teams FILE searches against BOTH --teams and FILE, keeping each field's
finalists, then evaluates their union on untouched, paired battles against both.
Use --rival bot --listed 1 for the task-21 list check. Every pairing is played on
both sides; --stages and --finals still count individual battles (must be even).
The same opponent-draw uniforms, pilot seeds and battle dice are used for all
line-ups and both lists. Opposing teams necessarily differ between lists.
Comparison output defaults to data/roster_teams_v2.json, preserving the old result.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import multiprocessing
import os
import shlex
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
from pogo.teamlist import TEAMS, drawer, weights_for  # noqa: E402

MODEL = ROOT / "runs" / "general-decide" / "q.npz"
_state: dict = {}


def setup(pool_size: int, listed: float, teams: str, rival: str, field: str = "standard") -> None:
    try:
        os.nice(10)
    except OSError:  # restricted environments may deny even lowering priority
        pass
    gd = GameData()
    pool = gd.meta(pool_size)
    draw = drawer(gd, pool, Path(teams), share=listed)
    if field == "mixed":
        from pogo.teamshape import mixed_field
        pool, draw = mixed_field(gd)
    pilot, opponent = Planner, lambda rng: varied(rng, pool)  # noqa: E731
    if MODEL.exists():
        from pogo.learner import Learner, QNet
        net = QNet.load(str(MODEL))
        pilot = lambda: Learner(q=net, margin=0.02)  # noqa: E731
        if rival == "bot":
            opponent = lambda rng: Learner(q=net, margin=0.02, seed=rng.getrandbits(30))  # noqa: E731
    _state.update(pool=pool, mine=builds(gd), pilot=pilot, opponent=opponent, draw=draw)


def play(job):
    lineup, battles, seed, keep_all = job
    s = _state
    points = field_results([s["mine"][sp] for sp in lineup], s["pool"], s["pilot"], s["opponent"], battles, seed, draw=s["draw"])
    return lineup, (points if keep_all else sum(points))


def compare_lists(args, parser):
    """Search both fields independently, then compare on a common held-out schedule."""
    from pogo.teamsearch import estimate, evaluate, schedule, seed_for, setup as paired_setup
    if args.rival != "bot" or not MODEL.is_file():
        parser.error("--compare-teams requires --rival bot and the trained model")
    if not 0 <= args.listed <= 1 or args.workers < 1 or args.finals < 4 or args.finals % 2:
        parser.error("comparison needs 0 <= --listed <= 1, positive workers, and even --finals >= 4")
    try:
        stages = [tuple(map(int, part.split(":"))) for part in args.stages.split(",")]
        if any(len(s) != 2 or s[0] < 4 or s[0] % 2 or s[1] < 10 for s in stages):
            raise ValueError
    except ValueError:
        parser.error("comparison stages must be even battles >= 4 : keep >= 10")
    out = Path(args.out) if args.out else ROOT / "data" / "roster_teams_v2.json"
    paths = [Path(args.teams), Path(args.compare_teams)]
    if out.resolve() in {p.resolve() for p in [*paths, TEAMS, ROOT / "data" / "roster_teams.json",
                                              ROOT / "data" / "owner_team.json", ROOT / "data" / "owner_roster.json"]}:
        parser.error("comparison --out must preserve the inputs and old roster result")
    gd = GameData()
    mine, pool = builds(gd), gd.meta(args.pool)
    ids = [b.species_id for b in pool]
    dex = {s: gd.species[s]["dex"] for s in set(ids) | set(mine)}
    current = tuple(builds(gd, files=(ROOT / "data" / "owner_team.json",)))
    lineups = [(lead, *(s for s in three if s != lead))
               for three in itertools.combinations(mine, 3) if len({dex[s] for s in three}) == 3 for lead in three]
    references = [t for t in lineups if set(t) == set(current)]
    if args.recheck:
        lineups = [tuple(e["team"]) for e in json.loads((ROOT / "data" / "roster_teams.json").read_text())["teams"]]
        stages = []
    fields = [json.loads(p.read_text())["teams"] for p in paths]
    weights = [weights_for(f) for f in fields]
    started = time.monotonic()
    print(f"paired list comparison: {len(lineups)} roster line-ups, trained bot on both sides; "
          f"{100 * args.listed:.0f}% listed, rest random top {args.pool}; {args.workers} workers", flush=True)
    survivors = []
    with multiprocessing.get_context("spawn").Pool(args.workers, initializer=paired_setup,
                                                    initargs=(str(MODEL), args.pool)) as workers:
        for field, entries in enumerate(fields):
            alive, total = list(lineups), {t: 0.0 for t in lineups}
            for number, (battles, keep) in enumerate(stages):
                rows = schedule([tuple(e["team"]) for e in entries], weights[field], ids, dex,
                                battles // 2, seed_for(args.seed, "roster-search", number), args.listed)
                for t, points in evaluate(workers, alive, rows, owner=True).items():
                    total[t] += sum(points)
                before = len(alive)
                alive = sorted(alive, key=lambda t: (-total[t], t))[:keep]
                print(f"{paths[field].name}, stage {number + 1}: {before} line-ups, {battles} more battles each; "
                      f"kept {len(alive)}; elapsed {(time.monotonic() - started) / 60:.1f} min", flush=True)
            survivors.append(alive)
        finalists = sorted(set(survivors[0]) | set(survivors[1]) | set(references))
        final_seed = seed_for(args.seed, "roster-untouched-final")
        results = []
        for entries, w in zip(fields, weights):
            rows = schedule([tuple(e["team"]) for e in entries], w, ids, dex, args.finals // 2, final_seed, args.listed)
            results.append(evaluate(workers, finalists, rows, owner=True))
    ranks = [{t: rank for rank, t in enumerate(sorted(finalists, key=lambda t: (-sum(result[t]), t)), start=1)}
             for result in results]
    rows = []
    for t in sorted(finalists, key=lambda t: ranks[1][t]):
        rows.append({"team": list(t), "old_rank": ranks[0][t], "new_rank": ranks[1][t],
                     "selected_by": [str(paths[i]) for i in range(2) if t in survivors[i]],
                     "old": estimate(results[0][t]), "new": estimate(results[1][t]),
                     "new_minus_old": estimate([a - b for a, b in zip(results[1][t], results[0][t])]),
                     "old_minus_current": estimate([a - b for a, b in zip(results[0][t], results[0][current])]),
                     "new_minus_current": estimate([a - b for a, b in zip(results[1][t], results[1][current])])})
    print(f"\nuntouched comparison: {args.finals} battles ({args.finals // 2} independent mirrored pairs) per line-up per list")
    print("lead first; ranks among the union of both searches' finalists; 95% pair-cluster margins")
    for row in rows:
        if row["new_rank"] <= max(10, args.show) or row["old_rank"] <= 10 or tuple(row["team"]) in references:
            a, b, d = row["old"], row["new"], row["new_minus_old"]
            print(f"  {' / '.join(row['team']):49s} old #{row['old_rank']:2d} {100*a['score']:5.1f}% ± {100*a['margin']:.1f}"
                  f"   new #{row['new_rank']:2d} {100*b['score']:5.1f}% ± {100*b['margin']:.1f}"
                  f"   change {100*d['score']:+5.1f} ± {100*d['margin']:.1f}")
    checks = [*paths, MODEL, ROOT / "data" / "owner_team.json", ROOT / "data" / "owner_roster.json",
              *[ROOT / p for p in ("pogo/battle.py", "pogo/agents.py", "pogo/learner.py", "pogo/gamedata.py",
                                   "pogo/roster.py", "pogo/teamsearch.py", "pogo/teamlist.py",
                                   "scripts/roster_teams.py", "data/gamemaster.json", "data/rankings-1500.json", "data/cpm.json")]]
    report = {"about": "Owner roster search against both lists, evaluated on matching untouched seeds. "
                       "Both sides use the same learned bot. Pairings played on both sides; margins cluster by pair. "
                       "All line-ups face identical opponents within a list; between lists only the drawn listed team changes. "
                       "Ranks are among finalists, not a proof of the global optimum; nearby ranks can be noise.",
              "command": shlex.join([sys.executable, *sys.argv]), "old_list": str(paths[0]), "new_list": str(paths[1]),
              "sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in checks},
              "pool": args.pool, "listed": args.listed, "rival": args.rival, "seed": final_seed,
              "search_lineups": len(lineups), "stages": stages, "battles": args.finals,
              "elapsed_seconds": time.monotonic() - started, "teams": rows}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1) + "\n")
    print(f"written: {out}; elapsed {report['elapsed_seconds'] / 60:.1f} min", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pool", type=int, default=100, help="opponents draw from this many top-ranked Pokémon")
    parser.add_argument("--listed", type=float, default=0.0, help="share of opposing teams drawn from the good-team list")
    parser.add_argument("--teams", default=str(TEAMS), help="the good-team list")
    parser.add_argument("--compare-teams", help="search and compare this list with --teams on paired fresh battles")
    parser.add_argument("--out", help="output JSON (comparison defaults to data/roster_teams_v2.json)")
    parser.add_argument("--rival", choices=("crowd", "bot"), default="crowd", help="who pilots the opponent")
    parser.add_argument("--field", choices=("mixed", "standard"), default="mixed",
                        help="opposing teams: the mixed field (realistic, docs/status.md rules) or --listed/--pool; "
                             "--compare-teams always uses the latter")
    parser.add_argument("--recheck", action="store_true", help="only the line-ups in data/roster_teams.json, fresh battles only")
    parser.add_argument("--stages", default="150:500,600:50,3000:12", help="battles:keep for each stage")
    parser.add_argument("--finals", type=int, default=6000)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--show", type=int, default=12)
    args = parser.parse_args()
    if args.compare_teams:
        compare_lists(args, parser)
        return
    gd = GameData()
    mine = builds(gd)
    dex = {sid: gd.species[sid]["dex"] for sid in mine}
    current = tuple(builds(gd, files=(ROOT / "data" / "owner_team.json",)))
    lineups = [(lead, *rest) for three in itertools.combinations(mine, 3) if len({dex[sp] for sp in three}) == 3
               for lead in three for rest in [tuple(sp for sp in three if sp != lead)]]
    out = Path(args.out) if args.out else ROOT / "data" / "roster_teams.json"
    stages = args.stages.split(",")
    if args.recheck:
        lineups, stages = [tuple(e["team"]) for e in json.loads(out.read_text())["teams"]], []
    field = (f"{100 * args.listed:.0f}% from {Path(args.teams).name}, the rest " if args.listed else "") + f"random legal threes from the top {args.pool}"
    if args.field == "mixed":
        field = "the mixed field (PvPoke usage three times in four, the usual draw otherwise)"
    rival = "the same bot" if args.rival == "bot" and MODEL.exists() else "the usual crowd"
    print(f"{len(mine)} Pokémon, {len(lineups)} line-ups; opposing teams: {field}; opposing pilot: {rival}; "
          f"our pilot: {'the trained bot' if MODEL.exists() else 'the Planner'}", flush=True)

    played, total = 0, {t: 0.0 for t in lineups}
    alive = list(lineups)
    with multiprocessing.get_context("spawn").Pool(args.workers, initializer=setup,
                                                    initargs=(args.pool, args.listed, args.teams, args.rival, args.field)) as workers:
        for number, stage in enumerate(stages, start=1):
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
    caution = ""
    if rows[0]["score"] > 0.65:  # the owner's test: between equals on real teams the game is close to 50-50
        caution = (f"The best line-up wins {100 * rows[0]['score']:.0f}%. Opponents this beatable are not what a good player meets, "
                   "so the order may only show which line-ups counter this particular set of opposing teams.")
        print("caution: " + caution)
    if args.recheck:
        return
    out.write_text(json.dumps({"about": "Best line-ups from the owner's own Pokémon (scripts/roster_teams.py). score: share of battles won on fresh battles "
                               f"against {field}, piloted by {rival}; margin: 95% range; behind_best: gap to the top line on the same battles.",
                               "caution": caution, "field": args.field, "pool": args.pool, "listed": args.listed, "rival": args.rival, "battles": args.finals, "teams": rows}, indent=1) + "\n")
    print(f"written: {out}")


if __name__ == "__main__":
    main()
