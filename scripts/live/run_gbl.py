#!/usr/bin/env python3
"""Play GO Battle League on the Android phone battle after battle (task 40): the menus by their text, each battle by
scripts/live/play_android.py with the repo's engine, every battle recorded.

    POGO_SCRCPY_DIR=... python3 scripts/live/run_gbl.py --serial ZY22JPBNMW --wins 3 --max-battles 25

Between battles the screen is read with OCR and one known button is tapped: NEXT BATTLE, the check under a result,
LET'S GO, BATTLE in the free (Basic Rewards) tier, Great League, USE THIS PARTY. Nothing with PREMIUM, SHOP, COIN,
PASS or BUY on the screen near it is ever tapped. It stops, saving the screen, at rewards that need collecting (an
encounter needs Poké Balls: the owner's call), the daily limit, the wins or battles asked for, or any screen it does
not know. Battles are recorded under --media (raw stream, times, and an .mp4) and logged in runs/live/.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402

from pogo import android_screen as screen  # noqa: E402
from pogo.android import _tools  # noqa: E402

NEVER = ("PREMIUM", "SHOP", "COIN", "PASS", "BUY", "PURCHASE", "SETTING", "TRANSFER", "POWERUP", "EVOLVE")
NEXT_BATTLE, CHECK, LETS_GO, USE_PARTY, GREAT = (0.5, 0.851), (0.5, 0.94), (0.5, 0.889), (0.5, 0.871), (0.5, 0.45)


class Runner:
    def __init__(self, serial: str, media: Path, wins: int, max_battles: int, log):
        self.serial, self.media, self.target, self.max_battles, self.log = serial, media, wins, max_battles, log
        self.adb, _ = _tools(None)
        from rapidocr_onnxruntime import RapidOCR
        self.ocr = RapidOCR()
        self.wins = self.losses = self.battles = 0

    def shot(self) -> np.ndarray:
        from PIL import Image
        import io
        png = subprocess.run([self.adb, "-s", self.serial, "exec-out", "screencap", "-p"], capture_output=True).stdout
        return np.asarray(Image.open(io.BytesIO(png)).convert("RGB"))

    def read(self, a: np.ndarray) -> list:
        """(text, x, y) for each line read, positions as shares of the screen."""
        h, w = a.shape[:2]
        small = a[::2, ::2]
        res, _ = self.ocr(small)
        out = []
        for box, text, conf in res or []:
            xs, ys = [p[0] for p in box], [p[1] for p in box]
            out.append((text, sum(xs) / len(xs) * 2 / w, sum(ys) / len(ys) * 2 / h))
        return out

    def tap(self, point, why: str, words: list) -> None:
        near = [t for t, x, y in words if abs(y - point[1]) < 0.06 and any(n in re.sub("[^A-Z]", "", t.upper()) for n in NEVER)]
        if near:
            raise RuntimeError(f"refused to tap {why} at {point}: next to {near}")
        focus = subprocess.run([self.adb, "-s", self.serial, "shell", "dumpsys window | grep mCurrentFocus"],
                               capture_output=True, text=True).stdout
        if "com.nianticlabs.pokemongo" not in focus:  # never a tap outside the game (it can crash to the home screen)
            raise RuntimeError(f"refused to tap {why}: Pokémon GO is not the app in front")
        h, w = 2400, 1080
        subprocess.run([self.adb, "-s", self.serial, "shell", "input", "tap", str(int(point[0] * w)), str(int(point[1] * h))])
        self.log("menu_tap", why=why, point=point)

    def battle_button(self, words) -> list:
        """BATTLE in the Basic Rewards box (above PREMIUM REWARDS, if that is on screen), as [(x, y)]."""
        premium = min((y for t, x, y in words if "PREMIUM" in t.upper()), default=1.0)
        return [(x, y) for t, x, y in words if re.sub("[^A-Z]", "", t.upper()) == "BATTLE" and 0.6 < y < premium]

    def stop(self, why: str, a: np.ndarray) -> str:
        from PIL import Image
        path = self.media / f"stopped-{time.strftime('%H%M%S')}.png"
        Image.fromarray(a).save(path)
        self.log("stop", why=why, frame=str(path))
        return why

    def play(self, start_tap=None) -> str | None:
        cmd = [sys.executable, str(ROOT / "scripts" / "live" / "play_android.py"), "--serial", self.serial, "--live",
               "--frames", str(self.media)]
        if start_tap:
            cmd += ["--start-tap", *map(str, start_tap)]
        self.log("battle_start", start_tap=start_tap)
        done = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
        line = next((l for l in reversed(done.stdout.splitlines()) if l.startswith("{")), None)
        result = json.loads(line)["result"] if line else None
        self.battles += 1
        self.wins += result == "win"
        self.losses += result == "loss"
        self.log("battle_end", result=result, wins=self.wins, losses=self.losses, stderr=done.stderr[-300:] if not line else "")
        for rec in sorted(self.media.glob("battle-*.h264")):
            if not rec.with_suffix(".mp4").exists():
                subprocess.run([sys.executable, str(ROOT / "scripts" / "live" / "to_mp4.py"), str(rec)], cwd=ROOT)
        return result

    def run(self) -> str:
        unknown = 0
        while True:
            if self.wins >= self.target:
                return f"{self.wins} wins reached"
            if self.battles >= self.max_battles:
                return f"{self.battles} battles played"
            a = self.shot()
            words = self.read(a)
            text = " ".join(t for t, _, _ in words).upper()
            flat = re.sub("[^A-Z0-9/]", "", text)
            self.log("screen", text=text[:200])
            # The day's limit, in the words the game uses for it (not the league card's "Max CP: No limit").
            if any(p in flat for p in ("COMEBACKTOMORROW", "BATTLEDALOT", "DAILYLIMIT", "LIMITFORTODAY",
                                       "MAXIMUMNUMBEROFBATTLES", "REACHEDTHELIMIT", "REACHEDYOURLIMIT")):
                return self.stop("daily limit", a)
            if screen.header_visible(a[::2, ::2]) and len(screen.bars(a[::2, ::2])) >= 1:
                self.play()  # a battle already under way
            elif "USETHISPARTY" in flat:
                self.play(start_tap=USE_PARTY)
            elif "NEXTBATTLE" in flat:
                self.tap(NEXT_BATTLE, "next battle", words)
            elif "CHOOSEYOURLEAGUE" in flat:
                card = next(((x, y) for t, x, y in words if "GREATLEAGUE" in re.sub("[^A-Z]", "", t.upper())), None)
                if card is None:
                    return self.stop("no Great League card", a)
                self.tap((0.5, card[1] + 0.02), "great league", words)
            elif "LETSGO" in flat:
                self.tap(LETS_GO, "let's go", words)
            elif "TRAINING" in flat and "BLANCHE" in flat and "GOBATTLELEAGUE" not in flat:
                # the Battle tab scrolled down to Training (after training battles): back up to the league's card
                subprocess.run([self.adb, "-s", self.serial, "shell", "input", "swipe", "540", "700", "540", "1900", "600"])
                self.log("menu_swipe", why="up to the league card")
            elif "COLLECT" in flat and not ("GOBATTLELEAGUE" in flat and self.battle_button(words)):
                return self.stop("rewards to collect (an encounter needs Poke Balls: the owner's call)", a)
            elif "GOBATTLELEAGUE" in flat and "BATTLE" in flat:
                # rewards waiting to be collected are left for the owner: the set goes on without them
                button = self.battle_button(words)
                if not button:
                    return self.stop("no Battle button", a)
                self.tap((0.5, button[-1][1]), "battle (basic rewards)", words)
            elif ("YOUWIN" in flat or "GOODEFFORT" in flat) and "NEXTBATTLE" not in flat:
                self.tap(CHECK, "continue after the result", words)
            elif "FINDING" in flat or "VS" in flat or re.search(r"\b[123]\b", text):
                time.sleep(1.0)
                continue
            else:
                unknown += 1
                if unknown >= 3:
                    return self.stop("a screen I do not know", a)
                time.sleep(1.5)
                continue
            unknown = 0
            time.sleep(2.5)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--serial", required=True)
    ap.add_argument("--wins", type=int, default=3)
    ap.add_argument("--max-battles", type=int, default=25)
    ap.add_argument("--media", default=r"C:\pogo-media\live")
    a = ap.parse_args()
    media = Path(a.media) / time.strftime("%Y%m%d")
    media.mkdir(parents=True, exist_ok=True)
    path = ROOT / "runs" / "live" / f"runner-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    f = open(path, "w", encoding="utf-8")

    def log(kind, **data):
        f.write(json.dumps({"time": time.strftime("%H:%M:%S"), "kind": kind, **data}, default=str) + "\n")
        f.flush()
        print(kind, json.dumps(data, default=str)[:200], flush=True)

    runner = Runner(a.serial, media, a.wins, a.max_battles, log)
    why = runner.run()
    log("done", why=why, wins=runner.wins, losses=runner.losses, battles=runner.battles)


if __name__ == "__main__":
    main()
