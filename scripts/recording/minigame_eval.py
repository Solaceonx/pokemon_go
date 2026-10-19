#!/usr/bin/env python3
"""Test pogo.minigame on the owner's recorded minigames, without the phone.

    .reader/py312/bin/python scripts/recording/minigame_eval.py [--sheet OUT.png] [--latency 0.1 0.2 0.3]

For every charged move of the owner's in the tracked recordings (games/screenrecording-*-N/timeline.json, the videos
in ~/Downloads), the frames of its minigame window are read at 30 a second; icons are detected and followed. Reported
per minigame: icons followed (seen in 3 frames or more), the detections per frame, and an estimate of the share of
icons a bot would swipe: every quarter second it plans a swipe from what it sees (pogo.minigame.plan), the swipe lands
`latency` later and lasts a quarter second, and an icon counts as swiped if the path passes within its radius of where
the icon really was then (the later frames' detections). That is an estimate from the recording, not the game's own
count. --sheet writes frames with the detections drawn, to check by eye.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

import av
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from pogo.minigame import Follower, detect, plan  # noqa: E402

ASPECT = 2622 / 1206
DOWNLOADS = Path.home() / "Downloads"


def windows():
    """(video, start, end, move) for each of the owner's charged moves in the tracked recordings."""
    for folder in sorted(glob.glob(str(ROOT / "games" / "screenrecording-*-1-*"))):
        tl = json.loads((Path(folder) / "timeline.json").read_text())
        stamp = Path(folder).name.split("screenrecording-")[1].rsplit("-1-", 1)[0]  # 10-10-2026-10-50-13
        date, clock = stamp[:10], stamp[11:]
        video = DOWNLOADS / f"ScreenRecording_{date} {clock}_1.MP4"
        if not video.exists():
            continue
        origin = tl.get("clip_origin_seconds") or 0.0
        for c in tl["charged"]:
            if c["side"] == "mine":
                yield str(video), origin + c["t"] + 1.5, origin + c["t"] + 7.5, c["move"] or "unnamed"


def frames(video: str, start: float, end: float, step: int = 2):
    container = av.open(video)
    stream = container.streams.video[0]
    container.seek(int(start / stream.time_base), stream=stream, backward=True)
    k = 0
    for frame in container.decode(stream):
        t = float(frame.pts * stream.time_base)
        if t < start:
            continue
        if t > end:
            break
        if k % step == 0:
            yield t, frame.to_ndarray(format="rgb24")
        k += 1


def segment_distance(p, a, b) -> float:
    (px, py), (ax, ay), (bx, by) = [(x, y * ASPECT) for x, y in (p, a, b)]
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    u = 0.0 if L == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L))
    return ((px - ax - u * dx) ** 2 + (py - ay - u * dy) ** 2) ** 0.5


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sheet")
    parser.add_argument("--latency", nargs="+", type=float, default=[0.1, 0.2, 0.3])
    args = parser.parse_args()
    tiles, rows = [], []
    for video, start, end, move in windows():
        follower, timeline = Follower(), []  # timeline: (t, [icons])
        for t, img in frames(video, start, end):
            icons = follower.update(detect(img), t)
            timeline.append((t, [(ic.ident, ic.x, ic.y, ic.r, ic.vx, ic.vy, ic.seen) for ic in icons]))
            if args.sheet and len(tiles) < 24 and len(timeline) % 15 == 7:
                small = cv2.resize(img, (220, int(img.shape[0] * 220 / img.shape[1])))
                for _, x, y, r, *_ in timeline[-1][1]:
                    cv2.circle(small, (int(x * 220), int(y * small.shape[0])), int(r * 220), (255, 0, 0), 2)
                cv2.putText(small, move[:12], (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 0), 1)
                tiles.append(small)
        seen = {}
        for t, icons in timeline:
            for ident, x, y, r, vx, vy, n in icons:
                seen.setdefault(ident, []).append((t, x, y, r))
        real = {k: v for k, v in seen.items() if len(v) >= 3}
        per_frame = np.mean([len(i) for _, i in timeline]) if timeline else 0
        scores = {}
        for latency in args.latency:
            hit = set()
            times = [t for t, _ in timeline]
            next_plan = times[0] if times else 0
            for t, icons in timeline:
                if t < next_plan:
                    continue
                next_plan = t + 0.25
                from pogo.minigame import Icon
                path = plan([Icon(x, y, r, t, vx, vy) for _, x, y, r, vx, vy, n in icons if n >= 2], latency)
                if len(path) < 2:
                    continue
                for ident, track in real.items():
                    for tt, x, y, r in track:
                        if t + latency <= tt <= t + latency + 0.25:
                            if min(segment_distance((x, y), a, b) for a, b in zip(path, path[1:])) < r:
                                hit.add(ident)
                                break
            scores[latency] = len(hit) / max(1, len(real))
        rows.append((Path(video).name[15:34], move, len(real), per_frame, scores))
        print(f"{Path(video).name[15:34]} {move:16s} icons followed {len(real):3d}, per frame {per_frame:.1f}, "
              + ", ".join(f"swiped at {int(1000 * L)} ms: {100 * s:.0f}%" for L, s in scores.items()), flush=True)
    if rows:
        for latency in args.latency:
            print(f"all minigames, {int(1000 * latency)} ms: {100 * np.mean([r[4][latency] for r in rows]):.0f}% of icons swiped on average")
    if args.sheet and tiles:
        cols = 8
        blank = np.zeros_like(tiles[0])
        grid = [tiles[i:i + cols] + [blank] * (cols - len(tiles[i:i + cols])) for i in range(0, len(tiles), cols)]
        cv2.imwrite(args.sheet, cv2.cvtColor(np.vstack([np.hstack(r) for r in grid]), cv2.COLOR_RGB2BGR))
        print(f"sheet: {args.sheet}")


if __name__ == "__main__":
    main()
