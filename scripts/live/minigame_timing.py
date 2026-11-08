#!/usr/bin/env python3
"""When the minigame's icons come and go relative to "Get Ready!", from battle recordings (30 fps), for each of our
throws in the battles given (task 40).

    python3 scripts/live/minigame_timing.py MEDIA_FOLDER STAMP [STAMP ...] [--out timing.json]

since = the frame the live player saw Get Ready! on, from its 'swipe' row (logged 1.05 s after it). Per throw:
ready_onset (Get Ready!'s first frame, by OCR every third frame), first_icon and last_icon (frames where
play_android.find_icons sees one; a frame or two before the minigame can give false ones), rating_last (the last
frame with Nice / Great / Excellent written at the top), and stroke (when the player's stroke began and ended), all
in seconds after since. Recordings: MEDIA_FOLDER/battle-STAMP.h264 and .times; logs: runs/live/STAMP.jsonl."""
import json
import re
import sys
from pathlib import Path

import av
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts" / "live"))
import play_android as pa  # noqa: E402
from pogo import android_screen as screen  # noqa: E402
from rapidocr_onnxruntime import RapidOCR  # noqa: E402

ocr = RapidOCR()
args = [a for a in sys.argv[1:] if not a.startswith("--")]
media = Path(args[0])
out_path = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else None
if out_path: args = [a for a in args if a != out_path]
TYPES = {"SHADOW_BALL": "ghost", "BUBBLE_BEAM": "water", "BULLDOZE": "ground", "MUD_BOMB": "ground",
         "DISCHARGE": "electric", "BODY_SLAM": "normal"}
out = []
for stem in args[1:]:
    rows = [json.loads(l) for l in open(ROOT / "runs" / "live" / f"{stem}.jsonl", encoding="utf-8")]
    epoch = next(r["epoch"] for r in rows if r["kind"] == "start")
    throws = []
    for i, r in enumerate(rows):
        if r["kind"] == "swipe":
            mg = next((x for x in rows[i:] if x["kind"] == "minigame"), None)
            if mg and mg["icons_seen"] > 0:
                throws.append((r["t"] - 1.05, r["move"], r["t"], mg["t"]))
    times = [float(l) for l in open(media / f"battle-{stem}.times")]
    frames = {}
    codec = av.CodecContext.create("h264", "r"); i = 0
    wins = [(s - 1.6, s + 8.0) for s, *_ in throws]
    for packet in codec.parse(open(media / f"battle-{stem}.h264", "rb").read()):
        for fr in codec.decode(packet):
            if i >= len(times): break
            t = times[i] - epoch; i += 1
            if any(a <= t <= b for a, b in wins):
                frames[round(t, 3)] = fr.to_ndarray(format="rgb24")
    ts = sorted(frames)
    for since, move, swipe_t, end_t in throws:
        kind = TYPES[move]
        colour, zone = pa.icon_colour(kind), pa.icon_zone(kind)
        near = [t for t in ts if since - 1.6 <= t <= since + 8.0]
        icons = {t: len(pa.find_icons(frames[t], colour, kind, zone)) for t in near}
        # Get Ready! onset: scan back from since in steps of 3 frames
        onset = None
        for t in reversed([t for t in near if t <= since + 0.05][::3]):
            res, _ = ocr(frames[t][int(0.17 * 1200):int(0.30 * 1200), int(0.18 * 540):int(0.82 * 540)])
            text = re.sub("[^A-Z]", "", " ".join(r[1] for r in (res or [])).upper())
            if "READY" in text or "GETRE" in text:
                onset = t
            elif onset is not None:
                break
        seen = [t for t in near if t > since - 0.5 and icons[t] >= 1]
        # the rating words: last frame that shows one, every 6th frame
        rated = []
        for t in near[::6]:
            if t < since + 2: continue
            res, _ = ocr(frames[t][int(0.20 * 1200):int(0.36 * 1200)])
            w = re.sub("[^A-Z]", "", " ".join(r[1] for r in (res or [])).upper())
            if any(x in w for x in ("NICE", "GREAT", "EXCELLENT")):
                rated.append(t)
        row = {"battle": stem, "move": move, "since": round(since, 2),
               "ready_onset": None if onset is None else round(onset - since, 2),
               "first_icon": round(seen[0] - since, 2) if seen else None,
               "last_icon": round(seen[-1] - since, 2) if seen else None,
               "rating_last": round(rated[-1] - since, 2) if rated else None,
               "stroke": [round(swipe_t - since, 2), round(end_t - since, 2)]}
        print(json.dumps(row)); out.append(row)
if out_path:
    json.dump(out, open(out_path, "w"))
