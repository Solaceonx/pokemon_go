#!/usr/bin/env python3
"""Every charged move of ours in a recorded battle, and whether the player swiped its minigame (task 40).

    python3 scripts/live/audit_cues.py MEDIA_FOLDER [--since EPOCH]

The minigame ratings (ratings.py) cover only minigames the player swiped: their frames are kept by the swipe. A move
of ours that went off unseen (2026-11-07: "Get Ready!" a moment after the player stopped waiting) has no frames and
no rating. This reads the top box ("Get Ready!") on the recording (MEDIA_FOLDER/battle-<stamp>.h264 and .times, read
while the fight is off the screen, four times a second) and matches each to a swipe in the battle's log
(runs/live/<stamp>.jsonl, its "swipe" rows: 1.05 s after the Get Ready! the player saw).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def cues(media: Path, stem: str, epoch: float, ocr) -> list:
    """Battle times at which a Get Ready! started (the first frame of each run of them)."""
    import av
    from pogo import android_screen as screen
    times = [float(line) for line in open(media / f"battle-{stem}.times")]
    codec = av.CodecContext.create("h264", "r")
    found, last, i, run_end = [], -9.0, 0, -9.0
    for packet in codec.parse((media / f"battle-{stem}.h264").read_bytes()):
        for fr in codec.decode(packet):
            if i >= len(times):
                break
            t = times[i] - epoch
            i += 1
            if t - last < 0.25:
                continue
            a = fr.to_ndarray(format="rgb24")
            look = screen.read(a, t)
            if look.header and len(look.bars) >= 1:
                continue
            last = t
            if screen.cue(ocr, a) == "mine":
                if t - run_end > 2.0:
                    found.append(round(t, 2))
                run_end = t
    return found


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("media")
    ap.add_argument("--since", type=int, default=0)
    a = ap.parse_args()
    from rapidocr_onnxruntime import RapidOCR
    ocr = RapidOCR()
    media = Path(a.media)
    total = swiped = 0
    for log in sorted((ROOT / "runs" / "live").glob("2*.jsonl")):
        rows = [json.loads(line) for line in open(log, encoding="utf-8")]
        epoch = next((r.get("epoch") for r in rows if r["kind"] == "start"), None)
        if epoch is None or epoch < a.since or not (media / f"battle-{log.stem}.h264").exists():
            continue
        swipes = [r["t"] - 1.05 for r in rows if r["kind"] == "swipe"]
        got = cues(media, log.stem, epoch, ocr)
        missed = [c for c in got if not any(-0.6 <= s - c <= 1.2 for s in swipes)]
        total += len(got)
        swiped += len(got) - len(missed)
        print(f"{log.stem}: our moves {len(got)}, swiped {len(got) - len(missed)}"
              + (f", NOT SWIPED at {missed}" if missed else ""))
    print(f"all: our moves {total}, swiped {swiped} ({100 * swiped / max(total, 1):.0f}%)")


if __name__ == "__main__":
    main()
