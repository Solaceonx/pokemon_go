"""Every logged shield prompt of the live league battles: the live call, and the worth of shielding against taking
the hit by look-ahead, (a) blind, as the engine would search it, and (b) in hindsight, with the move they actually
threw landing. Run from the repository root: python3 scripts/live/shield_worth.py LOGDIR OUT.json [SEEDS]"""
import glob, json, random, sys
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts" / "live"))
from pogo.battle import CHARGED, damage  # noqa
from pogo.engine import Engine  # noqa
from pogo.evaluation import Evaluator  # noqa
from pogo.gamedata import GameData  # noqa
from pogo.learner import QNet  # noqa
from pogo.realtime import WEBSITE  # noqa
from engine_view import LoggedView, build_mon  # noqa

logdir, out = sys.argv[1], sys.argv[2]
seeds = int(sys.argv[3]) if len(sys.argv) > 3 else 48
gd = GameData()
ev = Evaluator.load(ROOT / "runs" / "eval" / "eval.npz")
q = QNet.load(str(ROOT / "runs" / "general-decide" / "q.npz"))
meta = gd.meta(50)


def engine(seed):
    return Engine(Evaluator(ev.model), meta, q=q, seed=seed, heads=("throw", "swap", "mid_swap", "replace", "shield"),
                  **WEBSITE)


def worth(view, foe_hi, move_id=None):
    e = engine(1)
    e._foe_energy = foe_hi
    if move_id is not None:
        ids = [m.id for m in view.foe.build.charged]
        e.mix_shield = True
        e._their_first = CHARGED[ids.index(move_id)]
    tot = [0.0, 0.0]
    for s in range(seeds):
        for k in (0, 1):
            tot[k] += e._look(view, "shield", k, 1000 + s)
    return [t / seeds for t in tot]


rows_out = []
for f in sorted(glob.glob(f"{logdir}/*/log.jsonl")):
    rows = [json.loads(l) for l in open(f)]
    start = next((r for r in rows if r["kind"] == "start"), {})
    if "League" not in str(start.get("league")):
        continue
    result = next((r.get("result") for r in rows if r["kind"] == "end"), None)
    for i, r in enumerate(rows):
        if r["kind"] != "shield_prompt" or "view" not in r or "error" in (r["view"] or {}):
            continue
        rec = r["view"]
        view = LoggedView(gd, rec)
        if view.me.shields == 0:
            continue
        nxt = next((x for x in rows[i + 1:] if x["kind"] == "their_charged_named" and x["t"] - r["t"] < 12), None)
        move = nxt["move"] if nxt else None
        known = move in [m.id for m in view.foe.build.charged] if move else None
        if move and not known:  # a move the tracker did not have for them: put it in, in place of the second
            fr = dict(rec["foe"]); ch = list(fr["charged"])
            ch[-1 if len(ch) > 1 else 0] = move
            fr["charged"] = ch
            rec2 = dict(rec); rec2["foe"] = fr
            rec2["foe_shown"] = [fr if (m["species"], m["hp"]) == (rec["foe"]["species"], rec["foe"]["hp"]) else m
                                 for m in rec["foe_shown"]]
            hview = LoggedView(gd, rec2)
        else:
            hview = view
        foe_hi = r.get("foe_hi") if r.get("foe_hi") is not None else view.foe.energy
        me = view.me.mon
        blind = worth(view, foe_hi)
        hind = worth(hview, max(foe_hi, next((m.energy for m in hview.foe.build.charged if m.id == move), 0)), move) if move else None
        dmg = damage(hview.foe, next(m for m in hview.foe.build.charged if m.id == move), me) if move else None
        live_q = bool(Engine(Evaluator(ev.model), meta, q=q, seed=2, **WEBSITE).shield(view, foe_hi))  # the trained network, as live
        rows_out.append({"battle": Path(f).parent.name, "result": result, "t": r["t"], "live": r["shield"],
                         "net": live_q, "me": me.build.species_id, "hp": me.hp, "hp_max": me.build.hp,
                         "foe": view.foe.build.species_id, "foe_hi": foe_hi, "shields": [view.me.shields, view.foe_shields],
                         "left": [view.me.left(), view.foe_left], "move": move, "known": known,
                         "move_hp": None if dmg is None else round(dmg / me.hp, 2),
                         "blind": [round(x, 3) for x in blind], "hind": None if hind is None else [round(x, 3) for x in hind]})
        print(json.dumps(rows_out[-1]), flush=True)
json.dump(rows_out, open(out, "w"), indent=0)
