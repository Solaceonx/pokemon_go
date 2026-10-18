#!/usr/bin/env python3
"""A page on this computer for checking win chances: your three against any three.

    python3 scripts/lineup_site.py [--port 8767] [--battles 150] [--workers 3]

Then open http://localhost:8767 (it opens by itself). Pick both teams; it shows the chance that yours wins with
both sides played by the trained bot with shifted habits (pogo.lineup), for every choice of your lead against
every choice of theirs, since nobody sees the other's lead before the battle. Your Pokémon use your own IVs and
moves where data/owner_team.json or data/owner_roster.json has them; theirs, PvPoke's usual ones. Each cell is
--battles battles; the nine cells run on --workers cores at once and take a few seconds.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_v] = "1"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pogo.gamedata import GameData  # noqa: E402
from pogo.learner import QNet  # noqa: E402
from pogo.lineup import win_chance  # noqa: E402
from pogo.roster import builds  # noqa: E402

_state: dict = {}


def setup() -> None:
    os.nice(10)
    gd = GameData()
    _state.update(gd=gd, pool=gd.meta(50), net=QNet.load(str(ROOT / "runs" / "general-decide" / "q.npz")), owned=builds(gd))


def team_builds(species: list, ours: bool, use_owned: bool) -> list:
    s = _state
    return [(s["owned"].get(sid) if ours and use_owned else None) or s["gd"].default(sid) for sid in species]


def cell(job):
    mine, theirs, use_owned, battles, seed = job
    chance, margin = win_chance(_state["net"], _state["pool"], team_builds(mine, True, use_owned),
                                team_builds(theirs, False, False), battles, seed)
    return mine[0], theirs[0], chance, margin


def rotations(team: list) -> list:
    return [[team[k]] + [sid for j, sid in enumerate(team) if j != k] for k in range(3)]


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Line-up Odds</title>
<style>
:root { --bg: #0e141b; --panel: #16202b; --text: #e6edf3; --dim: #93a3b3; --line: #2a3a4a; --good: #3ddc97; --bad: #f0544f; --accent: #5ab0ff; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); font: 15px/1.45 -apple-system, system-ui, sans-serif; }
main { max-width: 760px; margin: 0 auto; padding: 24px 16px 48px; }
h1 { font-size: 22px; margin: 0 0 4px; } .sub { color: var(--dim); margin: 0 0 20px; font-size: 13px; }
.teams { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
@media (max-width: 560px) { .teams { grid-template-columns: 1fr; } }
.side { background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 14px; }
.side h2 { font-size: 14px; margin: 0 0 10px; color: var(--dim); font-weight: 600; text-transform: uppercase; letter-spacing: .04em; }
.slot { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.slot img { width: 40px; height: 40px; image-rendering: pixelated; flex: none; }
.slot input { flex: 1; min-width: 0; background: var(--bg); color: var(--text); border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; font: inherit; }
.slot input.bad { border-color: var(--bad); }
.slot .n { color: var(--dim); font-size: 12px; width: 34px; flex: none; }
label.own { font-size: 13px; color: var(--dim); display: flex; gap: 6px; align-items: center; margin-top: 4px; }
.go { margin: 16px 0; display: flex; gap: 12px; align-items: center; }
button { background: var(--accent); color: #06121e; border: 0; border-radius: 10px; padding: 10px 18px; font: 600 15px system-ui; cursor: pointer; }
button:disabled { opacity: .5; cursor: wait; }
#status { color: var(--dim); font-size: 13px; }
.result { background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 16px; }
.big { font-size: 40px; font-weight: 700; font-variant-numeric: tabular-nums; } .big small { font-size: 16px; color: var(--dim); font-weight: 400; }
table { width: 100%; border-collapse: collapse; margin-top: 12px; font-variant-numeric: tabular-nums; }
th, td { padding: 8px 6px; text-align: center; border-bottom: 1px solid var(--line); font-size: 14px; }
th { color: var(--dim); font-weight: 600; } td.row { text-align: left; color: var(--dim); }
.note { color: var(--dim); font-size: 12px; margin-top: 12px; }
</style></head><body><main>
<h1>Line-up odds</h1>
<p class="sub">Your three against any three, played out by the trained bot on both sides. Lead first.</p>
<datalist id="species"></datalist>
<div class="teams">
  <div class="side"><h2>Your team</h2><div id="mine"></div>
    <label class="own"><input type="checkbox" id="owned" checked> use my own IVs and moves where I have them</label></div>
  <div class="side"><h2>Their team</h2><div id="theirs"></div></div>
</div>
<div class="go"><button id="run">Work it out</button><span id="status"></span></div>
<div id="out"></div>
<script>
const $ = (id) => document.getElementById(id);
let SPECIES = [], BY_NAME = {}, BY_ID = {};
function slots(box, values) {
  $(box).innerHTML = values.map((v, i) => `<div class="slot"><span class="n">${i ? "back" : "lead"}</span><img alt="">
    <input list="species" value="${v}" autocomplete="off" spellcheck="false"></div>`).join("");
  $(box).querySelectorAll("input").forEach((inp) => { inp.addEventListener("input", () => look(inp)); look(inp); });
}
function find(text) { const t = text.trim().toLowerCase(); return BY_NAME[t] || BY_ID[t] || null; }
function look(inp) {
  const sp = find(inp.value), img = inp.parentElement.querySelector("img");
  inp.classList.toggle("bad", !sp && inp.value.trim() !== "");
  img.src = sp ? `https://play.pokemonshowdown.com/sprites/gen5/${sp.showdown}.png` : "";
  img.style.visibility = sp ? "visible" : "hidden";
}
function team(box) { return [...$(box).querySelectorAll("input")].map((i) => find(i.value)); }
async function start() {
  const info = await (await fetch("/api/species")).json();
  SPECIES = info.species;
  for (const s of SPECIES) { BY_NAME[s.name.toLowerCase()] = s; BY_ID[s.id] = s; }
  $("species").innerHTML = SPECIES.map((s) => `<option value="${s.name}">`).join("");
  slots("mine", info.mine.map((id) => BY_ID[id] ? BY_ID[id].name : id));
  slots("theirs", ["Corviknight", "Tinkaton", "Mandibuzz"]);
}
function pct(x) { return Math.round(100 * x) + "%"; }
function colour(x) { return x >= 0.5 ? `color: var(--good)` : `color: var(--bad)`; }
$("run").onclick = async () => {
  const mine = team("mine"), theirs = team("theirs");
  if (mine.includes(null) || theirs.includes(null)) { $("status").textContent = "Pick three known Pokémon on each side."; return; }
  if (new Set(mine.map((s) => s.dex)).size < 3 || new Set(theirs.map((s) => s.dex)).size < 3) { $("status").textContent = "A team cannot have the same species twice."; return; }
  $("run").disabled = true; $("status").textContent = "Playing it out…";
  try {
    const r = await (await fetch("/api/odds", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mine: mine.map((s) => s.id), theirs: theirs.map((s) => s.id), owned: $("owned").checked }) })).json();
    const name = (id) => BY_ID[id].name;
    const head = `<tr><th></th>${r.theirs_leads.map((id) => `<th>they lead ${name(id)}</th>`).join("")}<th>average</th></tr>`;
    const rows = r.mine_leads.map((a, i) => {
      const cells = r.grid[i].map((c) => `<td style="${colour(c[0])}">${pct(c[0])}</td>`).join("");
      const avg = r.grid[i].reduce((t, c) => t + c[0], 0) / 3;
      return `<tr><td class="row">you lead ${name(a)}</td>${cells}<td style="${colour(avg)}"><b>${pct(avg)}</b></td></tr>`;
    }).join("");
    const main = r.grid[0][0];
    $("out").innerHTML = `<div class="result"><div class="big">${pct(main[0])} <small>± ${pct(main[1])} with both leads as entered</small></div>
      <table>${head}${rows}</table>
      <div class="note">${r.battles} battles a cell (± about ${pct(r.margin)}). Both sides are the trained bot with its habits shifted a little each
      battle, so this is how the two teams do between equally good players, not a promise about any one game. Form-changing
      Pokémon (Aegislash, Mimikyu, Cramorant, Morpeko) are not in the list: the simulator cannot play them.</div></div>`;
    $("status").textContent = `Done in ${r.seconds}s.`;
  } catch (e) { $("status").textContent = "Something went wrong: " + e; }
  $("run").disabled = false;
};
start();
</script></main></body></html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--battles", type=int, default=150, help="battles for each lead against each lead")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT / "scripts"))
    from play import sprite
    import time
    gd = GameData()
    owned = builds(gd)
    species = []
    for entry in gd.rankings():
        sid = entry["speciesId"]
        if gd.supported(sid):
            b = gd.default(sid)
            species.append({"id": sid, "name": b.name, "dex": gd.species[sid]["dex"], "showdown": sprite(gd, b)["showdown"]})
    mine_default = list(owned)[:3]  # the owner's current three, as in data/owner_team.json
    workers = multiprocessing.get_context("spawn").Pool(args.workers, initializer=setup)
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, body: bytes, kind: str = "application/json") -> None:
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/api/species":
                self.send(json.dumps({"species": species, "mine": mine_default}).encode())
            else:
                self.send(PAGE.encode(), "text/html; charset=utf-8")

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            known = {s["id"] for s in species}
            mine, theirs = body.get("mine", []), body.get("theirs", [])
            if len(mine) != 3 or len(theirs) != 3 or not set(mine + theirs) <= known:
                self.send(json.dumps({"error": "three known Pokémon a side"}).encode())
                return
            t0 = time.time()
            ours, foes = rotations(mine), rotations(theirs)
            jobs = [(a, b, bool(body.get("owned", True)), args.battles, 7) for a in ours for b in foes]
            with lock:  # one calculation at a time
                got = {(m, t): (c, h) for m, t, c, h in workers.map(cell, jobs)}
            grid = [[[round(v, 3) for v in got[(a[0], b[0])]] for b in foes] for a in ours]
            margin = max(h for row in grid for _, h in row)
            self.send(json.dumps({"mine_leads": [a[0] for a in ours], "theirs_leads": [b[0] for b in foes], "grid": grid,
                                  "battles": args.battles, "margin": margin, "seconds": round(time.time() - t0, 1)}).encode())

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://localhost:{args.port}"
    print(f"line-up odds at {url} (Ctrl-C to stop)", flush=True)
    if not args.no_browser:
        threading.Timer(0.5, webbrowser.open, (url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        workers.terminate()


if __name__ == "__main__":
    main()
