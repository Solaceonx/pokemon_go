# A set's battles at a glance, with the likely mistakes flagged: set_review.py LOG.jsonl ...
#   weak throw: a charged move thrown into no shields when another of ours does twice the damage
#   unshielded knock-out: a shield prompt not shielded, shields left, their paid-for move knocking us out
#   fainted with a move paid for
import collections, json, sys, types
sys.path.insert(0, "scripts/live"); sys.path.insert(0, ".")
sys.modules.setdefault("cv2", types.ModuleType("cv2"))
import engine_view as ev_mod
from pogo.battle import damage
from pogo.gamedata import GameData

gd = GameData()
RULES = ("bad_lead", "hold_for_better", "shield_to_win", "save_the_low_one", "save_the_low_one_not",
         "waiting_for_better", "throw_before_fainting", "engine_error", "move_dominated")
total = collections.Counter()
for f in sys.argv[1:]:
    rows = [json.loads(l) for l in open(f)]
    end = next((r for r in rows if r["kind"] == "end"), {})
    fired = collections.Counter(r["kind"] for r in rows if r["kind"] in RULES)
    total[end.get("result")] += 1
    flags = []
    for r in rows:
        rec = r.get("view")
        if not rec or "error" in rec:
            continue
        try:
            v = ev_mod.LoggedView(gd, rec)
        except Exception:
            continue
        us, them = v.me.mon, v.foe
        if r["kind"] in ("decision", "throw_before_fainting") and str(r.get("action") or "charged:" + str(r.get("move"))).startswith("charged"):
            move = (r.get("action") or "").split(":")[-1] or r.get("move")
            mine = {m.id: damage(us, m, them) for m in us.build.charged}
            if move in mine and v.foe_shields == 0 and mine[move] < them.hp and any(d >= 2 * mine[move] for k, d in mine.items() if k != move):
                flags.append(f"{r['t']:.0f}s weak throw {move} {mine} into {them.build.species_id} {them.hp}hp")
        if r["kind"] == "shield_prompt" and not r.get("shield") and v.me.shields > 0:
            hi = r.get("foe_hi") or them.energy
            ko = [m.name for m in them.build.charged if hi >= m.energy and damage(them, m, us) >= us.hp]
            if ko:
                flags.append(f"{r['t']:.0f}s unshielded knock-out {ko} on {us.build.species_id} {us.hp}hp (shields {v.me.shields})")
    me_e = {}
    for r in rows:
        o = r.get("obs") or {}
        if r["kind"] == "look" and o.get("my_species") and o.get("my_energy") is not None:
            me_e[o["my_species"]] = o["my_energy"]
        if r["kind"] in ("replace", "fainted_unprompted"):
            was = (r.get("was") or "").lower()
            out = was or next(iter([k for k in me_e]), None)
            b = next((x for x in [gd.default(k) for k in [out]] if out), None) if False else None
    print(f"{f[-20:-6]} {end.get('result')} {end.get('foes')} {round(rows[-1]['t'])}s | {dict(fired)}")
    for fl in flags:
        print("    !", fl)
print(dict(total))
