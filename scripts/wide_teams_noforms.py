"""A second final for scripts/wide_teams.py: its 15 best shortlisted teams without form-changing Pokémon (the bot was never
trained with them), 1,000 fresh battles per lead on seed 2. Writes runs/wide-teams/noforms.out."""
import json, sys, time
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
import wide_teams as W
from multiprocessing import Pool
from pogo.gamedata import GameData
if __name__ == "__main__":
    gd = GameData(); rank = {e["speciesId"]: r + 1 for r, e in enumerate(gd.rankings())}
    r = json.loads((W.OUT / "result.json").read_text())
    plain = [(k, v) for k, v in r["shortlist"].items() if all(gd.supported(s) for s in k.split("/"))]
    plain.sort(key=lambda kv: -kv[1][0])
    top = [k for k, _ in plain[:15]]
    orders = {f"{k}|{lead}": [lead] + [s for s in k.split("/") if s != lead] for k in top for lead in k.split("/")}
    t0 = time.time()
    with Pool(3, W._init, (300, str(W.OUT / "matchups.json"))) as runner:
        final = W.score(runner, orders, 1000, 2)
    rows = []
    for k in top:
        leads = sorted(((final[f"{k}|{ld}"], ld) for ld in k.split("/")), key=lambda x: -x[0][0])
        rows.append((leads[0][0], leads[0][1], k, leads, dict(plain)[k]))
    rows.sort(key=lambda x: -x[0][0])
    out = []
    for (p, m), lead, k, leads, sl in rows:
        team = [lead] + [s for s in k.split("/") if s != lead]
        line = f"{100*p:5.1f}% ± {100*m:.1f}  " + " / ".join(f"{s} (#{rank.get(s)})" for s in team) + "   other leads " + ", ".join(f"{ld} {100*v[0]:.0f}%" for v, ld in leads[1:]) + f"   (shortlist {100*sl[0]:.0f}%)"
        print(line); out.append(line)
    (W.OUT / "noforms.out").write_text(f"15 best teams without form-changers from the shortlist, 1000 fresh battles per lead, seed 2 ({time.time()-t0:.0f}s)\n" + "\n".join(out) + "\n")
