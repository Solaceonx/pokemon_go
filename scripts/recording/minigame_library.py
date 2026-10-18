#!/usr/bin/env python3
"""Build the per-type minigame library from recorded minigames (pogo.minigame; the owner: "a little minigame for
each type", so a charged move of type X always plays X's pattern, in one of a few variants).

    .reader/py312/bin/python scripts/recording/minigame_library.py [--sheet OUT.png]

For each of the owner's charged moves in the tracked recordings (games/screenrecording-*-N/timeline.json, the videos
in ~/Downloads; type from the move's name):

1. the type's icon colour, from the icons the shape detector (pogo.minigame.detect) is sure of;
2. the icons in every frame (30 a second) by that colour (pogo.minigame.detect_colour), followed frame to frame;
3. time counted from the first icon, which comes 1.5 s or so after the move starts;
4. the runs of a type grouped into variants by where their icons are in the first second;
5. for each variant a swipe schedule: the icons of all its runs merged, each visited 0.15 s after it appears, where
   it is then (a path of (time, x, y) points through the icons in order);
6. each run with another of its variant scored on the schedule built without it: the share of its icons the path
   passes within their radius while they are on screen.

Writes data/minigame/<type>.json (colour, variants: runs, first icons for recognising the variant, schedule) and a
summary. With one run in a variant there is nothing to score it against; more recordings of that type are needed.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(Path(__file__).resolve().parent)]
import minigame_eval as me  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.minigame import Follower, detect, detect_colour, ring_colour  # noqa: E402

ASPECT = 2622 / 1206
VISIT_AFTER = 0.15  # seconds after an icon appears that the finger reaches it
OUT = ROOT / "data" / "minigame"


def runs_by_type():
    gd = GameData()
    by_name = {m.name: m for m in gd.moves.values()}
    out = collections.defaultdict(list)
    for video, start, end, move in me.windows():
        m = by_name.get(move)
        if m:
            out[m.type].append((video, start, end, move))
    return out


def colour_of(windows) -> np.ndarray:
    picks = []
    for video, start, end, _ in windows:
        for k, (t, img) in enumerate(me.frames(video, start, end, step=6)):
            icons = detect(img)
            if icons:
                c = ring_colour(img, icons)
                if c is not None:
                    picks.append(c)
    return np.median(np.array(picks), axis=0)


def tracks_of(window, colour, sheet=None):
    """{icon id: [(t from the first icon, x, y, r)]}, icons seen in 3 frames or more."""
    video, start, end, move = window
    follower, seen, first = Follower(), collections.defaultdict(list), None
    for t, img in me.frames(video, start, end, step=2):
        found = detect_colour(img, colour)
        if found and first is None:
            first = t
        for ic in follower.update(found, t):
            seen[ic.ident].append((t, ic.x, ic.y, ic.r))
        if sheet is not None and first is not None and len(sheet) < 40 and abs((t - first) % 0.75) < 0.017:
            small = cv2.resize(img, (200, int(img.shape[0] * 200 / img.shape[1])))
            for x, y, r in found:
                cv2.circle(small, (int(x * 200), int(y * small.shape[0])), int(r * 200), (255, 0, 0), 2)
            cv2.putText(small, f"{move[:10]} {t - first:.1f}", (3, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 0), 1)
            sheet.append(small)
    if first is None:
        return {}
    return {k: [(t - first, x, y, r) for t, x, y, r in v] for k, v in seen.items() if len(v) >= 3}


def dist(a, b) -> float:
    return ((a[0] - b[0]) ** 2 + ((a[1] - b[1]) * ASPECT) ** 2) ** 0.5


def early(tracks, until=1.0):
    return [(t, x, y) for v in tracks.values() for t, x, y, _ in v if t <= until]


def run_distance(a, b) -> float:
    """How far apart two runs' icons are in their first second (screen widths), matching points within 0.1 s."""
    def one_way(p, q):
        ds = []
        for t, x, y in p:
            near = [dist((x, y), (qx, qy)) for qt, qx, qy in q if abs(qt - t) < 0.1]
            if near:
                ds.append(min(near))
        return np.median(ds) if ds else 1.0
    return (one_way(a, b) + one_way(b, a)) / 2


def variants(all_tracks, threshold=0.12):
    """Runs grouped greedily: a run joins the first group whose first run is within `threshold` of it."""
    groups = []
    for i, tr in enumerate(all_tracks):
        for g in groups:
            if run_distance(early(all_tracks[g[0]]), early(tr)) < threshold:
                g.append(i)
                break
        else:
            groups.append([i])
    return groups


def position(track, t):
    """Where a track's icon is at time t (linear between its frames), or None outside its life."""
    if t < track[0][0] or t > track[-1][0]:
        return None
    for (t0, x0, y0, r0), (t1, x1, y1, r1) in zip(track, track[1:]):
        if t0 <= t <= t1:
            u = 0 if t1 == t0 else (t - t0) / (t1 - t0)
            return x0 + u * (x1 - x0), y0 + u * (y1 - y0), r0
    return track[-1][1], track[-1][2], track[-1][3]


def schedule(runs) -> list:
    """Merge the icons of several runs (the same icon: appearing within 0.12 s and 0.08 screen widths) and visit each
    VISIT_AFTER after it appears."""
    icons = []
    for tracks in runs:
        for track in tracks.values():
            t0, x0, y0, _ = track[0]
            for icon in icons:
                if abs(icon[0][0] - t0) < 0.12 and dist(icon[0][1:3], (x0, y0)) < 0.08:
                    if len(track) > len(icon):
                        icon[:] = track
                    break
            else:
                icons.append(list(track))
    visits = []
    for track in icons:
        at = track[0][0] + VISIT_AFTER
        p = position(track, min(at, track[-1][0]))
        if p:
            visits.append((round(at, 3), round(p[0], 4), round(p[1], 4)))
    return sorted(visits)


def path_at(visits, t):
    if t <= visits[0][0]:
        return visits[0][1:]
    for (t0, x0, y0), (t1, x1, y1) in zip(visits, visits[1:]):
        if t0 <= t <= t1:
            u = 0 if t1 == t0 else (t - t0) / (t1 - t0)
            return x0 + u * (x1 - x0), y0 + u * (y1 - y0)
    return visits[-1][1:]


def score(visits, tracks) -> float:
    """Share of a run's icons the scheduled path passes within their radius while they are on screen."""
    if not tracks or not visits:
        return 0.0
    hit = 0
    for track in tracks.values():
        if any(dist(path_at(visits, t), (x, y)) < r for t, x, y, r in track):
            hit += 1
    return hit / len(tracks)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sheet")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    sheet = [] if args.sheet else None
    for kind, windows in sorted(runs_by_type().items()):
        colour = colour_of(windows)
        all_tracks = [tracks_of(w, colour, sheet) for w in windows]
        groups = variants(all_tracks)
        saved = []
        print(f"\n{kind}: {len(windows)} runs, icon colour {np.round(colour).astype(int).tolist()}, "
              f"icons followed per run {[len(t) for t in all_tracks]}, variants {[len(g) for g in groups]}")
        for g in groups:
            runs = [all_tracks[i] for i in g]
            visits = schedule(runs)
            held_out = []
            for k in range(len(runs)) if len(runs) > 1 else []:
                held_out.append(score(schedule(runs[:k] + runs[k + 1:]), runs[k]))
            own = np.mean([score(visits, r) for r in runs]) if runs else 0
            print(f"  variant of {len(g)} run(s): {len(visits)} icons scheduled; path through them hits "
                  f"{100 * own:.0f}% of the icons of its own runs"
                  + (f", {100 * np.mean(held_out):.0f}% of a held-out run's (each run left out in turn)" if held_out else
                     "; no other run to test it on"))
            saved.append({"runs": [windows[i][3] + " @ " + Path(windows[i][0]).name for i in g],
                          "first_icons": sorted(early(all_tracks[g[0]], 0.4))[:12], "schedule": visits,
                          "held_out_hit_share": round(float(np.mean(held_out)), 3) if held_out else None})
        (OUT / f"{kind}.json").write_text(json.dumps({"type": kind, "colour": np.round(colour, 1).tolist(),
                                                      "visit_after_s": VISIT_AFTER, "variants": saved}, indent=1) + "\n")
    if sheet:
        cols = 8
        blank = np.zeros_like(sheet[0])
        rows = [sheet[i:i + cols] + [blank] * (cols - len(sheet[i:i + cols])) for i in range(0, len(sheet), cols)]
        cv2.imwrite(args.sheet, cv2.cvtColor(np.vstack([np.hstack(r) for r in rows]), cv2.COLOR_RGB2BGR))
        print(f"\nsheet: {args.sheet}")


if __name__ == "__main__":
    main()
