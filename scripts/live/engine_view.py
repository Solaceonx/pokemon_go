#!/usr/bin/env python3
"""Ask the engine again on the views the live player logged (task 40): each `decision` row that was not a fast move,
and each throw the player's own rules made (throw_before_fainting, throw_before_theirs), carries the whole view it
was made on (play_android.view_record). This rebuilds that view and asks the live engine, built as the player builds
it, N times.

    python3 scripts/live/engine_view.py STAMP              every logged view in runs/live/STAMP.jsonl
    python3 scripts/live/engine_view.py STAMP T [N]        the views within 0.05 s of battle time T, asked N times
    (STAMP can also be a log's path, e.g. a replay's runs/replay/STAMP-replay.jsonl)

The owner, 2026-11-09 (docs/status.md, the spare account's 25 battles): in the simulator the engine never threw
Discharge into Toxtricity on the same matchups, so the live throws came from the state the phone handed it, which
was not logged. Prints, per view: who is out, health and energy on both sides, shields, and the engine's picks
against what was done live.
"""
from __future__ import annotations

import collections
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts" / "live"))
from pogo.battle import CHARGED, FAST, SWITCH, Mon, Side  # noqa: E402
from pogo.evaluation import Evaluator  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.learner import QNet  # noqa: E402
from pogo.realtime import WEBSITE, RealTime  # noqa: E402


def build_mon(gd: GameData, r: dict) -> Mon:
    b = gd.build(r["species"], [r["fast"], *r["charged"]], level=r["level"], ivs=tuple(r["ivs"]))
    m = Mon(b, hp=int(r["hp"]), energy=int(r["energy"]))
    m.atk_stage, m.def_stage = (int(x) for x in r["stages"])
    return m


class LoggedView:
    """A logged view in the shape of pogo.tracker.TrackedView."""

    def __init__(self, gd: GameData, rec: dict):
        me = rec["me"]
        num = lambda v: None if v is None else int(v)  # the header's counts were logged as text at first
        self.me = Side([build_mon(gd, r) for r in me["team"]], num(me["shields"]))
        self.me.active, self.me.switch_wait, self.me.busy = num(me["active"]), num(me["switch_wait"]), num(me["busy"])
        self.foe = build_mon(gd, rec["foe"])
        shown = [build_mon(gd, r) for r in rec["foe_shown"]]
        # the active one is the same object in foe_shown, as in the tracker
        self.foe_shown = [self.foe if (m.build.species_id, m.hp) == (self.foe.build.species_id, self.foe.hp) else m
                          for m in shown]
        self.foe_shields, self.foe_switch_wait = num(rec["foe_shields"]), num(rec["foe_switch_wait"])
        self.foe_busy, self.foe_left, self.turn = num(rec["foe_busy"]), num(rec["foe_left"]), num(rec["turn"])
        if "foe_move_odds" in rec:
            self.foe_move_odds = [(gd.moves[m], p) for m, p in rec["foe_move_odds"]]
        if "foe_energy_odds" in rec:
            self.foe_energy_odds = {int(k): p for k, p in rec["foe_energy_odds"].items()}

    def legal(self) -> list[int]:
        me, mon = self.me, self.me.mon
        out = [FAST] + [CHARGED[k] for k, move in enumerate(mon.build.charged) if mon.energy >= move.energy]
        if me.switch_wait == 0:
            out += [SWITCH[j] for j in me.bench()]
        return out


def engine(gd: GameData, seed: int) -> RealTime:
    """As scripts/live/play_android.Player builds it."""
    ev = Evaluator.load(ROOT / "runs" / "eval" / "eval.npz")
    return RealTime(Evaluator(ev.model), gd.meta(50), q=QNet.load(str(ROOT / "runs" / "general-decide" / "q.npz")),
                    seed=seed, **WEBSITE, turn_ms=500, cap_ms=300, clock=time.perf_counter)


def name(view: LoggedView, action: int) -> str:
    if action == FAST:
        return "fast"
    if action in CHARGED:
        return "charged:" + view.me.mon.build.charged[action - CHARGED[0]].id
    return "switch:" + view.me.team[action - SWITCH[0]].build.species_id


def main() -> None:
    stamp = sys.argv[1]
    at = float(sys.argv[2]) if len(sys.argv) > 2 else None
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 6
    path = Path(stamp) if stamp.endswith(".jsonl") else ROOT / "runs" / "live" / f"{stamp}.jsonl"  # or a replay's log
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    gd = GameData()
    eng = engine(gd, seed=1)
    for r in rows:
        rec = r.get("view")
        if not rec or "error" in rec or (at is not None and abs(r["t"] - at) > 0.05):
            continue
        view = LoggedView(gd, rec)
        live = r.get("action") or f"{r['kind']}:{r.get('move')}"
        me, foe = view.me.mon, view.foe
        picks = collections.Counter(name(view, eng.act(view)) for _ in range(n))
        print(f"{r['t']:7.2f} live {live:<28} {me.build.species_id} {me.hp}/{me.build.hp}hp {me.energy}e "
              f"vs {foe.build.species_id} {foe.hp}/{foe.build.hp}hp {foe.energy}e  shields {view.me.shields}-{view.foe_shields}"
              f"  engine now: {dict(picks)}")


if __name__ == "__main__":
    main()
