#!/usr/bin/env python3
"""Each live GO Battle League battle's line-up odds (task 45): our chance of winning from the two line-ups alone,
two equally good bots playing them, kept in games/live/odds.json and copied into games/live/index.json.

    nice python3 scripts/live/odds.py            every league battle not done yet (saves after each)
    nice python3 scripts/live/odds.py --redo     all of them again

The method (as used for docs/status.md on 2026-11-08, "All the league battles to the evening"):
- our team as recorded (teams.mine, lead first), at its level and IVs where our_teams.json has them, else PvPoke's
  default level and IVs for the league; theirs as seen, at PvPoke's default builds (Darmanitan as
  darmanitan_standard, the only Great League build; a Mega with its base form's ranked moves at PvPoke's default
  level and IVs; another species with no build: the battle is left out);
- pogo.lineup.win_chance with the trained bot runs/general-decide/q.npz on both sides, pool gd.meta(50), 300
  battles, seed 7;
- a Pokémon of theirs not seen is filled at random from PvPoke's Great League ranks 101 to 400: 6 draws of 50
  battles (seeds 7 to 12), averaged.
A battle is redone when its inputs (our team, theirs seen, the method) change. One NumPy thread.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import sys
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "live"))

GAMES = ROOT / "games" / "live"
METHOD = ("win_chance q=runs/general-decide/q.npz pool=meta(50) battles=300 seed=7; unseen: ranks 101-400, 6 x 50; "
          "Megas with the base form's ranked moves")
BUILD_AS = {"darmanitan": "darmanitan_standard", "darmanitan_galarian_zen": "darmanitan_standard",
            "darmanitan_zen": "darmanitan_standard"}


def builds(gd, rec, teams):
    """(ours, theirs seen, a reason if the battle cannot be played)."""
    stats = (teams.get(rec["source"].get("team")) or {}).get("pokemon", [])
    ours = []
    for p in rec["teams"]["mine"]:
        moves = [p["fast_move"]["id"]] + [c["id"] for c in p["charged_moves"]]
        entry = next((e for e in stats if e["species"] == p["species"]), {})
        kw = {}
        if entry.get("level") is not None and entry.get("ivs") is not None:
            kw = {"level": entry["level"], "ivs": tuple(entry["ivs"])}
        ours.append(gd.build(p["species"], moves, **kw))
    start = next((a for a in rec["actions"] if a["kind"] == "start"), None)
    lead = start["mine"] if start else None
    ours.sort(key=lambda b: b.species_id != lead)  # the lead first, the rest in team order
    theirs = []
    for p in rec["teams"]["theirs"]:
        sid = BUILD_AS.get(p["species"], p["species"])
        try:
            theirs.append(gd.default(sid))
            continue
        except Exception as error:  # noqa: BLE001
            why = f"no Great League build for {p['species']} ({error})"
        mega = mega_build(gd, sid)
        if mega is None:
            return ours, theirs, why
        theirs.append(mega)
    return ours, theirs, None


def mega_build(gd, sid):
    """A Mega (allowed in the Mega Edition cups, not in PvPoke's Great League ranks) with its base form's ranked
    moves (a Mega keeps them) at PvPoke's default level and IVs; None for anything else."""
    if "_mega" not in sid:
        return None
    base = sid.split("_mega")[0]
    entry = next((e for e in gd.rankings() if e["speciesId"] == base), None)
    if entry is None or sid not in gd.species:
        return None
    return gd.build(sid, entry["moveset"])


def key(ours, theirs) -> str:
    text = json.dumps([[b.species_id, b.fast.id, [m.id for m in b.charged], b.level, b.ivs] for b in ours]
                      + [[b.species_id] for b in theirs] + [METHOD], default=str)
    return hashlib.sha1(text.encode()).hexdigest()[:12]


def main(argv) -> int:
    from pogo.gamedata import GameData
    from pogo.learner import QNet
    from pogo.lineup import win_chance
    import live_record

    gd = GameData()
    net = QNet.load(ROOT / "runs" / "general-decide" / "q.npz")
    pool = gd.meta(50)
    ranks = gd.rankings()
    filler = [e["speciesId"] for e in ranks[100:400]]
    teams = live_record.read_json("our_teams.json")
    path = GAMES / "odds.json"
    odds = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    for game in sorted(GAMES.glob("*/game.json")):
        rec = json.loads(game.read_text(encoding="utf-8"))
        stamp = game.parent.name
        if rec["source"]["mode"] != "league" or rec["result"]["value"] == "fragment":
            continue
        ours, theirs, why = builds(gd, rec, teams)
        if why:
            odds[stamp] = {"chance": None, "why_none": why, "method": METHOD}
            print(stamp, why, flush=True)
            continue
        k = key(ours, theirs)
        if "--redo" not in argv and (odds.get(stamp) or {}).get("inputs") == k:
            continue
        if len(theirs) >= 3:
            chance, margin = win_chance(net, pool, ours, theirs[:3], battles=300, seed=7)
            draws = 0
        else:
            parts = []
            for d in range(6):
                rng = random.Random(7 + d)
                fill = []
                while len(theirs) + len(fill) < 3:
                    sid = rng.choice(filler)
                    if sid in {b.species_id for b in theirs + fill} or not gd.supported(sid):
                        continue
                    try:
                        fill.append(gd.default(sid))
                    except Exception:  # noqa: BLE001
                        continue
                parts.append(win_chance(net, pool, ours, theirs + fill, battles=50, seed=7 + d))
            chance = sum(c for c, _ in parts) / len(parts)
            margin = (sum(m * m for _, m in parts) ** 0.5) / len(parts)
            draws = 6
        odds[stamp] = {"chance": round(chance, 3), "margin": round(margin, 3), "theirs_seen": [b.species_id for b in theirs],
                       "filled_draws": draws, "inputs": k, "method": METHOD}
        print(stamp, rec["result"]["value"], odds[stamp]["chance"], "+-", odds[stamp]["margin"], flush=True)
        path.write_text(json.dumps(dict(sorted(odds.items())), indent=1), encoding="utf-8")  # as it goes
    path.write_text(json.dumps(dict(sorted(odds.items())), indent=1), encoding="utf-8")
    live_record.write_index()
    done = [v for v in odds.values() if v.get("chance") is not None]
    print(f"{len(done)} league battles with odds; {sum(v['chance'] for v in done):.1f} expected wins")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
