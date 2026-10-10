#!/usr/bin/env python3
"""Report on one team of three in simulated Great League battles.

    python3 scripts/team.py melmetal jellicent altaria
    python3 scripts/team.py melmetal jellicent altaria --grid    also print every one-on-one

Each Pokémon gets PvPoke's recommended moveset and default level and IVs. The
first one named leads.
"""
from __future__ import annotations

import argparse
import difflib
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pogo.agents import Masher, Planner  # noqa: E402
from pogo.battle import DRAW, Battle, Mon  # noqa: E402
from pogo.gamedata import SUPER, Build, GameData, effectiveness, _CHART  # noqa: E402

SHIELD_CASES = (0, 1, 2)


def one_on_one(a: Build, b: Build, shields: int) -> float:
    """Share of health a keeps minus the share b keeps, both played by the Planner without switching."""
    x, y = Mon(a), Mon(b)
    Battle([x], [y], Planner(switches=False), Planner(switches=False), seed=0, shields=(shields, shields)).run()
    return max(x.hp, 0) / a.hp - max(y.hp, 0) / b.hp


def offence(a: Build, b: Build) -> float:
    """Mean type multiplier of a's moves against b."""
    moves = (a.fast, *a.charged)
    return sum(effectiveness(m.type, b.types) for m in moves) / len(moves)


def type_edge(a: Build, b: Build) -> float:
    """Above 1 when the type chart favours a over b."""
    return offence(a, b) / offence(b, a)


def record(team: list[Build], pool: list[Build], make_mine, make_theirs, battles: int, seed: int):
    """Win share against random teams from the pool, and the same split by opposing Pokémon."""
    rng = random.Random(seed)
    points = 0.0
    faced: dict[str, list[float]] = {}
    for _ in range(battles):
        theirs = rng.sample(pool, 3)
        winner = Battle(team, theirs, make_mine(), make_theirs(), seed=rng.getrandbits(32)).run()
        point = 1.0 if winner == 0 else 0.5 if winner == DRAW else 0.0
        points += point
        for b in theirs:
            faced.setdefault(b.name, []).append(point)
    share = points / battles
    return share, 1.96 * math.sqrt(share * (1 - share) / battles), faced


def pct(share: float, margin: float) -> str:
    return f"{100 * share:5.1f}% ± {100 * margin:.1f}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("species", nargs=3, help="three species ids, lead first")
    parser.add_argument("--battles", type=int, default=10000)
    parser.add_argument("--pool", type=int, default=50, help="opponents come from this many top-ranked Pokémon")
    parser.add_argument("--grid", action="store_true", help="print every one-on-one against the pool")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    gd = GameData()
    for sid in args.species:
        if sid not in gd.species:
            close = ", ".join(difflib.get_close_matches(sid, gd.species, n=4)) or "nothing similar"
            sys.exit(f"unknown species id {sid!r}; closest: {close}")
    team = [gd.default(sid) for sid in args.species]
    pool = gd.meta(args.pool)

    print("Team (Great League, PvPoke default level and IVs)")
    for b in team:
        moves = " / ".join(m.name for m in (b.fast, *b.charged))
        print(f"  {b.name:10s} CP {b.cp}  level {b.level:g}  IVs {'/'.join(map(str, b.ivs))}  "
              f"atk {b.atk:.1f} def {b.defense:.1f} hp {b.hp}  {'/'.join(b.types)}  {moves}")

    weak = {t: [b.name for b in team if effectiveness(t, b.types) >= SUPER] for t in _CHART}
    resist = {t: [b.name for b in team if effectiveness(t, b.types) < 1] for t in _CHART}
    print("\nType chart")
    for b in team:
        print(f"  {b.name:10s} weak to {', '.join(t for t in _CHART if b.name in weak[t]) or 'nothing'}")
    shared = [t for t in _CHART if len(weak[t]) >= 2]
    print(f"  hits two or more of the team super effectively: {', '.join(shared) or 'no type'}")
    print(f"  resisted by none of the team: {', '.join(t for t in _CHART if not resist[t]) or 'no type'}")

    n = args.battles
    print(f"\nRecord with {team[0].name} leading, {n} battles per line, against random threes from the top {len(pool)}")
    share, margin, faced = record(team, pool, Planner, Planner, n, args.seed)
    print(f"  Planner on both sides       {pct(share, margin)}")
    s2, m2, _ = record(team, pool, Planner, Masher, n, args.seed)
    print(f"  Planner against Masher      {pct(s2, m2)}")
    s3, m3, _ = record(team, pool, Masher, Masher, n, args.seed)
    print(f"  Masher on both sides        {pct(s3, m3)}")

    print("\nBy lead, Planner on both sides")
    for k in range(3):
        order = [team[k]] + [b for j, b in enumerate(team) if j != k]
        s, m, _ = record(order, pool, Planner, Planner, n, args.seed)
        print(f"  {order[0].name:10s} lead  {pct(s, m)}")

    print(f"\nHardest and easiest opposing Pokémon (team's win share when they are on the other side, Planner both sides)")
    rows = sorted(((sum(v) / len(v), name, len(v)) for name, v in faced.items()))
    for label, chunk in (("hardest", rows[:8]), ("easiest", rows[-5:])):
        print(f"  {label}: " + ", ".join(f"{name} {100 * s:.0f}%" for s, name, _ in chunk))
    print(f"  (about {n * 3 // len(pool)} battles each, so roughly ±{100 * 1.96 * 0.5 / math.sqrt(n * 3 / len(pool)):.0f} points)")

    others = [b for b in pool]
    grid = {b.name: {o.name: [one_on_one(b, o, s) for s in SHIELD_CASES] for o in others if o.species_id != b.species_id}
            for b in team}
    print(f"\nOne-on-one against the top {len(pool)} (Planner both sides, no switching): wins at 0, 1 and 2 shields each")
    for b in team:
        wins = [sum(r[k] > 0 for r in grid[b.name].values()) for k in range(3)]
        print(f"  {b.name:10s} {wins[0]:2d}, {wins[1]:2d}, {wins[2]:2d} of {len(grid[b.name])}")
    holes = [o.name for o in others if all(grid[b.name].get(o.name, [0, 1, 0])[1] <= 0 for b in team)]
    print(f"  beats all three at 1 shield each: {', '.join(holes) or 'nobody'}")

    if args.grid:
        print("\nHealth margin at 1 shield each (+ means the team member wins); type edge in brackets")
        print(f"  {'opponent':24s}" + "".join(f"{b.name:>22s}" for b in team))
        for o in others:
            cells = []
            for b in team:
                if o.name in grid[b.name]:
                    cells.append(f"{grid[b.name][o.name][1]:+.2f} [{type_edge(b, o):4.2f}]".rjust(22))
                else:
                    cells.append("mirror".rjust(22))
            print(f"  {o.name:24s}" + "".join(cells))

    agree = total = 0
    for a in pool:
        for b in pool:
            edge = type_edge(a, b)
            if a.uid < b.uid and abs(edge - 1) > 0.05:
                total += 1
                agree += (one_on_one(a, b, 1) > 0) == (edge > 1)
    print(f"\nType advantage as a predictor: across the {total} pairs in the top {len(pool)} where the type chart favours "
          f"one side,\n  that side wins the one-on-one at 1 shield each {100 * agree / total:.0f}% of the time.")


if __name__ == "__main__":
    main()
