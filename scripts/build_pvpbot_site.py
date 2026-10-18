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
MODULES = ["__init__", "agents", "arena", "battle", "gamedata", "learner", "lineup", "roster", "teamlist",
           "engine", "evaluation", "realtime", "value"]
DATA = ["gamemaster.json", "rankings-1500.json", "cpm.json", "matchups.json", "teams.json", "owner_team.json",
        "owner_roster.json", "PVPOKE_LICENSE"]


def play_page() -> str:
    """play.html: the setup screen and controller (scripts/pvpbot_site/) around the battle screen of scripts/play.py's page."""
    page = (ROOT / "scripts" / "play" / "index.html").read_text()
    style = page[page.index("<style>") + len("<style>"):page.index("</style>")]
    body = page[page.index('<div class="phone">'):page.index("<script>")]
    script = page[page.index("<script>") + len("<script>"):page.rindex("</script>")]
    script = script[:script.rindex("poll();")]  # the server's polling: the controller drives the screen instead
    old_row = '<div class="row"><button class="big go" onclick="newBattle()">New battle</button></div>'
    if old_row not in body:
        raise SystemExit("scripts/play/index.html changed: the end-of-battle buttons were not found")
    body = body.replace(old_row, '<textarea id="notes" placeholder="Notes on this game: what went right or wrong, what the bot did"></textarea>'
                        '<div class="row"><button class="big go" onclick="newBattle()">Play again</button>'
                        '<button class="big no" onclick="changeTeams()">Change teams</button></div>')
    return ("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n<title>Battle the Bot</title>\n"
            f"<style>{style}</style>\n</head>\n<body>\n{(SOURCE / 'play_setup.html').read_text()}\n"
            f"<div id=\"game\" style=\"display:none; width:100%; justify-content:center\">\n{body}</div>\n"
            f"<script>{script}</script>\n<script>\n{(SOURCE / 'play_controller.js').read_text()}</script>\n</body>\n</html>\n")


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
        if any(m in gd.moves for m in entry["moveset"][:1]):
            b = gd.default(sid)
            species.append({"id": sid, "name": b.name, "dex": gd.species[sid]["dex"], "showdown": sprite(gd, b)["showdown"]})
    listed = sorted(json.loads((ROOT / "data" / "teams.json").read_text())["teams"], key=lambda e: -e["score"])[:30]
    top = [{"team": e["team"], "score": e["score"]} for e in listed]
    (out / "species.json").write_text(json.dumps({"species": species, "mine": list(builds(gd))[:3], "top": top}, separators=(",", ":")))
    with zipfile.ZipFile(out / "bundle.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for m in MODULES:
            z.write(ROOT / "pogo" / f"{m}.py", f"pogo/{m}.py")
        for name in DATA:
            z.write(ROOT / "data" / name, f"data/{name}")
        z.write(ROOT / "runs" / "general-decide" / "q.npz", "runs/general-decide/q.npz")
        z.write(ROOT / "runs" / "eval" / "eval.npz", "runs/eval/eval.npz")
        z.write(SOURCE / "site_api.py", "site_api.py")
        z.write(SOURCE / "play_api.py", "play_api.py")
    for name in ("index.html", "worker.js", "play_worker.js"):
        shutil.copy(SOURCE / name, out / name)
    (out / "play.html").write_text(play_page())
    sizes = {p.name: p.stat().st_size for p in out.iterdir()}
    print(f"built {out}: " + ", ".join(f"{k} {v / 1024:.0f} KB" for k, v in sorted(sizes.items())))


if __name__ == "__main__":
    main()
