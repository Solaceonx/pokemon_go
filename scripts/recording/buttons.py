"""Read the two charged-move buttons at the bottom of the battle screen.

Each button is a disc that fills from the bottom with the move's type colour as energy builds: the filled
share of its height is energy / cost, up to full. The buttons are on screen only while the fight is running;
they vanish the moment either side starts a charged move.

    measure(frame)  ->  {"left": {...}, "right": {...}}  for one frame as an H x W x 3 array of 0..255

Positions are for a portrait phone screen: measured on a 1206 x 2622 iPhone recording and expressed as shares
of the width, counted up from the bottom edge.
"""
import numpy as np

CENTRES = (0.3093, 0.6907)  # across, as a share of the width
UP = 0.2322  # centre above the bottom edge, as a share of the width
RADIUS = 0.0763  # of the coloured disc, as a share of the width


def one(a: np.ndarray, cx: float, cy: float, r: float) -> dict:
    ys = np.arange(int(cy - 0.82 * r), int(cy + 0.82 * r))
    left = a[ys, int(cx - 0.62 * r):int(cx - 0.42 * r)].mean(1) / 255.0  # two strips either side of the icon
    right = a[ys, int(cx + 0.42 * r):int(cx + 0.62 * r)].mean(1) / 255.0
    lopsided = float(np.median(np.abs(left - right).mean(1)))  # a disc looks the same on both sides, row by row
    row = (left + right) / 2
    glow = row.max(1) + (row.max(1) - row.min(1))  # brightness plus colourfulness: high where filled
    n = len(glow)
    sums = np.cumsum(glow)
    k = np.arange(4, n - 4)
    above, below = sums[k - 1] / k, (sums[-1] - sums[k - 1]) / (n - k)
    score = (below - above) * np.sqrt(k * (n - k)) / n
    best = int(np.argmax(score))
    step = float(below[best] - above[best])  # how much brighter the part below the line is
    # The rim: all round the disc, the inside differs from the scene just outside it, either in colour (where
    # it is filled) or by being darker (where it is empty). On plain scenery there is no such edge.
    angles = np.deg2rad(np.arange(0, 360, 15))
    inner = np.array([a[int(cy + 0.86 * r * np.sin(q)), int(cx + 0.86 * r * np.cos(q))] for q in angles]) / 255.0
    outer = np.array([a[int(cy + 1.2 * r * np.sin(q)), int(cx + 1.2 * r * np.cos(q))] for q in angles]) / 255.0
    edge = (np.abs(inner - outer).max(1) > 0.10) | (outer.max(1) - inner.max(1) > 0.04)
    rim = float(edge.mean())
    ring = a[int(cy - 1.07 * r):int(cy - 1.02 * r), int(cx - 0.25 * r):int(cx + 0.25 * r)].mean((0, 1)) / 255.0
    ready = bool(ring.min() > 0.8)  # a white ring round the disc: the move can be thrown
    level = float(np.mean(glow))
    if step >= 0.12:
        fill = (cy + r - ys[k[best]]) / (2 * r)
    else:
        fill = 1.0 if (ready or level > 0.75) else 0.0
    return {"fill": round(float(fill), 3), "present": bool(rim >= 0.75 and lopsided < 0.08), "ready": ready,
            "step": round(step, 3), "lopsided": round(lopsided, 3), "rim": round(rim, 2), "level": round(level, 3)}


def measure(a: np.ndarray) -> dict:
    h, w = a.shape[:2]
    cy, r = h - UP * w, RADIUS * w
    return {name: one(a, c * w, cy, r) for name, c in zip(("left", "right"), CENTRES)}
