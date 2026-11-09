#!/usr/bin/env python3
"""The end of a GO Battle League set on the phone (task 40): claim the rank rewards, tap through the reward screens,
catch a reward encounter with Ultra Balls (the owner's word, 2026-11-09: "you are allowed to do all of bryan's
battles, including catching pokemon and claiming items for end of set rewards"), and, with --restart, restart the
app and come back to the Battle tab (the owner: "maybe refresh the app after every set of 5").

    POGO_SCRCPY_DIR=... python3 scripts/live/set_end.py --serial ZY22JPBNMW [--restart] [--steps 80]

Every step reads the screen (OCR), logs what it saw and did to runs/live/setend-<time>.jsonl, and saves the screen
under --media. It stops, saving the screen, at anything it does not know, and taps nothing with PREMIUM, SHOP, COIN,
PASS or BUY near it (run_gbl.NEVER). It ends on the Battle tab with the league card's BATTLE button showing.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "live"))
from pogo.android import _tools  # noqa: E402
from run_gbl import NEVER  # noqa: E402

GAME = "com.nianticlabs.pokemongo"
DISMISSAL = ("DISMISS", "OK", "CLOSE", "GOTIT")  # words that close a notice; never SEE DETAILS
W, H = 1080, 2400


class Stuck(RuntimeError):
    """The same tap again and again with nothing changing: a restart of the app may clear it."""


class SetEnd:
    def __init__(self, serial: str, media: Path, log):
        self.serial, self.media, self.log = serial, media, log
        self.adb, _ = _tools(None)
        from rapidocr_onnxruntime import RapidOCR
        self.ocr = RapidOCR()
        self.throws = 0
        self.caught = False
        self.collected = 0
        self._ultra = False
        self.same, self.last_why = 0, None

    def adb_run(self, *args, **kw):
        return subprocess.run([self.adb, "-s", self.serial, *args], capture_output=True, **kw)

    def shot(self) -> np.ndarray:
        from PIL import Image
        png = self.adb_run("exec-out", "screencap", "-p").stdout
        return np.asarray(Image.open(io.BytesIO(png)).convert("RGB"))

    def read(self, a: np.ndarray) -> list:
        """(text, x, y) for each line read, positions as shares of the screen."""
        h, w = a.shape[:2]
        res, _ = self.ocr(a[::2, ::2])
        out = []
        for box, text, conf in res or []:
            xs, ys = [p[0] for p in box], [p[1] for p in box]
            out.append((text, sum(xs) / len(xs) * 2 / w, sum(ys) / len(ys) * 2 / h))
        return out

    def in_front(self) -> bool:
        out = self.adb_run("shell", "dumpsys window | grep mCurrentFocus", text=True).stdout
        return GAME in out

    def tap(self, x: float, y: float, why: str, words: list) -> None:
        self.same = self.same + 1 if why == self.last_why else 1
        self.last_why = why
        if self.same > 4:
            # 2026-11-09: CLAIM RANK REWARDS stayed up after the rank's rewards came (a server hitch, "ERROR CLAIMING
            # RANK REWARDS"), tapped 25 times; a restart clears it
            raise Stuck(f"tapped {why} five times running with nothing changing")
        near = [t for t, _, ty in words if abs(ty - y) < 0.06 and any(n in re.sub("[^A-Z]", "", t.upper()) for n in NEVER)]
        if near:
            raise RuntimeError(f"refused to tap {why}: next to {near}")
        if not self.in_front():
            raise RuntimeError(f"refused to tap {why}: Pokémon GO is not the app in front")
        self.adb_run("shell", "input", "tap", str(int(x * W)), str(int(y * H)))
        self.log("tap", why=why, point=[round(x, 3), round(y, 3)])

    def swipe(self, x0, y0, x1, y1, ms: int, why: str) -> None:
        if not self.in_front():
            raise RuntimeError(f"refused to swipe {why}: Pokémon GO is not the app in front")
        self.adb_run("shell", "input", "swipe", str(int(x0 * W)), str(int(y0 * H)), str(int(x1 * W)), str(int(y1 * H)), str(ms))
        self.log("swipe", why=why)

    def save(self, a: np.ndarray, why: str) -> str:
        from PIL import Image
        path = self.media / f"setend-{time.strftime('%H%M%S')}-{why}.png"
        Image.fromarray(a).save(path)
        return str(path)

    @staticmethod
    def find(words: list, *keys: str):
        """The first line whose letters (upper case, nothing else) contain one of keys, as (x, y), or None."""
        for t, x, y in words:
            flat = re.sub("[^A-Z]", "", t.upper())
            if any(k in flat for k in keys):
                return x, y
        return None

    # the encounter

    def encounter(self, a: np.ndarray, words: list) -> bool:
        """A reward encounter: the Pokémon's name and CP in the upper half ("Vulpix / CP 504", at 35% of the height,
        2026-11-09) and none of the league card's or a Pokémon page's words. Throws one Ultra Ball."""
        flat = re.sub("[^A-Z]", "", " ".join(t for t, _, _ in words).upper())
        if "GOBATTLELEAGUE" in flat or "POWERUP" in flat or "EVOLVE" in flat or "TOTAL" in flat:
            return False
        if not any(y < 0.5 and re.search(r"CP\s*\d{2,4}", t.upper()) for t, x, y in words):
            return False
        if self.throws >= 20:
            raise RuntimeError("20 balls thrown and not caught: stopping for the owner")
        if not self.ultra_chosen(words):
            return True
        # a flick straight up from the ball (at 83% of the height) toward the Pokémon (2026-11-09: caught on the
        # first throw this way)
        self.swipe(0.5, 0.831, 0.5, 0.367, 130, "throw an Ultra Ball")
        self.throws += 1
        time.sleep(9.0)  # the ball's flight and the shakes
        return True

    def ultra_chosen(self, words: list) -> bool:
        """Make the Ultra Ball the ball in hand: the ball button at the bottom right opens the Poké Balls tray (a
        shop button sits at its top right: never touched), then Ultra Ball. True once it is in hand."""
        if self._ultra:
            return True
        self.tap(0.877, 0.906, "the Poké Ball button", [w for w in words if w[1] > 0.6])
        time.sleep(2.0)
        b = self.shot()
        bw = self.read(b)
        at = next(((x, y) for t, x, y in bw if re.sub("[^A-Z]", "", t.upper()) == "ULTRABALL"), None)
        if at is None:
            self.log("no_ultra_ball", text=" ".join(t for t, _, _ in bw)[:200], frame=self.save(b, "no-ultra"))
            self.adb_run("shell", "input", "keyevent", "4")  # back: close the tray and throw what is in hand
            time.sleep(1.5)
            self._ultra = True
            return False
        self.tap(at[0], at[1] - 0.05, "Ultra Ball", [w for w in bw if w[1] > 0.7])  # its ball, above its name
        self._ultra = True
        time.sleep(2.0)
        return False  # read the encounter again before throwing

    def reward_tile(self, words: list) -> bool:
        """The finished set's rewards on the league card, each a tile with COLLECT under it: tap the first tile
        (above its label; tapping the label does nothing). True when one was tapped."""
        labels = sorted(((x, y) for t, x, y in words if re.sub("[^A-Z]", "", t.upper()) == "COLLECT"), key=lambda p: p[0])
        if not labels:
            return False
        x, y = labels[0]
        self.tap(x, y - 0.05, "collect a reward", [w for w in words if abs(w[2] - (y - 0.05)) < 0.06 and abs(w[1] - x) < 0.15])
        self.collected += 1
        return True

    # the loop

    def run(self, steps: int) -> str:
        unknown = 0
        for _ in range(steps):
            a = self.shot()
            words = self.read(a)
            text = " ".join(t for t, _, _ in words).upper()
            flat = re.sub("[^A-Z0-9/]", "", text)
            self.log("screen", text=text[:240])
            exact = {re.sub("[^A-Z]", "", t.upper()): (x, y) for t, x, y in words}
            if ("GOBATTLELEAGUE" in flat and "COLLECT" not in exact and "CLAIMRANKREWARDS" not in flat
                    and ("CHOOSEAREWARDTIER" in flat or re.search(r"[0-4]/5BATTLESPLAYED", flat))):
                return f"the league card offers a new set (collected {self.collected}, caught {self.caught})"
            if ("YOUWIN" in flat or "GOODEFFORT" in flat or "ITSADRAW" in flat) and "NEXTBATTLE" not in flat:
                self.tap(0.5, 0.94, "the check under the result", words)  # as run_gbl.py's CHECK
            elif "NEXTBATTLE" in flat:
                self.tap(*self.find(words, "NEXTBATTLE"), "next battle", words)
            elif "POWERUP" in flat or "EVOLVE" in flat:
                # the caught Pokémon's page: its buttons are never touched; back closes it
                self.adb_run("shell", "input", "keyevent", "4")
                self.log("key", why="back: close the Pokémon's page")
            elif "OK" in exact:
                if "CAUGHT" in flat or "TOTAL" in flat:
                    self.caught = True
                    self.log("caught", throws=self.throws)
                self.tap(*exact["OK"], "OK", words)
            elif "CLAIMRANKREWARDS" in flat:
                self.tap(*self.find(words, "CLAIMRANKREWARDS"), "claim rank rewards", words)
            elif "GOBATTLELEAGUE" in flat and self.reward_tile(words):
                time.sleep(3.0)  # the item flies off, or the encounter loads
            elif self.encounter(a, words):
                pass
            elif "TAPTOCONTINUE" in flat or "RANK" in flat:
                self.tap(0.5, 0.75, "continue past the rank", words)
            elif "TRAINING" in flat and "BLANCHE" in flat and "GOBATTLELEAGUE" not in flat:
                self.swipe(0.5, 0.29, 0.5, 0.79, 600, "up to the league card")
            else:
                unknown += 1
                if unknown >= 5:
                    path = self.save(a, "unknown")
                    raise RuntimeError(f"a screen I do not know ({text[:120]}); saved {path}")
                time.sleep(2.0)
                continue
            unknown = 0
            time.sleep(2.5)
        raise RuntimeError("out of steps")

    # restarting the app

    def restart(self) -> None:
        """Close the game and start it again, then from the map to the Battle tab."""
        self.log("restart")
        self.adb_run("shell", "am", "force-stop", GAME)
        time.sleep(3.0)
        self.adb_run("shell", "monkey", "-p", GAME, "-c", "android.intent.category.LAUNCHER", "1")
        time.sleep(30.0)
        self.to_battle_tab()

    def to_battle_tab(self) -> None:
        """From wherever the game is (its news cards, the map, the main menu) to the Battle tab."""
        for _ in range(40):
            if not self.in_front():
                time.sleep(3.0)
                continue
            a = self.shot()
            words = self.read(a)
            text = " ".join(t for t, _, _ in words).upper()
            flat = re.sub("[^A-Z0-9/]", "", text)
            self.log("screen", text=text[:240])
            p = lambda x, y: a[int(y * a.shape[0]), int(x * a.shape[1])].astype(int)
            if "GOBATTLELEAGUE" in flat or ("TRAINING" in flat and "BLANCHE" in flat):
                return  # the Battle tab
            if p(0.5, 0.919)[0] > 200 and p(0.5, 0.919)[1] < 100:  # the map: its red Poké Ball button
                self.tap(0.5, 0.937, "the main menu", words)
                time.sleep(2.0)
            elif ("POKDEX" in flat or "POKEDEX" in flat) and "ITEMS" in flat and self.find(words, "BATTLE"):  # the main menu
                # the Battle button's icon, under its label (pixels 840, 1484, as train_loop.py taps it). SHOP is in
                # the middle column (its label 0.05 below the icon's height), so the never-tap check is given the
                # words near the icon both ways
                self.tap(840 / W, 1484 / H, "Battle",
                         [w for w in words if abs(w[2] - 1484 / H) < 0.06 and abs(w[1] - 840 / W) < 0.15])
                time.sleep(3.0)
            elif any(re.sub("[^A-Z]", "", t.upper()) in DISMISSAL for t, _, _ in words):
                # a news card or notice (2026-11-09: "Twilight Trails ... SEE DETAILS / DISMISS" after the restart)
                t, x, y = next(w for w in words if re.sub("[^A-Z]", "", w[0].upper()) in DISMISSAL)
                self.tap(x, y, f"dismiss ({t})", words)
                time.sleep(2.0)
            else:
                time.sleep(3.0)  # loading, or a screen that passes by itself
        a = self.shot()
        raise RuntimeError(f"not back at the Battle tab after the restart; saved {self.save(a, 'restart')}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--serial", required=True)
    ap.add_argument("--restart", action="store_true")
    ap.add_argument("--steps", type=int, default=80)
    ap.add_argument("--media", default=r"C:\pogo-media\live")
    a = ap.parse_args()
    media = Path(a.media) / time.strftime("%Y%m%d")
    media.mkdir(parents=True, exist_ok=True)
    path = ROOT / "runs" / "live" / f"setend-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    f = open(path, "w", encoding="utf-8")
    names = []
    local = ROOT / "data" / "accounts" / "trainers.local.json"
    if local.exists():
        names = [n.upper() for n in json.loads(local.read_text(encoding="utf-8"))]

    def log(kind, **data):
        if "text" in data:
            for n in names:
                data["text"] = data["text"].replace(n, "(trainer)")
        f.write(json.dumps({"time": time.strftime("%H:%M:%S"), "kind": kind, **data}, default=str) + "\n")
        f.flush()
        print(kind, json.dumps(data, default=str)[:220], flush=True)

    s = SetEnd(a.serial, media, log)
    try:
        try:
            why = s.run(a.steps)
        except Stuck as stuck:
            log("stuck", why=str(stuck))
            s.restart()
            s.same, s.last_why = 0, None
            why = s.run(a.steps)
        if a.restart:
            s.restart()
            why += "; the app restarted and back at the Battle tab"
        log("done", why=why, caught=s.caught, throws=s.throws)
    except RuntimeError as error:
        log("stop", why=str(error), caught=s.caught, throws=s.throws)
        sys.exit(1)


if __name__ == "__main__":
    main()
