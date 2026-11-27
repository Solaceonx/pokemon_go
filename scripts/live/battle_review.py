#!/usr/bin/env python3
"""A game review of each live league battle, for both sides, like a chess site's: every throw, shield and voluntary
switch either side made is played on to the end of the battle against the other choices it had, and scored by the win
chance it gave up.

    nice python3 scripts/live/battle_review.py --out ../records/games/live [--playouts 24] [--workers 3] [STAMP ...]

For each league battle in runs/live/ (or the stamps given) it writes OUT/<STAMP>/review.json; a battle already
reviewed at this version is skipped, so a run can stop and go on. How a decision is scored:
- The position: the live player's logged view nearest before the decision (ours: the decision that made it; theirs:
  the last view before the tracker saw it), with both teams as known at the battle's end (hindsight, the same for both
  sides), their energy at least what the move they threw costs.
- The choices: a throw against fast-moving and the other move it could pay for; a voluntary switch against staying
  and the other switch; a shield against no shield (their move as it was named). Replacements after a faint and the
  moments either side held energy are not scored yet (we cannot see the opponent's holds).
- Each choice is played to the end `--playouts` times, both sides the trained bot with habits varied in each battle
  (as pogo.lineup.win_chance), the same dice and habits for every choice: win 1, draw 0.5. A choice "gave up" the
  best choice's win chance minus its own, counted only beyond the 95% margin of that paired difference.
- Accuracy per decision is the chess-site curve on the win chance given up (0 lost = 100; 10 points = 62; 20 = 39):
  103.1668 exp(-0.04354 lost) - 3.1669, between 0 and 100; a side's accuracy is the mean over its decisions.
  Inaccuracy 5 to 10 points given up, mistake 10 to 20, blunder 20 or more.
Standard library and numpy (the bot's networks).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import random
import sys
import types
from multiprocessing import get_context
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "1")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts" / "live"))
VERSION = 1
LOGS = ROOT / "runs" / "live"
_w: dict = {}


def accuracy(lost: float) -> float:
    return max(0.0, min(100.0, 103.1668 * math.exp(-0.04354 * lost) - 3.1669))


def grade(lost: float) -> str:
    return "blunder" if lost >= 20 else "mistake" if lost >= 10 else "inaccuracy" if lost >= 5 else ""


def setup() -> None:
    if importlib.util.find_spec("cv2") is None:
        sys.modules["cv2"] = types.ModuleType("cv2")
    try:
        os.nice(10)
    except OSError:
        pass
    from engine_view import LoggedView
    from pogo.gamedata import GameData
    from pogo.learner import QNet
    gd = GameData()
    _w.update(gd=gd, LoggedView=LoggedView, pool=gd.meta(50), q=QNet.load(str(ROOT / "runs" / "general-decide" / "q.npz")))


def views(rows: list) -> list:
    return [r for r in rows if isinstance(r.get("view"), dict) and "error" not in r["view"]]


def league_battle(rows: list) -> bool:
    start = next((r for r in rows if r["kind"] == "start"), {})
    end = next((r for r in rows if r["kind"] == "end"), {})
    return bool(start.get("league")) and bool(end.get("foes")) and any(r["kind"] == "decision" for r in rows)


def decisions(rows: list, rec: dict) -> list:
    """(t, side, kind, view row, chosen, extra) for every scored decision of the battle: ours from the player's own
    decision rows and shield prompts, theirs from the record's actions (games/live/<STAMP>/game.json)."""
    gd = _w["gd"]
    vs = views(rows)
    acts = rec["actions"]
    out = []

    def last_view(t, within, kinds=("decision", "throw_before_fainting")):
        before = [r for r in vs if r["t"] <= t and r["kind"] in kinds]
        return before[-1] if before and t - before[-1]["t"] < within else None

    for r in vs:  # our shields, their move as the record has it
        if r["kind"] != "shield_prompt":
            continue
        a = next((x for x in acts if x["kind"] == "charged" and x["side"] == "theirs" and abs(x["t"] - r["t"]) < 1.0), None)
        if a and a.get("move_id") in gd.moves:
            out.append((r["t"], "mine", "shield", r, bool(r.get("shield")),
                        {"move": a["move_id"], "energy": max((a.get("their_energy_believed") or [0])[-1], a.get("cost") or 0)}))
    faints = [(a["t"], a.get("side")) for a in acts if a["kind"] == "faint"]
    for a in acts:  # every throw, and every switch made with the one switched out still healthy
        side = a.get("side")
        if side not in ("mine", "theirs") or a["kind"] not in ("charged", "switch"):
            continue
        if a["kind"] == "charged":
            v = last_view(a["t"] - 0.2, 20.0)
            v = v and brought_up(v, a.get("state"))
            if v is None or a.get("move_id") not in gd.moves:
                continue
            mon = v["view"]["foe"] if side == "theirs" else v["view"]["me"]["team"][v["view"]["me"]["active"]]
            if mon["species"] == a.get("pokemon"):
                out.append((a["t"], side, "throw", v, a["move_id"], {}))
            continue
        if any(0 <= a["t"] - ft < 4 and fs == side for ft, fs in faints):
            continue  # a replacement
        v = last_view(a["t"] - 0.3, 8.0)
        if v is None or not a.get("to"):
            continue
        lv = _w["LoggedView"](_w["gd"], v["view"])
        mon, full = (v["view"]["foe"], lv.foe.build.hp) if side == "theirs" else (
            v["view"]["me"]["team"][v["view"]["me"]["active"]], lv.me.mon.build.hp)
        if mon["species"] == a.get("from") and mon["hp"] > 0.15 * full:
            out.append((a["t"], side, "switch", v, a["to"], {}))
    for t, side, kind, v, move, _ in list(out):  # their shields on our throws: their shield count drops
        if side != "mine" or kind != "throw" or v["view"]["foe_shields"] <= 0:
            continue
        after = [r for r in vs if t + 1.5 < r["t"] < t + 15]
        if after:
            out.append((t, "theirs", "shield", v, after[0]["view"]["foe_shields"] < v["view"]["foe_shields"], {"move": move}))
    return sorted(out, key=lambda d: d[0])


def brought_up(row: dict, state: dict | None):
    """A logged view moved on to the tracker's picture at the look just before an action of theirs (health, energy,
    shields), when both active Pokémon are the same; None when they are not."""
    import copy
    if not state:
        return None
    lv = _w["LoggedView"](_w["gd"], row["view"])
    d = copy.deepcopy(row["view"])
    m, th = state.get("mine") or {}, state.get("theirs") or {}
    me = d["me"]["team"][d["me"]["active"]]
    if me["species"] != m.get("active") or d["foe"]["species"] != th.get("active"):
        return None
    if m.get("hp_share") is not None:
        me["hp"] = max(1, round(m["hp_share"] * lv.me.mon.build.hp))
    if m.get("energy") is not None:
        me["energy"] = int(m["energy"])
    if th.get("hp_share") is not None:
        d["foe"]["hp"] = max(1, round(th["hp_share"] * lv.foe.build.hp))
    if th.get("energy"):
        d["foe"]["energy"] = int(th["energy"][-1])
    for key, val in (("shields", m.get("shields")),):
        if val is not None:
            d["me"][key] = val
    if th.get("shields") is not None:
        d["foe_shields"] = th["shields"]
    for m in d.get("foe_shown", []):  # the active one is the same Pokémon in both lists
        if m["species"] == d["foe"]["species"]:
            m["hp"], m["energy"] = d["foe"]["hp"], d["foe"]["energy"]
    return {**row, "view": d, "t": state.get("look_t", row["t"])}


def foe_builds(rows: list):
    LoggedView = _w["LoggedView"]
    builds = {}
    for r in views(rows):
        v = LoggedView(_w["gd"], r["view"])
        for m in [v.foe] + list(v.foe_shown):
            builds[m.build.species_id] = m.build
    order = next(r for r in rows if r["kind"] == "end")["foes"]
    return order, builds


def options(view, side: str, kind: str, chosen, extra: dict) -> tuple[list, object]:
    """The choices (as forced first actions, or True/False for a shield) and which of them was made."""
    from pogo.battle import CHARGED, FAST, SWITCH
    gd = _w["gd"]
    if kind == "shield":
        return [False, True], bool(chosen)
    me = view.me if side == "mine" else None
    if side == "mine":
        mon, team, active = me.mon, me.team, me.active
    else:
        mon = view.foe
        team, active = None, None
    if kind == "throw":
        cost = gd.moves[chosen].energy
        energy = mon.energy if side == "mine" else max(mon.energy, cost)
        ids = [m.id for m in mon.build.charged]
        if chosen not in ids:
            return [], None
        opts = [FAST] + [CHARGED[k] for k, m in enumerate(mon.build.charged) if energy >= m.energy]
        return opts, CHARGED[ids.index(chosen)]
    # switch: theirs are placed by species once the battle is imagined
    if side == "mine":
        slots = [j for j in range(3) if j != active and team[j].hp > 0]
        target = next((j for j in slots if team[j].build.species_id == chosen), None)
        if target is None:
            return [], None
        return [FAST] + [SWITCH[j] for j in slots], SWITCH[target]
    return [FAST, ("to", chosen)], ("to", chosen)


def land(battle, thrower: int, move_id: str, energy, shielded: bool) -> bool:
    from pogo.engine import _FirstShield
    mon = battle.sides[thrower].mon
    ids = [m.id for m in mon.build.charged]
    if move_id not in ids:
        return False
    mon.energy = max(mon.energy, int(energy or 0), _w["gd"].moves[move_id].energy)
    d = 1 - thrower
    player = battle.agents[d]
    battle.agents[d] = _FirstShield(player, shielded, battle.turn)
    try:
        battle._throw(thrower, ids.index(move_id))
    finally:
        battle.agents[d] = player
    return True


def playout(job: tuple) -> float:
    from pogo.agents import varied_settings
    from pogo.battle import DRAW, FAST, SWITCH
    from pogo.engine import _First, imagine
    from pogo.learner import Learner
    rec, side, kind, option, extra, seed, teams, builds = job
    view = _w["LoggedView"](_w["gd"], rec)
    for m in [view.foe] + list(view.foe_shown):
        if m.build.species_id in builds:
            m.build = builds[m.build.species_id]
    rng = random.Random(seed)
    pool, q = _w["pool"], _w["q"]
    agents = [Learner(q=q, margin=rng.choice((0.02, 0.05)), **varied_settings(rng, pool)) for _ in range(2)]
    s = 0 if side == "mine" else 1
    first = option
    if kind in ("throw", "switch") and isinstance(option, tuple):
        first = None  # their switch: the slot is known once the battle is imagined
    if kind in ("throw", "switch"):
        agents[s] = _First(agents[s], first)
    battle = imagine(view, rng, pool, agents[0], agents[1], teams=teams, team_builds=builds)
    if kind in ("throw", "switch") and isinstance(option, tuple):
        team = battle.sides[1].team
        slot = next((j for j, m in enumerate(team) if m.build.species_id == option[1] and m.hp > 0 and j != battle.sides[1].active), None)
        if slot is None:
            return float("nan")
        agents[1].action = SWITCH[slot]
    if kind == "throw" and s == 1:
        from pogo.battle import CHARGED
        if option in CHARGED:
            mon = battle.sides[1].mon
            mon.energy = max(mon.energy, mon.build.charged[CHARGED.index(option)].energy)
    if kind == "shield":
        if not land(battle, 1 - s, extra["move"], extra.get("energy"), bool(option)):
            return float("nan")
    for i in (0, 1):  # a knock-out from the landed throw: the next one comes in
        side_i = battle.sides[i]
        if battle.winner is None and side_i.mon.hp <= 0:
            if not side_i.bench():
                battle.winner = 1 - i
            else:
                side_i.active = side_i.bench()[0]
                if side_i.active not in side_i.shown:
                    side_i.shown.append(side_i.active)
    if battle.winner is None:
        battle.run()
    return 1.0 if battle.winner == s else 0.5 if battle.winner == DRAW else 0.0


def name(option) -> str:
    from pogo.battle import CHARGED, FAST, SWITCH
    if option is True:
        return "shield"
    if option is False:
        return "no shield"
    if option == FAST:
        return "fast moves"
    if isinstance(option, tuple):
        return f"switch to {option[1]}"
    if option in CHARGED:
        return f"charged {CHARGED.index(option) + 1}"
    if option in SWITCH:
        return f"switch slot {SWITCH.index(option)}"
    return str(option)


def review(stamp: str, playouts: int, rec: dict) -> dict | None:
    rows = [json.loads(l) for l in open(LOGS / f"{stamp}.jsonl", encoding="utf-8") if l.strip()]
    if not league_battle(rows):
        return None
    order, builds = foe_builds(rows)
    teams = [(1.0, tuple(order))] if len(order) == 3 else None
    LoggedView = _w["LoggedView"]
    out = []
    for i, (t, side, kind, row, chosen, extra) in enumerate(decisions(rows, rec)):
        view = LoggedView(_w["gd"], row["view"])
        opts, made = options(view, side, kind, chosen, extra)
        if len(opts) < 2 or made not in opts:
            continue
        wins = {}
        for k, o in enumerate(opts):
            wins[k] = [playout((row["view"], side, kind, o, extra, 9_000_000 + i * 1000 + s, teams, builds))
                       for s in range(playouts)]
        if any(any(math.isnan(x) for x in w) for w in wins.values()):
            continue
        mean = {k: sum(w) / playouts for k, w in wins.items()}
        c = opts.index(made)
        best = max(mean, key=mean.get)
        diff = [a - b for a, b in zip(wins[best], wins[c])]
        md = sum(diff) / playouts
        sd = math.sqrt(sum((x - md) ** 2 for x in diff) / max(1, playouts - 1))
        lost = 100 * md if best != c and md > 1.96 * sd / math.sqrt(playouts) else 0.0
        names = {k: label(view, side, o) for k, o in enumerate(opts)}
        out.append({"t": round(t, 1), "side": side, "kind": kind, "chosen": names[c], "best": names[best],
                    "win": {names[k]: round(100 * m) for k, m in mean.items()}, "lost": round(lost, 1),
                    "accuracy": round(accuracy(lost), 1), "grade": grade(lost)})
    sides = {}
    for side in ("mine", "theirs"):
        ds = [d for d in out if d["side"] == side]
        worst = max(ds, key=lambda d: d["lost"], default=None)
        sides[side] = {"accuracy": round(sum(d["accuracy"] for d in ds) / len(ds), 1) if ds else None,
                       "decisions": len(ds), **{g: sum(d["grade"] == g for d in ds) for g in ("inaccuracy", "mistake", "blunder")},
                       "worst": worst if worst and worst["lost"] > 0 else None}
    end = next(r for r in rows if r["kind"] == "end")
    return {"version": VERSION, "stamp": stamp, "playouts": playouts, "result": end.get("result"),
            "sides": sides, "decisions": out}


def label(view, side: str, option) -> str:
    from pogo.battle import CHARGED, FAST, SWITCH
    if option is True or option is False or option == FAST or isinstance(option, tuple):
        return name(option)
    mon = view.me.mon if side == "mine" else view.foe
    if option in CHARGED:
        return mon.build.charged[CHARGED.index(option)].id.replace("_", " ").title()
    if option in SWITCH:
        return f"switch to {view.me.team[SWITCH.index(option)].build.species_id}"
    return name(option)


def work(job):
    stamp, out_dir, playouts = job
    folder = Path(out_dir) / stamp
    if not (folder / "game.json").exists():
        return stamp, "no record"
    try:
        r = review(stamp, playouts, json.loads((folder / "game.json").read_text(encoding="utf-8")))
    except Exception as e:  # one battle's failure must not stop the rest
        return stamp, f"error: {type(e).__name__}: {e}"
    if r is None:
        return stamp, "not a league battle"
    (folder / "review.json").write_text(json.dumps(r, indent=1) + "\n", encoding="utf-8")
    m, th = r["sides"]["mine"], r["sides"]["theirs"]
    return stamp, f"ours {m['accuracy']} ({m['decisions']}), theirs {th['accuracy']} ({th['decisions']})"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("stamps", nargs="*")
    ap.add_argument("--out", required=True, help="games/live of a checkout of main (the records)")
    ap.add_argument("--playouts", type=int, default=24)
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args()
    out = Path(a.out)
    stamps = a.stamps or sorted(p.name for p in out.iterdir() if (p / "log.jsonl").exists())
    todo = []
    for s in stamps:
        f = out / s / "review.json"
        if f.exists() and json.loads(f.read_text()).get("version") == VERSION and json.loads(f.read_text()).get("playouts") == a.playouts:
            continue
        if (LOGS / f"{s}.jsonl").exists():
            todo.append((s, str(out), a.playouts))
    print(f"{len(todo)} battles to review", flush=True)
    if a.workers <= 1:
        setup()
        for j in todo:
            print(*work(j), flush=True)
        return
    with get_context("spawn").Pool(a.workers, initializer=setup) as p:
        for k, (s, msg) in enumerate(p.imap_unordered(work, todo), 1):
            print(f"{k}/{len(todo)} {s} {msg}", flush=True)


if __name__ == "__main__":
    main()
