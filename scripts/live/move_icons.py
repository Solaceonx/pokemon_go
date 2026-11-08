"""A charged move's minigame icons found by matching a cut-out of the icon itself (task 40), as Normal's are in
normal_icons.py: data/minigame/android/icon_<MOVE>.png, cut from this phone's recordings on a half-size frame
(270 x 600), matched at four sizes by normalised cross-correlation.

Templates were cut by scripts/live/cut_icon_template.py: of the colour detector's candidates with a white type symbol
in the middle and a ring of the type's colour, the sharpest forty, and of those the one most like the rest. On each
move's recorded minigames real icons scored about 0.9 to 0.97 and the rest (dust, sky, the Pokemon) under 0.85:
icons are taken from 0.9.

    move_icons(rgb, "MUD_BOMB") -> [(x, y, score)]   as shares of the screen, best first; [] with no template
"""
from pathlib import Path

import cv2
import numpy as np

FOLDER = Path(__file__).resolve().parents[2] / "data" / "minigame" / "android"
SIZES = (0.8, 1.0, 1.25, 1.6)
THRESHOLD = 0.9
_cache: dict = {}


def template_path(move_id: str, move_type: str = ""):
    """The move's own cut-out, else its type's: the icons are the type's (Foul Play's cut-out found Dark Pulse's
    icons, 110 matches over 0.9 where Dark Pulse's own made 4; Mud Bomb's found Bulldoze's as well as its own)."""
    for path in (FOLDER / f"icon_{move_id.lower()}.png", FOLDER / f"icon_type_{move_type.lower()}.png"):
        if path.name != "icon_type_.png" and path.exists():
            return path
    return None


def has_template(move_id: str, move_type: str = "") -> bool:
    return template_path(move_id, move_type) is not None


def _templates(move_id: str, width: int, move_type: str = "") -> list:
    key = (move_id, move_type, width)
    if key not in _cache:
        path = template_path(move_id, move_type)
        if path is None:
            _cache[key] = []
        else:
            base = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE).astype(np.float32)
            s = width / 270  # cut on a 270-wide frame
            _cache[key] = [cv2.resize(base, None, fx=f * s, fy=f * s) for f in SIZES]
    return _cache[key]


def move_icons(rgb, move_id: str, threshold: float = THRESHOLD, move_type: str = "") -> list:
    """[(x, y, score)] as shares of the screen for a half-size frame (any size works; the cut-outs are scaled)."""
    tps = _templates(move_id, rgb.shape[1], move_type)
    if not tps:
        return []
    h, w = rgb.shape[:2]
    g = cv2.cvtColor(np.ascontiguousarray(rgb), cv2.COLOR_RGB2GRAY).astype(np.float32)
    best = np.full((h, w), -1.0, np.float32)
    for t in tps:
        if t.shape[0] >= h or t.shape[1] >= w:
            continue
        r = cv2.matchTemplate(g, t, cv2.TM_CCOEFF_NORMED)
        oy, ox = t.shape[0] // 2, t.shape[1] // 2
        view = best[oy:oy + r.shape[0], ox:ox + r.shape[1]]
        np.maximum(view, r, out=view)
    found, rr = [], max(4, int(15 * w / 270))
    for _ in range(8):
        y, x = np.unravel_index(np.argmax(best), best.shape)
        v = float(best[y, x])
        if v < threshold:
            break
        found.append((x / w, y / h, v))
        best[max(0, y - rr):y + rr, max(0, x - rr):x + rr] = -1
    return [f for f in found if 0.15 < f[1] < 0.97]
