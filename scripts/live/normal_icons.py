"""A detector for the Normal type's minigame icons: a grey disc with a white ring symbol in the middle.

First (2026-11-08, night) a white ring in a grey disc was looked for with ring-shaped kernels. By day, with the sky
at brightness 228 against 100 at night, the real icons' rings averaged 200 to 213 against its 215, and Body Slam rated
Great in 5 of 6; loosened, the kernels fired all over Vigoroth's white fur and eyes.

Now the icon itself, cut from a daytime frame (data/minigame/android/normal_icon.png, 45 px across on a 540-wide
frame), is matched at seven sizes (normalised cross-correlation). On the day's 16 recorded Body Slams, night and day,
real icons scored 0.82 to 0.93 and everything else (stars, clouds, Vigoroth's eyes) 0.42 to 0.58: the threshold is
0.7. It finds about half the icons on a frame and nothing else, 15 ms a half-size frame.
"""
from pathlib import Path

import cv2
import numpy as np

TEMPLATE = Path(__file__).resolve().parents[2] / "data" / "minigame" / "android" / "normal_icon.png"
SIZES = (0.75, 0.9, 1.05, 1.25, 1.5, 1.8, 2.2)
THRESHOLD = 0.7
_cache: dict = {}


def _templates(width: int) -> list:
    if width not in _cache:
        base = cv2.imread(str(TEMPLATE), cv2.IMREAD_GRAYSCALE).astype(np.float32)
        s = width / 540
        _cache[width] = [cv2.resize(base, None, fx=f * s, fy=f * s) for f in SIZES]
    return _cache[width]


def normal_icons(rgb, scales=None, threshold: float = THRESHOLD):
    """[(x, y, score)] as shares of the screen, best first. `scales` is accepted for the old callers and ignored."""
    h, w = rgb.shape[:2]
    g = cv2.cvtColor(np.ascontiguousarray(rgb), cv2.COLOR_RGB2GRAY).astype(np.float32)
    best = np.full((h, w), -1.0, np.float32)
    for t in _templates(w):
        if t.shape[0] >= h or t.shape[1] >= w:
            continue
        r = cv2.matchTemplate(g, t, cv2.TM_CCOEFF_NORMED)
        oy, ox = t.shape[0] // 2, t.shape[1] // 2
        view = best[oy:oy + r.shape[0], ox:ox + r.shape[1]]
        np.maximum(view, r, out=view)
    found = []
    rr = int(35 * w / 540)
    for _ in range(8):
        y, x = np.unravel_index(np.argmax(best), best.shape)
        v = float(best[y, x])
        if v < threshold:
            break
        found.append((x / w, y / h, v))
        best[max(0, y - rr):y + rr, max(0, x - rr):x + rr] = -1
    return [f for f in found if 0.15 < f[1] < 0.97]
