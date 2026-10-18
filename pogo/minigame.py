"""The charged-move minigame: find the type icons on screen, follow them, and plan swipes through them.

The minigame scales a charged move's damage from a quarter (nothing swiped) to all of it (Excellent: 95% of the icons
or more). For about four and a half seconds icons stream across the upper screen: solid discs in the move's type
colour, about a quarter of the screen wide, with a thin light rim and a white type symbol. Measured on the owner's
recordings; scripts/recording/minigame_eval.py checks this module on them.

Needs OpenCV (the screen reader's Python, .reader/py312), as the live loop does; the rest of pogo does not.

- `detect(frame)`: the icons in one frame, as (x, y, r) in shares of the screen width (x, r) and height (y).
- `Follower`: matches icons from frame to frame and estimates each one's velocity.
- `plan(icons, latency)`: a swipe path through where the icons will be when the swipe lands.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

WIDTH = 300  # frames are shrunk to this width for detection
RADIUS = (0.085, 0.135)  # icon radius as a share of the screen width
REGION = (0.05, 0.86)  # icons appear between these shares of the height


def detect(frame: np.ndarray) -> list[tuple[float, float, float]]:
    import cv2
    h, w = frame.shape[:2]
    scale = WIDTH / w
    small = cv2.resize(frame, (WIDTH, int(h * scale)), interpolation=cv2.INTER_AREA)
    sh = small.shape[0]
    gray = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_RGB2GRAY), (5, 5), 1.2)
    rmin, rmax = int(RADIUS[0] * WIDTH), int(RADIUS[1] * WIDTH)
    found = cv2.HoughCircles(gray, cv2.HOUGH_GRADIENT, dp=1.2, minDist=int(1.2 * rmin), param1=90, param2=22,
                             minRadius=rmin, maxRadius=rmax)
    out = []
    if found is None:
        return out
    hsv = cv2.cvtColor(small, cv2.COLOR_RGB2HSV).astype(np.float32)
    yy, xx = np.mgrid[0:sh, 0:WIDTH]
    for cx, cy, r in found[0]:
        if not (REGION[0] * sh < cy < REGION[1] * sh):
            continue
        d2 = (xx - cx) ** 2 + (yy - cy) ** 2
        ring = (d2 > (0.5 * r) ** 2) & (d2 < (0.85 * r) ** 2)  # the disc's colour, outside the symbol
        core = d2 < (0.35 * r) ** 2  # the white symbol
        outside = (d2 > (1.15 * r) ** 2) & (d2 < (1.5 * r) ** 2)
        if ring.sum() < 20 or core.sum() < 5 or outside.sum() < 20:
            continue
        disc, sym, around = small[ring].astype(np.float32), small[core].astype(np.float32), small[outside].astype(np.float32)
        uniform = disc.std(axis=0).mean() < 26  # one flat colour
        symbol = (sym.min(axis=1) > 200).mean() > 0.12  # some white in the middle
        sat = hsv[..., 1][ring].mean() / 255
        distinct = np.abs(disc.mean(axis=0) - around.mean(axis=0)).mean() > 18 or sat > 0.35
        if uniform and symbol and distinct:
            out.append((float(cx / WIDTH), float(cy / sh), float(r / WIDTH)))
    return out


def ring_colour(frame: np.ndarray, icons: list) -> np.ndarray | None:
    """The median colour of the discs around these icons (outside their white symbols): a type's icon colour."""
    import cv2
    h, w = frame.shape[:2]
    small = cv2.resize(frame, (WIDTH, int(h * WIDTH / w)), interpolation=cv2.INTER_AREA)
    yy, xx = np.mgrid[0:small.shape[0], 0:WIDTH]
    picked = []
    for x, y, r in icons:
        cx, cy, rr = x * WIDTH, y * small.shape[0], r * WIDTH
        d2 = (xx - cx) ** 2 + (yy - cy) ** 2
        picked.append(small[(d2 > (0.5 * rr) ** 2) & (d2 < (0.85 * rr) ** 2)])
    return np.median(np.vstack(picked), axis=0) if picked else None


def detect_colour(frame: np.ndarray, colour, tolerance: float = 48.0, radius=(0.035, 0.17)) -> list[tuple[float, float, float]]:
    """Icons of one type, found by their colour: pixels near `colour`, holes (the white symbol) filled, and the
    centres of the discs taken from the distance to the edge, so overlapping icons of different sizes come apart."""
    import cv2
    h, w = frame.shape[:2]
    small = cv2.resize(frame, (WIDTH, int(h * WIDTH / w)), interpolation=cv2.INTER_AREA).astype(np.float32)
    sh = small.shape[0]
    mask = (np.linalg.norm(small - np.asarray(colour, dtype=np.float32), axis=2) < tolerance).astype(np.uint8)
    mask[: int(REGION[0] * sh)] = 0
    mask[int(REGION[1] * sh):] = 0
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    filled = mask.copy()
    flood = np.zeros((sh + 2, WIDTH + 2), np.uint8)
    cv2.floodFill(filled, flood, (0, 0), 1)
    mask = mask | (1 - filled)  # the white symbols become part of their discs
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    dist = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
    rmin, rmax = radius[0] * WIDTH, radius[1] * WIDTH
    peaks = (dist == cv2.dilate(dist, np.ones((9, 9), np.uint8))) & (dist >= rmin)
    out = []
    for y, x in sorted(zip(*np.nonzero(peaks)), key=lambda p: -dist[p]):
        r = float(dist[y, x])
        if r > rmax or any((x - ox) ** 2 + (y - oy) ** 2 < (0.8 * max(r, orr)) ** 2 for ox, oy, orr in out):
            continue
        out.append((float(x), float(y), r))
    return [(x / WIDTH, y / sh, r / WIDTH) for x, y, r in out]


@dataclass
class Icon:
    x: float
    y: float
    r: float
    t: float
    vx: float = 0.0
    vy: float = 0.0
    seen: int = 1
    ident: int = 0


@dataclass
class Follower:
    """Icons matched across frames by nearest neighbour; velocity in screen shares per second."""

    aspect: float = 2622 / 1206  # screen height over width, to measure distance in one unit
    icons: list = field(default_factory=list)
    _next: int = 0

    def update(self, found: list, t: float) -> list[Icon]:
        out, used = [], set()
        for x, y, r in found:
            best, best_d = None, None
            for k, ic in enumerate(self.icons):
                if k in used:
                    continue
                dt = t - ic.t
                px, py = ic.x + ic.vx * dt, ic.y + ic.vy * dt
                d = ((x - px) ** 2 + ((y - py) * self.aspect) ** 2) ** 0.5
                if d < 1.2 * r and (best_d is None or d < best_d):
                    best, best_d = k, d
            if best is None:
                out.append(Icon(x, y, r, t, ident=self._next))
                self._next += 1
                continue
            used.add(best)
            old = self.icons[best]
            dt = max(t - old.t, 1e-3)
            vx, vy = (x - old.x) / dt, (y - old.y) / dt
            a = 0.5 if old.seen > 1 else 1.0
            out.append(Icon(x, y, r, t, a * vx + (1 - a) * old.vx, a * vy + (1 - a) * old.vy, old.seen + 1, old.ident))
        self.icons = out
        return out


def plan(icons: list[Icon], latency: float, ms: int = 250) -> list[tuple[float, float]]:
    """A swipe through where the icons will be `latency` seconds from now, right to left as they arrive. A single
    icon gets a short stroke across it."""
    if not icons:
        return []
    ahead = [(ic.x + ic.vx * latency, ic.y + ic.vy * latency, ic.r) for ic in icons]
    ahead = [(min(max(x, 0.03), 0.97), min(max(y, 0.08), 0.85), r) for x, y, r in ahead]
    ahead.sort(key=lambda p: -p[0])
    if len(ahead) == 1:
        x, y, r = ahead[0]
        return [(x + 0.6 * r, y), (x - 0.6 * r, y)]
    return [(x, y) for x, y, _ in ahead]
