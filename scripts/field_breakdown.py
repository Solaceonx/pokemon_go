#!/usr/bin/env python3
"""Split an engine_versus.py run by whether a form-changing Pokémon was in the battle.

    python3 scripts/field_breakdown.py field-pvpoke [--species cramorant mimikyu]

The teams of every battle are drawn again from its battle number (the run's draw is the first use of each battle's
dice), so nothing extra had to be saved. Head to head (each pair played both ways, so team strength cancels): the
candidate's score in battles with and without the named Pokémon on either side. Against the crowd: the trained bot's
and the candidate's scores when the named Pokémon are on our side, on theirs, or on neither.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pogo.arena import mean_and_margin  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.teamlist import drawer  # noqa: E402


def line(label, values, unit="battles") -> str:
    if not values:
        return f"    {label:34s} no {unit}"
    m, h = mean_and_margin(values)
    return f"    {label:34s} {100 * m:5.1f}% ± {100 * h:4.1f}  ({len(values)} {unit})"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("tag")
    parser.add_argument("--species", nargs="+", default=["cramorant", "mimikyu"])
    args = parser.parse_args()
    saved = json.loads((ROOT / "runs" / "engine_versus" / f"{args.tag}.json").read_text())
    gd = GameData()
    if saved.get("field") == "pvpoke":
        from pogo.teamshape import pvpoke_field
        draw = pvpoke_field(gd)[1]
    else:
        draw = drawer(gd, gd.meta(50))
    seed, named = saved["seed"], set(args.species)
    teams = {}

    def teams_of(n: int):
        if n not in teams:
            rng = random.Random(seed * 1_000_003 + n)
            a, b = draw(rng), draw(rng)
            teams[n] = ({x.species_id for x in a} & named, {x.species_id for x in b} & named)
        return teams[n]

    res = saved["results"]
    print(f"{args.tag} (field {saved.get('field', 'standard')}), split by {', '.join(sorted(named))}")
    for spec, got in res.get("h2h", {}).items():
        print(f"  head to head, {spec or 'the confirmed engine'} against {saved['baseline']}:")
        with_, without = [], []
        for k, v in got.items():
            a, b = teams_of(int(k))
            (with_ if a or b else without).append(v)
        print(line("with one of them in the battle", with_, "pairings"))
        print(line("with neither", without, "pairings"))
    for spec, got in res.get("crowd", {}).items():
        print(f"  against the crowd, {spec or 'the confirmed engine'}:")
        ours, theirs, neither = [], [], []
        for k, v in got.items():
            a, b = teams_of(int(k))
            (ours if a and not b else theirs if b and not a else neither if not (a or b) else []).append(v)
        print(line("on our side only", ours))
        print(line("on their side only", theirs))
        print(line("on neither side", neither))


if __name__ == "__main__":
    main()
