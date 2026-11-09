"""Cut a template of a move's minigame icon from its recorded minigames, automatically: candidates from the colour
detector whose centre is white (the type symbol), patches 45 px across on half-size frames, the median patch. Then
match it on the same frames and show the score spread and a sheet of the best matches.

    python3 scripts/live/cut_icon_template.py MOVE [N] [FOLDER] [--hue LO HI]

--hue: candidates are round discs of that OpenCV hue (0-180) with a white symbol in the middle, not the colour
detector's: for a type whose ring colour is near the sky's (Ice's mint, hue about 86 against the sky's 102, picked
clouds twice; as discs of hue 78-94 it cut the snowflake, real icons scoring 0.86-1.00 and the rest 0.62 or less).

FOLDER holds mg_list.json ({move: [[stem, Get Ready! time, recording], ...]}) and gets tpl_MOVE.npy/.png and a sheet
tplsheet_MOVE.png of the best matches; copy a good one to data/minigame/android/icon_MOVE.png.
"""
import json
import sys
from pathlib import Path

import av
import cv2
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts" / "live"))
import play_android as pa  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402

HUE = None
if "--hue" in sys.argv:
    i = sys.argv.index("--hue")
    HUE = (int(sys.argv[i + 1]), int(sys.argv[i + 2]))
    del sys.argv[i:i + 3]
SCR = Path(sys.argv[3]) if len(sys.argv) > 3 else ROOT / "runs" / "icon_templates"  # list, outputs and sheets
SCR.mkdir(parents=True, exist_ok=True)
move = sys.argv[1]
n = int(sys.argv[2]) if len(sys.argv) > 2 else 10
kind = GameData().moves[move].type
colour = pa.icon_colour(kind)
lst = json.load(open(SCR / "mg_list.json"))[move][-n:]
from pogo.android_screen import TYPE_COLOURS as TYPE_RGB  # the game's type colours (the header icons matched them)
R = 11  # half the patch, on a half-size frame (the recordings are 540 x 1200, so 270 x 600)


def frames():
    by = {}
    for stem, ready, rec in lst:
        by.setdefault((stem, rec), []).append(ready)
    for (stem, rec), cues in by.items():
        rows = [json.loads(l) for l in open(ROOT / "runs" / "live" / f"{stem}.jsonl", encoding="utf-8")]
        epoch = next((r["epoch"] for r in rows if r["kind"] == "start" and "epoch" in r), None)
        if epoch is None:
            continue
        times = [float(l) for l in open(Path(rec).with_suffix(".times"))]
        codec = av.CodecContext.create("h264", "r")
        i = 0
        for p in codec.parse(Path(rec).read_bytes()):
            for fr in codec.decode(p):
                if i >= len(times):
                    break
                t = times[i] - epoch
                i += 1
                near = [c for c in cues if c + 1.0 <= t <= c + 6.3]
                if near and i % 6 == 0:
                    yield f"{stem}@{near[0]}", t - near[0], fr.to_ndarray(format="rgb24")


def discs(small, gray) -> list:
    """Round discs of the hue, icon-sized (radius 12-40 px on the half frame), with a white symbol in the middle."""
    hsv = cv2.cvtColor(np.ascontiguousarray(small), cv2.COLOR_RGB2HSV)
    m = ((hsv[..., 0] >= HUE[0]) & (hsv[..., 0] <= HUE[1]) & (hsv[..., 1] > 60) & (hsv[..., 2] > 140)).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    out = []
    H, W = small.shape[:2]
    for c in cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]:
        a = cv2.contourArea(c)
        per = cv2.arcLength(c, True)
        circ = 4 * np.pi * a / (per * per + 1e-6)
        if not np.pi * 12 ** 2 <= a <= np.pi * 40 ** 2 or circ < 0.7:  # water's are up to about 33 px
            continue
        (cx, cy), _ = cv2.minEnclosingCircle(c)
        cx, cy = int(cx), int(cy)
        if not (R <= cx < W - R and R <= cy < H - R) or not 0.3 < cy / H < 0.9:
            continue
        if (small[cy - 3:cy + 4, cx - 3:cx + 4].min(2) > 200).mean() < 0.3:
            continue
        g2 = gray[cy - R:cy + R + 1, cx - R:cx + R + 1]
        out.append((circ * float(g2.std()), g2))
    return out


pool, kept = [], []
for g, dt, rgb in frames():
    small = rgb[::2, ::2]
    gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY).astype(np.float32)
    kept.append((g, dt, small, gray))
    if HUE is not None:
        pool += discs(small, gray)
        continue
    for x, y in pa.find_icons(rgb, colour, kind, pa.icon_zone(kind)):
        H, W = small.shape[:2]
        cx, cy = int(x * W), int(y * H)
        if R <= cx < W - R and R <= cy < H - R:
            core = small[cy - 3:cy + 4, cx - 3:cx + 4]
            if (core.min(2) > 200).mean() > 0.3 and y < 0.8:  # a white symbol in the middle, above the move's dust
                patch = small[cy - R:cy + R + 1, cx - R:cx + R + 1].astype(np.float32)
                yy, xx = np.mgrid[-R:R + 1, -R:R + 1]
                ring = (np.hypot(xx, yy) > 0.6 * R) & (np.hypot(xx, yy) <= R)
                ring_colour = TYPE_RGB.get(kind, colour)
                near = (np.abs(patch[ring] - np.array(ring_colour)).max(1) < 45).mean() if ring_colour is not None else 0.5
                g2 = gray[cy - R:cy + R + 1, cx - R:cx + R + 1]
                pool.append((near * float(g2.std()), g2))
print(move, kind, "frames", len(kept), "candidates with a white centre", len(pool))
if not pool:
    sys.exit()
# the sharpest, most type-coloured candidates; of those, the one most like the rest (a medoid by correlation)
pool.sort(key=lambda x: -x[0])
top = [g for _, g in pool[:40]]
def ncc(a, b):
    a, b = a - a.mean(), b - b.mean()
    return float((a * b).sum() / (np.sqrt((a * a).sum() * (b * b).sum()) + 1e-6))
best_i = max(range(len(top)), key=lambda i: sum(ncc(top[i], top[j]) for j in range(len(top)) if j != i))
tpl = top[best_i].astype(np.float32)
print("template chosen from", len(top), "candidates; mean likeness", round(sum(ncc(tpl, t) for t in top) / len(top), 2))
Image.fromarray(np.clip(tpl, 0, 255).astype(np.uint8)).resize((135, 135)).save(SCR / f"tpl_{move}.png")
np.save(SCR / f"tpl_{move}.npy", tpl)
scores, tiles = [], []
for k, (g, dt, small, gray) in enumerate(kept):
    best = np.full(gray.shape, -1.0, np.float32)
    for f in (0.8, 1.0, 1.25, 1.6):
        t = cv2.resize(tpl, None, fx=f, fy=f)
        r = cv2.matchTemplate(gray, t, cv2.TM_CCOEFF_NORMED)
        o = t.shape[0] // 2
        v = best[o:o + r.shape[0], o:o + r.shape[1]]
        np.maximum(v, r, out=v)
    found = []
    for _ in range(5):
        y, x = np.unravel_index(np.argmax(best), best.shape)
        s = float(best[y, x])
        found.append((x, y, s)); scores.append(s)
        best[max(0, y - 15):y + 15, max(0, x - 15):x + 15] = -1
    if k % max(1, len(kept) // 12) == 0 and len(tiles) < 12:
        im = Image.fromarray(small.copy()); d = ImageDraw.Draw(im)
        for x, y, s in found:
            d.ellipse([x - 12, y - 12, x + 12, y + 12], outline=(255, 0, 0) if s > 0.6 else (255, 255, 0), width=4)
            d.text((x + 13, y - 6), f"{s:.2f}", fill=(255, 0, 0))
        tiles.append(im)
print("top-5 scores per frame, percentiles 10/50/90:", np.percentile(scores, [10, 50, 90]).round(2))
print("histogram:", np.histogram(scores, bins=[0, .3, .4, .5, .6, .7, .8, .9, 1])[0])
W = Image.new("RGB", (270 * 6, 600 * ((len(tiles) + 5) // 6)))
for i, t in enumerate(tiles):
    W.paste(t, (270 * (i % 6), 600 * (i // 6)))
W.save(SCR / f"tplsheet_{move}.png")
