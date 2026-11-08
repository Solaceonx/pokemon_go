#!/usr/bin/env python3
"""Team Leader training battles back to back, hands-off (task 40): fixed taps through the menus, each battle played
by scripts/live/play_android.py with the repo's engine, every battle recorded.

    POGO_SCRCPY_DIR=... python3 scripts/live/train_loop.py --serial ZY22JPBNMW --battles 5 [--leaders spark candela blanche]

Start it from the Battle tab scrolled down to Training (where the game puts you after a training battle). Each
round: tap the leader, BATTLE, Great League, then USE THIS PARTY only when its green button is there; after the
battle, the check under the result. No text reading in the menus. It stops if the party button is not where it
should be, saving the screen.
"""
from __future__ import annotations

import argparse
import io
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from pogo.android import _tools  # noqa: E402

LEADERS = {"blanche": (280, 1956), "candela": (540, 1956), "spark": (800, 1956)}  # pixels of the 1080 x 2400 screen
LEADER_BATTLE, GREAT_LEAGUE, USE_PARTY, CHECK = (540, 1734), (540, 1080), (540, 2090), (540, 2256)


def is_white(c):
    return min(c) > 235


def is_teal(c):
    return c[0] < 80 and 105 < c[1] < 165 and 115 < c[2] < 175


def game_in_front(adb: str, serial: str) -> bool:
    """Whether Pokémon GO is the app in front (Android's own window focus): every tap and swipe here needs it. On
    the home screen the pixel tests below can pass by chance (2026-11-07: the game crashed to it)."""
    out = subprocess.run([adb, "-s", serial, "shell", "dumpsys window | grep mCurrentFocus"],
                         capture_output=True, text=True).stdout
    return "com.nianticlabs.pokemongo" in out


def leaders_in_place(im) -> bool:
    """Whether the three Team Leaders are where LEADERS taps them: the coloured backs of their portraits, beside each
    tap point, as on the Battle tab scrolled to the bottom (measured 2026-11-08: Blanche's light blue, Candela's pink,
    Spark's yellow). The Training card can show higher up when the tab is not scrolled all the way; then the taps
    land elsewhere (2026-11-08: they opened the Nearby Battle QR code)."""
    p = lambda x, y: im.getpixel((x, y))[:3]
    b, c, s = p(210, 1956), p(470, 1956), p(870, 1956)
    return b[2] > b[0] + 30 and c[0] > c[1] + 15 and c[0] > c[2] + 15 and s[2] < s[1] - 30 and s[0] > 200


def to_training(adb: str, serial: str, shot, steps: int = 16) -> bool:
    """From whatever the phone shows after a battle back to the Battle tab scrolled to Training, by a few pixels of
    each screen (measured 2026-11-07): Training has the white card at (100, 1780) under the teal tab bar; the top of
    the Battle tab is white there too but has no teal bar; the map has the red Poke Ball button; the main menu is
    pale green with the teal Battle icon; a result screen is dark with the teal check button."""
    away = 0
    for _ in range(steps):
        if not game_in_front(adb, serial):
            away += 1
            if away > 20:  # about 30 s with the game not in front: stop, touching nothing
                return False
            time.sleep(1.5)
            continue
        im = shot()
        p = lambda x, y: im.getpixel((x, y))
        if is_white(p(100, 1780)) and is_teal(p(540, 140)):
            if leaders_in_place(im):
                return True
            # the Battle tab, the Training card not yet at the bottom: scroll on
            subprocess.run([adb, "-s", serial, "shell", "input", "swipe", "540", "1500", "540", "700", "600"]); time.sleep(1.3)
            continue
        if p(540, 2205)[0] > 200 and p(540, 2205)[1] < 100:  # the map: open the main menu
            subprocess.run([adb, "-s", serial, "shell", "input", "tap", "540", "2248"]); time.sleep(1.8)
        elif min(p(100, 600)) > 200 and p(100, 600)[1] > 245 and is_teal(p(840, 1484)):  # the main menu: Battle
            subprocess.run([adb, "-s", serial, "shell", "input", "tap", "840", "1484"]); time.sleep(2.5)
        elif is_white(p(100, 1780)):  # the Battle tab, not scrolled down to Training yet
            subprocess.run([adb, "-s", serial, "shell", "input", "swipe", "540", "1900", "540", "700", "600"]); time.sleep(1.3)
        elif max(p(100, 1780)) < 60 and is_teal(p(540, 2256)):  # a result screen: the check under it
            subprocess.run([adb, "-s", serial, "shell", "input", "tap", "540", "2256"]); time.sleep(2.0)
        else:
            time.sleep(1.5)  # something is loading
    return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--serial", required=True)
    ap.add_argument("--battles", type=int, default=5)
    ap.add_argument("--leaders", nargs="+", default=["spark", "candela", "blanche"])
    ap.add_argument("--media", default=r"C:\pogo-media\live")
    ap.add_argument("--team", default=str(ROOT / "data" / "alt_team.json"), help="the party's team file (play_android)")
    a = ap.parse_args()
    adb, _ = _tools(None)
    media = Path(a.media) / (time.strftime("%Y%m%d") + "-training")
    media.mkdir(parents=True, exist_ok=True)
    def tap(p):
        if not game_in_front(adb, a.serial):  # never a tap outside the game
            print(json.dumps({"stopped": "Pokémon GO is not the app in front"}), flush=True)
            raise SystemExit(1)
        subprocess.run([adb, "-s", a.serial, "shell", "input", "tap", str(p[0]), str(p[1])])

    def pixel(x, y):
        from PIL import Image
        png = subprocess.run([adb, "-s", a.serial, "exec-out", "screencap", "-p"], capture_output=True).stdout
        im = Image.open(io.BytesIO(png)).convert("RGB")
        return im, im.getpixel((x, y))

    def shot():
        return pixel(0, 0)[0]

    results = []
    for k in range(a.battles):
        if not to_training(adb, a.serial, shot):
            path = media / f"stopped-{time.strftime('%H%M%S')}.png"
            shot().save(path)
            print(json.dumps({"stopped": "could not find the way back to Training", "frame": str(path)}), flush=True)
            break
        leader = a.leaders[k % len(a.leaders)]
        tap(LEADERS[leader]); time.sleep(2.2)
        tap(LEADER_BATTLE); time.sleep(2.2)
        tap(GREAT_LEAGUE); time.sleep(2.6)
        im, (r, g, b) = pixel(*USE_PARTY)
        if not (g > 180 and r < 150):  # not the party screen: stop rather than tap blind
            path = media / f"stopped-{time.strftime('%H%M%S')}.png"
            im.save(path)
            print(json.dumps({"stopped": "the party screen was not where expected", "frame": str(path)}), flush=True)
            break
        done = subprocess.run([sys.executable, str(ROOT / "scripts" / "live" / "play_android.py"), "--serial", a.serial,
                               "--live", "--start-tap", "0.5", "0.871", "--frames", str(media), "--team", a.team],
                              capture_output=True, text=True, cwd=ROOT)
        line = next((l for l in reversed(done.stdout.splitlines()) if l.startswith("{")), "{}")
        out = json.loads(line)
        results.append({"leader": leader, "result": out.get("result"), "log": out.get("log")})
        print(json.dumps(results[-1]), flush=True)
        time.sleep(2.0)  # the way back to Training is found at the top of the next round
    for rec in sorted(media.glob("battle-*.h264")):
        if not rec.with_suffix(".mp4").exists():
            subprocess.run([sys.executable, str(ROOT / "scripts" / "live" / "to_mp4.py"), str(rec)], cwd=ROOT)
    print(json.dumps({"done": len(results), "wins": sum(r["result"] == "win" for r in results),
                      "losses": sum(r["result"] == "loss" for r in results)}), flush=True)


if __name__ == "__main__":
    main()
