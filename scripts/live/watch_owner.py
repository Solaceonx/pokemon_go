#!/usr/bin/env python3
"""Watch the owner play on the Android phone, sending nothing: the screen as play_android records it (OUT.h264 and
OUT.times, each frame's arrival on this computer's clock) and every touch on the screen from the phone's own input
events (adb getevent, read only), to OUT.touches.jsonl: {"t": this computer's clock, "x", "y": shares of the
screen, "down": the finger on}. For learning the owner's minigame swipes (2026-11-24: Stone Edge, which no stroke
of ours swiped Excellent more than two times in three).

    POGO_SCRCPY_DIR=... python3 scripts/live/watch_owner.py OUT --serial ZY22JPBNMW --seconds 900

The touchscreen is found by its ABS_MT_POSITION_X axis; its range (getevent -p) scales the positions. Times: each
event's own time on the phone, put on this computer's clock by the smallest gap seen between an event's phone time
and its arrival here (the arrival less any delay in the pipe).
"""
from __future__ import annotations

import argparse
import json
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pogo.android import Android, _tools  # noqa: E402


def touchscreen(adb: str, serial: str):
    """(device path, x max, y max) of the screen's touch input."""
    out = subprocess.run([adb, "-s", serial, "shell", "getevent", "-pl"], capture_output=True, text=True).stdout
    dev, found = None, {}
    for line in out.splitlines():
        m = re.match(r"add device \d+: (\S+)", line)
        if m:
            dev = m.group(1)
        m = re.search(r"(ABS_MT_POSITION_[XY])\s*:.*max (\d+)", line)
        if m and dev:
            found.setdefault(dev, {})[m.group(1)] = int(m.group(2))
    for d, axes in found.items():
        if len(axes) == 2:
            return d, axes["ABS_MT_POSITION_X"], axes["ABS_MT_POSITION_Y"]
    raise SystemExit("no touchscreen found")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--serial", required=True)
    ap.add_argument("--seconds", type=float, default=900)
    a = ap.parse_args()
    adb, _ = _tools(None)
    dev, xmax, ymax = touchscreen(adb, a.serial)
    phone = Android(a.serial, record=a.out, dry_run=True)  # dry run: nothing can be sent
    phone.start()
    ev = subprocess.Popen([adb, "-s", a.serial, "shell", "getevent", "-lt", dev], stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, text=True, bufsize=1)
    print(json.dumps({"recording": a.out, "touchscreen": dev}), flush=True)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())  # kill: stop and close the files properly
    f = open(f"{a.out}.touches.jsonl", "w")

    def read_touches():
        offset = None  # this computer's clock less the phone's
        x = y = None
        down = False
        for line in ev.stdout:
            now = time.time()
            m = re.match(r"\[\s*([\d.]+)\]\s+\S+\s+(\S+)\s+(\S+)", line)
            if not m:
                continue
            t_dev, code, value = float(m.group(1)), m.group(2), m.group(3)
            offset = now - t_dev if offset is None else min(offset, now - t_dev)
            if code == "ABS_MT_POSITION_X":
                x = int(value, 16) / xmax
            elif code == "ABS_MT_POSITION_Y":
                y = int(value, 16) / ymax
            elif code == "BTN_TOUCH":
                down = value == "DOWN"
            elif code == "SYN_REPORT" and x is not None:
                f.write(json.dumps({"t": round(t_dev + offset, 4), "x": round(x, 4), "y": round(y, 4),
                                    "down": down}) + "\n")
                f.flush()

    threading.Thread(target=read_touches, daemon=True).start()
    try:
        stop.wait(a.seconds)
    except KeyboardInterrupt:
        pass
    ev.terminate()
    phone.close()
    f.close()
    print(json.dumps({"done": a.out}), flush=True)


if __name__ == "__main__":
    main()
