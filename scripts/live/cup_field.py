#!/usr/bin/env python3
"""A cup's field as we met it, for the engines' imagined opponents (POGO_FIELD in play_android.py): every species
seen in our own ranked battles of the cup and how often, and every team of three seen, from the battle logs.

    python3 scripts/live/cup_field.py data/fields/mega_catch_cup.json --season catch --league "Great League Edition"
        [--accounts owner spare]

The engines imagine the Pokémon of theirs not yet seen. By default they draw them from the open Great League top 50
(GameData.meta), but a cup has its own field: in the Mega Catch Cup (2026-11-24 to 26) Toxtricity, Tinkaton and Minior
were the commonest opponents, and the open top 50 holds a quarter of the opponents met (PvPoke's own "Catch Cup" is
a different cup and holds no more). The file lists the species seen (count) and the teams seen (weight = times met,
the format of data/teams.json, so Engine(unseen="teams") can imagine their bench from the real teams that hold the
ones seen so far), and for each species the moves the tracker knew at the end of the battles it was met in (the commonest
set: many cup Pokémon, Minior and the Megas among them, are not in the open rankings that give default moves). Trainer
names are never read: only the start row's league/season/account keys, the views' species and moves, and the end row.
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def battles(logs, season: str, league: str | None, accounts: list | None):
    """(stamp, account, their species in the order seen) of each finished ranked battle of the season: its start row
    names the season, or (older rows, no season read) the league."""
    for path in sorted(logs):
        rows = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
        start = next((r for r in rows if r["kind"] == "start"), {})
        end = next((r for r in rows if r["kind"] == "end"), {})
        named = season.lower() in str(start.get("season")).lower()
        if not end.get("foes") or not (named or (league and league.lower() in str(start.get("league")).lower())):
            continue
        if accounts and start.get("account") not in accounts:
            continue
        last = next((r["view"] for r in reversed(rows) if isinstance(r.get("view"), dict) and "foe_shown" in r["view"]), {})
        moves = {m["species"]: (m["fast"], tuple(m["charged"])) for m in last.get("foe_shown", []) if m.get("fast")}
        yield Path(path).stem, start.get("account"), list(end["foes"]), moves


def field(found) -> dict:
    species, teams, sets = collections.Counter(), collections.Counter(), collections.defaultdict(collections.Counter)
    n = 0
    for _, _, foes, moves in found:
        n += 1
        species.update(set(foes))
        for sp, mv in moves.items():
            sets[sp][mv] += 1
        if len(foes) == 3:
            teams[tuple(sorted(foes))] += 1
    return {"battles": n,
            "species": [[sp, k] for sp, k in species.most_common()],
            "teams": [{"team": list(t), "weight": k} for t, k in teams.most_common()],
            "moves": {sp: {"fast": c.most_common(1)[0][0][0], "charged": list(c.most_common(1)[0][0][1])}
                      for sp, c in sorted(sets.items())}}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--season", required=True, help="a word of the season as the start rows have it, e.g. catch")
    ap.add_argument("--league", help="or the league as the start rows have it, e.g. 'Great League Edition'")
    ap.add_argument("--accounts", nargs="*", help="only these accounts' battles (data/accounts keys)")
    ap.add_argument("--logs", default=str(ROOT / "runs" / "live"))
    a = ap.parse_args()
    found = list(battles(Path(a.logs).glob("2*.jsonl"), a.season, a.league, a.accounts))
    out = {"about": f"Opponents met in our ranked battles of the season matching '{a.season}' (or league '{a.league}')"
                    f"{' (accounts ' + ', '.join(a.accounts) + ')' if a.accounts else ''}, by scripts/live/cup_field.py; "
                    f"logs {found[0][0]} to {found[-1][0]}." if found else "none found",
           "min_seen": 2, **field(found)}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(f"{out['battles']} battles, {len(out['species'])} species, {len(out['teams'])} teams -> {a.out}")


if __name__ == "__main__":
    main()
