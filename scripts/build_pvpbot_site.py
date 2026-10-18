#!/usr/bin/env python3
"""Build the in-browser line-up odds page for the owner's website (solaceonx.github.io/pokemon_go_pvpbot).

    python3 scripts/build_pvpbot_site.py OUT_FOLDER

Writes index.html and worker.js (scripts/pvpbot_site/), species.json (every supported Pokémon in the Great
League rankings, with names and sprite names for the page) and bundle.zip (the simulator's Python, the game data
and the trained model) to OUT_FOLDER. The page runs the simulator in the visitor's browser with Pyodide, so the
site needs no server. Rebuild and push after the model or the simulator changes.
"""
from __future__ import annotations

import json
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
from pogo.gamedata import GameData  # noqa: E402
from pogo.roster import builds  # noqa: E402

SOURCE = ROOT / "scripts" / "pvpbot_site"
MODULES = ["__init__", "agents", "arena", "battle", "gamedata", "learner", "lineup", "roster", "teamlist"]
DATA = ["gamemaster.json", "rankings-1500.json", "cpm.json", "matchups.json", "teams.json", "owner_team.json",
        "owner_roster.json", "PVPOKE_LICENSE"]


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    from play import sprite
    gd = GameData()
    species = []
    for entry in gd.rankings():
        sid = entry["speciesId"]
        if gd.supported(sid):
            b = gd.default(sid)
            species.append({"id": sid, "name": b.name, "dex": gd.species[sid]["dex"], "showdown": sprite(gd, b)["showdown"]})
    (out / "species.json").write_text(json.dumps({"species": species, "mine": list(builds(gd))[:3]}, separators=(",", ":")))
    with zipfile.ZipFile(out / "bundle.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for m in MODULES:
            z.write(ROOT / "pogo" / f"{m}.py", f"pogo/{m}.py")
        for name in DATA:
            z.write(ROOT / "data" / name, f"data/{name}")
        z.write(ROOT / "runs" / "general-decide" / "q.npz", "runs/general-decide/q.npz")
        z.write(SOURCE / "site_api.py", "site_api.py")
    for name in ("index.html", "worker.js"):
        shutil.copy(SOURCE / name, out / name)
    sizes = {p.name: p.stat().st_size for p in out.iterdir()}
    print(f"built {out}: " + ", ".join(f"{k} {v / 1024:.0f} KB" for k, v in sorted(sizes.items())))


if __name__ == "__main__":
    main()
