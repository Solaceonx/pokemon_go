#!/usr/bin/env python3
"""Play a logged live position out to the end, many times, for each first action of ours (task 40): which choice
actually wins more in the simulator, against what the engine picked there (scripts/live/engine_view.py).

    python3 scripts/live/play_out.py LOG T N [THEIR_MOVES|-] [THEIR_TEAM]

LOG: a log with views (runs/live/STAMP.jsonl or a replay's); T: the battle time of the view (within 0.03 s);
N: battles per option per opponent style. THEIR_MOVES (e.g. BUBBLE,ICE_BEAM,HYDRO_PUMP) sets their active
Pokemon's moves; THEIR_TEAM (e.g. whiscash,altaria) their unseen ones, else drawn from the top 50.

After the first action our side, and theirs throughout, are played by the trained bot (as inside the engine's
look-ahead), their style drawn round pogo.engine.STYLES. Every option gets the same dice. Prints, per option, the
share won with its 95% margin, the share weighted by the styles' weights, the paired difference from a fast move,
decisiveness (pogo.arena.decisive) and the share won per style.
"""
from __future__ import annotations

import collections
import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts" / "live"))
from engine_view import LoggedView, name  # noqa: E402
from pogo.arena import decisive  # noqa: E402
from pogo.battle import Mon  # noqa: E402
from pogo.engine import STYLES, _First, imagine, style_player  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.learner import Learner, QNet  # noqa: E402


def main() -> None:
    log, at, n = sys.argv[1], float(sys.argv[2]), int(sys.argv[3])
    moves = sys.argv[4].split(",") if len(sys.argv) > 4 and sys.argv[4] != "-" else None
    team = sys.argv[5].split(",") if len(sys.argv) > 5 else None
    gd = GameData()
    q = QNet.load(str(ROOT / "runs" / "general-decide" / "q.npz"))
    pool = gd.meta(50)
    rows = (json.loads(line) for line in open(log, encoding="utf-8") if line.strip())
    rec = next(r["view"] for r in rows if r.get("view") and "me" in r["view"] and abs(r["t"] - at) < 0.03)
    view = LoggedView(gd, rec)
    if moves:
        f = view.foe
        m = Mon(gd.build(rec["foe"]["species"], moves, level=rec["foe"]["level"], ivs=tuple(rec["foe"]["ivs"])),
                hp=f.hp, energy=f.energy)
        view.foe_shown = [m if x is f else x for x in view.foe_shown]
        view.foe = m
    teams = [(1.0, [view.foe.build.species_id] + team)] if team else None
    me, foe = view.me.mon, view.foe
    print(f"{me.build.species_id} {me.hp}/{me.build.hp}hp {me.energy}e vs {foe.build.species_id} {foe.hp}/{foe.build.hp}hp"
          f" {foe.energy}e {[x.id for x in foe.build.charged]}; shields {view.me.shields}-{view.foe_shields}; ours"
          f" {[(x.build.species_id, x.hp) for x in view.me.team]}; their unseen from"
          f" {'the team ' + str(team) if team else 'the top 50'}")
    options, styles = view.legal(), list(STYLES)
    won = collections.defaultdict(list)
    t0 = time.time()
    for k in range(n):
        for style in styles:
            seed = random.Random(f"{k}-{style}").getrandbits(32)
            for opt in options:
                rng = random.Random(seed)
                us = Learner(q=q, margin=0.02, seed=rng.getrandbits(32))
                them = style_player(style, rng, q, 0.02, pool)
                battle = imagine(view, rng, pool, _First(us, opt), them, teams=teams)
                battle.run()
                won[(name(view, opt), style)].append((battle.winner == 0, decisive(battle, 0)))
    print(f"{n} battles per option per style, {time.time() - t0:.0f} s")
    weight = {s: STYLES[s]["weight"] for s in styles}
    base = [w for s in styles for w, _ in won[("fast", s)]]
    for opt in options:
        o = name(view, opt)
        every = [x for s in styles for x in won[(o, s)]]
        wins = [w for w, _ in every]
        p = sum(wins) / len(wins)
        share = {s: sum(w for w, _ in won[(o, s)]) / len(won[(o, s)]) for s in styles}
        mix = sum(weight[s] * share[s] for s in styles) / sum(weight.values())
        diff = [a - b for a, b in zip(wins, base)]
        md = sum(diff) / len(diff)
        sd = (sum((d - md) ** 2 for d in diff) / max(1, len(diff) - 1)) ** 0.5
        print(f"{o:<22} won {p:.1%} ±{1.96 * (p * (1 - p) / len(wins)) ** 0.5:.1%} (styles weighted {mix:.1%});"
              f" against fast {md:+.1%} ±{1.96 * sd / len(diff) ** 0.5:.1%}; decisive {sum(d for _, d in every) / len(every):.3f};"
              f" " + ", ".join(f"{s} {share[s]:.0%}" for s in styles))


if __name__ == "__main__":
    main()
