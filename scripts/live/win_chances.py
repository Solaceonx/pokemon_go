# The engine's own evaluation (runs/eval/eval.npz, 0-1, the value its searches end on) of each battle's positions:
# at the start (both full, lead against lead, two shields each), at each logged view, and its lowest and highest.
#   win_chances.py LOG.jsonl ...   -> one line per battle, then a summary per account
import json, sys, copy, collections
sys.path.insert(0, "scripts/live"); sys.path.insert(0, ".")
import engine_view as ev_mod
from pogo.evaluation import Evaluator
from pogo.gamedata import GameData

gd = GameData()
E = Evaluator.load("runs/eval/eval.npz")
out = []
for f in sys.argv[1:]:
    rows = [json.loads(l) for l in open(f)]
    s = next((r for r in rows if r["kind"] == "start"), {})
    e = next((r for r in rows if r["kind"] == "end"), {})
    if not e.get("result"):
        continue
    views = [(r["t"], r["view"]) for r in rows if isinstance(r.get("view"), dict) and "error" not in r["view"]]
    if not views:
        continue
    vals = []
    for t, rec in views:
        try:
            vals.append((t, E(ev_mod.LoggedView(gd, rec))))
        except Exception:
            pass
    # the start: everyone full, our lead against their first one seen
    rec = copy.deepcopy(views[0][1])
    v = ev_mod.LoggedView(gd, rec)
    for m in v.me.team:
        m.hp, m.energy, m.atk_stage, m.def_stage = m.build.hp, 0, 0, 0
    v.me.active, v.me.shields, v.me.switch_wait, v.me.busy = 0, 2, 0, 0
    lead = v.foe_shown[0]
    lead.hp, lead.energy, lead.atk_stage, lead.def_stage = lead.build.hp, 0, 0, 0
    v.foe, v.foe_shown, v.foe_left, v.foe_shields, v.foe_switch_wait, v.foe_busy, v.turn = lead, [lead], 3, 2, 0, 0, 0
    start = E(v)
    lo = min(vals, key=lambda x: x[1]); hi = max(vals, key=lambda x: x[1])
    out.append(dict(stamp=f.split("/")[-1][:15], account=s.get("account"), ranked=s.get("league") is not None,
                    result=e["result"], foes=e.get("foes"), start=start, first=vals[0][1], lo=lo, hi=hi,
                    last=vals[-1][1], n=len(vals)))
for o in out:
    print(f"{o['stamp']} {o['account']:5} {'GBL ' if o['ranked'] else 'trn '} {o['result']:4} start {o['start']:.2f} "
          f"low {o['lo'][1]:.2f}@{o['lo'][0]:.0f}s high {o['hi'][1]:.2f}@{o['hi'][0]:.0f}s last {o['last']:.2f} "
          f"({o['n']} views) {','.join(o['foes'] or [])}")
json.dump(out, open("/Users/lyxia/Projects/pokemon_go/.session_scratch/2026-11-24_mcc/win_chances.json", "w"))
