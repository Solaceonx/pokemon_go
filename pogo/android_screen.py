"""Read the battle screen of the Android phone (task 40): health bars, shields, Pokémon left, the charged-move buttons,
and the prompts. Calibrated on the owner's moto g stylus 5G (2024), 1080 x 2400 streamed by scrcpy at 540 x 1200;
positions are shares of that frame, so another size of the same screen works too.

Everything here is a quick look at pixels (a few milliseconds a frame). Names are text and need OCR, which is slow
(about 0.4 s), so `NameReader` reads the opponent's name in the background only when that part of the header changes.
"""
from __future__ import annotations

import difflib
import re
import threading
from dataclasses import dataclass, field

import numpy as np

W, H = 540, 1200  # the frame the positions below were measured on
BALL_Y = 115
BALLS = {"mine": (29, 58, 88), "theirs": (452, 482, 511)}
SHIELDS = {"mine": (128, 153), "theirs": (387, 413)}
HEADER_PATCHES = ((195, 124), (340, 124))  # inside the two header boxes, clear of text and icons
FOE_NAME = (395, 76, 536, 106)  # x0, y0, x1, y1: their Pokémon's name, right-aligned in their header box
# Ours, left-aligned in our header box. In GO Battle League it is the species ("Jellicent": online battles hide
# nicknames); against the Team Leaders it is the nickname (".gl1" on the owner's spare account).
MY_NAME = (4, 76, 130, 106)
LABELS = (30, 1118, 510, 1150)  # the move names under the two charged-move buttons
SHIELD_ICON = (258, 998, 282, 1022)  # the pink shield in the middle of the shield prompt
NOT_NOW_ROW = (1133, 1147, 200, 340)  # y0, y1, x0, x1 of "NOT NOW" under it
PANEL = (60, 875, 480, 895)  # a strip of the dark panel the prompts come up in
BAR_ROWS = (250, 950)  # health bars float over the Pokémon somewhere in these rows


def _scale(a: np.ndarray):
    h, w = a.shape[:2]
    return w / W, h / H


def _patch(a: np.ndarray, x: int, y: int, r: int = 1) -> np.ndarray:
    sx, sy = _scale(a)
    x, y = int(x * sx), int(y * sy)
    return a[max(0, y - r):y + r + 1, max(0, x - r):x + r + 1].reshape(-1, 3).astype(int).mean(0)


def header_visible(a: np.ndarray) -> bool:
    for x, y in HEADER_PATCHES:
        p = _patch(a, x, y, 2)
        if p.min() < 140 or p.max() - p.min() > 70:
            return False
    return True


def left(a: np.ndarray, side: str) -> int:
    """Pokémon not yet fainted: the red balls in that side's header."""
    n = 0
    for x in BALLS[side]:
        r, g, b = _patch(a, x, BALL_Y)
        n += r > 140 and g < 100 and b < 100
    return n


def shields(a: np.ndarray, side: str) -> int:
    n = 0
    for x in SHIELDS[side]:
        r, g, b = _patch(a, x, BALL_Y)
        n += r > 175 and b > 185 and 110 < g < 215
    return n


def shield_prompt(a: np.ndarray) -> bool:
    sx, sy = _scale(a)
    x0, y0, x1, y1 = SHIELD_ICON
    icon = a[int(y0 * sy):int(y1 * sy), int(x0 * sx):int(x1 * sx)].reshape(-1, 3).astype(int)
    # The shield is a true pink (green well under red and blue: 217, 162, 238); Jellicent's pale lavender body
    # (about 220, 210, 240) passed the looser test during our own minigames and cut the swipe short.
    pink = ((icon[:, 0] > 175) & (icon[:, 2] > 185) & (icon[:, 1] > 110)
            & (icon[:, 1] < np.minimum(icon[:, 0], icon[:, 2]) - 35)).mean()
    ya, yb, xa, xb = NOT_NOW_ROW
    words = a[int(ya * sy):int(yb * sy), int(xa * sx):int(xb * sx)].reshape(-1, 3).astype(int)
    white = (words.min(1) > 225).mean()
    # ... and it sits on the prompt's dark panel: beside the shield, left of it.
    panel = a[int(1040 * sy):int(1100 * sy), int(70 * sx):int(150 * sx)].reshape(-1, 3).astype(int)
    dark = panel.mean(0).max() < 120
    return pink > 0.5 and white > 0.02 and dark


def dark_panel(a: np.ndarray) -> bool:
    sx, sy = _scale(a)
    x0, y0, x1, y1 = PANEL
    strip = a[int(y0 * sy):int(y1 * sy), int(x0 * sx):int(x1 * sx)].reshape(-1, 3).astype(int)
    return strip.mean(0).max() < 85


def _flat_dark(a: np.ndarray, y0: int, y1: int, x0: int = 60, x1: int = 480) -> bool:
    """A strip of the prompts' panel: dark and even (the battlefield, even at night, is neither)."""
    sx, sy = _scale(a)
    strip = a[int(y0 * sy):int(y1 * sy), int(x0 * sx):int(x1 * sx)].reshape(-1, 3).astype(int)
    return strip.mean(0).max() < 85 and strip.std(0).max() < 14


def replace_prompt(a: np.ndarray) -> bool:
    """'Switch in a new Pokémon?': an even dark panel from above its title down below the cards, the title's white
    words in it, and no shield (that is the shield prompt)."""
    return (_flat_dark(a, 875, 895) and _flat_dark(a, 1160, 1185) and _title(a) and not shield_prompt(a))


def _title(a: np.ndarray) -> bool:
    """White title text across the top of the panel (the replacement prompt's question)."""
    sx, sy = _scale(a)
    row = a[int(902 * sy):int(918 * sy), int(120 * sx):int(420 * sx)].reshape(-1, 3).astype(int)
    return (row.min(1) > 225).mean() > 0.04


def _damage_mask(row: np.ndarray) -> np.ndarray:
    """The orange strip a hit leaves at the end of the fill for a second or so while it shrinks (about (250, 155,
    10) on this phone; yellow fill is (244, 206, 57) and red (235, 100, 105)). It is health already lost."""
    r, g, b = row[:, 0], row[:, 1], row[:, 2]
    return (r > 200) & (g >= 125) & (g <= 182) & (b < 60)


def _fill_mask(row: np.ndarray) -> np.ndarray:
    r, g, b = row[:, 0], row[:, 1], row[:, 2]
    green = (g > 180) & (r < 130) & (g > b)
    yellow = (r > 180) & (g > 150) & (b < 120)
    red = (r > 180) & (g < 140) & (b < 120)
    return (green | yellow | red) & ~_damage_mask(row)


def _empty_mask(row: np.ndarray) -> np.ndarray:
    return (row.max(1) < 130) & (row[:, 2] >= row[:, 0])


BAR_INSIDE = 148.5  # the fill of a full bar, in pixels of the 540-wide frame; every bar is the same size


def bar_places(a: np.ndarray) -> dict:
    """{"mine": (share, top row, left end of the fill), ...} for each health bar found, rows and columns on the
    540 x 1200 frame (a side is missing when its bar is not seen). The fill (green, yellow or red) starts just inside the bar's light left border and runs for the share of
    BAR_INSIDE that is left; the empty part is see-through, so it is not used. The orange strip a hit leaves is not
    fill (2026-11-08: counted on some frames and not others, it made the bar jump 2 to 6 pixels each frame for a
    second after every hit, so steps of one fast move could not be told from noise). A bar is three rows deep or more;
    ours is the one whose left end is in the left third of the screen."""
    sx, sy = _scale(a)
    lo, hi = int(BAR_ROWS[0] * sy), int(BAR_ROWS[1] * sy)
    full = BAR_INSIDE * sx
    found = []  # (y, x0, fill length)
    for y in range(lo, hi, 2):
        row = a[y].astype(int)
        xs = np.nonzero(_fill_mask(row))[0]
        if not len(xs):
            continue
        for run in np.split(xs, np.nonzero(np.diff(xs) > 4)[0] + 1):  # a blended pixel or two is bridged
            x0, length = int(run[0]), int(run[-1] - run[0] + 1)
            if length > full + 5 * sx or x0 < 4 or x0 + full > a.shape[1] + 3 * sx:
                continue  # too long for a bar, or a bar starting here would run off the screen
            rest = row[x0 + length + int(3 * sx):int(x0 + full)]
            if len(rest) > 8 * sx and ((rest.max(1) < 150) | _damage_mask(rest)).mean() < 0.7:
                continue  # the part after the fill is not the bar's dark, see-through empty part
            border = row[x0 - 4:x0].min(1).max()  # the light border a few pixels left of the fill
            if border > 150:
                found.append((y, x0, length))
    groups: list[list] = []
    for run in found:
        for g in groups:
            if 0 < run[0] - g[-1][0] <= 4 and abs(g[-1][1] - run[1]) <= 3:
                g.append(run)
                break
        else:
            groups.append([run])
    def framed(g) -> bool:
        """The bar's light top border runs along just above the fill."""
        y0, x0 = g[0][0], g[0][1]
        span = slice(x0, x0 + max(4, int(12 * sx)))
        return any((a[y, span].astype(int).min(1) > 140).mean() > 0.7 for y in range(max(0, y0 - 6), y0))

    out = {}
    for g in sorted(groups, key=len, reverse=True):
        if not 3 <= len(g) <= 9 or not framed(g):  # a bar is about 10 pixels deep: 3 to 9 rows sampled every 2
            continue
        side = "mine" if g[0][1] / sx < W / 3 else "theirs"
        if side not in out:
            out[side] = (round(min(1.0, float(np.median([r[2] for r in g])) / full), 3),
                         round(g[0][0] / sy), round(float(np.median([r[1] for r in g])) / sx))
    return out


def bars(a: np.ndarray) -> dict:
    """{"mine": share, "theirs": share} for each health bar found (a side is missing when its bar is not seen)."""
    return {side: v[0] for side, v in bar_places(a).items()}


def bar_near(a: np.ndarray, y_at: int, x_at: int, y_slack: int = 40, x_slack: int = 3) -> float | None:
    """A health bar's share where one was just read (its top row and the left end of its fill, on the 540 x 1200
    frame), without the checks bars() needs to find one anywhere: its light borders, which a word over the bar
    ("NOT VERY EFFECTIVE...", "BLOCKED!") or a thin red sliver at low health hides. The dark, see-through part after
    the fill is still required. The fill must start within x_slack of the same place and keep one length (within 3 pixels) over two to
    nine rows sampled every two; None if no such run is there (2026-11-08: of 30 fight looks with our bar unread,
    such words were over it in 5 and a red sliver of 4% in 4)."""
    sx, sy = _scale(a)
    full = BAR_INSIDE * sx
    lo = max(int(BAR_ROWS[0] * sy), int((y_at - y_slack) * sy))
    hi = min(int(BAR_ROWS[1] * sy), int((y_at + y_slack) * sy))
    x_lo, x_hi = max(1, int((x_at - x_slack) * sx)), int((x_at + x_slack) * sx) + 1
    runs = []
    for y in range(lo, hi, 2):
        row = a[y].astype(int)
        m = _fill_mask(row)
        if m[x_lo - 1] or not m[x_lo:x_hi].any():
            continue  # no fill starting in the window (fill already running before it is not the bar's start)
        x0 = x_lo + int(np.argmax(m[x_lo:x_hi]))
        xs = np.nonzero(m[x0:int(x0 + full + 6 * sx)])[0]
        ends = np.split(xs, np.nonzero(np.diff(xs) > 4)[0] + 1)[0]  # the run from x0, a blended pixel bridged
        length = int(ends[-1]) + 1
        if length > full + 5 * sx or length < 4 * sx:
            continue  # too long for a bar, or a pixel or two (a bar that moved leaves those: 0.007 read for 0.35)
        rest = row[x0 + length + int(3 * sx):int(x0 + full)]
        if len(rest) > 8 * sx and ((rest.max(1) < 150) | _damage_mask(rest)).mean() < 0.7:
            continue  # after the fill, not the bar's dark empty part (a minigame's icons, "GO!" over the bar)
        runs.append((y, length))
    best: list = []
    for y, length in runs:  # the longest stack of rows two apart with one length
        stack = [(y, length)]
        for y2, l2 in runs:
            if y2 == stack[-1][0] + 2 and abs(l2 - length) <= 3 * sx:
                stack.append((y2, l2))
        if len(stack) > len(best):
            best = stack
    if not 2 <= len(best) <= 9:
        return None
    return round(min(1.0, float(np.median([l for _, l in best])) / full), 3)


_HINTS: dict = {}  # side -> (share, top row, left end, time) of the last bar bars() found with all its checks


def bars_held(a: np.ndarray, t: float, keep_s: float = 3.0) -> dict:
    """bars(), and for a side it misses that it found in the last keep_s seconds, bar_near() at that place, kept
    only if not higher than that last reading (health does not come back in a fight; a Pokémon coming in is read
    afresh by bars())."""
    places = bar_places(a)
    out = {}
    fight = header_visible(a)
    for side, (share, y, x0) in places.items():
        if fight:  # a place only from the fight view, not a camera pan or close-up (where bars sit elsewhere)
            _HINTS[side] = (share, y, x0, t)
        out[side] = share
    for side in ("mine", "theirs"):
        if side in out or side not in _HINTS:
            continue
        share, y, x0, at = _HINTS[side]
        if t - at > keep_s or t < at:
            continue
        near = bar_near(a, y, x0)
        if near is not None and near <= share + 0.03:
            out[side] = near
    return out


CUE = (0.18, 0.17, 0.82, 0.30)  # x0, y0, x1, y1: the box "Get Ready!" (our move) or "Attack incoming!" (theirs)


def cue(ocr, a: np.ndarray) -> str | None:
    """'mine' when the top-middle box says Get Ready! (our charged move has started), 'theirs' for Attack incoming!"""
    h, w = a.shape[:2]
    res, _ = ocr(a[int(CUE[1] * h):int(CUE[3] * h), int(CUE[0] * w):int(CUE[2] * w)])
    text = re.sub("[^A-Z]", "", " ".join(r[1] for r in (res or [])).upper())
    if "READY" in text or "GETRE" in text:
        return "mine"
    if "INCOMING" in text or "ATTACKIN" in text:
        return "theirs"
    return None


# Our energy from the two charged-move buttons, as this phone draws them (measured on the training recordings of
# 2026-11-07, C:\pogo-media\live61107-training). Short of a move's cost the button is a dark see-through disc
# with the type's colour rising from the bottom, and no name under it; at the cost the whole disc turns a light shade
# of the colour (with a white ring for a moment) and the move's name shows; past it a darker shade rises from the
# bottom toward a second throw. So the fill is read as a level from 0 to 2: the share of the disc's height below
# the boundary, plus 1 when the part above is the brighter (the light shade, over a darker second fill). Energy =
# level x cost, never above 100. Checks that the buttons are on screen at all (a charged move's close-ups put a
# Pokémon's body there): each name shows exactly when its level is 1 or more, and the two buttons, with their
# different costs, give the same energy.
BUTTONS = ((0.3093, 0.893), (0.6907, 0.893))  # centres, shares of width and height (pogo.controls.CHARGED_BUTTONS)
BUTTON_INSIDE = 0.087  # radius inside the ring, share of the width
BUTTON_LABELS_Y = (0.932, 0.958)  # the move name under each button


def _button_profile(a: np.ndarray, k: int) -> np.ndarray:
    """Mean colour of each row of button k's disc, top to bottom: the middle column above and below the type
    symbol, two short strips either side of it level with it."""
    h, w = a.shape[:2]
    cx, cy = int(BUTTONS[k][0] * w), int(BUTTONS[k][1] * h)
    r = int(BUTTON_INSIDE * w)
    prof = []
    for dy in range(-r + 2, r - 1):
        half = int((r * r - dy * dy) ** 0.5)
        if abs(dy) > 0.55 * r:
            m = min(int(0.09 * r) + 4, half - 2)
            px = a[cy + dy, cx - m:cx + m + 1]
        else:
            lo, hi = int(0.58 * r), min(int(0.80 * r), half - 3)
            px = np.concatenate([a[cy + dy, cx - hi:cx - lo + 1], a[cy + dy, cx + lo:cx + hi + 1]])
        prof.append(px.reshape(-1, 3).astype(float).mean(0))
    return np.array(prof)


def button_level(a: np.ndarray, k: int):
    """How full button k is: a level from 0 to 2 (see above); "uniform" when the disc is one colour (empty, exactly
    one throw's worth, or two); None when it cannot be told."""
    return _button_parts(a, k)[0]


def _button_parts(a: np.ndarray, k: int):
    """(level as button_level gives it, colour of the part above the boundary, colour below, the whole disc's)."""
    prof = _button_profile(a, k)
    n = len(prof)
    cs, cs2 = np.cumsum(prof, 0), np.cumsum(prof ** 2, 0)
    best, s = None, None
    for i in range(3, n - 2):  # the row the two parts meet at, by least squares
        top, top2 = cs[i - 1], cs2[i - 1]
        bot, bot2 = cs[-1] - top, cs2[-1] - top2
        cost = (top2 - top ** 2 / i).sum() + (bot2 - bot ** 2 / (n - i)).sum()
        if best is None or cost < best:
            best, s = cost, i
    upper, lower, whole = prof[:s].mean(0), prof[s:].mean(0), prof.mean(0)
    if np.abs(upper - lower).max() < 22:
        return "uniform", upper, lower, whole
    share = (n - s) / n
    if lower.mean() > upper.mean() + 15:
        return share, upper, lower, whole  # the empty dark above, the colour below
    if upper.mean() > lower.mean() + 15:
        return 1 + share, upper, lower, whole  # one throw paid for (light), the darker shade below toward a second
    return None, upper, lower, whole


# The light shade a paid-for button turns, by the move's type, measured on this phone (2026-11-07 training
# recordings; the median of 47 to 161 frames each). The pair (button, type) tells the move, so which of ours is out.
PAID_SHADES = {"ghost": (134, 144, 195), "water": (130, 177, 220), "electric": (244, 221, 120),
               "ground": (221, 156, 120), "normal": (177, 183, 186)}


def paid_shades(a: np.ndarray, k: int) -> dict | None:
    """How far button k's colour is from each type's paid-for shade (mean per channel), when the button shows its
    move paid for; None when it does not (not paid for, or not on screen)."""
    level, upper, _, whole = _button_parts(a, k)
    if isinstance(level, float) and level >= 1.0:
        colour = upper
    elif level == "uniform" and button_labels(a)[k]:
        colour = whole
    else:
        return None
    return {t: float(np.abs(colour - np.array(c)).mean()) for t, c in PAID_SHADES.items()}


def paid_type(a: np.ndarray, k: int) -> str | None:
    """The type of button k's move when the button shows it paid for, or None: not paid for, not on screen, or no
    shade near (within 25) and clear of the next nearest by 15. Right on 97% of frames of known Pokémon; most misses
    were Water (Bubble Beam) taken for Normal."""
    far = paid_shades(a, k)
    if far is None:
        return None
    first, second = sorted(far, key=far.get)[:2]
    return first if far[first] < 25 and far[second] > far[first] + 15 else None


def button_labels(a: np.ndarray) -> list:
    """Whether each button's move name shows under it (white letters, a few per cent of the box): the game writes
    it only when the move is paid for. None for a box that is neither clear nor plain text."""
    h, w = a.shape[:2]
    out = []
    for bx, _ in BUTTONS:
        box = a[int(BUTTON_LABELS_Y[0] * h):int(BUTTON_LABELS_Y[1] * h), int((bx - 0.11) * w):int((bx + 0.11) * w)]
        white = (box.reshape(-1, 3).min(1) > 215).mean()
        out.append(True if 0.03 <= white <= 0.22 else False if white < 0.005 else None)
    return out


def button_rim(a: np.ndarray, k: int) -> float:
    """How sharply button k's rim is drawn: the median brightness step across a circle near its edge, the best of a
    few radii (a button on screen: 10 or more, empty; 150 or more, paid; hidden: under 4)."""
    h, w = a.shape[:2]
    g = a.astype(np.float32).mean(2)
    cx, cy = BUTTONS[k][0] * w, BUTTONS[k][1] * h
    ang = np.linspace(0, 2 * np.pi, 120, endpoint=False)

    def ring(r):
        xs = (cx + r * w * np.cos(ang)).astype(int).clip(0, w - 1)
        ys = (cy + r * w * np.sin(ang)).astype(int).clip(0, h - 1)
        return g[ys, xs]
    return max(float(np.median(np.abs(ring(r + 0.006) - ring(r - 0.006)))) for r in np.arange(0.080, 0.104, 0.004))


def my_energy(a: np.ndarray, costs) -> float | None:
    """Our energy from the buttons' fill (costs: the two charged moves' energy, in button order), or None when the
    buttons are not both on screen and in agreement."""
    if len(costs) != 2:
        return None
    labels = button_labels(a)
    spans = []
    for k, c in enumerate(costs):
        lv, named = button_level(a, k), labels[k]
        tol = max(3.0, 0.07 * c)
        if lv is None or named is None:
            return None
        if lv == "uniform":
            if named is False and float(np.mean(_button_parts(a, k)[3])) < 120 and button_rim(a, k) >= 7:
                # an empty button: dark all over, its name plainly not showing, and its rim drawn. Without the rim
                # test this read 0 on frames where the game hides the buttons (around charged moves; 2026-11-08:
                # nearly all such frames had no rim, edge under 4, against 10 to 12 for an empty button shown).
                spans.append([(0.0, max(3.0, 0.08 * c))])
                continue
            if not named:
                return None  # bright, or its name unclear: not to be read
            spans.append([(c - tol, c + tol), (min(100.0, 2 * c) - tol, 100.0)])  # one throw's worth, or two
            continue
        if named != (lv >= 0.97) and abs(lv - 1) > 0.06:
            return None  # the name shows exactly when the move is paid for
        if lv < 0.04:
            return None
        if lv >= 1.95:  # the second fill complete: two throws' worth or more
            spans.append([(min(100.0, 2 * c) - tol, 100.0)])
        else:
            e = min(100.0, lv * c)
            spans.append([(e - tol, min(100.0, e + tol))])
    best = None
    for lo0, hi0 in spans[0]:
        for lo1, hi1 in spans[1]:
            lo, hi = max(lo0, lo1), min(hi0, hi1)
            if lo <= hi and (best is None or hi - lo < best[1] - best[0]):
                best = (lo, hi)
    if best is None:
        return None
    return max(0.0, min(100.0, (best[0] + best[1]) / 2))


BENCH_STRIP = (0.84, 0.57, 0.97, 0.73)  # x0, y0, x1, y1: our two benched Pokémon's portraits at the right edge


def bench_strip(a: np.ndarray) -> np.ndarray:
    """The bench portraits, coarsely, to tell whether a switch went through: after one, the Pokémon sent in leaves
    the bench and the one called back sits there under the switch timer (the strip differs from before by 60 to 75
    on average, and stays so); a tap the game did not take leaves it within 17 to 31 (2026-11-07 recordings)."""
    h, w = a.shape[:2]
    x0, y0, x1, y1 = BENCH_STRIP
    return a[int(y0 * h):int(y1 * h):2, int(x0 * w):int(x1 * w):2].astype(np.int16)


def buttons(a: np.ndarray) -> dict:
    """The two charged-move buttons (scripts/recording/buttons.py): fill share, present, ready."""
    import sys
    from pathlib import Path
    here = Path(__file__).resolve().parent.parent / "scripts" / "recording"
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))
    from buttons import measure
    return measure(a)


@dataclass
class Look:
    """One reading of the screen."""

    t: float
    header: bool
    my_left: int | None = None
    foe_left: int | None = None
    my_shields: int | None = None
    foe_shields: int | None = None
    bars: dict = field(default_factory=dict)
    buttons: dict = field(default_factory=dict)
    shield_prompt: bool = False
    replace_prompt: bool = False


def read(a: np.ndarray, t: float) -> Look:
    head = header_visible(a)
    look = Look(t=t, header=head, bars=bars_held(a, t), buttons=buttons(a), shield_prompt=shield_prompt(a))
    look.replace_prompt = not look.shield_prompt and replace_prompt(a)
    if head:
        look.my_left, look.foe_left = left(a, "mine"), left(a, "theirs")
        look.my_shields, look.foe_shields = shields(a, "mine"), shields(a, "theirs")
    return look


# The type icons in each header's top corner (their Pokémon's on the right, right-aligned; ours on the left), and the
# game's type colours: measured on this phone (2026-11-08) for fire, rock, ground, electric, water, psychic, ice,
# ghost and normal within 10 of these, and the sky behind an empty slot 60 or more from all of them.
TYPE_COLOURS = {"normal": (160, 162, 159), "fire": (251, 165, 76), "water": (83, 157, 223), "electric": (242, 217, 78),
                "grass": (95, 189, 88), "ice": (117, 208, 193), "fighting": (211, 66, 95), "poison": (183, 99, 207),
                "ground": (218, 124, 77), "flying": (161, 187, 236), "psychic": (250, 133, 129), "bug": (146, 188, 44),
                "rock": (201, 187, 138), "ghost": (95, 109, 188), "dragon": (12, 105, 200), "dark": (89, 87, 97),
                "steel": (86, 149, 163), "fairy": (238, 144, 230)}
TYPE_SLOTS = {"theirs": (0.957, 0.902), "mine": (0.043, 0.098)}  # first type's slot, then the second's
TYPE_Y = 0.0425


def header_types(a: np.ndarray, side: str = "theirs") -> list:
    """The types the header's icons show for that side's Pokémon (one or two), [] if none can be told."""
    h, w = a.shape[:2]
    r = max(3, int(0.016 * w))
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    disc = (xx ** 2 + yy ** 2) <= r * r
    out = []
    for cx in TYPE_SLOTS[side]:
        x, y = int(cx * w), int(TYPE_Y * h)
        px = a[y - r:y + r + 1, x - r:x + r + 1][disc].astype(float)
        px = px[px.min(1) < 200]  # not the white symbol
        if len(px) < 10:
            break
        col = np.median(px, 0)
        name, d = min(((k, float(np.abs(col - np.array(v)).max())) for k, v in TYPE_COLOURS.items()), key=lambda x: x[1])
        if d > 30:
            break
        out.append(name)
    return out


def species_lookup(gd) -> dict:
    """Screen names ("Plusle", "Mega Venusaur") to species ids. Where forms share a name, the one in the Great League
    rankings, the regular form before regional ones: 2026-11-08, "Darmanitan" was taken for Galarian Zen Darmanitan
    (the first in the game data's order), which no league ranks, so the tracker failed for the whole of its stretch
    and the engine threw Discharge where Mud Bomb was super effective. Regional forms are found later by their moves
    (Tracker._other_form)."""
    ranked = {e["speciesId"] for e in gd.rankings(1500)}
    regional = ("_alolan", "_galarian", "_hisuian", "_paldean")
    forms: dict[str, list] = {}
    for sid, p in gd.species.items():
        name = p["speciesName"]
        if "(Shadow)" in name or sid.endswith("_shadow"):
            continue
        m = re.match(r"^(.*) \(Mega( [XY])?\)$", name)
        screen = f"Mega {m.group(1)}{m.group(2) or ''}" if m else re.sub(r" \(.*\)$", "", name)
        forms.setdefault(screen.lower(), []).append(sid)
    return {name: min(sids, key=lambda s: (s not in ranked, any(r in s for r in regional), sids.index(s)))
            for name, sids in forms.items()}


def form_by_types(gd, sid: str, types: list) -> str:
    """Of the forms sharing sid's screen name, the one whose types are those the header's icons show (2026-11-08:
    Hisuian Arcanine, fire and rock, was taken for the regular one until it threw Rock Slide, 130 s in; the icons
    showed both types from the first second). sid itself when the icons tell nothing new."""
    if not types:
        return sid
    name = re.sub(r" \(.*\)$", "", gd.species[sid]["speciesName"])
    ranked = {e["speciesId"] for e in gd.rankings(1500)}
    same = [x for x, p in gd.species.items() if re.sub(r" \(.*\)$", "", p["speciesName"]) == name
            and not x.endswith("_shadow") and "(Shadow)" not in p["speciesName"]]
    fits = [x for x in same if {t for t in gd.species[x]["types"] if t != "none"} == set(types)]
    if sid in fits or not fits:
        return sid
    return min(fits, key=lambda x: (x not in ranked, same.index(x)))


class NameReader:
    """Reads their Pokémon's name in a background thread when that part of the header changes."""

    def __init__(self, gd):
        from rapidocr_onnxruntime import RapidOCR
        self.ocr = RapidOCR()
        self.gd = gd
        self.names = species_lookup(gd)
        self.types = []  # their Pokémon's types as the header's icons last showed
        self.resolved = {}  # a name's usual form -> the form its type icons showed
        self.species = None  # the last name read, as a species id
        self.read_at = None  # time of the frame it was read from
        self.labels, self.labels_at = [], None  # the last button labels read
        self.my_name, self.my_name_at = "", None  # the last name read in our header
        self._sig = None
        self._busy = False
        self._lock = threading.Lock()

    def offer(self, a: np.ndarray, t: float) -> None:
        sx, sy = _scale(a)
        x0, y0, x1, y1 = FOE_NAME
        crop = a[int(y0 * sy):int(y1 * sy), int(x0 * sx):int(x1 * sx)]
        sig = crop[::3, ::3].astype(int)
        with self._lock:
            if self._busy or (self._sig is not None and np.abs(sig - self._sig).mean() < 6):
                return
            self._busy, self._sig = True, sig
        types = header_types(a, "theirs")
        threading.Thread(target=self._read, args=(crop.copy(), t, types), daemon=True).start()

    def _read(self, crop: np.ndarray, t: float, types: list | None = None) -> None:
        try:
            res, _ = self.ocr(crop)
            words = [r[1] for r in (res or []) if not re.match(r"^\W*CP", r[1], re.I)]
            text = " ".join(words).strip()
            sid = self.match(text)
            if sid and types:
                self.resolved[sid] = form_by_types(self.gd, sid, types)
                self.types = types
            if sid:
                # a name once told apart by its type icons stays so when they are hidden on a later reading
                sid = self.resolved.get(sid, sid)
                with self._lock:
                    self.species, self.read_at = sid, t
        finally:
            with self._lock:
                self._busy = False

    def offer_mine(self, a: np.ndarray, t: float) -> None:
        """Our Pokémon's name in our header, read in the background when that part changes: self.my_name, as read,
        and self.my_name_at, the time of the frame it was read from. Its own thread and flag, so it waits for
        neither of the other readings (2026-11-08: the names under the buttons show only for moves paid for, and
        after a wrong switch the player took Jellicent for Vigoroth for 40 s)."""
        sx, sy = _scale(a)
        x0, y0, x1, y1 = MY_NAME
        crop = a[int(y0 * sy):int(y1 * sy), int(x0 * sx):int(x1 * sx)]
        sig = crop[::3, ::3].astype(int)
        with self._lock:
            if getattr(self, "_mine_busy", False) or (getattr(self, "_mine_sig", None) is not None
                                                      and np.abs(sig - self._mine_sig).mean() < 6):
                return
            self._mine_busy, self._mine_sig = True, sig

        def read():
            try:
                res, _ = self.ocr(crop.copy())
                words = " ".join(r[1] for r in (res or []) if not re.match(r"^\W*CP", r[1], re.I))
                with self._lock:
                    self.my_name, self.my_name_at = words, t
            finally:
                with self._lock:
                    self._mine_busy = False
        threading.Thread(target=read, daemon=True).start()

    def offer_labels(self, a: np.ndarray, t: float) -> None:
        """The names under our two charged-move buttons, which say which of our Pokémon is out (the header shows
        nicknames). Read in the background when that band changes; the result is in self.labels."""
        sx, sy = _scale(a)
        crop = a[int(LABELS[1] * sy):int(LABELS[3] * sy), int(LABELS[0] * sx):int(LABELS[2] * sx)]
        sig = crop[::3, ::3].astype(int)
        with self._lock:
            if self._busy or (getattr(self, "_label_sig", None) is not None and np.abs(sig - self._label_sig).mean() < 6):
                return
            self._busy, self._label_sig = True, sig
        threading.Thread(target=self._read_labels, args=(crop.copy(), t), daemon=True).start()

    def _read_labels(self, crop: np.ndarray, t: float) -> None:
        try:
            res, _ = self.ocr(crop)
            words = [r[1] for r in (res or []) if "EFFECTIVE" not in r[1].upper()]
            with self._lock:
                self.labels, self.labels_at = words, t
        finally:
            with self._lock:
                self._busy = False

    def match(self, text: str) -> str | None:
        key = re.sub(r"[^a-z .'-]", "", text.lower()).strip()
        if not key:
            return None
        if key in self.names:
            return self.names[key]
        close = difflib.get_close_matches(key, list(self.names), n=1, cutoff=0.75)
        return self.names[close[0]] if close else None
