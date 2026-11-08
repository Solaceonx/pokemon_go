#!/usr/bin/env python3
"""How each live battle went, on the things that decide confidence (task 40): the result; charged moves thrown,
tapped too early and beaten to it; every minigame's rating; shield decisions against shields really used (the
header's count); throws made because our health was low.

    python3 scripts/live/report.py MEDIA_FOLDER [--since EPOCH]

Battles are the logs in runs/live/ with a start time (their "start" line's epoch); minigames are MEDIA_FOLDER's
minigame-<epoch>-<move>/ frame folders, matched to the battle they fall in. Ratings are read with OCR
(scripts/live/ratings.py).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ratings import rating  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("media")
    ap.add_argument("--since", type=int, default=0)
    a = ap.parse_args()
    from rapidocr_onnxruntime import RapidOCR
    ocr = RapidOCR()
    minis = sorted(Path(a.media).glob("minigame-*"))
    total = Counter()
    for log in sorted((ROOT / "runs" / "live").glob("2*.jsonl")):
        rows = [json.loads(l) for l in open(log, encoding="utf-8")]
        start = next((r.get("epoch") for r in rows if r["kind"] == "start"), None)
        end = next((r for r in rows if r["kind"] == "end"), None)
        if start is None or end is None or start < a.since:
            continue
        stop = start + end["t"] + 5
        rated = Counter()
        for d in minis:
            if start - 2 <= int(d.name.split("-")[1]) <= stop:
                rated[rating(d, ocr) or "none"] += 1
        k = lambda kind: sum(r["kind"] == kind for r in rows)
        decided = sum(r["kind"] == "shield_prompt" and r["shield"] for r in rows)
        shields = [int(r["obs"]["my_shields"]) for r in rows if r["kind"] == "look" and r["obs"].get("my_shields") is not None]
        used = (shields[0] - min(shields)) if shields else 0
        line = (f"{log.stem} {str(end.get('result')):5s} vs {','.join(end.get('foes') or [])[:40]:40s} | throws {k('throw_started')} "
                f"(too early {k('throw_not_taken')}, beaten {k('throw_beaten')}) | minigames "
                + " ".join(f"{w[0]}{rated[w]}" for w in ("EXCELLENT", "GREAT", "NICE", "none") if rated[w])
                + f" | shields decided {decided}, used {used} | low-health throws {k('throw_before_fainting')}")
        print(line)
        total.update(rated)
        total["battles"] += 1
        total["wins"] += end.get("result") == "win"
    n = sum(total[w] for w in ("EXCELLENT", "GREAT", "NICE", "none"))
    print(f"battles {total['battles']}, wins {total['wins']} | minigames {n}: Excellent {total['EXCELLENT']} "
          f"({100 * total['EXCELLENT'] / max(n, 1):.0f}%), Great {total['GREAT']}, Nice {total['NICE']}, not read {total['none']}")


if __name__ == "__main__":
    main()
