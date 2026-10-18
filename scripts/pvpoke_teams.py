#!/usr/bin/env python3
"""What PvPoke's public team data says about the opponents we model (data/pvpoke_training_1500.json).

    python3 scripts/pvpoke_teams.py [--threshold 0.3]

PvPoke publishes, from its training battles (players and bots at Elite and Champion), how often each Pokémon is
brought and the best-scoring teams with their game counts, plus the 37 hand-made teams its bots bring. This prints:

1. usage: each Pokémon's share of team slots, and whether our opponent pools (gd.meta(50), with and without the
   form-changing Pokémon) contain it;
2. team shapes (pogo.teamshape: ABC, ABB, AAB, AAA) of the listed teams and the bot teams, next to random threes
   drawn by usage (what picking Pokémon one at a time by popularity would give) and our shaped drawer; the ratio of
   listed to random is how much players favour or avoid a shape.

The letters need one-on-one records against a common set; the set here is our pool with the form-changers plus every
Pokémon in the PvPoke lists, played out once and kept in data/matchups_wide.json (data/matchups.json is untouched).
"""
from __future__ import annotations

import argparse
import collections
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
from pogo.gamedata import GameData  # noqa: E402
from pogo.teamshape import SHAPES, Shapes, shaped_drawer  # noqa: E402
from teams import one_on_one  # noqa: E402

DATA = ROOT / "data" / "pvpoke_training_1500.json"
WIDE = ROOT / "data" / "matchups_wide.json"


def wide_table(gd, ids) -> None:
    saved = json.loads(WIDE.read_text()) if WIDE.exists() else {}
    builds = {sp: gd.default(sp) for sp in ids}
    for a in ids:
        row = saved.setdefault(a, {})
        for b in ids:
            if b not in row:
                row[b] = round(sum(one_on_one(builds[a], builds[b], s) for s in (0, 1, 2)) / 3, 4)
    for a in list(saved):  # keep the table square over `ids`
        if a not in ids:
            del saved[a]
        else:
            saved[a] = {b: saved[a][b] for b in ids}
    WIDE.write_text(json.dumps(saved))


def mix(counts) -> str:
    total = sum(counts.values()) or 1
    return " ".join(f"{s} {100 * counts[s] / total:3.0f}%" for s in SHAPES)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--threshold", type=float, default=0.3)
    args = parser.parse_args()
    gd = GameData()
    data = json.loads(DATA.read_text())
    usage, bots = data["usage"], data["bot_teams"]["teams"]
    known = {e["speciesId"] for e in gd.rankings(1500)}
    ok = lambda sp: sp in known and "_mega" not in sp  # noqa: E731

    slots = collections.Counter()
    for p in usage["performers"]:
        slots[p["pokemon"]] += p["games"]
    total = usage["totalPerformers"]
    plain = {b.species_id for b in gd.meta(50)}
    forms = {b.species_id for b in gd.meta(50, forms=True)}
    print(f"PvPoke training, Great League, updated {usage['lastUpdated']}: {usage['totalTeams']} teams; "
          f"the {len(slots)} Pokémon listed fill {100 * sum(slots.values()) / total:.0f}% of team slots")
    print("  share  Pokémon               in our pool")
    for sp, n in slots.most_common():
        where = "yes" if sp in plain else "only with form-changers" if sp in forms else "no"
        print(f"  {100 * n / total:4.1f}%  {sp:21s} {where}")
    for name, pool in (("our pool (no form-changers)", plain), ("our pool with form-changers", forms)):
        print(f"  {name}: {100 * sum(n for sp, n in slots.items() if sp in pool) / total:.0f}% of team slots")

    teams = [(t["team"], t["games"]) for t in usage["teams"] if all(ok(sp) for sp in t["team"])]
    bot_teams = [t["team"] for t in bots if all(ok(sp) for sp in t["team"])]
    ids = sorted(forms | {sp for t, _ in teams for sp in t} | {sp for t in bot_teams for sp in t} | {sp for sp in slots if ok(sp)})
    wide_table(gd, ids)
    shapes = Shapes(args.threshold, path=WIDE)

    listed, listed_games, bot_mix = collections.Counter(), collections.Counter(), collections.Counter()
    for team, games in teams:
        s = shapes.shape(team)
        listed[s] += 1
        listed_games[s] += games
    for team in bot_teams:
        bot_mix[shapes.shape(team)] += 1
    rng = random.Random(0)
    by_usage, names, weights = collections.Counter(), [sp for sp in slots if ok(sp)], [slots[sp] for sp in slots if ok(sp)]
    dex = lambda sp: gd.species[sp]["dex"]  # noqa: E731
    while sum(by_usage.values()) < 20000:
        t = rng.choices(names, weights, k=3)
        if len({dex(sp) for sp in t}) == 3:
            by_usage[shapes.shape(t)] += 1
    pool = gd.meta(50, forms=True)
    draw = shaped_drawer(gd, pool, shapes=shapes)
    ours = collections.Counter(shapes.shape([b.species_id for b in draw(rng)]) for _ in range(3000))

    print(f"\nteam shapes (letters: one-on-one records over {len(ids)} Pokémon correlate {args.threshold} or more)")
    print(f"  {len(teams)} best-scoring teams listed, counted once:  {mix(listed)}")
    print(f"  the same, weighted by games played:   {mix(listed_games)}")
    print(f"  {len(bot_teams)} teams PvPoke's bots bring:          {mix(bot_mix)}")
    print(f"  random threes drawn by usage:          {mix(by_usage)}")
    print(f"  our shaped drawer (top 50 + forms):    {mix(ours)}")
    lt, rt = sum(listed_games.values()), sum(by_usage.values())
    print("  listed (by games) / random by usage:   " + " ".join(
        f"{s} {(listed_games[s] / lt) / max(by_usage[s] / rt, 1e-9):.2f}" for s in SHAPES))
    print("\nlisted teams by shape:")
    for team, games in sorted(teams, key=lambda x: -x[1]):
        print(f"  {shapes.shape(team)}  {games:4d} games  {' / '.join(team)}")


if __name__ == "__main__":
    main()
