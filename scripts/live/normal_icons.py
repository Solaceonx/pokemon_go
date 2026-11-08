"""A detector for the Normal type's minigame icons: a grey disc with a white ring symbol in the middle (measured
2026-11-08 on this phone: ring radius 15-24 px of the 540-wide frame, grey about 150 inside and around it)."""
import cv2
import numpy as np


def _kernel(r0, r1, size):
    yy, xx = np.mgrid[-size:size + 1, -size:size + 1]
    r = np.hypot(xx, yy)
    k = ((r >= r0) & (r <= r1)).astype(np.float32)
    return k / k.sum()


KERNELS = {}


def normal_icons(rgb, scales=(0.8, 1.0, 1.2)):
    """[(x, y, score)] as shares of the screen."""
    h, w = rgb.shape[:2]
    s = w / 540
    g = rgb.astype(np.float32).mean(2)
    best = None
    for sc in scales:
        key = (round(sc * s, 3))
        if key not in KERNELS:
            f = sc * s
            size = int(36 * f)
            KERNELS[key] = (_kernel(16 * f, 23 * f, size), _kernel(0, 10 * f, size), _kernel(28 * f, 34 * f, size))
        ka, kc, ko = KERNELS[key]
        ann = cv2.filter2D(g, -1, ka)
        cen = cv2.filter2D(g, -1, kc)
        out = cv2.filter2D(g, -1, ko)
        score = np.where((ann > 215) & (cen < 190) & (out < 195), ann - np.maximum(cen, out), 0)
        best = score if best is None else np.maximum(best, score)
    found = []
    sm = best.copy()
    for _ in range(8):
        y, x = np.unravel_index(np.argmax(sm), sm.shape)
        v = sm[y, x]
        if v < 35:
            break
        found.append((x / w, y / h, float(v)))
        rr = int(40 * s)
        sm[max(0, y - rr):y + rr, max(0, x - rr):x + rr] = 0
    return [f for f in found if 0.15 < f[1] < 0.97]
