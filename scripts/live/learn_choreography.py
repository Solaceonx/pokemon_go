#!/usr/bin/env python3
"""Learn where and when each charged move's minigame icons come up on this phone, from icon sightings on recorded
minigames, as a fixed timed path for the stroke to follow (task 40; the owner, 2026-11-08: "a working model of just
doing some swipe pattern instead of relearning the swipes every time").

    python3 scripts/live/learn_choreography.py SIGHTINGS.json MOVE [--test 0.5] [--out data/minigame/android/MOVE.json]

SIGHTINGS.json: [(minigame, seconds after Get Ready!, x, y, r)], every icon found on every third frame of each
recorded minigame (the scratch icon_map.py: the type's ring colour, or Normal's white ring symbol). The icons follow
much the same choreography every time (Body Slam: right side first at 1 s, the middle at 2.5 to 3 s, the left at 4 s,
the bottom left at 4.5 to 5 s). A cell of (time 0.25 s, x 0.05, y 0.025) scores the number of different minigames
with a sighting in it or next to it; local maxima seen in at least --share of the minigames are the predicted icons,
each (t0, t1, x, y, share). With --test, the minigames are split; the icons are learnt on one part, and the stroke's
path (play_android: predicted icons chased nearest first, the sweep between) is scored on the other: the share of
sightings it passes within an icon's radius while they show.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import random
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "live"))

TYPES = {"SHADOW_BALL": "ghost", "BUBBLE_BEAM": "water", "BULLDOZE": "ground", "MUD_BOMB": "ground",
         "DISCHARGE": "electric", "BODY_SLAM": "normal"}
DT, DX, DY = 0.25, 0.05, 0.025


def learn(sightings, share: float = 0.35) -> list:
    games = sorted({s[0] for s in sightings})
    cells = collections.defaultdict(set)
    for g, t, x, y, _ in sightings:
        cells[(int(t / DT), int(x / DX), int(y / DY))].add(g)
    score = {}
    for (i, j, k) in cells:
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for dk in (-1, 0, 1):
                    c = (i + di, j + dj, k + dk)
                    if c in score:
                        continue
                    seen = set()
                    for ei in (-1, 0, 1):
                        for ej in (-1, 0, 1):
                            for ek in (-1, 0, 1):
                                seen |= cells.get((c[0] + ei, c[1] + ej, c[2] + ek), set())
                    score[c] = len(seen)
    need = max(2, share * len(games))
    peaks = []
    for c, v in sorted(score.items(), key=lambda kv: -kv[1]):
        if v < need:
            break
        # a peak: no stronger one already taken close by in time and place
        if any(abs(c[0] - p[0]) <= 2 and math.hypot((c[1] - p[1]) * DX, (c[2] - p[2]) * DY * 2.2) < 0.12 for p in peaks):
            continue
        peaks.append(c)
    out = []
    for i, j, k in peaks:
        near = [(t, x, y) for g, t, x, y, _ in sightings
                if abs(t - (i + 0.5) * DT) <= 1.5 * DT and math.hypot(x - (j + 0.5) * DX, (y - (k + 0.5) * DY) * 2.2) < 0.08]
        if len(near) < 3:
            continue
        ts = [n[0] for n in near]
        out.append((round(float(np.percentile(ts, 10)) - 0.1, 2), round(float(np.percentile(ts, 90)) + 0.1, 2),
                    round(float(np.median([n[1] for n in near])), 3), round(float(np.median([n[2] for n in near])), 3),
                    round(score[(i, j, k)] / len(games), 2)))
    return sorted(out)


def simulate(predicted, move_type: str, t0: float = 1.05, t1: float = 6.6, speed: float = 6.5, step: float = 0.01):
    """The finger's path (t, x, y) under play_android.minigame_stroke's rules, with only predicted icons to chase:
    each visited once, nearest first, the sweep between."""
    import play_android as pa
    route = pa.sweep_path(pa.sweep_box(move_type, pa.icon_zone(move_type)))
    leg, (x, y) = 0, route[0]
    pts, pending, done, t, last_look = [], [], set(), t0, -1.0
    while t < t1:
        if t - last_look >= 0.05:
            last_look = t
            icons = [(px, py, k) for k, (a, b, px, py, _) in enumerate(predicted) if a <= t <= b and k not in done]
            pending = icons or pending
        for p in pending:
            if math.hypot(p[0] - x, (p[1] - y) * 2.2) <= 0.02:
                done.add(p[2])
        pending = [p for p in pending if p[2] not in done]
        target = min(pending, key=lambda p: math.hypot(p[0] - x, (p[1] - y) * 2.2)) if pending else None
        if target is None and math.hypot(route[leg][0] - x, (route[leg][1] - y) * 2.2) < 0.01:
            leg = (leg + 1) % len(route)
        gx, gy = target[:2] if target else route[leg]
        d = math.hypot(gx - x, (gy - y) * 2.2)
        mv = speed * step
        if d > mv:
            x, y = x + (gx - x) * mv / d, y + (gy - y) * mv / d
        else:
            x, y = gx, gy
            if target is not None:
                done.add(target[2])
        pts.append((t, x, y))
        t += step
    return np.array(pts)


def coverage(path, sightings) -> float:
    hit = 0
    for _, t, x, y, _ in sightings:
        near = path[np.abs(path[:, 0] - t) <= 0.35]
        hit += bool(len(near)) and float(np.min(np.hypot(near[:, 1] - x, (near[:, 2] - y) * 2.2))) <= 0.085
    return hit / max(1, len(sightings))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("sightings")
    ap.add_argument("move")
    ap.add_argument("--share", type=float, default=0.35)
    ap.add_argument("--test", type=float, default=0.0, help="share of the minigames held out to score the path on")
    ap.add_argument("--out")
    a = ap.parse_args()
    s = [tuple(x) for x in json.load(open(a.sightings))]
    games = sorted({x[0] for x in s})
    kind = TYPES[a.move]
    if a.test:
        random.Random(0).shuffle(games)
        held = set(games[:max(1, int(a.test * len(games)))])
        train = [x for x in s if x[0] not in held]
        test = [x for x in s if x[0] in held]
        predicted = learn(train, a.share)
        none = coverage(simulate([], kind), test)
        learnt = coverage(simulate(predicted, kind), test)
        print(f"{a.move}: {len(predicted)} icons learnt on {len(games) - len(held)} minigames; on {len(held)} held out, "
              f"sightings passed over: sweep alone {none:.0%}, learnt path {learnt:.0%}")
    predicted = learn(s, a.share)
    for p in predicted:
        print("  ", p)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps({"move": a.move, "type": kind, "minigames": len(games),
                                           "icons": predicted}, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
