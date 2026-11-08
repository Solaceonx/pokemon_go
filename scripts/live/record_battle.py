#!/usr/bin/env python3
"""Record the phone's screen to JPEG frames for calibration: optionally one tap first (e.g. "Use this party"),
then no input at all.

    POGO_SCRCPY_DIR=... python3 scripts/live/record_battle.py OUT_DIR --serial ZY22JPBNMW --seconds 200 --fps 4 \
        [--tap 0.5 0.871]

Frames are named by milliseconds since the start. They stay out of git (captures and scratch folders only).
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from PIL import Image  # noqa: E402

from pogo.android import Android  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--serial")
    ap.add_argument("--seconds", type=float, default=200)
    ap.add_argument("--fps", type=float, default=4)
    ap.add_argument("--tap", type=float, nargs=2)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    phone = Android(serial=a.serial, max_actions=1)
    phone.start()
    try:
        start = time.time()
        if a.tap:
            phone.tap(*a.tap)
        saved, last = 0, 0.0
        while time.time() - start < a.seconds:
            rgb, when = phone.next_frame(last, timeout=1.0)
            if when > last:
                Image.fromarray(rgb).save(out / f"{int((when - start) * 1000):07d}.jpg", quality=85)
                saved += 1
                last = when
            time.sleep(max(0.0, 1 / a.fps - 0.01))
        print(f"saved {saved} frames to {out}")
    finally:
        phone.close()


if __name__ == "__main__":
    main()
