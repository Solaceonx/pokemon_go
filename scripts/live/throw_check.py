#!/usr/bin/env python3
"""How well the tracker knew their energy, judged by their own charged moves (task 40).

    python3 scripts/live/throw_check.py STAMP [STAMP ...] [--energy hits|rhythm|both]

Each battle's looks (runs/live/STAMP.jsonl) are given again to a fresh tracker (pogo.tracker, the counting mode
asked), as the live player gave them. At each charged move of theirs whose name the screen showed (the looks'
foe_move), the tracker's range for their energy just before it is set beside the move's cost: they had at least the
cost, and players throw soon after reaching it, so a range under the cost is a count that fell short, and one far
over it a count that ran ahead. This needs no other truth than the game's own words.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "live"))

from pogo.gamedata import GameData  # noqa: E402
from pogo.tracker import Observation, Tracker  # noqa: E402


def off_screen(cache: Path, stamp: str):
    """From a frame-by-frame record of the recording (the scratch fastcount.py cache: [t, header, our bar, theirs,
    ...]): a function giving the seconds the fight was off the screen between two times (gaps under 0.4 s are the
    fight's own: bars missed on a frame or two)."""
    frames = json.loads((cache / f"fc_{stamp}.json").read_text())
    on = [f[0] for f in frames if f[1] and (f[2] is not None or f[3] is not None)]

    def off(t0: float, t1: float) -> float:
        inside = [t for t in on if t0 <= t <= t1]
        pts = [t0] + inside + [t1]
        return sum(b - a for a, b in zip(pts, pts[1:]) if b - a > 0.4)
    return off


def check(gd, team, stamp: str, energy: str, still: float | None = None, cache: Path | None = None) -> list:
    rows = [json.loads(l) for l in open(ROOT / "runs" / "live" / f"{stamp}.jsonl", encoding="utf-8")]
    off = off_screen(cache, stamp) if cache else None
    last_t = None
    import tempfile
    notes = Path(tempfile.mkdtemp()) / "notes.jsonl"
    tracker = Tracker(gd, team, energy=energy, path=notes)
    fields = set(Observation.__dataclass_fields__)
    out, before = [], None
    for r in rows:
        if r["kind"] != "look":
            continue
        obs = Observation(**{k: int(v) if isinstance(v, str) and v.isdigit() else v
                             for k, v in r["obs"].items() if k in fields})
        if off is not None and last_t is not None:
            # the off-screen time measured on the frames, less the 10 s the tracker takes off for each charged move
            thrown = bool(obs.foe_charged) + (obs.my_charged is not None)
            obs.paused = off(last_t, obs.t) - 10.0 * thrown
        last_t = obs.t
        if still is not None and obs.paused is not None and off is None:
            # a gap counts as the fight standing still only from `still` seconds (a prompt or a throw aside)
            gap = obs.paused + 10.0 * (bool(obs.foe_charged) + (obs.my_charged is not None))
            obs.paused = obs.paused if (gap >= still or obs.foe_charged or obs.my_charged is not None) else None
        if obs.foe_charged and obs.foe_move and before is not None and obs.foe_move in gd.moves:
            out.append((stamp, r["t"], before[0], obs.foe_move, gd.moves[obs.foe_move].energy, before[1], before[2]))
        try:
            tracker.update(obs)
        except Exception:  # noqa: BLE001
            continue
        if obs.my_energy is not None and tracker.foe is not None:
            tracker.me.mon.energy = int(round(obs.my_energy))
        if tracker.foe is not None and not obs.foe_charged:
            before = (tracker.foe.mon.build.species_id, tracker.foe.lo, tracker.foe.hi)
    tracker.close()
    # the range the tracker held at the very moment it took each charged move off (its own note), which includes the
    # turns counted at that look; matched to the named throws by time
    spent = [json.loads(l) for l in open(notes) if '"foe_charged"' in l]
    fixed = []
    for row in out:
        near = [n for n in spent if abs(n["t"] - row[1]) < 0.01]
        if near and near[0].get("energy_before"):
            lo, hi = near[0]["energy_before"]
            row = row[:5] + (lo, hi)
        fixed.append(row)
    return fixed


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("stamps", nargs="+")
    ap.add_argument("--energy", default="both")
    ap.add_argument("--still", type=float, help="recount: a gap is a standstill only from this many seconds")
    ap.add_argument("--cache", help="recount the turns from the frames: the folder of fastcount.py's fc_STAMP.json")
    a = ap.parse_args()
    import play_android as pa
    gd = GameData()
    team = pa.load_team(gd, ROOT / "data" / "alt_team.json")
    for mode in (["hits", "rhythm"] if a.energy == "both" else [a.energy]):
        rows = [x for s in a.stamps for x in check(gd, team, s, mode, a.still, Path(a.cache) if a.cache else None)]
        short = [x for x in rows if x[6] < x[4]]
        near = [x for x in rows if x[5] - 10 <= x[4] <= x[6] + 10]
        ahead = [x for x in rows if x[5] > x[4] + 30]
        print(f"{mode}: {len(rows)} throws named; range short of the cost {len(short)}, within 10 of covering it "
              f"{len(near)}, more than 30 over it {len(ahead)}")
        for s, t, sp, mv, cost, lo, hi in rows:
            print(f"   {s} {t:6.1f} {sp:12s} {mv:14s} cost {cost:3d}  believed {lo:3d}-{hi:3d}")


if __name__ == "__main__":
    main()
