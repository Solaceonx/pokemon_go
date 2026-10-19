#!/usr/bin/env python3
"""How long the game pauses, measured from tracked battles: the time the real-time engine has (pogo.realtime).

    python3 scripts/recording/pause_lengths.py [games/*/timeline.json ...]

From each battle's timeline.json (scripts/recording/assemble.py): for every charged move, the time from its start
(the cue) to its damage on the bar and to the first fast-move hit after it (play resumes); for every Pokémon sent in
after a faint, the time from the knockout to its entry and to the first hit after; and the time from the lead's
"Go" to the first hit. Prints medians and the 10th and 90th percentiles, in seconds.
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def first_after(steps, t, gap=0.0):
    return next((s for s, _ in steps if s > t + gap), None)


def main() -> None:
    paths = sys.argv[1:] or sorted(glob.glob(str(ROOT / "games" / "**" / "timeline.json"), recursive=True))
    rows = {k: [] for k in ("charged: start to damage shown", "charged: damage shown to play resuming",
                            "charged: start to play resuming (unblocked)", "charged: start to play resuming (blocked)",
                            "faint: knockout to replacement in", "faint: replacement in to play resuming",
                            "start: lead's Go to first hit")}
    used = 0
    for path in paths:
        t = json.loads(Path(path).read_text())
        if "steps" not in t or "charged" not in t:
            continue
        used += 1
        steps = {side: sorted(t["steps"].get(side, [])) for side in ("mine", "theirs")}
        both = sorted(steps["mine"] + steps["theirs"])
        for c in t["charged"]:
            target = "theirs" if c["side"] == "mine" else "mine"
            if c.get("blocked"):
                resume = first_after(both, c["t"], 6.0)
                if resume:
                    rows["charged: start to play resuming (blocked)"].append(resume - c["t"])
                continue
            hit = next(((s, v) for s, v in steps[target] if c["t"] + 2 < s < c["t"] + 16 and v >= 8), None)
            if not hit:
                continue
            resume = first_after(both, hit[0], 0.3)
            rows["charged: start to damage shown"].append(hit[0] - c["t"])
            if resume and resume - hit[0] < 6:
                rows["charged: damage shown to play resuming"].append(resume - hit[0])
                rows["charged: start to play resuming (unblocked)"].append(resume - c["t"])
        for side in ("mine", "theirs"):
            entries = t["field"].get(side, [])
            for e in entries:
                if e.get("faint"):
                    before = [s for s, _ in steps[side] if s < e["t"]]
                    ko = before[-1] if before else None
                    resume = first_after(both, e["t"], 0.2)
                    if ko is not None and e["t"] - ko < 20:
                        rows["faint: knockout to replacement in"].append(e["t"] - ko)
                    if resume and resume - e["t"] < 10:
                        rows["faint: replacement in to play resuming"].append(resume - e["t"])
            if entries and side == "mine" and both:
                rows["start: lead's Go to first hit"].append(both[0][0] - entries[0]["t"])
    print(f"{used} battles")
    for name, v in rows.items():
        if v:
            a = np.array(v)
            print(f"  {name:45s} {len(a):4d}   median {np.median(a):5.2f} s   10th {np.percentile(a, 10):5.2f}   90th {np.percentile(a, 90):5.2f}")


if __name__ == "__main__":
    main()
