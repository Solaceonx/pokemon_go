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
        self.last_why, self.same = None, 0  # the last menu tap, and how many times running
        self.expect: list = []  # words the party screen must show before USE THIS PARTY (the party's names)
        self.team = None  # the team file passed to play_android
        self.party_swipes = 0
        # for the record (task 45): the account and team, the league and season as read, the standing last read
        self.account = self.team_key = self.league = self.season = None
        self.standing = None  # read on the league card since the last battle, for the next one
        self.last_log = None  # the last battle's log, for the standing read after it
        self.card_read = False
        local = ROOT / "data" / "accounts" / "trainers.local.json"  # trainer names, never written to the logs
        self.names = [n.upper() for n in json.loads(local.read_text(encoding="utf-8"))] if local.exists() else []

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
        self.same = self.same + 1 if why == self.last_why else 1
        self.last_why = why
        if self.same > 4:
            # the same tap five times running with no change: the button does nothing (2026-11-08: BATTLE greyed
            # out once a set's five battles were played, tapped 150 times)
            raise RuntimeError(f"tapped {why} five times running with nothing changing")
        h, w = 2400, 1080
        subprocess.run([self.adb, "-s", self.serial, "shell", "input", "tap", str(int(point[0] * w)), str(int(point[1] * h))])
        self.log("menu_tap", why=why, point=point)

    def battle_button(self, words) -> list:
        """BATTLE in the Basic Rewards box (above PREMIUM REWARDS, if that is on screen), as [(x, y)]."""
        premium = min((y for t, x, y in words if "PREMIUM" in t.upper()), default=1.0)
        return [(x, y) for t, x, y in words if re.sub("[^A-Z]", "", t.upper()) == "BATTLE" and 0.6 < y < premium]

    def read_standing(self, a: np.ndarray, words: list, flat: str) -> None:
        """The league card on the Battle tab: the season's wins and battles, the rank in its badge (left of WINS),
        the rating where it shows (from rank 20). Kept for the next battle's start row, and written after the last
        battle's log as its standing_after."""
        season = re.search(r"POK[A-Z]?MONGO([A-Z]+?)GREATLEAGUE", flat)  # flat has no colons or accents
        # the season's own figures, under CURRENT SEASON (the top of the tab has the lifetime ones; LAST SEASON follows)
        part = flat.split("CURRENTSEASON", 1)[1] if "CURRENTSEASON" in flat else ""
        part = re.split("ENDSIN|LASTSEASON|SEESCHEDULE", part)[0]
        wins, battles = re.search(r"WINS(\d+)", part), re.search(r"BATTLES(\d+)", part)
        rating = re.search(r"RATING(\d{3,4})", part)
        rank = None
        head = next((y for t, x, y in words if "CURRENTSEASON" in re.sub("[^A-Z]", "", t.upper())), None)
        at = next(((x, y) for t, x, y in words if "WINS" in t.upper() and head is not None and y > head), None)
        if at is not None:
            h, w = a.shape[:2]
            x0, x1 = max(0, int((at[0] - 0.40) * w)), max(1, int((at[0] - 0.04) * w))
            y0, y1 = max(0, int((at[1] - 0.05) * h)), min(h, int((at[1] + 0.08) * h))
            res, _ = self.ocr(a[y0:y1, x0:x1])
            digits = [re.sub("[^0-9]", "", r[1]) for r in res or []]
            rank = next((int(d) for d in digits if d and 1 <= int(d) <= 24), None)
        self.standing = {"rank": rank, "rating": int(rating.group(1)) if rating else None,
                         "season_wins": int(wins.group(1)) if wins else None,
                         "season_battles": int(battles.group(1)) if battles else None,
                         "read_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        if season and season.group(1) == "TWILIGHTTRAILS":
            self.season = "Twilight Trails"
        elif season:
            self.season = season.group(1).title()
        self.log("standing", **self.standing, season=self.season)
        if self.last_log is not None and self.last_log.exists():  # the battle before this reading: its after
            with self.last_log.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"t": None, "kind": "standing_after", **self.standing}) + "\n")
            self.last_log = None

    def stop(self, why: str, a: np.ndarray) -> str:
        from PIL import Image
        path = self.media / f"stopped-{time.strftime('%H%M%S')}.png"
        Image.fromarray(a).save(path)
        self.log("stop", why=why, frame=str(path))
        return why

    def play(self, start_tap=None) -> str | None:
        cmd = [sys.executable, str(ROOT / "scripts" / "live" / "play_android.py"), "--serial", self.serial, "--live",
               "--frames", str(self.media)]
        if self.team:
            cmd += ["--team", self.team]
        for flag, value in (("--account", self.account), ("--team-key", self.team_key), ("--league", self.league),
                            ("--season", self.season)):
            if value:
                cmd += [flag, value]
        if self.standing:
            cmd += ["--standing", json.dumps(self.standing)]
        self.standing = None  # used: the next battle's is read after this one
        self.card_read = False  # read the league card again when next on it
        if start_tap:
            cmd += ["--start-tap", *map(str, start_tap)]
        self.log("battle_start", start_tap=start_tap)
        self.last_why, self.same = None, 0
        done = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
        line = next((l for l in reversed(done.stdout.splitlines()) if l.startswith("{")), None)
        result = json.loads(line)["result"] if line else None
        self.last_log = Path(json.loads(line)["log"]) if line else None
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
            if re.search(r"\bVS\b", text):  # the matchmaking screen
                self.log("screen", text="(a VS screen: not logged, it shows the opponent's trainer name)")
            else:
                shown = text
                for name in self.names:
                    shown = shown.replace(name, "(trainer)")
                self.log("screen", text=shown[:200])
            # The day's limit, in the words the game uses for it (not the league card's "Max CP: No limit").
            if any(p in flat for p in ("COMEBACKTOMORROW", "BATTLEDALOT", "DAILYLIMIT", "LIMITFORTODAY",
                                       "MAXIMUMNUMBEROFBATTLES", "REACHEDTHELIMIT", "REACHEDYOURLIMIT")):
                return self.stop("daily limit", a)
            if screen.header_visible(a[::2, ::2]) and len(screen.bars(a[::2, ::2])) >= 1:
                self.play()  # a battle already under way
            elif "USETHISPARTY" in flat:
                # Only the party the team file is for (2026-11-08: a second party was saved, and the party screens
                # show the newest first): else the next saved party, a swipe left, and stop after three.
                missing = [w for w in self.expect if w not in flat]
                if missing:
                    self.log("party_check", missing=missing, text=text[:200])
                    if self.party_swipes >= 3:
                        return self.stop(f"the party with {self.expect} not found", a)
                    self.party_swipes += 1
                    subprocess.run([self.adb, "-s", self.serial, "shell", "input", "swipe", "900", "1700", "180", "1700", "400"])
                    time.sleep(1.5)
                    continue
                self.party_swipes = 0
                self.play(start_tap=USE_PARTY)
            elif "NEXTBATTLE" in flat:
                self.tap(NEXT_BATTLE, "next battle", words)
            elif "CHOOSEYOURLEAGUE" in flat:
                card = next(((x, y) for t, x, y in words if "GREATLEAGUE" in re.sub("[^A-Z]", "", t.upper())), None)
                if card is None:
                    return self.stop("no Great League card", a)
                name = next((t for t, x, y in words if "GREATLEAGUE" in re.sub("[^A-Z]", "", t.upper())), "")
                self.league = re.sub(r"\s+", " ", name.replace(":", ": ")).strip().title().replace(": ", ": ")
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
                if not self.card_read:
                    # the season's rank and figures are just below the fold: scroll down, read them, scroll back
                    # (BATTLE is then where it was)
                    self.card_read = True
                    subprocess.run([self.adb, "-s", self.serial, "shell", "input", "swipe", "540", "1700", "540", "1250", "900"])
                    time.sleep(1.5)
                    b = self.shot()
                    bw = self.read(b)
                    self.read_standing(b, bw, re.sub("[^A-Z0-9/]", "", " ".join(t for t, _, _ in bw).upper()))
                    subprocess.run([self.adb, "-s", self.serial, "shell", "input", "swipe", "540", "1250", "540", "1700", "900"])
                    time.sleep(1.5)
                    continue
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
    ap.add_argument("--team", help="the party's team file (play_android); default: the account's league party's")
    ap.add_argument("--account", help="data/accounts/<NAME>.json (default: data/accounts/current.txt)")
    ap.add_argument("--party-key", help="the account's party to play (default: its league party)")
    ap.add_argument("--expect", nargs="*", default=[], help="words the party screen must show, as read with spaces taken out: its CPs in order, CP1498CP1499CP1499 (it shows nicknames, not species)")
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
    sys.path.insert(0, str(ROOT / "scripts" / "live"))
    import accounts
    chosen = accounts.party(a.account, a.party_key)
    runner.expect = [w.upper() for w in a.expect] or [chosen["expect"]]
    runner.team = a.team or chosen["team"]
    runner.account = a.account or accounts.current()
    runner.team_key = f"{runner.account}/{chosen['key']}"
    log("account", account=a.account or accounts.current(), party=chosen["key"], team=runner.team, expect=runner.expect)
    try:
        why = runner.run()
    except RuntimeError as error:  # a refused tap: stop touching anything
        why = f"stopped: {error}"
    log("done", why=why, wins=runner.wins, losses=runner.losses, battles=runner.battles)


if __name__ == "__main__":
    main()
