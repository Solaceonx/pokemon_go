#!/usr/bin/env python3
"""The rating each charged-move minigame got (Nice, Great, Excellent), read from the frames play_android.py keeps of
every minigame (FOLDER/minigame-<time>-<move>/), by move.

    python3 scripts/live/ratings.py C:\\pogo-media\\live\\20261107-training [--since EPOCH]

The game writes the running rating at the top of the screen during the swipe; the last one written is the result.
"""
from __future__ import annotations

import argparse
import re
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

WORDS = ("NICE", "GREAT", "EXCELLENT")


def rating(folder: Path, ocr) -> str | None:
    seen = []
    for f in sorted(folder.glob("*.jpg")):
        a = np.asarray(Image.open(f).convert("RGB"))
        res, _ = ocr(a[int(0.20 * a.shape[0]):int(0.36 * a.shape[0])])
        for r in res or []:
            w = re.sub("[^A-Z]", "", r[1].upper())
            if w in WORDS and (not seen or seen[-1] != w):
                seen.append(w)
    return seen[-1] if seen else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folders", nargs="+")
    ap.add_argument("--since", type=int, default=0)
    a = ap.parse_args()
    from rapidocr_onnxruntime import RapidOCR
    ocr = RapidOCR()
    by_move = defaultdict(Counter)
    for root in a.folders:
        for d in sorted(Path(root).glob("minigame-*")):
            stamp, move = d.name.split("-")[1], d.name.split("-", 2)[2]
            if int(stamp) < a.since:
                continue
            by_move[move][rating(d, ocr) or "none read"] += 1
    total = Counter()
    for move, c in sorted(by_move.items()):
        total.update(c)
        n = sum(c.values())
        print(f"{move:14s} {n:3d} minigames: " + ", ".join(f"{w} {c[w]}" for w in ("EXCELLENT", "GREAT", "NICE", "none read") if c[w]))
    n = sum(total.values())
    print(f"{'all':14s} {n:3d} minigames: Excellent {total['EXCELLENT']} ({100 * total['EXCELLENT'] / max(n, 1):.0f}%)")


if __name__ == "__main__":
    main()
