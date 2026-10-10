#!/usr/bin/env python3
"""Check the link to the phone: permissions, screenshot, text reading, and (on request) input.

    python3 scripts/probe.py                 look only: status, one screenshot, text, timing
    python3 scripts/probe.py --tap 0.5 0.9   also send one tap and report whether the screen changed
    python3 scripts/probe.py --drag          also send one drag across the middle of the screen

Open iPhone Mirroring with the phone connected first. Input moves your Mac's pointer.
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pogo.phone import Phone, PhoneError  # noqa: E402


def difference(a, b) -> float:
    """Mean absolute pixel difference between two screenshots, on a 0-255 scale."""
    if a.size != b.size:
        return float("inf")
    return float(np.abs(np.asarray(a, dtype=np.int16) - np.asarray(b, dtype=np.int16)).mean())


def check_input(phone: Phone, label: str, action) -> None:
    """Compare how much the screen changes on its own with how much it changes after the action."""
    before = phone.shot()
    time.sleep(0.6)
    idle = phone.shot()
    action()
    time.sleep(0.6)
    after = phone.shot()
    noise = difference(before.image, idle.image)
    change = difference(idle.image, after.image)
    print(f"\n{label}: screen change {change:.1f} against {noise:.1f} with no input (0-255 scale)")
    print(f"  before: {idle.path}\n  after:  {after.path}")
    print("  Compare the two images to judge whether the input reached the phone.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tap", nargs=2, type=float, metavar=("X", "Y"), help="send one tap at this screen fraction")
    parser.add_argument("--drag", action="store_true", help="send one horizontal drag across the middle of the screen")
    parser.add_argument("--request", action="store_true", help="ask macOS to show the permission prompts")
    args = parser.parse_args()

    phone = Phone()
    status = phone.doctor(request=args.request)
    print("status:", status)
    if not status["mirroring_running"] or "window" not in status:
        print("Open iPhone Mirroring and connect the phone, then run this again.")
        return 1
    if not status["screen_recording"]:
        print("Screen Recording permission is missing for the app running this script.")
        print("Run with --request, switch it on in System Settings > Privacy & Security, then restart that app.")
        return 1

    try:
        shot = phone.shot(ocr=True)
        win = status["window"]
        print(f"\nwindow {win['w']:.0f} x {win['h']:.0f} points, screenshot {shot.image.width} x {shot.image.height} px")
        print(f"saved {shot.path}")
        print(f"\ntext on screen ({len(shot.text)} lines):")
        for t in sorted(shot.text, key=lambda t: (t.y, t.x)):
            print(f"  ({t.x + t.w / 2:.2f}, {t.y + t.h / 2:.2f})  {t.text!r}  conf {t.conf:.2f}")

        capture = [phone.shot().capture_ms for _ in range(5)]
        t0 = time.perf_counter()
        fast = phone.shot(ocr=True, fast=True)
        round_trip = (time.perf_counter() - t0) * 1000
        print(f"\ncapture alone: median {statistics.median(capture):.0f} ms inside the helper")
        print(f"text reading: {shot.ocr_ms:.0f} ms accurate, {fast.ocr_ms:.0f} ms fast")
        print(f"one full look from Python (capture + fast text): {round_trip:.0f} ms")

        if args.tap or args.drag:
            if not status["accessibility"]:
                print("\nAccessibility permission is missing, so input would be dropped. Run with --request.")
                return 1
            if args.tap:
                x, y = args.tap
                check_input(phone, f"tap at ({x}, {y})", lambda: phone.tap(x, y))
            if args.drag:
                check_input(phone, "drag", lambda: phone.drag(0.75, 0.5, 0.25, 0.5, ms=250))
    except PhoneError as err:
        print("error:", err)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
