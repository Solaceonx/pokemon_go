"""The owner's own Pokémon as told to us: moves, IVs and level."""
from __future__ import annotations

import json
from pathlib import Path

from .gamedata import GameData

DATA = Path(__file__).resolve().parent.parent / "data"
TEAM, OTHERS = DATA / "owner_team.json", DATA / "owner_roster.json"


def builds(gd: GameData, files=(TEAM, OTHERS)) -> dict:
    """{species id: Build} for every Pokémon listed in the files.

    Moves not given are the usual ones. With IVs, the level is the one whose CP is nearest
    the CP given, or without a CP the highest the league allows; without IVs, the usual spread.
    """
    ids = {v["speciesName"]: k for k, v in gd.species.items()}
    moves = {m.name: m.id for m in gd.moves.values()}
    out = {}
    for path in files:
        if not Path(path).exists():
            continue
        for e in json.loads(Path(path).read_text())["pokemon"]:
            sid = ids[e["species"]]
            usual = gd.default(sid)
            moveset = [moves[e["fast"]] if e.get("fast") else usual.fast.id,
                       *([moves[c] for c in e["charged"]] if e.get("charged") else [m.id for m in usual.charged])]
            ivs, level = tuple(e["ivs"]) if e.get("ivs") else None, None
            if ivs and e.get("cp"):
                level = min((1 + i / 2 for i in range(100)), key=lambda lv: (abs(gd.cp_at(sid, lv, ivs) - e["cp"]), -lv))
            elif ivs:
                level = gd.level_for(sid, ivs)
            out[sid] = gd.build(sid, moveset, level=level, ivs=ivs)
    return out
