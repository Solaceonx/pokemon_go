#!/usr/bin/env python3
"""Run the live player (dry run: taps only logged, none sent) on a recorded battle replayed at its own speed, to test
its reading and its logic without the phone (task 40). Every fix to scripts/live/play_android.py was checked this way.

    python3 scripts/live/replay.py STAMP [MEDIA_FOLDER] [TEAM_FILE]

The recording is MEDIA_FOLDER/battle-STAMP.h264 and .times (default C:/pogo-media/live/20261107-training); the log
goes to runs/replay/STAMP-replay.jsonl. The touches the minigame stroke would make are dropped, so the recording's
own minigames play out as they did."""
import json
import sys
import threading
import time
from pathlib import Path

import av

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts" / "live"))
import play_android as pa  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402

stem = sys.argv[1]
media = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("C:/pogo-media/live/20261107-training")


class ReplayPhone:
    def __init__(self):
        self.times = [float(l) for l in open(media / f"battle-{stem}.times")]
        self._latest = None
        self._lock = threading.Lock()
        self.actions = 0
        self.size = (540, 1200)
        self.finished = False
        threading.Thread(target=self._play, daemon=True).start()
        while self._latest is None:
            time.sleep(0.01)

    def _play(self):
        codec = av.CodecContext.create("h264", "r")
        t_start, rec_start, i = time.time(), self.times[0], 0
        for packet in codec.parse(open(media / f"battle-{stem}.h264", "rb").read()):
            for fr in codec.decode(packet):
                due = t_start + (self.times[min(i, len(self.times) - 1)] - rec_start)
                i += 1
                wait = due - time.time()
                if wait > 0:
                    time.sleep(wait)
                a = fr.to_ndarray(format="rgb24")
                with self._lock:
                    self._latest = (a, time.time())
        self.finished = True

    def frame(self):
        with self._lock:
            return self._latest

    def next_frame(self, after, timeout=1.0):
        deadline = time.time() + timeout
        while True:
            rgb, when = self.frame()
            if when > after or time.time() > deadline:
                return rgb, when
            time.sleep(0.003)

    def tap(self, x, y, hold_ms=40):
        self.actions += 1
        return {"ok": True}

    def _send(self, *a):
        pass

    def close(self):
        pass


gd = GameData()
team = pa.load_team(gd, Path(sys.argv[3]) if len(sys.argv) > 3 else ROOT / "data" / "alt_team.json")  # [TEAM_FILE]
log = pa.Log(ROOT / "runs" / "replay" / f"{stem}-replay.jsonl")
phone = ReplayPhone()
player = pa.Player(phone, gd, team, False, log, None)
result = player.run(timeout=(phone.times[-1] - phone.times[0]) + 5)
player.done = True
log("end", player.now(), result=result, foes=player.tracker.order)
print(json.dumps({"result": result, "foes": player.tracker.order, "log": str(log.path)}))
