#!/usr/bin/env python3
"""Where their fast move in progress lands when we throw a charged move, measured on the live battles' recordings
(task 40; the owner, 2026-11-10: "if we throw in the middle of their fast move that should knock us out, we get
knocked out immediately"). PvPoke, and pogo.battle after it, land a fast move in progress just after the charged move.

For each of our charged moves that went off, in battles whose logs carry the engine's view (their fast move and its
damage to us): our bar frame by frame from 1.5 s before the tap to Get Ready!, and on the first frames once the fight
is back (within 0.4 s of the first, before a new fast move of theirs can land: 0.5 s at least). Their rhythm comes
from their last hit on our bar. The tables give the HP lost by Get Ready! beyond the hits their rhythm makes due by
then, and the HP lost at the resume, both in their fast moves.

    python3 scripts/live/throw_order.py            measure the battles not done yet (runs/throw_order.json), then the tables
    python3 scripts/live/throw_order.py --tables   the tables only

The recordings are in C:/pogo-media/live (not in git); about 40 s a battle.
"""
from __future__ import annotations

import collections
import glob
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "runs" / "throw_order.json"
MEDIA = Path("C:/pogo-media/live")


def build(gd, x):
    from pogo.battle import Mon
    b = gd.build(x["species"], [x["fast"], *x["charged"]], level=x["level"], ivs=tuple(x["ivs"]))
    m = Mon(b, hp=int(x["hp"]), energy=int(x["energy"]))
    m.atk_stage, m.def_stage = (int(v) for v in x["stages"])
    return m


def measure() -> None:
    import av
    from pogo import android_screen as screen
    from pogo.battle import damage
    from pogo.gamedata import GameData
    gd = GameData()
    results = json.loads(OUT.read_text()) if OUT.exists() else {}
    for p in sorted(glob.glob(str(ROOT / "runs" / "live" / "202611*.jsonl"))):
        stem = Path(p).stem
        if stem.startswith(("runner", "setend")) or stem in results:
            continue
        rows = [json.loads(line) for line in open(p, encoding="utf-8") if line.strip()]
        if not any(r.get("view") for r in rows):
            continue
        rec = next(MEDIA.glob(f"*/battle-{stem}.h264"), None)
        start = next((r for r in rows if r["kind"] == "start"), None)
        if rec is None or start is None or rec.with_suffix(".times").read_bytes()[:1] == bytes(1):
            continue  # no recording, or a broken one (cut off as the player was stopped)
        hits = [r["t"] for r in rows if r["kind"] == "their_hit"]
        throws = []
        for i, r in enumerate(rows):
            if r["kind"] != "throw_started" or r.get("queued") or r.get("cue_t") is None:
                continue
            mg = next((q for q in rows[i + 1:] if q["kind"] == "minigame"), None)
            vrow = next((q for q in reversed(rows[max(0, i - 60):i])
                         if q.get("view") and "me" in q["view"] and r["cue_t"] - q["t"] < 3.0), None)
            if mg is None or vrow is None:
                continue
            try:
                me = build(gd, vrow["view"]["me"]["team"][vrow["view"]["me"]["active"]])
                foe = build(gd, vrow["view"]["foe"])
            except Exception:  # noqa: BLE001
                continue
            dur = foe.build.fast.turns * 0.5
            last = max([h for h in hits if h <= r["cue_t"]], default=None)
            tap = next((q["t"] for q in reversed(rows[:i]) if q["kind"] == "tap"
                        and (q.get("note") or "").startswith("charged move")), r["cue_t"] - 1.5)
            throws.append({"cue": r["cue_t"], "end": mg["t"], "tap": tap, "d": damage(foe, foe.build.fast, me),
                           "hp_max": me.build.hp, "dur": dur, "phase": None if last is None else (r["cue_t"] - last) / dur,
                           "foe": foe.build.species_id, "fast": foe.build.fast.id, "move": r["move"],
                           "lethal": me.hp <= damage(foe, foe.build.fast, me), "before": [], "after": []})
        if not throws:
            continue
        times = [float(line) for line in open(rec.with_suffix(".times"))]
        codec = av.CodecContext.create("h264", "r")
        k = 0
        for packet in codec.parse(rec.read_bytes()):
            for frame in codec.decode(packet):
                if k >= len(times):
                    break
                t = times[k] - start["epoch"]
                k += 1
                want = [th for th in throws if th["tap"] - 1.5 <= t <= th["cue"] or th["end"] <= t <= th["end"] + 8.0]
                if not want:
                    continue
                a = frame.to_ndarray(format="rgb24")
                if not screen.header_visible(a):
                    continue
                bars = screen.bar_places(a)
                if "mine" not in bars:
                    continue
                for th in want:
                    (th["before"] if t <= th["cue"] else th["after"]).append((round(t, 2), round(bars["mine"][0], 4)))
        out = []
        for th in throws:
            if len(th["before"]) < 2 or len(th["after"]) < 3 or not th["d"]:
                continue
            t0 = th["after"][0][0]
            first = [s for t, s in th["after"] if t - t0 <= 0.4]
            if len(first) < 2:
                continue
            b = statistics.median([s for _, s in th["before"][-4:]])
            a = statistics.median(first)
            out.append({key: th[key] for key in ("cue", "tap", "phase", "d", "hp_max", "dur", "foe", "fast", "move", "lethal")}
                       | {"trace": th["before"], "resume_t": t0, "units": round((b - a) * th["hp_max"] / th["d"], 2)})
        results[stem] = out
        OUT.write_text(json.dumps(results, indent=0))
        print(stem, len(out), "throws measured", flush=True)


def tables() -> None:
    d = json.loads(OUT.read_text())
    groups = collections.defaultdict(list)
    n = 0
    for v in d.values():
        for x in v:
            tr = x.get("trace") or []
            if x.get("phase") is None or len(tr) < 4 or x["phase"] > 1.6:
                continue  # no last hit, or they had paused: no rhythm to go by
            last = x["cue"] - x["phase"] * x["dur"]
            at_tap = [s for t, s in tr if x["tap"] - 0.6 <= t <= x["tap"]]
            at_cue = [s for t, s in tr if x["cue"] - 0.3 <= t <= x["cue"]]
            if not at_tap or not at_cue:
                continue
            n += 1
            due = sum(1 for k in range(1, 20) if x["tap"] < last + k * x["dur"] <= x["cue"])
            extra = (statistics.median(at_tap) - statistics.median(at_cue)) * x["hp_max"] / x["d"] - due
            mid = (x["cue"] - last) % x["dur"] / x["dur"]
            key = "their move mid-way at Get Ready! (0.2-0.8)" if 0.2 <= mid <= 0.8 else "their move at its start or end"
            groups[key].append((extra, x["units"]))
    print(n, "of our throws with our bar read at the tap, at Get Ready! and at the resume, their rhythm known")
    for key, v in groups.items():
        ex, af = [e for e, _ in v], [a for _, a in v]
        print(f"\n{key}: {len(v)}")
        print(f"  lost by Get Ready! beyond the hits due, in their fast moves: median {statistics.median(ex):.2f};"
              f" about one (0.6-1.4) {sum(0.6 <= e <= 1.4 for e in ex) / len(v):.0%}; none {sum(abs(e) < 0.4 for e in ex) / len(v):.0%}")
        print(f"  lost at the resume: median {statistics.median(af):.2f}; about one {sum(0.6 <= a <= 1.4 for a in af) / len(v):.0%};"
              f" none {sum(abs(a) < 0.4 for a in af) / len(v):.0%}")
        print(f"  neither (cancelled): {sum(abs(e) < 0.4 and abs(a) < 0.4 for e, a in v) / len(v):.0%}")


if __name__ == "__main__":
    if "--tables" not in sys.argv:
        measure()
    tables()
