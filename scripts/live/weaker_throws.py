"""Every logged charged-move throw of the live league battles: each of our charged moves' damage on the view, which
were paid for, and the fast moves still needed for the others; flags throws where a knock-out or a hit twice as
big was paid for or one or two fast moves away; asks the engine (task 47's evaluation) again on those views.
Run from the repository root: python3 scripts/live/weaker_throws.py LOGDIR OUT.json [ASKS]"""
import collections, glob, json, math, sys, time
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts" / "live"))
from pogo.battle import CHARGED, FAST, damage  # noqa
from pogo.evaluation import Evaluator  # noqa
from pogo.gamedata import GameData  # noqa
from pogo.learner import QNet  # noqa
from pogo.realtime import WEBSITE, RealTime  # noqa
from engine_view import LoggedView, name  # noqa

logdir, out = sys.argv[1], sys.argv[2]
asks = int(sys.argv[3]) if len(sys.argv) > 3 else 4
gd = GameData()
ev = Evaluator.load(ROOT / "runs" / "eval" / "eval.npz")
q = QNet.load(str(ROOT / "runs" / "general-decide" / "q.npz"))
meta = gd.meta(50)


def fresh(seed):
    return RealTime(Evaluator(ev.model), meta, q=q, seed=seed, **WEBSITE, turn_ms=500, cap_ms=300, clock=time.perf_counter)


res = []
for f in sorted(glob.glob(f"{logdir}/*/log.jsonl")):
    rows = [json.loads(l) for l in open(f)]
    start = next((r for r in rows if r["kind"] == "start"), {})
    if "League" not in str(start.get("league")):
        continue
    result = next((r.get("result") for r in rows if r["kind"] == "end"), None)
    for r in rows:
        if "view" not in r or r["kind"] == "shield_prompt" or "error" in (r["view"] or {}):
            continue
        act = r.get("action") or ("charged:" + r.get("move", "?"))
        if not act.startswith("charged:"):
            continue
        view = LoggedView(gd, r["view"])
        me, foe = view.me.mon, view.foe
        thrown = act.split(":")[1]
        moves = {m.id: m for m in me.build.charged}
        if thrown not in moves:
            continue
        gain = me.build.fast.energy_gain
        info = {}
        for mid, m in moves.items():
            d = damage(me, m, foe)
            need = max(0, math.ceil((m.energy - me.energy) / gain)) if me.energy < m.energy else 0
            info[mid] = {"dmg": d, "ko": d >= foe.hp, "fasts_needed": need, "cost": m.energy}
        t = info[thrown]
        flag = None
        for mid, x in info.items():
            if mid == thrown:
                continue
            better = (x["ko"] and not t["ko"]) or x["dmg"] >= 2 * max(1, t["dmg"])
            if better and x["fasts_needed"] == 0:
                flag = f"{mid} paid for and {'knocks out' if x['ko'] else 'twice the damage'}"
            elif better and x["fasts_needed"] <= 2 and view.foe_shields == 0:
                flag = flag or f"{mid} {x['fasts_needed']} fast move(s) away and {'knocks out' if x['ko'] else 'twice the damage'}"
        row = {"battle": Path(f).parent.name, "result": result, "t": r["t"], "kind": r["kind"], "thrown": thrown,
               "me": me.build.species_id, "energy": me.energy, "foe": foe.build.species_id, "foe_hp": foe.hp,
               "foe_shields": view.foe_shields, "info": info, "flag": flag}
        if flag:
            row["engine_now"] = dict(collections.Counter(name(view, fresh(s).act(view)) for s in range(asks)))
            print(json.dumps(row), flush=True)
        res.append(row)
json.dump(res, open(out, "w"), indent=0)
print("throws", len(res), "flagged", sum(1 for x in res if x["flag"]))
