#!/usr/bin/env python3
"""After a live battle, ask the engine again what it should have done, knowing what we learnt afterwards (task 40;
the owner's idea, 2026-11-08).

    python3 scripts/live/resim.py STAMP [--foe-fast kabutops=WATERFALL jolteon=VOLT_SWITCH ...] [--ms 1500]

Every look the live player gave its tracker (runs/live/STAMP.jsonl, the "look" rows) is given again to a fresh
tracker. That tracker is told each opposing Pokémon's true fast move (--foe-fast, from the recording: the scratch
fastcount.py checker, or by eye), so their energy is counted with the right move from the first hit. At each look
the engine decides with --ms of thinking (live: 300), and the decision is set beside the live one. Printed: where
they differ, with what each tracker believed of their energy and ours. A difference is a lead, not a verdict: the
engine draws at random among close lines, and after the first difference the live battle went its own way.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "live"))

from pogo.battle import CHARGED, FAST, SWITCH  # noqa: E402
from pogo.evaluation import Evaluator  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.learner import QNet  # noqa: E402
from pogo.realtime import WEBSITE, RealTime  # noqa: E402
from pogo.tracker import Observation, Tracker  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("stamp")
    ap.add_argument("--foe-fast", nargs="*", default=[], help="species=MOVE_ID, their true fast moves")
    ap.add_argument("--ms", type=float, default=1500.0, help="thinking time per decision")
    ap.add_argument("--team", default=str(ROOT / "data" / "alt_team.json"))
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    import play_android as pa
    gd = GameData()
    team = pa.load_team(gd, Path(a.team))
    foe_fast = dict(x.split("=", 1) for x in a.foe_fast)
    rows = [json.loads(l) for l in open(ROOT / "runs" / "live" / f"{a.stamp}.jsonl", encoding="utf-8")]
    tracker = Tracker(gd, team, energy="hits", foe_fast=foe_fast)
    ev = Evaluator.load(ROOT / "runs" / "eval" / "eval.npz")
    engine = RealTime(Evaluator(ev.model), gd.meta(50), q=QNet.load(str(ROOT / "runs" / "general-decide" / "q.npz")),
                      seed=a.seed, **WEBSITE, turn_ms=500, cap_ms=a.ms, clock=time.perf_counter)
    fields = set(Observation.__dataclass_fields__)

    def name(action, active):
        if action == FAST:
            return "fast"
        if action in CHARGED:
            return "charged:" + team[active].charged[action - CHARGED[0]].id
        if action in SWITCH:
            return "switch:" + team[action - SWITCH[0]].species_id
        return str(action)

    looks = [(i, r) for i, r in enumerate(rows) if r["kind"] == "look"]
    differ = same = 0
    for n, (i, r) in enumerate(looks):
        # header counts were numpy integers live, written as text in the log
        obs = Observation(**{k: int(v) if isinstance(v, str) and v.isdigit() else v
                             for k, v in r["obs"].items() if k in fields})
        try:
            tracker.update(obs)
        except Exception as error:  # noqa: BLE001
            print(f"{r['t']:6.1f} tracker error: {error}")
            continue
        if tracker.foe is None:
            continue
        if obs.my_energy is not None:  # as live: the buttons overrule the count
            tracker.me.mon.energy = int(round(obs.my_energy))
        live = next((x["action"] for x in rows[i + 1:i + 6] if x["kind"] == "decision"), None)
        active = next((j for j, b in enumerate(team) if b.species_id == obs.my_species), 0)
        try:
            again = name(engine.act(tracker.view()), active)
        except Exception as error:  # noqa: BLE001
            import traceback
            print(f"{r['t']:6.1f} engine error: {error}")
            traceback.print_exc(limit=-4)
            continue
        f, lf = tracker.foe, r.get("foe")
        if live is None or again == live:
            same += live is not None
            continue
        differ += 1
        was = f" (live tracker: {lf[1]}-{lf[2]} {lf[3]})" if lf else ""
        print(f"{r['t']:6.1f}  live {live:22s} again {again:22s}  ours {obs.my_species} {tracker.me.mon.energy:3d}"
              f" hp {obs.my_hp}  theirs {f.mon.build.species_id} {f.mon.build.fast.id} {f.lo}-{f.hi}{was}")
    print(f"{a.stamp}: {same} decisions the same, {differ} different")


if __name__ == "__main__":
    main()
