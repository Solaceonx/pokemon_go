#!/usr/bin/env python3
"""Where each type's minigame icons appear, and a circling swipe there (the owner: icons "are always at the same
place", and "most of them you can just swipe circles in the same place").

    .reader/py312/bin/python scripts/recording/minigame_zones.py [--sheet OUT.png]

For every recorded charged move of the owner's (see minigame_library.py), live icons are found by their white symbol
(pogo.minigame.detect_symbol: precise, though it misses many) from 1.3 s to 6.5 s after the move starts. All their
positions for a type are pooled: the zone is where most of them are (the median centre, and an ellipse holding 80% of
them). The swipe is a loop of circles around that zone for the minigame's length, starting when the first icon is due.
Scored per run: the share of its icons (sightings joined frame to frame) that the circling path crosses while on screen.
Writes data/minigame/<type>.json (colour kept) and, with --sheet, one frame per type with the zone and path drawn.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(Path(__file__).resolve().parent)]
import minigame_eval as me  # noqa: E402
import minigame_library as ml  # noqa: E402
from pogo.minigame import detect_symbol  # noqa: E402

ASPECT = 2622 / 1206
START, LENGTH, LAP = 1.45, 4.6, 0.5  # seconds after the move starts; the minigame's length; one circle


def circles(cx, cy, rx, ry, length=LENGTH, lap=LAP, step=0.02):
    """(t, x, y) points of a loop around (cx, cy), radii rx (across) and ry (down), one lap every `lap` seconds."""
    out, t = [], 0.0
    while t <= length:
        a = 2 * math.pi * t / lap
        out.append((round(t, 3), round(cx + rx * math.cos(a), 4), round(cy + ry * math.sin(a), 4)))
        t += step
    return out


def spiral(cx, cy, rx, ry, length=LENGTH, lap=0.4, breathe=1.2, inner=0.25, step=0.02):
    """A loop whose radius swells from `inner` of the zone's spread to all of it and back every `breathe` seconds,
    so the finger sweeps the zone's middle as well as its edge."""
    out, t = [], 0.0
    while t <= length:
        a = 2 * math.pi * t / lap
        k = inner + (1 - inner) * abs(math.sin(math.pi * t / breathe))
        out.append((round(t, 3), round(cx + k * rx * math.cos(a), 4), round(cy + k * ry * math.sin(a), 4)))
        t += step
    return out


def icons_of(seen):
    """Sightings joined into icons: one per place and moment, seen at least twice."""
    icons = []
    for t, x, y, r in sorted(seen):
        for icon in icons:
            lt, lx, ly, lr = icon[-1]
            if t - lt < 0.15 and ml.dist((x, y), (lx, ly)) < max(r, lr):
                icon.append((t, x, y, r))
                break
        else:
            icons.append([(t, x, y, r)])
    return [i for i in icons if len(i) >= 2]


def crossed(path, icons) -> float:
    if not icons:
        return 0.0
    return sum(1 for icon in icons if any(ml.dist(at(path, max(0.0, t - START)), (x, y)) < r + 0.02 for t, x, y, r in icon)) / len(icons)


def at(path, t):
    if t <= path[0][0]:
        return path[0][1:]
    k = min(int(t / (path[1][0] - path[0][0])), len(path) - 1)
    return path[k][1:]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sheet")
    args = parser.parse_args()
    tiles = []
    for kind, windows in sorted(ml.runs_by_type().items()):
        lib = ml.OUT / f"{kind}.json"
        colour = json.loads(lib.read_text())["colour"] if lib.exists() else [round(float(v), 1) for v in ml.colour_of(windows)]
        per_run, pooled, frame_for_sheet = [], [], None
        cache = ml.OUT / "sightings" / f"{kind}.json"
        if cache.exists() and not args.sheet:
            per_run = json.loads(cache.read_text())
            pooled = [p for seen in per_run for p in seen]
            windows = [None] * len(per_run)
        for video, start, end, move in ([] if per_run else windows):
            seen = []
            for t, img in me.frames(video, start - 1.5 + 1.3, start - 1.5 + 6.5, step=2):
                found = detect_symbol(img, colour)
                seen += [(t - (start - 1.5), x, y, r) for x, y, r in found]
                if frame_for_sheet is None and len(found) >= 2:
                    frame_for_sheet = img
            per_run.append(seen)
            pooled += seen
        if not pooled:
            print(f"{kind}: no icons found")
            continue
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(per_run))
        xs, ys = np.array([p[1] for p in pooled]), np.array([p[2] for p in pooled])
        cx, cy = float(np.median(xs)), float(np.median(ys))
        rx = float(np.percentile(np.abs(xs - cx), 80))
        ry = float(np.percentile(np.abs(ys - cy), 80))
        r_icon = float(np.median([p[3] for p in pooled]))
        # the zone's spread, but at least an icon's radius; try a plain loop and spirals, keep the one crossing most
        RX, RY = max(rx, r_icon), max(ry, r_icon / ASPECT)
        shapes = {"circle 0.5 s": circles(cx, cy, RX, RY)}
        for lap in (0.3, 0.4, 0.6):
            for breathe in (0.8, 1.2):
                shapes[f"spiral lap {lap} s, in and out every {breathe} s"] = spiral(cx, cy, RX, RY, lap=lap, breathe=breathe)
        run_icons = [icons_of(seen) for seen in per_run]
        rated = {name: [crossed(p, icons) for icons in run_icons if icons] for name, p in shapes.items()}
        best = max(rated, key=lambda n: np.mean(rated[n]))
        path, scores = shapes[best], rated[best]
        print(f"   circle {100 * np.mean(rated['circle 0.5 s']):.0f}%, best: {best} {100 * np.mean(scores):.0f}%")
        first = [min(p[0] for p in seen) for seen in per_run if seen]
        shape_used = best
        print(f"{kind}: {len(windows)} runs, {len(pooled)} icon sightings; zone centre ({cx:.2f}, {cy:.2f}), spread "
              f"±{rx:.2f} across, ±{ry:.2f} down; first icon {np.median(first):.2f} s after the move starts; "
              f"circling path crosses {100 * np.mean(scores):.0f}% of icons while on screen (per run {[round(100 * s) for s in scores]})")
        data = json.loads(lib.read_text()) if lib.exists() else {"type": kind, "colour": colour}
        data.update(zone={"centre": [round(cx, 3), round(cy, 3)], "spread": [round(rx, 3), round(ry, 3)],
                          "icon_radius": round(r_icon, 3)},
                    swipe={"start_after_move_s": START, "shape": shape_used, "path": path},
                    circling_reach_share=round(float(np.mean(scores)), 3), runs=len(windows))
        data.pop("variants", None)
        data.pop("visit_after_s", None)
        lib.write_text(json.dumps(data) + "\n")
        if args.sheet and frame_for_sheet is not None:
            img = np.ascontiguousarray(frame_for_sheet)
            h, w = img.shape[:2]
            for t, x, y, r in pooled[:400]:
                cv2.circle(img, (int(x * w), int(y * h)), 6, (255, 255, 0), -1)
            pts = np.array([(int(x * w), int(y * h)) for _, x, y in path[: int(LAP / 0.02) + 1]], np.int32)
            cv2.polylines(img, [pts], True, (255, 0, 0), 8)
            cv2.putText(img, kind, (30, 160), cv2.FONT_HERSHEY_SIMPLEX, 3, (255, 0, 0), 6)
            tiles.append(cv2.resize(img, (300, int(h * 300 / w))))
    if tiles:
        cv2.imwrite(args.sheet, cv2.cvtColor(np.hstack(tiles), cv2.COLOR_RGB2BGR))
        print(f"sheet: {args.sheet}")


if __name__ == "__main__":
    main()
