#!/usr/bin/env python3
"""Find the teams of three that do best in simulation, and save them as a list to draw opponents from.

    python3 scripts/teams.py                                   search the top 50 Pokémon
    python3 scripts/teams.py --include melmetal jellicent altaria   also rank this team

1. Every one-on-one among the pool is played out and saved (data/matchups.json).
2. Every legal team of three (no species twice) gets a quick score from those one-on-ones:
   against each possible opponent, how good are its best two answers.
3. The best couple of hundred by quick score, and as many again picked at random, play real
   three-on-three battles in stages that keep the better teams and test them harder. Between
   stages the leaders are bred: one Pokémon is changed and the new team tested. From the second stage on, half of the
   opposing teams are drawn from the current leaders, so a team has to beat good teams,
   not just random ones. The last stage tries each Pokémon as the lead.

The result goes to data/teams.json, best first. "seen" in that file is for counts of
teams met in real games, to weight the list later; it starts at zero.
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pogo.agents import Planner  # noqa: E402
from pogo.battle import DRAW, Battle, Mon  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def one_on_one(a, b, shields: int) -> float:
    x, y = Mon(a), Mon(b)
    Battle([x], [y], Planner(switches=False, seed=0), Planner(switches=False, seed=0), seed=0, shields=(shields, shields)).run()
    return max(x.hp, 0) / a.hp - max(y.hp, 0) / b.hp


def matchups(pool) -> list[list[float]]:
    """Mean health margin of each Pokémon against each other one, over 0, 1 and 2 shields each."""
    path = ROOT / "data" / "matchups.json"
    saved = json.loads(path.read_text()) if path.exists() else {}
    ids = [b.species_id for b in pool]
    table = []
    for a in pool:
        row = saved.setdefault(a.species_id, {})
        for b in pool:
            if b.species_id not in row:
                row[b.species_id] = round(sum(one_on_one(a, b, s) for s in (0, 1, 2)) / 3, 4)
        table.append([row[i] for i in ids])
    path.write_text(json.dumps(saved))
    return table


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pool", type=int, default=50)
    parser.add_argument("--include", nargs=3, metavar="SPECIES", help="a team to keep in every stage, to see where it ranks")
    parser.add_argument("--shortlist", type=int, default=200)
    parser.add_argument("--generations", type=int, default=3)
    parser.add_argument("--stages", type=int, nargs=6, default=[100, 80, 400, 24, 600, 0], metavar="N",
                        help="battles per team in stage 1, teams kept, battles in stage 2, teams kept, battles per lead in stage 3, unused")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    n1, keep1, n2, keep2, n3, _ = args.stages

    gd = GameData()
    pool = gd.meta(args.pool)
    index = {b.species_id: k for k, b in enumerate(pool)}
    dex = [gd.species[b.species_id]["dex"] for b in pool]
    rng = random.Random(args.seed)
    t0 = time.time()
    table = matchups(pool)
    n = len(pool)
    print(f"one-on-ones for {n} Pokémon ready ({time.time() - t0:.0f}s)", flush=True)

    legal = [t for t in itertools.combinations(range(n), 3) if len({dex[k] for k in t}) == 3]

    def quick(team) -> float:
        total = 0.0
        for o in range(n):
            a, b, c = sorted(table[k][o] for k in team)
            total += (b + c) / 2  # its best two answers to this opponent
        return total / n

    ranked = sorted(legal, key=quick, reverse=True)
    # The quick score is only a rough guide, so start from its best and from as many again chosen at random.
    teams = ranked[:args.shortlist] + rng.sample(ranked[args.shortlist:], args.shortlist)
    mine = None
    if args.include:
        mine = tuple(sorted(index[s] for s in args.include))
        if mine not in teams:
            teams.append(mine)
        print(f"{' / '.join(args.include)}: quick score ranks {ranked.index(mine) + 1} of {len(legal)} legal teams")

    def general_first(team) -> list[int]:
        """Lead with the Pokémon that does best against the pool as a whole."""
        return sorted(team, key=lambda k: -sum(table[k]) / n)

    def random_team() -> list[int]:
        while True:
            team = rng.sample(range(n), 3)
            if len({dex[k] for k in team}) == 3:
                return team

    def play(order: list[int], battles: int, leaders: list[list[int]]) -> tuple[float, float]:
        points = 0.0
        for _ in range(battles):
            foe = rng.choice(leaders) if leaders and rng.random() < 0.5 else random_team()
            winner = Battle([pool[k] for k in order], [pool[k] for k in foe], Planner(), Planner(), seed=rng.getrandbits(32)).run()
            points += 1.0 if winner == 0 else 0.5 if winner == DRAW else 0.0
        share = points / battles
        return share, 1.96 * math.sqrt(share * (1 - share) / battles)

    def stage(label: str, orders: list[list[int]], battles: int, leaders: list[list[int]]):
        t = time.time()
        scored = sorted(((*play(order, battles, leaders), order) for order in orders), key=lambda r: -r[0])
        print(f"{label}: {len(orders)} line-ups x {battles} battles in {(time.time() - t) / 60:.1f} min; best {100 * scored[0][0]:.1f}%", flush=True)
        return scored

    def keep(scored, count: int) -> list[list[int]]:
        kept = [order for _, _, order in scored[:count]]
        if mine and not any(tuple(sorted(o)) == mine for o in kept):
            kept.append(next(o for _, _, o in scored if tuple(sorted(o)) == mine))
        return kept

    first = stage("stage 1, against random teams", [general_first(t) for t in teams], n1, [])
    survivors = keep(first, keep1)
    second = stage("stage 2, half against the leaders", survivors, n2, survivors[:40])

    # Breed: change one Pokémon in each of the current best teams, test the new teams, keep the best of all.
    tried = {tuple(sorted(t)) for t in teams}
    for generation in range(1, args.generations + 1):
        parents = [order for _, _, order in second[:40]]
        children = set()
        for order in parents:
            for _ in range(5):
                child = list(order)
                child[rng.randrange(3)] = rng.randrange(n)
                key = tuple(sorted(child))
                if len({dex[k] for k in child}) == 3 and key not in tried:
                    children.add(key)
                    tried.add(key)
        bred = stage(f"generation {generation}, one Pokémon changed", [general_first(c) for c in children], n2 // 2, parents)
        second = sorted(second + bred, key=lambda r: -r[0])[:keep1]
    finalists = keep(second, keep2)
    leads = [[k] + [j for j in team if j != k] for team in finalists for k in team]
    third = stage("stage 3, every lead, half against the leaders", leads, n3, finalists)

    best_lead: dict[tuple, tuple] = {}
    for share, margin, order in third:
        best_lead.setdefault(tuple(sorted(order)), (share, margin, order))
    out = [{"team": [pool[k].species_id for k in order], "score": round(share, 4), "margin": round(margin, 4),
            "battles": n3, "lead_tested": True, "quick": round(quick(key), 4), "seen": 0}
           for key, (share, margin, order) in sorted(best_lead.items(), key=lambda kv: -kv[1][0])]
    # The rest of the last population, for variety. Their scores come from fewer battles and an untested lead.
    for share, margin, order in second:
        if tuple(sorted(order)) not in best_lead:
            out.append({"team": [pool[k].species_id for k in order], "score": round(share, 4), "margin": round(margin, 4),
                        "battles": None, "lead_tested": False, "quick": round(quick(tuple(sorted(order))), 4), "seen": 0})
    (ROOT / "data" / "teams.json").write_text(json.dumps(
        {"pool": args.pool, "pilot": "Planner", "field": "half finalists, half random teams", "teams": out}, indent=1) + "\n")

    print(f"\nbest teams (lead first), win share against a field of half finalists, half random teams; {n3} battles each:")
    for rank, entry in enumerate(out, start=1):
        names = " / ".join(gd.species[s]["speciesName"] for s in entry["team"])
        flag = "   <- yours" if mine and tuple(sorted(index[s] for s in entry["team"])) == mine else ""
        if (rank <= 15 and entry["lead_tested"]) or flag:
            print(f"  {rank:2d}. {100 * entry['score']:.1f}% ± {100 * entry['margin']:.1f}  {names}{flag}")
    counts: dict = {}
    for entry in out:
        for sid in entry["team"]:
            counts[sid] = counts.get(sid, 0) + 1
    print("most used among all saved teams: " + ", ".join(f"{gd.species[sid]['speciesName']} {c}" for sid, c in sorted(counts.items(), key=lambda kv: -kv[1])[:10]))
    print(f"saved {len(out)} teams to data/teams.json; total {(time.time() - t0) / 60:.1f} min")


if __name__ == "__main__":
    main()
