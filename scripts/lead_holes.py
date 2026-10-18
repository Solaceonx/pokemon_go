#!/usr/bin/env python3
"""Where a team has holes: its win chance against each opposing lead.

    python3 scripts/lead_holes.py --team empoleon_shadow jellicent stunfisk --team melmetal altaria jellicent [--battles 60]

For every one of the top 50 as the opponent's lead, with two others drawn at random from the top 50 (no species
twice), both sides played by the trained bot with shifted habits (pogo.lineup). An average over a field can hide a
lead that the team cannot answer; this lists each team's worst leads, how many leads it loses more often than it
wins, and the average over all leads alike. Pokémon are built with PvPoke's usual moves and IVs, so teams compare
fairly; --owned uses the owner's own builds where they have them. --lists also gives each team's win chance
against teams drawn from the two opposing lists (data/teams.json and data/teams_v2.json, by their weights).
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
from pogo.agents import varied_settings  # noqa: E402
from pogo.battle import DRAW, Battle  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.learner import Learner, QNet  # noqa: E402
from pogo.roster import builds  # noqa: E402

_state: dict = {}


def setup(owned: bool) -> None:
    os.nice(10)
    gd = GameData()
    _state.update(gd=gd, pool=gd.meta(50), net=QNet.load(str(ROOT / "runs" / "general-decide" / "q.npz")),
                  owned=builds(gd) if owned else {})


def against_list(job):
    team, path, battles, seed = job
    from pogo.teamlist import drawer
    s = _state
    gd, pool, net = s["gd"], s["pool"], s["net"]
    mine = [s["owned"].get(sp) or gd.default(sp) for sp in team]
    draw = drawer(gd, pool, Path(path), share=1.0)
    rng = random.Random(seed)
    points = 0.0
    for _ in range(battles):
        ours = Learner(q=net, margin=rng.choice((0.02, 0.05)), **varied_settings(rng, pool))
        foes = Learner(q=net, margin=rng.choice((0.02, 0.05)), **varied_settings(rng, pool))
        winner = Battle(mine, draw(rng), ours, foes, seed=rng.getrandbits(32)).run()
        points += 1.0 if winner == 0 else 0.5 if winner == DRAW else 0.0
    return team, Path(path).name, points / battles


def play(job):
    team, lead, battles, seed = job
    s = _state
    gd, pool, net = s["gd"], s["pool"], s["net"]
    mine = [s["owned"].get(sp) or gd.default(sp) for sp in team]
    first = next(b for b in pool if b.species_id == lead)
    dex = lambda b: gd.species[b.species_id]["dex"]  # noqa: E731
    others = [b for b in pool if dex(b) != dex(first)]
    rng = random.Random(seed)
    points = 0.0
    for _ in range(battles):
        while True:
            back = rng.sample(others, 2)
            if dex(back[0]) != dex(back[1]):
                break
        ours = Learner(q=net, margin=rng.choice((0.02, 0.05)), **varied_settings(rng, pool))
        foes = Learner(q=net, margin=rng.choice((0.02, 0.05)), **varied_settings(rng, pool))
        winner = Battle(mine, [first, *back], ours, foes, seed=rng.getrandbits(32)).run()
        points += 1.0 if winner == 0 else 0.5 if winner == DRAW else 0.0
    return team, lead, points / battles


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--team", nargs=3, action="append", required=True, metavar="SPECIES", help="lead first; repeat for more teams")
    parser.add_argument("--battles", type=int, default=60, help="battles per opposing lead")
    parser.add_argument("--worst", type=int, default=6)
    parser.add_argument("--owned", action="store_true", help="use the owner's own builds where they have them")
    parser.add_argument("--lists", type=int, default=0, metavar="BATTLES",
                        help="also this many battles against each of the two opposing lists")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--seed", type=int, default=9)
    args = parser.parse_args()
    leads = [b.species_id for b in GameData().meta(50)]
    teams = [tuple(t) for t in args.team]
    jobs = [(t, lead, args.battles, args.seed * 1000 + k) for t in teams for k, lead in enumerate(leads)]
    got: dict = {}
    with multiprocessing.get_context("spawn").Pool(args.workers, initializer=setup, initargs=(args.owned,)) as workers:
        for team, lead, chance in workers.imap_unordered(play, jobs, chunksize=4):
            got.setdefault(team, {})[lead] = chance
        listed: dict = {}
        if args.lists:
            lists = [ROOT / "data" / "teams.json", ROOT / "data" / "teams_v2.json"]
            per = -(-args.lists // 6)
            parts = [(t, str(p), per, args.seed * 7 + k) for t in teams for p in lists for k in range(6)]
            for team, name, chance in workers.imap_unordered(against_list, parts):
                listed.setdefault((team, name), []).append(chance)
    print(f"each team against every top-50 lead, {args.battles} battles per lead (random back two), both sides the bot")
    gd = GameData()
    for t in teams:
        by = got[t]
        worst = sorted(by.items(), key=lambda kv: kv[1])[:args.worst]
        losing = sum(c < 0.5 for c in by.values())
        print(f"\n{' / '.join(t)}: average over leads {100 * sum(by.values()) / len(by):.0f}%; "
              f"loses more than it wins against {losing} of {len(by)} leads")
        print("  worst leads: " + ", ".join(f"{lead} {100 * c:.0f}%" for lead, c in worst))
        print("  best leads: " + ", ".join(f"{lead} {100 * c:.0f}%" for lead, c in sorted(by.items(), key=lambda kv: -kv[1])[:4]))
        if listed:
            print("  against the opposing lists: " + ", ".join(
                f"{name} {100 * sum(v) / len(v):.0f}%" for (team, name), v in sorted(listed.items()) if team == t)
                + f" (about {args.lists} battles each, ± {100 * 0.98 / args.lists ** 0.5:.0f})")


if __name__ == "__main__":
    main()
