#!/usr/bin/env python3
"""Icon sightings on our recorded minigames, for learn_type_pattern.py / learn_choreography.py (task 40; the PC's
scratch icon_map.py was never pushed, 2026-11-22). For each throw that started in a battle's log, every second frame
of the recording from its Get Ready! to 5.5 s after is searched with play_android's own detector (find_icons: the
type's ring colour, or Normal's icon) and its icon cut-out (move_icons) where there is one.
    python3 scripts/live/icon_map.py LOG.jsonl RECORDING.h264 OUTDIR [--type grass]
Writes OUTDIR/icons_<MOVE>.json: [(minigame, seconds after Get Ready!, x, y, r)], x and y shares of the screen,
minigame = '<log stem>-<n>'; appends to a file already there (several battles pooled).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import av

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts" / "live"))
from pogo.gamedata import GameData  # noqa: E402
import play_android as pa  # noqa: E402
from move_icons import has_template, move_icons  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("log"); ap.add_argument("recording"); ap.add_argument("out")
    ap.add_argument("--type", help="only throws of this type")
    a = ap.parse_args()
    rows = [json.loads(l) for l in open(a.log)]
    epoch = next(r["epoch"] for r in rows if r["kind"] == "start")
    gd = GameData()
    throws = [(r["move"], epoch + r["cue_t"]) for r in rows if r["kind"] == "throw_started" and r.get("cue_t") is not None]
    times = [float(x) for x in Path(a.recording).with_suffix(".times").read_text().split()]
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    found: dict = {}
    windows = []
    for n, (move, ready) in enumerate(throws):
        mtype = gd.moves[move].type
        if a.type and mtype != a.type:
            continue
        windows.append((ready, ready + 5.5, move, mtype, f"{Path(a.log).stem}-{n}"))
    c = av.open(a.recording)
    for i, frame in enumerate(c.decode(video=0)):
        if i >= len(times) or i % 2:
            continue
        t = times[i]
        hit = [w for w in windows if w[0] <= t <= w[1]]
        if not hit:
            continue
        rgb = frame.to_ndarray(format="rgb24")
        for ready, _, move, mtype, game in hit:
            zone = pa.icon_zone(mtype)
            r = 0.08
            pts = [(x, y) for x, y in pa.find_icons(rgb, pa.icon_colour(mtype), mtype, zone)]
            if has_template(move, mtype):
                pts += [(x, y) for x, y, _ in move_icons(rgb, move, move_type=mtype)]
            for x, y in pts:
                found.setdefault(move, []).append((game, round(t - ready, 3), round(float(x), 4), round(float(y), 4), r))
    for move, sightings in found.items():
        path = out / f"icons_{move}.json"
        old = json.loads(path.read_text()) if path.exists() else []
        path.write_text(json.dumps(old + sightings))
        print(move, len({s[0] for s in sightings}), "minigames,", len(sightings), "sightings ->", path)


if __name__ == "__main__":
    main()
