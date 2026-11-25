#!/usr/bin/env python3
"""Play one Pokémon GO battle on the Android phone with the repo's engine (task 40).

    POGO_SCRCPY_DIR=... python3 scripts/live/play_android.py --serial ZY22JPBNMW [--start-tap 0.5 0.871] [--live]

The phone must already show the battle (or the party screen, with --start-tap on "Use this party"). Each look at
the screen (pogo.android_screen) goes to the tracker (pogo.tracker), whose picture goes to the engine the website
plays (pogo.realtime.WEBSITE); its choices become touches (pogo.controls, with the Android bench positions):
fast moves, charged moves with the type's swipe from data/minigame/, switches, shields and replacements.
Without --live nothing is sent (dry run). Every look, decision and touch goes to runs/live/<time>.jsonl (small text);
frames of the minigames go to the scratch folder given by --frames, never to git. Stops at the result screen.
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import json
import math
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
from move_icons import has_template, move_icons  # noqa: E402

from pogo import android_screen as screen  # noqa: E402
from pogo import controls  # noqa: E402
from pogo.android import Android  # noqa: E402
from pogo.battle import CHARGED, FAST, SWITCH  # noqa: E402
from pogo.evaluation import Evaluator  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.learner import QNet  # noqa: E402
from pogo.realtime import WEBSITE, RealTime  # noqa: E402
from pogo.tracker import Observation, Tracker  # noqa: E402

BENCH = ((0.90, 0.603), (0.90, 0.692))  # measured on the moto g stylus 5G (2024)
SHIELD_YES, SHIELD_NO = (0.50, 0.842), (0.50, 0.950)  # the shield's centre and "NOT NOW" on this phone
LOOK = 0.5  # seconds between looks given to the tracker (a turn)
# Their energy as the engine is given it: the count and this many of their fast moves more. Judged by their named
# throws (2026-11-08), the count fell short by a fast move or two at 3 of 8, and Dachsbun threw Psychic Fangs (35) on
# a count of 16; believing them further from a move than they were, the engine farmed on (the owner's rule: until
# they are about to get one) and threw late, and saw no need to shield (the owner: "you're attacking too late").
# 1 since 2026-11-23: replaying 2026-11-22's 91 named throws of theirs, the engine's view at their throw (the count, the
# fast move under way and those the fight had time for, as its simulation adds them) was short of the move with no
# margin at 8 (one by more than a fast move), with 1 at 1, with 2 at none; 2 put them a median 46 over the cost, where
# the owner's recordings show players throwing about one fast move past it. Applied at the shield prompt too.
FOE_MARGIN = 1
# 2026-11-23: the count's error is in turns, not fast moves (a turn or two of phase), so the margin is at least
# FOE_MARGIN_TURNS turns' worth: for a 1-turn move (Psywave, Lick, Bite) two moves, for longer ones one. Replaying
# 2026-11-22's 91 named throws: short at none, not 1, at a median 42 over the cost, not 40.
FOE_MARGIN_TURNS = 2


def foe_margin(fast) -> int:
    """Energy added to their count for the engine: FOE_MARGIN fast moves, or FOE_MARGIN_TURNS turns' worth if more."""
    return max(FOE_MARGIN, -(-FOE_MARGIN_TURNS // fast.turns)) * fast.energy_gain
# Turns from our decision to the game having the throw (the fight stops: both buttons gone), our own fast move aside:
# 0.43 s median from the decision's frame to the tap on the PC (2026-11-18, 368 throws; 0.1 s less since), and 0.31 s
# at the fastest from the tap to the buttons going (10th percentile of 48 recorded throws; median 0.63 s with our fast
# move finishing). Get Ready! comes a median 0.76 s after that, the fight already stopped. About two turns.
THROW_DELAY_TURNS = 2
# A decision at the start of each of our fast moves when a charged move is paid for (Player.at_our_hit); the
# environment's POGO_DECIDE_ON_HIT=0 turns it off, to compare on replays
import os as _os
DECIDE_ON_HIT = _os.environ.get("POGO_DECIDE_ON_HIT", "1") != "0"
# The next decision searched ahead during our fast move (Player.precompute); POGO_PRECOMPUTE=0 turns it off. Its search
# may take up to PRECOMPUTE_MS: a fast move lasts 500 ms or more, and the thread shares the processor with the loop.
PRECOMPUTE = _os.environ.get("POGO_PRECOMPUTE", "1") != "0"
PRECOMPUTE_MS = 500
# A charged move's button tapped again every 0.2 s until the game has the move (Player.throw); POGO_SPAM_CHARGED=0
# goes back to a second tap every 0.6 s while the buttons read it paid for
SPAM_CHARGED = _os.environ.get("POGO_SPAM_CHARGED", "1") != "0"
# A switch's bench portrait tapped again every 0.2 s until the switch shows, for up to SWITCH_SPAM_S after the first
# tap (Player.check_switch); POGO_SPAM_SWITCH=0 goes back to one tap and one retry once it is seen not to be taken
SPAM_SWITCH = _os.environ.get("POGO_SPAM_SWITCH", "1") != "0"
SWITCH_SPAM_S = 3.0  # 9 in 10 switches showed within 3 s of the tap (2026-11-08 to 10, 144 switches)
# Fast moves this many turns or longer: no fast taps while the one under way pays for a charged move (Player.slow_pause_for)
SLOW_FAST_TURNS = int(_os.environ.get("POGO_SLOW_FAST_TURNS", "4"))
STRIP_SAME = 40  # the bench strip as at the tap: an ignored tap left it within 17 to 31, a switch moves it 60 to 75
TYPE_SWIPE = {"ghost": "dark", "ground": "rock", "dragon": "flying", "psychic": "fairy"}  # types the library lacks


# The owner's preferred charged move of a Pokémon (the team file's "prefer"), by species id: thrown in place of the
# engine's other move whenever paid for, unless not very effective on the one out (Player.owner_prefers)
PREFER: dict[str, str] = {}


def load_team(gd: GameData, path: Path):
    by_name = {m.name: m.id for m in gd.moves.values()}
    team = []
    for entry in json.loads(path.read_text(encoding="utf-8"))["pokemon"]:
        sid = next(k for k, v in gd.species.items() if v["speciesName"] == entry["species"])
        if entry.get("prefer"):
            PREFER[sid] = by_name[entry["prefer"]]
        # the exact level and IVs when the team file gives them (read off the appraisals), else PvPoke's default
        exact = {"level": entry["level"], "ivs": tuple(entry["ivs"])} if "level" in entry and "ivs" in entry else {}
        team.append(gd.build(sid, [by_name[entry["fast"]], *(by_name[m] for m in entry["charged"])], **exact))
    return team


def mon_record(m) -> dict:
    """One Pokémon as the engine saw it: build (species, level, IVs, moves) and state."""
    b = m.build
    return {"species": b.species_id, "level": b.level, "ivs": list(b.ivs), "fast": b.fast.id,
            "charged": [x.id for x in b.charged], "hp": int(m.hp), "energy": int(m.energy),
            "stages": [int(m.atk_stage), int(m.def_stage)]}


def view_record(view) -> dict:
    """The whole view a decision was made on, to ask the engine again later (scripts/live/engine_view.py): the owner,
    2026-11-09 (docs/status.md, the spare account's 25 battles): the live Discharge throws were not the engine's
    judgment on the same matchups in the simulator, so the state the phone hands it is to be logged and replayed."""
    me = view.me
    num = lambda v: None if v is None else int(v)  # the header's counts are numpy integers (logged as text)
    out = {"turn": num(view.turn), "me": {"active": num(me.active), "shields": num(me.shields),
                                          "switch_wait": num(me.switch_wait), "busy": num(me.busy),
                                          "team": [mon_record(m) for m in me.team]},
           "foe": mon_record(view.foe), "foe_shields": num(view.foe_shields), "foe_switch_wait": num(view.foe_switch_wait),
           "foe_busy": num(view.foe_busy), "foe_left": num(view.foe_left), "foe_shown": [mon_record(m) for m in view.foe_shown]}
    for name in ("foe_move_odds", "foe_energy_odds"):
        try:
            v = getattr(view, name)
        except Exception:  # noqa: BLE001
            continue
        out[name] = [[mv.id, round(pr, 3)] for mv, pr in v] if name == "foe_move_odds" else {str(k): round(pr, 3) for k, pr in v.items()}
    return out


def swipe_for(move) -> list:
    kind = TYPE_SWIPE.get(move.type, move.type)
    path = ROOT / "data" / "minigame" / f"{kind}.json"
    if not path.exists():
        path = ROOT / "data" / "minigame" / "normal.json"
    data = json.loads(path.read_text(encoding="utf-8"))["swipe"]
    return data["start_after_move_s"], [(t, x, y) for t, x, y in data["path"]]


# Measured on this phone's own minigames (2026-11-07; C:\pogo-media\live\20261107-training): the icons' colour, and
# the zone they come up in as (centre, spread). Water's stream in from the right edge (Jellicent's body below is the
# same blue, so looking outside the zone chased it); Normal's are grey-white, with no colour to look for.
ICON_COLOUR = {"ground": (210, 131, 86), "electric": (245, 215, 82), "ghost": (101, 108, 188), "water": (94, 167, 218),
               "normal": None, "ice": (117, 208, 193),  # ice: mint discs (the iPhone file's colour was orange)
               "rock": (202, 193, 140)}  # rock: khaki discs, measured on Stone Edge's (2026-11-09)
ICON_ZONE = {"ground": ((0.50, 0.70), (0.31, 0.05)), "water": ((0.86, 0.42), (0.10, 0.11)),
             "electric": ((0.49, 0.58), (0.22, 0.10)), "ghost": ((0.60, 0.71), (0.24, 0.11)),
             "normal": ((0.53, 0.60), (0.29, 0.16)), "ice": ((0.58, 0.60), (0.15, 0.09))}


def icon_colour(move_type: str):
    if move_type in ICON_COLOUR:
        return ICON_COLOUR[move_type]  # None: no colour to look for (Normal's grey icons)
    path = ROOT / "data" / "minigame" / f"{move_type}.json"
    return tuple(json.loads(path.read_text(encoding="utf-8"))["colour"]) if path.exists() else None


def icon_zone(move_type: str):
    """Where a type's icons come up: (centre, spread) as shares of the screen (data/minigame/, measured on the
    owner's iPhone recordings, whose screen has nearly the same shape)."""
    if move_type in ICON_ZONE:
        return ICON_ZONE[move_type]
    path = ROOT / "data" / "minigame" / f"{move_type}.json"
    if path.exists():
        zone = json.loads(path.read_text(encoding="utf-8"))["zone"]
        return tuple(zone["centre"]), tuple(zone["spread"])
    return (0.5, 0.62), (0.35, 0.18)


# Where each type's icons come up on this phone, as a box to sweep (x0, x1, y0, y1, shares of the screen): the 2nd to
# 98th percentile of the icons found on 14 recorded minigames of each move (2026-11-08), a little wider. Normal's grey
# icons are found by their white ring symbol (scratch normal_det.py), most of them only on the dark background.
SWEEP_BOX = {"normal": (0.08, 0.93, 0.52, 0.90), "ground": (0.05, 0.95, 0.54, 0.90),
             "electric": (0.17, 0.83, 0.43, 0.74), "ghost": (0.08, 0.95, 0.40, 0.86),
             "water": (0.05, 0.98, 0.27, 0.90), "ice": (0.17, 0.83, 0.42, 0.85),  # ice: 9 minigames (2026-11-08)
             "rock": (0.03, 0.66, 0.22, 0.88),  # rock: 16 Stone Edge minigames (2026-11-09), the left half mostly
             "fairy": (0.10, 0.90, 0.25, 0.90)}  # fairy: 11 Play Rough minigames (2026-11-09), low in the middle
SWEEP_ONLY: set = set()  # types whose icons no detector finds: the predicted ones and the sweep alone
# Types whose icons are found but not chased: the learnt icons and the sweep only, the detector kept to tell which
# move's minigame it is. Stone Edge's rocks fly in from the left edge at about 0.9 of the width a second and settle a
# third of the way across; on a frame 0.1 to 0.2 s old the finger chased where they had been, behind them. On 8 ranked
# Stone Edges of 2026-11-24 (3 Great) the live stroke passed over 61% of the icons' sightings; the learnt path alone,
# icons of 2026-11-09 only, 82% (all 8 higher), with today's icons too, each minigame's own left out, 86%.
# Live it was worse: Stone Edge Great 4 times in 4 (2026-11-24, 184005 and 184319), so the share of sightings passed
# over does not tell the rating for Rock's moving icons. Off again; kept for a type it helps.
PREDICTED_FIRST: set = set()
# Types whose icons are chased where they will be, not where the frame had them: each icon's speed from the look
# before (the same icon, the nearest within 0.1), times how far behind the frame is (its age, LEAD_LAG for the screen
# to the frame and the touch to the game, and the finger's way there), at most LEAD_MAX s. Stone Edge's rocks fly in
# from the left at up to 0.9 of the width a second and settle a third of the way across (2026-11-24: on frames 0.1 to
# 0.2 s old the finger came in 0.1 to 0.2 behind them; 6 of 9 Excellent chased as seen, 0 of 4 on the learnt path).
# Led, Stone Edge rated Excellent 9 times in 14 in training (184901 to 185313), as chased as seen (6 of 9): off.
LEAD_TYPES, LEAD_LAG, LEAD_MAX = set(), 0.10, 0.35
# Types whose icons all come in through one lane: the stroke sweeps it up and down in place of the sweep box, and
# chases only icons seen at CHASE_FROM_X or beyond (the ones settled past the lane). Stone Edge's rocks come in from
# the left edge along five rows, y 0.22 to 0.75, at up to 0.9 of the width a second, and slow to a stop a third of the
# way across (2026-11-24, every recorded minigame): a finger at x 0.12 meets each one as it comes in, whatever the
# detector sees and however old the frame.
LANE = {"rock": ((0.12, 0.22), (0.12, 0.78))}
CHASE_FROM_X = {"rock": 0.26}


def lead_icons(icons, prev, dt: float, behind: float, finger, speed: float) -> list:
    """Where the icons seen will be `behind` s on plus the finger's travel time to each: their speed from `prev`
    (the icons on the frame dt s earlier), the nearest within 0.1 (widths, the height times 2.2), else none."""
    out = []
    for x, y in icons:
        q = min(prev, key=lambda p: math.hypot(p[0] - x, (p[1] - y) * 2.2), default=None) if 0.02 < dt < 0.3 else None
        if q is None or math.hypot(q[0] - x, (q[1] - y) * 2.2) > 0.10:
            out.append((x, y))
            continue
        vx, vy = (x - q[0]) / dt, (y - q[1]) / dt
        if math.hypot(vx, vy * 2.2) > 3.0:  # not the same icon
            out.append((x, y))
            continue
        ahead = min(LEAD_MAX, behind + math.hypot(x - finger[0], (y - finger[1]) * 2.2) / speed)
        out.append((min(0.98, max(0.02, x + vx * ahead)), min(0.90, max(0.15, y + vy * ahead))))
    return out


def sweep_path(box, spacing: float = 0.09) -> list:
    """A back-and-forth raster over the box: rows `spacing` apart (shares of the height; an icon is 0.085 of the
    width or more across in radius, about 0.04 of the height, so nothing fits between two rows), down and back up.
    Waypoints (x, y), to be followed round and round."""
    x0, x1, y0, y1 = box
    rows = max(2, int(round((y1 - y0) / spacing)) + 1)
    ys = [y0 + (y1 - y0) * k / (rows - 1) for k in range(rows)]
    down = []
    for k, y in enumerate(ys):
        down += [(x0, y), (x1, y)] if k % 2 == 0 else [(x1, y), (x0, y)]
    return down + down[::-1][1:-1]


def sweep_box(move_type: str, zone) -> tuple:
    if move_type in SWEEP_BOX:
        return SWEEP_BOX[move_type]
    (cx, cy), (spx, spy) = zone
    return (max(0.03, cx - 2 * spx), min(0.98, cx + 2 * spx), max(0.25, cy - 2 * spy), min(0.90, cy + 2 * spy))


COLOUR_BLOBS = {"ground"}  # types whose colour nothing else on screen shares: blobs of it count as icons too


def raw_circles(frame, param2: int = 15) -> list:
    """Every circle of icon size by its outline (cv2.HoughCircles, as pogo.minigame.detect, at a looser threshold
    and without its shape filters, which drop many real icons): candidates for ring_matches to sort."""
    import cv2
    from pogo import minigame
    h, w = frame.shape[:2]
    width = minigame.WIDTH
    small = cv2.resize(frame, (width, int(h * width / w)), interpolation=cv2.INTER_AREA)
    gray = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_RGB2GRAY), (5, 5), 1.2)
    rmin, rmax = int(minigame.RADIUS[0] * width), int(minigame.RADIUS[1] * width)
    found = cv2.HoughCircles(gray, cv2.HOUGH_GRADIENT, dp=1.2, minDist=int(1.2 * rmin), param1=90, param2=param2,
                             minRadius=rmin, maxRadius=rmax)
    return [] if found is None else [(cx / width, cy / small.shape[0], r / width) for cx, cy, r in found[0]]


def find_icons(rgb, colour, move_type: str, zone) -> list:
    """The minigame icons in one frame, as (x, y) shares of the screen."""
    from pogo import minigame
    (cx, cy), (spx, spy) = zone
    if colour is None:
        # Normal's grey icons: the icon itself matched on a half-size frame (normal_icons, about 15 ms); outlines and
        # grey rings matched Vigoroth's white fur everywhere, and ring kernels missed the icons by day (2026-11-08)
        from normal_icons import normal_icons
        return [(x, y) for x, y, v in normal_icons(rgb[::2, ::2]) if 0.15 < y < 0.95]
    icons = [(x, y) for x, y, r in raw_circles(rgb) if 0.15 < y < 0.92 and ring_matches(rgb, x, y, r, colour, 45)
             and (move_type not in RING_SHARE or ring_share(rgb, x, y, r, colour) >= RING_SHARE[move_type])]
    if move_type in COLOUR_BLOBS:
        icons += [(x, y) for x, y, r in minigame.detect_colour(rgb, colour) if 0.045 <= r < 0.17
                  and abs(x - cx) < 2.5 * spx + 0.05 and abs(y - cy) < 2.5 * spy + 0.05]
    return icons


# Types whose ring must be mostly their colour, not on average: Rock's khaki is near the yellow of the rating words
# ("GREAT!", "NICE!") and of the popped icons' fading discs, which passed ring_matches and were chased (2026-11-09,
# Stone Edge rated Great 11 times in 16). On 16 Stone Edge minigames real icons had 0.9 to 1.0 of their ring within 40
# of the colour (0.55 to 0.75 half covered), the words 0.0 to 0.1, the fading discs 0.2 to 0.5.
RING_SHARE = {"rock": 0.55}


def ring_share(rgb, x: float, y: float, r: float, colour, tolerance: float = 40) -> float:
    """The share of a circle's ring (between its symbol and its rim, the white left out) within `tolerance` of the
    colour on every channel."""
    h, w = rgb.shape[:2]
    cx, cy, rr = int(x * w), int(y * h), max(3, int(r * w))
    yy, xx = np.mgrid[-rr:rr + 1, -rr:rr + 1]
    m = (xx ** 2 + yy ** 2 <= (0.8 * rr) ** 2) & (xx ** 2 + yy ** 2 >= (0.45 * rr) ** 2)
    ys, xs = cy + yy[m], cx + xx[m]
    ok = (ys >= 0) & (ys < h) & (xs >= 0) & (xs < w)
    px = rgb[ys[ok], xs[ok]].astype(int)
    px = px[px.min(1) < 200]
    if len(px) < 15:
        return 0.0
    return float((np.abs(px - np.array(colour)).max(1) < tolerance).mean())


def ring_matches(rgb, x: float, y: float, r: float, colour, tolerance: float = 60) -> bool:
    """Whether a circle found by its outline is a minigame icon of this type: the ring between its white symbol and
    its rim is the type's colour (within 60 per channel on average), or grey for a type with no colour (Normal)."""
    h, w = rgb.shape[:2]
    cx, cy, rr = int(x * w), int(y * h), max(3, int(r * w))
    yy, xx = np.mgrid[-rr:rr + 1, -rr:rr + 1]
    m = (xx ** 2 + yy ** 2 <= (0.8 * rr) ** 2) & (xx ** 2 + yy ** 2 >= (0.45 * rr) ** 2)
    ys, xs = cy + yy[m], cx + xx[m]
    ok = (ys >= 0) & (ys < h) & (xs >= 0) & (xs < w)
    px = rgb[ys[ok], xs[ok]].astype(int)
    px = px[px.min(1) < 200]  # leave out the white symbol
    if len(px) < 15:
        return False
    med = np.median(px, 0)
    if colour is None:
        return med.max() - med.min() < 45  # grey
    # every icon has its white type symbol in the middle; sky, clouds and the Pokémon's body have none
    core = (xx ** 2 + yy ** 2 <= (0.32 * rr) ** 2)
    cys, cxs = cy + yy[core], cx + xx[core]
    inside = (cys >= 0) & (cys < h) & (cxs >= 0) & (cxs < w)
    if not inside.any() or (rgb[cys[inside], cxs[inside]].min(1) > 205).mean() < 0.15:
        return False
    return float(np.abs(med - np.array(colour)).mean()) < tolerance


def icon_count(rgb, move) -> int:
    """How many of a move's minigame icons one frame shows, by the detectors its stroke uses."""
    zone, colour = icon_zone(move.type), icon_colour(move.type)
    if has_template(move.id, move.type):
        n = len(move_icons(rgb[::2, ::2], move.id, move_type=move.type))
        if move.type in COLOUR_BLOBS:
            n = max(n, len(find_icons(rgb, colour, move.type, zone)))
        return n
    return 0 if move.type in SWEEP_ONLY else len(find_icons(rgb, colour, move.type, zone))


def strict_icon_count(rgb, move) -> int:
    """A move's icons by the strict detectors only, to say a minigame is another move's: its cut-out template
    (ground without its colour blobs), else round rings mostly of the type's colour. Simulated on 263 of the third
    account's minigames (2026-11-09) with the lenient detectors, 66 would have switched, Night Slash to Earthquake on
    Thievul's orange fur and Body Slam to Play Rough on Snorlax; with these, only the Earthquake taken for Stone Edge."""
    if has_template(move.id, move.type):
        return len(move_icons(rgb[::2, ::2], move.id, move_type=move.type))
    from pogo.android_screen import TYPE_COLOURS
    col = icon_colour(move.type) or TYPE_COLOURS.get(move.type)
    if col is None:
        return 0
    return sum(1 for x, y, r in raw_circles(rgb) if 0.15 < y < 0.92 and ring_matches(rgb, x, y, r, col, 45)
               and ring_share(rgb, x, y, r, col) >= 0.55)


def choreography(move_id: str, move_type: str = "") -> list:
    """The icons a move's minigame is known to show, (t0, t1, x, y, share): seconds after Get Ready!, where, and in
    what share of the recorded minigames (scripts/live/learn_choreography.py). Its type's pattern first
    (data/minigame/android/type_<type>.json, learnt on every move of the type: moves of one type share it, Foul Play's
    covering 96% of Dark Pulse's held-out icons against 93% for Dark Pulse's own), else the move's own."""
    folder = ROOT / "data" / "minigame" / "android"
    path = next((p for p in (folder / f"type_{move_type.lower()}.json", folder / f"{move_id.lower()}.json")
                 if p.name != "type_.json" and p.exists()), None)
    if path is None:
        return []
    return [tuple(x) for x in json.loads(path.read_text(encoding="utf-8"))["icons"]]


def first_icon_s(move_id: str) -> float:
    """Seconds from Get Ready! to the first icons of a move's minigame (its learnt choreography; 1.0 if none)."""
    return min((x[0] for x in choreography(move_id) if x[4] >= 0.5), default=1.0)


def minigame_on(rgb, move) -> bool:
    """A frame with the buttons hidden and the move's minigame icons on it: our minigame has begun. The game does not
    always say Get Ready! first (2026-11-08: a Body Slam started 2.2 s after its tap with no Get Ready!, the header
    and our bar stayed up, and it went unswiped while the player took it for not taken)."""
    if move.type != "normal":
        # Normal's detector matches the icon itself and found nothing else on the day's 16 Body Slams; the colour
        # ones find icons in the fight (Ground's in the brown earth a second before Mud Bomb started, on a replay)
        return False
    if any(v["present"] for v in screen.buttons(rgb).values()):
        return False
    return bool(find_icons(rgb, icon_colour(move.type), move.type, icon_zone(move.type)))


def minigame_stroke(phone: Android, seconds: float = 4.6, speed: float = 6.5, colour=None, zone=None,
                    move_type: str = "", trace: list | None = None, predicted: list | None = None,
                    ready_at: float | None = None, move_id: str = "", alternatives: list | None = None,
                    switched: list | None = None) -> int:
    """The charged-move minigame as one unbroken touch: visit the icons found on the newest frame every 50 ms
    nearest first (by their round outline and the type's colour, find_icons), leaving out those the finger has just
    been over, and while none is left sweep a figure of eight over the zone the type's icons come up in (Water's at the upper
    right, Ground's low in the middle). Stops at once if a shield prompt comes up: that screen is theirs. Returns
    how many times an icon was being chased, or -1 if it stopped for a prompt."""
    from pogo import minigame
    from pogo.android import DOWN, MOVE, UP
    (cx, cy), (spx, spy) = zone or ((0.5, 0.62), (0.35, 0.18))
    # With no icon to chase, the finger sweeps the box the type's icons come up in, row by row (the owner,
    # 2026-11-08: a fixed pattern rather than relearning each time; the figure of eight it replaces went over one
    # curve again and again, and Body Slam rated Great twice).
    route = list(LANE[move_type]) if move_type in LANE else sweep_path(sweep_box(move_type, zone or ((cx, cy), (spx, spy))))
    leg = 0
    x, y = route[0]
    phone._send(DOWN, x, y)
    start = last_seen = time.perf_counter()
    chased, step = 0, 0.010
    # The icons seen on the newest look and not reached yet, visited nearest first; and where the finger has been in
    # the last 0.4 s. A frame is 0.1 to 0.2 s old when it is read, so an icon the finger has just popped still shows
    # on it: chasing it again wastes the time the next icon needs (Shadow Ball's spread over all of Jellicent).
    pending: list = []
    trail = collections.deque()
    passed = 0.06  # the finger within this of an icon's centre (shares of the width; icons' radius is 0.085 or more)
    # The move's known choreography: icons predicted where and when they have come up in most recorded minigames,
    # each visited once, as if seen (the only icons for a type the detector seldom finds, Normal).
    predicted = list(predicted or [])
    done: set = set()
    wall0 = time.time()
    # Which move's minigame this is, by its icons (2026-11-09, 231134: Earthquake, beaten and queued, went off after
    # their Shadow Ball as Stone Edge was tapped, and its ground icons were swiped for rock: Nice; 123219: Thievul's
    # Night Slash swiped for Body Slam's normal icons): over the stroke's first 1.2 s, a look that finds none of the
    # believed type's icons also counts our other moves' types', and two or more of one switch the stroke to it.
    seen_own = False
    alternatives = list(alternatives or [])
    alt_seen = None  # (move, first look time) of another type showing two icons or more, looks running
    # LEAD_TYPES: the icons on the newest frame and on the one before, the newest one's arrival, the time between
    lead_last, lead_prev, lead_got, lead_dt = [], [], 0.0, 0.0
    while (now := time.perf_counter()) - start < seconds:
        if now - last_seen >= 0.05:
            last_seen = now
            try:
                rgb, got = phone.frame()
                if screen.shield_prompt(rgb):
                    phone._send(UP, x, y)
                    return -1
                # Anywhere on screen: a round disc of icon size whose ring is the type's colour (grey for Normal).
                # Water's icons stream right across the screen, over Jellicent's body, which is the same blue but
                # not a disc of that size; Ghost's sit on a Jellicent dark with smoke.
                if move_id and has_template(move_id, move_type):
                    # the move's or its type's icon cut out (move_icons.py): exact where the colour detectors are not
                    icons = [(x, y) for x, y, v in move_icons(rgb[::2, ::2], move_id, move_type=move_type)]
                    if move_type in COLOUR_BLOBS:
                        # Ground: the colour detector's too (2026-11-08: on the cut-out alone Mud Bomb's stroke chased
                        # icons 55-60% of the time and rated Excellent 5 of 10; on the colour detector, blobs and
                        # all, 85-98% and 31 of 36)
                        more = find_icons(rgb, colour, move_type, zone or ((cx, cy), (spx, spy)))
                        icons += [p for p in more if all(math.hypot(p[0] - q[0], (p[1] - q[1]) * 2.2) > 0.06
                                                         for q in icons)]
                else:
                    icons = [] if move_type in SWEEP_ONLY else find_icons(rgb, colour, move_type, zone or ((cx, cy), (spx, spy)))
                seen_own = seen_own or bool(icons)
                if alternatives and not seen_own and now - start < 1.2:
                    counts = [(strict_icon_count(rgb, m), m) for m in alternatives]
                    n, alt = max(counts, key=lambda c: c[0])
                    if n < 2 or (alt_seen is not None and alt_seen[0] is not alt):
                        alt_seen = None
                    if n >= 2 and alt_seen is None:
                        alt_seen = (alt, now)
                    if n >= 2 and now - alt_seen[1] >= 0.2:  # the same on looks 0.2 s apart and between
                        if switched is not None:
                            switched.append((alt, round(now - start, 2), n))
                        alternatives = []
                        move_id, move_type = alt.id, alt.type
                        colour, zone = icon_colour(alt.type), icon_zone(alt.type)
                        (cx, cy), (spx, spy) = zone
                        route, leg = (list(LANE[move_type]) if move_type in LANE else sweep_path(sweep_box(move_type, zone))), 0
                        predicted, done = list(choreography(alt.id, alt.type)), set()
                        icons = [(x_, y_) for x_, y_, _ in move_icons(rgb[::2, ::2], move_id, move_type=move_type)]                             if has_template(move_id, move_type) else find_icons(rgb, colour, move_type, zone)
                if move_type in PREDICTED_FIRST and predicted and ready_at is not None:
                    icons = []  # seen, to tell which move's minigame this is; the learnt icons are chased instead
                if move_type in LEAD_TYPES:
                    if got != lead_got:  # a new frame: the speeds are from the one before it
                        lead_prev, lead_dt = lead_last, (got - lead_got if lead_got else 0.0)
                        lead_last, lead_got = list(icons), got
                    icons = lead_icons(icons, lead_prev, lead_dt, time.time() - got + LEAD_LAG, (x, y), speed)
                if move_type in CHASE_FROM_X:
                    icons = [p for p in icons if p[0] >= CHASE_FROM_X[move_type]]  # those in the lane: the sweep's
            except Exception:  # noqa: BLE001
                icons = []
            while trail and now - trail[0][0] > 0.4:
                trail.popleft()
            if icons and trail:
                been = np.array([(px, py) for _, px, py in trail])
                icons = [p for p in icons
                         if np.min(np.hypot(been[:, 0] - p[0], (been[:, 1] - p[1]) * 2.2)) > passed]
            if predicted and ready_at is not None and not icons:
                # only when none is seen: the icons the detector finds are chased first (all Excellent for the types
                # it finds well), the predicted ones stand in for them, and the sweep for both
                u = wall0 + (now - start) - ready_at  # seconds since Get Ready!
                icons = [(px, py, k) for k, (a, b, px, py, _) in enumerate(predicted) if a <= u <= b and k not in done]
            if icons:
                pending = icons
                chased += 1
        # reached: Water's icons drift, so go to the centre seen rather than stop at its edge
        for p_ in pending:
            if len(p_) == 3 and math.hypot(p_[0] - x, (p_[1] - y) * 2.2) <= 0.02:
                done.add(p_[2])  # a predicted icon visited
        pending = [p for p in pending if math.hypot(p[0] - x, (p[1] - y) * 2.2) > 0.02]
        target = min(pending, key=lambda p: math.hypot(p[0] - x, (p[1] - y) * 2.2)) if pending else None
        if target is None and math.hypot(route[leg][0] - x, (route[leg][1] - y) * 2.2) < 0.01:
            leg = (leg + 1) % len(route)  # this waypoint of the sweep reached: on to the next
        goal = target[:2] if target else route[leg]
        dx, dy = goal[0] - x, goal[1] - y
        dist = math.hypot(dx, dy * 2.2)  # the screen is 2.2 times taller than wide
        move = speed * step
        if dist > move:
            x, y = x + dx * move / dist, y + dy * move / dist
        else:
            x, y = goal
            if target is not None:
                pending.remove(target)
                if len(target) == 3:
                    done.add(target[2])
        # Never near the flee button at the top left (it forfeits): kept 0.09 of the width from it, the corner
        # around it open (2026-11-09: a box of x < 0.22 above y 0.32 was kept clear, and Stone Edge, whose icons
        # come up there, rated Great three times in one battle)
        sx, sy = controls.clear_of_flee(min(0.995, max(0.02, x)), min(0.90, max(0.15, y)))
        trail.append((now, sx, sy))
        if trace is not None and (not trace or now - start - trace[-1][0] >= 0.05):
            trace.append((round(now - start, 2), round(sx, 3), round(sy, 3), int(target is not None)))
        controls.Gesture("stroke", [(sx, sy)], 0, "minigame stroke").check()
        phone._send(MOVE, sx, sy)
        time.sleep(step)
    # Lift the finger on the open field, never over the bench portraits at the right edge (as the fight resumes, a
    # touch ending there could switch our Pokémon).
    fx, fy = controls.FIELD
    phone._send(MOVE, fx, fy)
    time.sleep(0.02)
    phone._send(UP, fx, fy)
    return chased


class HitSteps:
    """Hits landing on one health bar, frame by frame: a drop of 2 pixels or more (of 148.5 for a full bar) in the
    median of the last five frames that holds for four frames. Drops within 0.35 s are one hit (the bar can step
    twice). Since the orange strip a hit leaves is no longer read as health (2026-11-08), each fast move is one clean
    step, so their fast moves can be counted and timed as they land, not guessed from a rhythm."""

    def __init__(self):
        self.reset()

    def reset(self) -> None:
        self.vals: list = []
        self.level = None
        self.below = 0
        self.last_hit = -9.0

    def add(self, t: float, px: float):
        """The size of a hit that landed by this frame, in pixels, or None."""
        self.vals = (self.vals + [px])[-5:]
        med = float(np.median(self.vals))
        if self.level is None or len(self.vals) < 3:
            self.level = med if self.level is None else max(self.level, med)
            return None
        if med >= self.level + 4:  # back up: a misread before, or another Pokémon
            self.level, self.below = med, 0
            return None
        if self.level - med >= 2:
            self.below += 1
            if self.below >= 4:
                size, self.level, self.below = self.level - med, med, 0
                merged = t - self.last_hit < 0.35
                self.last_hit = t
                return None if merged else size
        else:
            self.below = 0
        return None


class FineSteps:
    """Their fast moves landing on our bar, for counting and timing them: a fall of 1 pixel or more (of 148.5) in the
    median of the readings of the last 0.23 s, held 0.07 s and 3 readings; timed at the first reading below; falls
    within 0.3 s are one hit. On every frame of eight of 2026-11-22's battles (the frame-by-frame bar), it found 86% of
    the hits that would have landed while our bar showed against HitSteps's 61%, and with its hits in place of the
    logged ones the count at their named throws fell short with no margin at 4 of 33, not 8. self.at: the hit's time."""

    def __init__(self):
        self.reset()

    def reset(self) -> None:
        self.vals: list = []
        self.level = None
        self.first = None
        self.n = 0
        self.last_hit = -9.0
        self.at = None

    def add(self, t: float, px: float):
        """The size of a hit that landed by this reading, in pixels, or None; self.at is when it landed."""
        self.vals = [(u, v) for u, v in self.vals if t - u <= 0.23] + [(t, px)]
        med = float(np.median([v for _, v in self.vals]))
        if self.level is None or len(self.vals) < 4:
            self.level = med if self.level is None else max(self.level, med)
            return None
        if med >= self.level + 3:  # back up: a misread before, or another Pokémon
            self.level, self.n = med, 0
            return None
        if self.level - med >= 1.0:
            if self.n == 0:
                self.first = t
            self.n += 1
            if self.n >= 3 and t - self.first >= 0.07:
                size, self.level, self.n = self.level - med, med, 0
                if self.first - self.last_hit < 0.3:
                    return None
                self.last_hit = self.at = self.first
                return size
        else:
            self.n = 0
        return None


class Log:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.f = open(path, "w", encoding="utf-8")
        self.path = path

    _lock = threading.Lock()

    def __call__(self, kind: str, t: float, **data) -> None:
        line = json.dumps({"t": round(t, 3), "kind": kind, **data}, default=str) + "\n"
        with self._lock:  # the fast-move thread logs its taps too
            self.f.write(line)
            self.f.flush()


class Player:
    def __init__(self, phone: Android, gd: GameData, team, live: bool, log: Log, frames: Path | None):
        self.phone, self.gd, self.team, self.live, self.log, self.frames = phone, gd, team, live, log, frames
        # Their energy by rhythm (a fast move every so many turns while out), the hits seen landing (HitSteps)
        # keeping it in step. Counting only the hits seen fell short at all 17 of their throws named on 2026-11-08:
        # a resisted fast move takes a pixel or less off our bar (Vaporeon's Water Gun on Jellicent), so it is never
        # seen; the rhythm fell short at 10 of the 17, and with the turns measured on the frames at 6.
        self.tracker = Tracker(gd, team)
        self.hits_since_look = 0
        # "<Pokémon> used <move>!", read while the fight is off the screen: their charged move by name (its exact
        # cost), and a throw of theirs even when no prompt came (2026-11-08: Cranidos's Rock Tomb knocked out
        # Vigoroth with no shields left; the count never took off its 50 energy).
        self.used_read_at = 0.0
        self.used_busy = False
        self.result_busy, self.result_seen = False, None
        self.pending_lock = threading.Lock()  # pending_theirs and foe_move_seen are set from the reading thread
        self.header_seen = 0.0  # the last frame with the battle header (cheap to check), for the no-fight guard
        self.fight_frame_t = -9.0  # the last frame counted as the fight, for keeping the fast taps on
        self.button_seen_t = -9.0  # the last frame with a charged-move button on screen
        self.fast_time = 0.0  # seconds since the last look with fast taps on and the fight on the clock
        self.fast_carry = 0.0  # the part of a fast move counted at no look yet (the count with no reading)
        self.clock_frame_t = -9.0  # the last frame the turn clock counted
        self.hold_taps_until = 0.0  # no fast taps before this (after a switch tap)
        self.slow_pause = None  # (slot, until, reading, since): no fast taps while a long fast move pays (slow_pause_for)
        self.pause_hold_until = 0.0  # after the pause, no fast taps before the engine has decided on the energy paid
        self.hold_ended_at = 0.0  # when the last armed hold or slow pause ended
        self.unsure_hold = None  # (slot, until, since): a throw decided on the count alone, no fast taps (long fast moves)
        # A switch the engine chose that has yet to be tapped: one chosen during "GO!" (the engine searches its first
        # decision fully and wanted Stunfisk in; its next ones, on a short deadline, fell back to fast moves), or one
        # the game ignored, tapped once more.
        self.switch_wanted = None
        self.switch_retried = False
        self.foe_move_seen = None
        self.used_names: dict = {}  # a move's name as read (letters only) -> the ids with that name
        for m in gd.moves.values():
            self.used_names.setdefault("".join(ch for ch in m.name.upper() if ch.isalpha()), []).append(m.id)
        self.used_last = (None, 0.0)
        self.my_throw_at = 0.0  # when a throw of ours last started (Get Ready!)
        self.late_move = None  # a move of theirs named after its throw was already counted
        # When a throw of theirs was last given to the tracker by any sign (prompt, pause, words): the words come a
        # moment after the pause and must not count it again (2026-11-08: each of Altaria's Moonblasts was taken
        # off its energy twice).
        self.their_throw_at = 0.0
        # Seconds the fight has been off the screen since the last look (measured on the frames), for the turns.
        self.off_time, self.frame_t = 0.0, None
        self.foe_seen_species = None  # the last "used" text read for theirs, and when: it stays up a second or two
        self.my_move_names = {"".join(ch for ch in m.name.upper() if ch.isalpha()) for b in team for m in b.charged}
        self.my_names = {"".join(ch for ch in b.name.upper() if ch.isalpha()) for b in team}
        charged_ids = {i for sp in gd.species.values() for i in sp.get("chargedMoves", [])}
        self.used_names = {n: [i for i in ids if i in charged_ids] for n, ids in self.used_names.items()}
        self.used_names = {n: ids for n, ids in self.used_names.items() if ids}
        # POGO_EVAL / POGO_Q: other networks, paths from the repository root. In Ultra League the evaluation trained
        # there (task 48: 51.5% +/- 1.2 head to head on a fresh seed; 2026-11-23, 214336: asked again where the shipped
        # one sent Skeledirge on 17 HP into Charizard, it sent Blastoise)
        ul = getattr(gd, "league", None) == 2500 and (ROOT / "runs" / "ul-eval" / "eval.npz").exists()
        ev = Evaluator.load(ROOT / _os.environ.get("POGO_EVAL", "runs/ul-eval/eval.npz" if ul else "runs/eval/eval.npz"))
        self.engine = RealTime(Evaluator(ev.model), gd.meta(50), q=QNet.load(str(ROOT / _os.environ.get("POGO_Q", "runs/general-decide/q.npz"))),
                               seed=int(time.time()) % 100000, **WEBSITE, turn_ms=500, cap_ms=300, clock=time.perf_counter)
        self.names = screen.NameReader(gd)
        self.active = 0
        self.t0 = None
        self.last_look = -1.0
        self.last_fight = None  # time of the last look with the fight on screen
        self.pending_mine = None  # index of a charged move of ours not yet given to the tracker
        self.pending_theirs = False
        self.gap_throws = 0
        self.prompt_answered = False
        self.replaced = False
        self.decision = FAST
        # A throw the engine wants once the fast moves under way and queued have paid for it: (button, give up at).
        # The fast taps stop meanwhile, so none is queued behind them, and the move is tapped as its button lights.
        self.armed = None
        self.decided_for = 0  # which of ours was out when the engine last decided
        # our bar's last readings on fight frames, (time, share): the low-health rule goes by their median, not one
        # frame (2026-11-08: mid-switch our bar read 0.7% for a frame, at 54%, and a throw was tapped on it)
        self.my_bar_seen = collections.deque(maxlen=12)
        self.last_fast_tap = 0.0
        self.switch_ready_at = 0.0
        self.my_left_seen, self.foe_left_seen = 3, 3
        self.history = []  # recent header readings, for a majority
        self.fight_since = None  # since when the fight has been on screen without a break
        self.labels_checked = None
        self.header_checked = None
        self._last_active, self.active_changed_at = 0, -1.0
        self.last_reading_t = -1.0  # battle time of the buttons' last energy reading
        self.replace_run = 0  # frames in a row on which the replacement prompt was read
        self.replace_since = 0.0  # and the time of the first of them
        self.replacements = 0  # replacement prompts answered: our faints
        self.prompt_shield, self.prompt_tapped = False, 0.0  # the answer to the shield prompt up now, and when tapped
        self.prompt_first = 0.0
        self.replace_point, self.replace_tapped = None, 0.0
        # Our energy read from the buttons (pogo.android_screen.my_energy): (energy, time) when two frames in a row
        # agree, and the last frame's own reading. The count from our fast moves drifts 20 to 50 off (2026-11-07).
        self.energy_read = None
        self._energy_raw = None
        # When the reading last moved by half a fast move or more from where it stood then (reading_base), or came
        # back after 1.5 s unread: a fast move of ours has just landed, or the fight is just back from a close-up
        # (look_ahead). Measured from that reading, not the one before: the fill rises over several frames, 5 or so
        # each (2026-11-23, 235319, 70.8 s: 18 to 37 in steps, none of them 10)
        self.reading_new_at, self.reading_base = 0.0, 0.0
        self.queued = None  # (button, move, time tapped, deadline, battle time set): a move of ours still to start
        self.pre = None  # a search run ahead (Player.precompute)
        self.engine_calls = 0  # calls to the engine: a search run ahead on a copy is used only if none came since
        self.cue_busy, self.cue_found = False, None  # watch_queued's Get Ready! read, on its own thread
        self.armed_read = 0.0  # the energy read when the hold for a throw began
        # A switch tapped and not yet seen: (slot, time tapped, bench strip before, since when it differs, fighting
        # frames looked at). The game sometimes ignores the tap (2026-11-07: Jellicent stayed out; the player took
        # Stunfisk for out for 36 s and pressed Stunfisk's moves on Jellicent's buttons).
        self.switching = None
        self.switch_point, self.switch_last_tap = None, 0.0  # where the switch was tapped, and when last (SPAM_SWITCH)
        self.switch_fight_s, self.switch_fight_last = 0.0, 0.0  # seconds of fight on screen since the switch tap
        self._switch_fits = []  # which Pokémon's costs the energy reading fitted, the last three frames of a switch check
        self.last_not_taken = 0.0  # when a charged tap last came to nothing
        self.fight_frames = 0  # frames in a row with the fight on screen
        self.unread_since = None  # since when the fight has been on with the buttons unread
        self.prompt_seen = 0.0  # the last frame with a shield prompt
        # Which moves' names show under the buttons (shown = paid for): (names, time) when two frames in a row agree
        self.names_seen = None
        self.names_blocked_until = 0.0
        self.queued_retapped = False
        self._names_raw = None
        self.queued_checked = 0.0
        # Their fast moves landing on our bar, frame by frame (HitSteps): the times of those in the current unbroken
        # stretch of fighting, and every gap between hits so far for each of their Pokémon. The gaps tell the tracker
        # how many turns their fast move takes.
        self.their_steps = FineSteps()  # theirs landing on our bar (2026-11-23: HitSteps found 61% of them)
        self.my_steps = HitSteps()  # ours landing on their bar
        self.my_hits_since_look = 0
        self.their_hits: list = []
        self.hit_gaps: dict = {}
        self.hits_key = None
        self.last_fight_frame = 0.0
        # Fast moves on their own thread, so the engine's thinking (up to 300 ms a look) leaves no gaps: one tap in
        # five came more than 0.45 s after the last, and a one-turn move (Scratch) loses its turn at such a gap.
        self.touch_lock = threading.RLock()  # one touch at a time: fast taps, charged taps, the minigame stroke
        self.tapping = False  # fast taps on: the fight is on screen and nothing else is going on
        self.done = False
        # Training only (--practise): charged moves thrown in place of the engine's choice, to record their minigames
        self.practise: set = set()
        self.practise_logged = 0.0
        self.practised: dict = {}  # move id -> times thrown: of two practised moves, the one thrown less goes next
        self.open_with = None  # training only (--open-with): the slot switched in first, whatever the engine asks for
        self.stay = False  # training only (--stay): no switches but the opening one
        self.start_info: dict = {}  # written into the log's start row: the bot's version, account, team, league
        self.farm_logged = self.farm_checked = 0.0
        self.farm_for, self.farm_since = None, 0.0
        self.foe_sid, self.foe_since, self.saved_for = None, 0.0, None  # save_the_low_one: their Pokémon and since when
        self.save_checked = None
        threading.Thread(target=self._tap_fast, daemon=True).start()

    # touching

    def touch(self, point, note: str) -> None:
        controls.tap(point, note)  # refuses keep-out zones
        with self.touch_lock:
            self.log("tap", self.now(), point=point, note=note, live=self.live)
            if self.live:
                self.phone.tap(*point)

    def clear_of_fast_taps(self) -> None:
        """Stop the fast taps and wait until 0.15 s have passed since the last began. The game drops a touch that
        starts just after another ends: over both days' logs, of the switch taps sent within 0.1 s of a fast tap
        about 20 in 23 were ignored, and of those sent 0.13 s or more after one nearly all went through (2026-11-08;
        charged taps "sometimes not taken" were most likely the same)."""
        self.tapping = False
        with self.touch_lock:  # a fast tap under way ends first
            # 0.15 s, not 0.25 (2026-11-18): the taps found ignored had come within 0.1 s of a fast tap, and those 0.13 s
            # or more after one nearly all went through; the 0.25 s was a median 0.25 s of every charged tap's delay
            wait = 0.15 - (time.time() - self.last_fast_tap)
            if wait > 0:
                time.sleep(wait)

    def _tap_fast(self) -> None:
        while not self.done:
            if self.tapping and time.time() - self.last_fast_tap >= 0.15:
                with self.touch_lock:
                    if not self.tapping:  # turned off while another touch was under way (a charged tap)
                        continue
                    self.last_fast_tap = time.time()
                    try:
                        self.touch(controls.FIELD, "fast move")
                    except Exception as error:  # noqa: BLE001 - the action cap, or the phone gone: stop tapping
                        self.log("tap_error", self.now(), error=str(error))
                        self.done = True
            time.sleep(0.01)

    def now(self) -> float:
        return time.time() - (self.t0 or time.time())

    # the loop

    def run(self, timeout: float = 420.0) -> str | None:
        start = time.time()
        last = 0.0
        while time.time() - start < timeout:
            rgb, when = self.phone.next_frame(last, timeout=0.5)
            if when <= last:
                continue
            last = when
            look = screen.read(rgb, when)
            if self.t0 is None:
                if time.time() - start > 90.0:
                    # no battle 90 s after the start tap (2026-11-09: one waited out its 7 minutes on a start that came
                    # to nothing): the runner goes on from whatever screen this is
                    self.log("no_battle", round(time.time() - start, 1))
                    return None
                point = getattr(self, "start_point", None)
                if point is not None and time.time() - self.start_tapped > 5.0 and self.start_retaps < 3:
                    # the start tap lost (2026-11-09: sent as the phone's link opened, it did nothing and the party
                    # screen stayed up for the 90 s): tap again while the green button is still under it
                    h, w = rgb.shape[:2]
                    r, g, b = (int(v) for v in rgb[int(point[1] * h), int(point[0] * w)])
                    if g > 180 and r < 150:
                        self.touch(point, "start again")
                        self.start_retaps += 1
                        self.log("start_retap", round(time.time() - start, 1))
                    self.start_tapped = time.time()
                if look.header and len(look.bars) == 2 and not look.shield_prompt and not look.replace_prompt:
                    self.t0 = when
                    # epoch lines the log up with the recording's .times; the rest is what the record needs (task 45)
                    self.log("start", 0.0, epoch=round(when, 3), **self.start_info)
                else:
                    continue
            t = when - self.t0
            if look.header:
                self.header_seen = t
            if self.last_fight is not None and t - self.last_fight > 20.0 and t - self.header_seen > 20.0:
                # No fight on screen for 20 s, and no result: the game has gone (2026-11-07: it crashed to the
                # home screen and the player went on for 200 s, tapping a prompt it thought it saw). Touch nothing.
                self.tapping = False
                self.log("no_fight", t, since=round(self.last_fight, 2))
                return None
            if look.shield_prompt:
                self.tapping = False
                self.armed = None
                self.fight_frames = 0
                self.fight_since = None
                self.on_shield_prompt(t, look)
                continue
            # The replacement prompt only on two frames running: on a night arena, as their next Pokemon came in
            # ("Go, Lickilicky!"), the dark ground and the white court lines passed its test on single frames, three
            # times in a battle (2026-11-09, 231134), and "send in" was tapped beside our move buttons; the real
            # prompt stays up a second or more
            self.replace_run = self.replace_run + 1 if look.replace_prompt else 0
            # and up 0.3 s unbroken (2026-11-23, 205934: after our Double Iron Bash the camera swept a night arena's
            # ground and court lines, taken for the prompt on 2 frames 0.03 s apart; Melmetal was put down as fainted
            # and "Skeledirge" tapped. Real prompts on yesterday's recordings stayed up 0.59 to 2 s unbroken)
            if look.replace_prompt and self.replace_run == 1:
                self.replace_since = t
            if look.replace_prompt and (self.replace_run < 2 or t - self.replace_since < 0.3):
                continue
            if look.replace_prompt:
                self.tapping = False
                self.armed = None
                self.fight_frames = 0
                self.queued = None  # our Pokémon fainted: a move it had waiting went with it
                self.switching = self.switch_wanted = None
                self.fight_since = None
                self.on_replace_prompt(t, look, rgb)
                continue
            if look.countdown:
                # A charged move's countdown (theirs with no prompt, or ours while they choose to shield): the fight
                # is not on, whatever the header and bars say (2026-11-09, 124910: through Beedrill's 5 s our count
                # ran 41 to 68 and a Stone Edge was tapped that could not go off). No taps, no turns; told to the
                # tracker as their throw, once, only when it can be theirs (countdown_is_theirs).
                self.tapping = False
                self.armed = None
                self.fight_frames = 0
                self.fight_since = None
                with self.pending_lock:
                    if self.countdown_is_theirs():
                        self.pending_theirs = True
                        self.their_throw_at = time.time()
                        self.log("their_charged_countdown", t)
                continue
            # The fight is on screen after three frames in a row with the header and a bar: in close-ups and
            # changes of Pokémon a false bar shows on a frame or two (2026-11-07, GO Battle League: looks given then
            # counted fast moves that were not happening, and a Shadow Ball was tapped on 53 counted, 16 real).
            buttons_up = bool(look.buttons) and any(look.buttons[k]["present"] for k in ("left", "right"))
            both_buttons = bool(look.buttons) and all(look.buttons[k]["present"] for k in ("left", "right"))
            # The header with a bar, or with both buttons drawn: they are drawn only in the fight (2026-11-08, 231958:
            # after their Surf both buttons were back, paid, at 143.1 s, our bar under "BLOCKED!" and theirs read on
            # some frames only; the fight was taken up again 1.5 s later, the fast taps with it)
            on_screen = look.header and (len(look.bars) >= 1 or both_buttons)
            if buttons_up:
                self.button_seen_t = t
            # In the close-ups of a charged move the header stays up and the camera puts one Pokémon's bar where the
            # other's goes (2026-11-08: after our Discharge our 15% was read as Darmanitan's). A lone bar with no
            # button up is not read.
            both_bars = len(look.bars) == 2
            if not buttons_up and len(look.bars) == 1:
                look.bars = {}
            # The fight, for the fast taps and the looks, is the header and a bar, buttons or not: for an afternoon
            # it needed a button up too, and the taps fell from 530 a battle to 200 (the owner: "you let the
            # rapidash get in like 5 fast moves before you started tapping"). An empty button is see-through, and
            # Vigoroth coming in, white behind it, hid both for 6 s while Toxtricity attacked.
            self.fight_frames = self.fight_frames + 1 if on_screen else 0
            fighting = self.fight_frames >= 3
            # The turn clock: the fight with a button seen in the last second (close-ups, prompts and the other
            # side's throw are off). Scored on 8 named throws of theirs in four battles: by the header and a bar
            # their energy was believed 100 at 7 (8 s of Zeraora's Wild Charge counted as turns); with a button,
            # short at 3 by a fast move or two, which FOE_MARGIN covers.
            # Also both bars up within 8 s of a button: Vigoroth stands white behind the empty buttons for seconds
            # while it fights, and a clock held still there left both counts short (close-ups show a lone bar).
            clock_on = fighting and (t - self.button_seen_t < 1.0 or (both_bars and t - self.button_seen_t < 8.0))
            if self.tapping and fighting and self.frame_t is not None:
                # time our fast moves could run, for our count (the fight, not the clock: the buttons go unseen
                # behind Vigoroth for seconds while it attacks, and a count held still there was 15 short)
                self.fast_time += min(0.2, max(0.0, t - self.frame_t))
            if self.frame_t is not None and not clock_on and t - self.clock_frame_t > 0.4:
                self.off_time += t - self.frame_t  # off the screen (beyond a missed bar or two)
            self.frame_t = t
            if clock_on:
                self.clock_frame_t = t
            if fighting:
                self.fight_frame_t = t
            # A frame or two without the bars in the middle of the fight (they are missed now and then) does not stop
            # the fast taps: they go on until the fight has been off for 0.4 s. Prompts stop them at once (above).
            self.tapping = (bool(fighting) or (self.tapping and t - self.fight_frame_t < 0.4)) \
                and time.time() >= self.hold_taps_until and self.armed is None and self.slow_pause is None \
                and time.time() >= self.pause_hold_until and self.unsure_hold is None and not self.slow_paid_wait()
            if fighting:
                self.watch_hits(t, look.bars)
                if "mine" in look.bars and self.switching is None:
                    # not while a switch is under way: the bar can be the one coming in (2026-11-08, 231958:
                    # Jellicent's 10% coming in was put down to Stunfisk, at 86% before, as it left)
                    self.my_bar_seen.append((t, look.bars["mine"]))
                if self.switching is not None:
                    self.check_switch(t, rgb)
                self.read_energy(rgb, when)
            if self.queued is not None and self.watch_queued(t, rgb, when, bool(fighting)):
                continue
            if fighting:
                # A prompt counts as answered until the fight has been back on screen for a second: it fades in
                # and out over several frames.
                self.fight_since = t if self.fight_since is None else self.fight_since
                if t - self.fight_since >= 1.0:
                    self.prompt_answered = self.replaced = False
                self.names.offer(rgb, t)
                self.names.offer_labels(rgb, t)
                self.names.offer_mine(rgb, t)
                self.read_my_types(rgb, t)
                self.check_active(t)
                # 4 s: an unprompted charged move holds the fight 7 s or so; a switch of theirs 2 to 3 s (2026-11-08:
                # Greedent's switch to Vaporeon was taken for a throw, and Vaporeon's energy counted from too late)
                # 5.5 s since the fight needs a button up (2026-11-08): a switch-in, buttons hidden, no longer counts
                # as fighting, so a switch of theirs leaves a longer gap; the unprompted throws logged so far left
                # 6.7 to 8.4 s.
                if self.last_fight is not None and t - self.last_fight > 5.5 and self.pending_mine is None and not self.pending_theirs:
                    # the fight stood still with no prompt and no throw of ours: their charged move, with no shield of ours to offer
                    if (look.my_shields or 0) == 0 and look.my_left == self.my_left_seen and look.foe_left == self.foe_left_seen:
                        self.pending_theirs = True
                        self.their_throw_at = time.time()
                        self.log("their_charged_unprompted", t, gap=round(t - self.last_fight, 2))
                # a look at once for a new name of theirs too: the engine's next call is on the one now out
                if t - self.last_look >= LOOK or (t - self.last_look >= 0.12 and (
                        self.energy_crossed() or self.at_our_hit(t) or self.foe_name_new())):
                    self.give_look(t, look, rgb)
                self.act(t, look, rgb)
                self.last_fight = t
            else:
                self.fight_since = None
                self.read_used(t, rgb)
                result = self.result(rgb, t)
                if result:
                    return result
        return None

    def read_used(self, t: float, rgb) -> None:
        """Read the top box for "... used <move>!" three times a second while the fight is off the screen. A move
        that is not one of ours is theirs: noted for the next look, by name."""
        if self.last_fight is None or time.time() - self.used_read_at < 0.33 or self.used_busy:
            return
        self.used_read_at = time.time()
        self.used_busy = True
        h, w = rgb.shape[:2]
        crop = rgb[int(0.17 * h):int(0.30 * h), int(0.10 * w):int(0.90 * w)].copy()

        def read():
            try:
                res, _ = self.names.ocr(crop)
                self._used_text(t, res)
            except Exception:  # noqa: BLE001
                pass
            finally:
                self.used_busy = False
        threading.Thread(target=read, daemon=True).start()

    def _used_text(self, t: float, res) -> None:
        text = "".join(ch for ch in " ".join(r[1] for r in (res or [])).upper() if ch.isalpha())
        if "USED" not in text:
            return
        who, said = text.split("USED", 1)
        mine = "".join(ch for ch in self.team[self.active].name.upper() if ch.isalpha())
        theirs = "".join(ch for ch in (self.gd.species[self.tracker.foe.mon.build.species_id]["speciesName"].split(" (")[0]
                                       if self.tracker.foe is not None else "").upper() if ch.isalpha())
        named_mine = any(said.startswith(n) or (len(said) >= 5 and n.startswith(said)) for n in self.my_move_names)
        if len(who) >= 4 and mine and mine != theirs and (who in mine or mine.endswith(who)) and named_mine:
            # "VIGOROTH USED BODY SLAM": ours by the name, whenever it came (2026-11-08: a Body Slam whose start was
            # missed was taken for Charizard's, and 40 came off Charizard's count)
            return
        # Ours: one of our moves, read whole or in part, within 12 s of a throw of ours starting (2026-11-08:
        # "JELLICENTUSEDBUBBLEBEA" was taken for their Bubble, a fast move; and in a Stunfisk mirror their
        # "STUNFISK USED EARTHQUAKE" was taken for ours by the name and ignored).
        if time.time() - self.my_throw_at < 12.0 and \
                any(said.startswith(n) or (len(said) >= 5 and n.startswith(said)) for n in self.my_move_names):
            return
        ids = next((i for n, i in sorted(self.used_names.items(), key=lambda x: -len(x[0])) if said.startswith(n)), None)
        if not ids:
            return
        foe = self.tracker.foe
        own = [i for i in ids if foe is not None and i in self.gd.species[foe.mon.build.species_id]["chargedMoves"]]
        base = foe.mon.build.species_id.split("_")[0] if foe is not None else None
        forms = [i for i in ids if base and any(i in sp.get("chargedMoves", []) for sid, sp in self.gd.species.items()
                                                if sid.split("_")[0] == base)]
        own = own or forms
        move = (own or ids)[0]
        last, self.used_last = self.used_last, (text, time.time())
        if last[0] == text and time.time() - last[1] < 3.0:
            return  # the same words still up (2026-11-08: one Brick Break read three times, counted three times)
        with self.pending_lock:
            if not self.pending_theirs and time.time() - max(self.prompt_seen, self.their_throw_at) < 10.0:
                # The words of a throw whose shield prompt the tracker has already had (the fight showed between):
                # the same throw, not another.
                self.log("their_charged_named", t, move=move, text=text[:40], counted_already=True)
                self.late_move = move  # its name still tells the move, and the form (given at the next look)
                return
            self.foe_move_seen = move
            self.log("their_charged_named", t, move=move, text=text[:40], prompted=self.pending_theirs)
            self.pending_theirs = True
            self.their_throw_at = time.time()

    def watch_hits(self, t: float, bars: dict) -> None:
        """Count their fast moves as they land on our bar (HitSteps), within unbroken fighting with the same two
        Pokémon out; pass the gaps between them to the tracker (Tracker.their_hit_gaps)."""
        foe = self.tracker.foe
        key = (self.active, foe.mon.build.species_id if foe is not None else None)
        if key != self.hits_key or t - self.last_fight_frame > 1.0:
            self.their_steps.reset()
            self.my_steps.reset()
            self.their_hits = []
            self.hits_key = key
        self.last_fight_frame = t
        theirs = bars.get("theirs")
        mon = self.team[self.active]
        if theirs is not None and foe is not None and self.my_steps.add(t, theirs * screen.BAR_INSIDE) is not None:
            last = getattr(self, "my_hit_at", None)
            self.my_step_at = t  # any step down of their bar, a flame's or the hit's: holds end on it
            # 0.4 s a turn, not 0.3 (2026-11-23, 232848: a step 1.53 s after Incinerate's hit was taken for the next
            # hit, and the real one 1.31 s later was ignored; a long move's hits come 2.5 s apart)
            if mon.fast.turns >= SLOW_FAST_TURNS and last is not None and 0 <= t - last < 0.4 * mon.fast.turns:
                # A long fast move lands once in 2.5 s; Incinerate's flames step their bar twice or more (2026-11-22:
                # 'hits' 0.5 to 0.8 s apart, each adding 20 to the count, which ran a move ahead of the buttons)
                self.log("my_hit_ignored", t, since=round(t - last, 2))
                return self._their_side(t, bars, foe, key)
            self.my_hits_since_look += 1
            self.my_hit_at = t  # our fast move landed: the next has just begun
            self.log("my_hit", t)
        self._their_side(t, bars, foe, key)

    def _their_side(self, t: float, bars: dict, foe, key) -> None:
        """watch_hits for their fast moves landing on our bar."""
        px = bars.get("mine")
        if px is None or foe is None:
            return
        size = self.their_steps.add(t, px * screen.BAR_INSIDE)
        if size is None:
            return
        t = getattr(self.their_steps, "at", None) or t  # when it landed: the first reading below
        self.log("their_hit", t, px=round(size, 1), foe=key[1])
        self.hits_since_look += 1
        if self.their_hits:
            gaps = self.hit_gaps.setdefault(key[1], [])
            gaps.append(round(t - self.their_hits[-1], 3))
            try:
                before = foe.mon.build.fast.id
                self.tracker.their_hit_gaps(t, gaps)
                if foe.mon.build.fast.id != before:
                    self.log("foe_fast_by_gaps", t, foe=key[1], was=before, now=foe.mon.build.fast.id,
                             gaps=sorted(gaps)[:5])
            except Exception as error:  # noqa: BLE001
                self.log("tracker_error", t, error=str(error))
        self.their_hits.append(t)

    def read_my_types(self, rgb, t: float) -> None:
        """Which of ours the type icons in our header's corner show (pogo.android_screen.header_types), once three
        frames in a row agree: self.types_seen = (slot, time). In training the header shows nicknames, and the owner's
        Melmetal and Umbreon are both ".gl1" (2026-11-08: Gengar was out and taken for Melmetal a whole battle, its
        minigames hunting Steel icons); the icons say steel, dark, ghost and poison."""
        types = set(screen.header_types(rgb, "mine"))
        slot = None
        if types:
            fits = [j for j, b in enumerate(self.team)
                    if {x for x in self.gd.species[b.species_id]["types"] if x != "none"} == types]
            slot = fits[0] if len(fits) == 1 else None
        self.types_hist = (getattr(self, "types_hist", []) + [slot])[-3:]
        if slot is not None and self.types_hist.count(slot) == 3:
            self.types_seen = (slot, t)

    def header_says(self):
        """The team slot our header names (GO Battle League shows the species), or None."""
        canon = lambda s: "".join(ch for ch in s.upper() if ch.isalpha())
        read = canon(self.names.my_name or "")
        if len(read) < 4:
            return None
        hits = [j for j, b in enumerate(self.team) if canon(b.name) in read or read in canon(b.name)]
        return hits[0] if len(hits) == 1 else None

    def labels_say(self):
        """The team slot whose moves the last reading of the names under the buttons names (one alone), or None."""
        canon = lambda s: "".join(ch for ch in s.upper() if ch.isalpha())
        read = [canon(w) for w in self.names.labels]
        scores = [sum(any(canon(m.name) in r or r in canon(m.name) for r in read if len(r) >= 4) for m in b.charged)
                  for b in self.team]
        best = max(range(len(self.team)), key=lambda j: scores[j])
        return best if scores[best] >= 1 and scores.count(scores[best]) == 1 else None

    def check_active(self, t: float) -> None:
        """Which of ours is out, from the move names under the buttons (our header shows nicknames). While a switch
        is being checked, check_switch reads them."""
        if self.switching is not None:
            return
        if self.active != self._last_active:  # the belief changed (a switch, a replacement): older readings are stale
            self._last_active, self.active_changed_at = self.active, t
            with self.names._lock:  # and both are read again now, changed on screen or not (a wrong belief leaves
                self.names._mine_sig = self.names._label_sig = None  # the screen as it was)
        # Our header first: it names the species in GO Battle League, at every look, paid for or not. A reading
        # counts only if it is newer than the last change of belief (2026-11-08: names under the buttons read before
        # a switch were applied after it, and the belief flipped back for a moment).
        mine = self.header_says() if (self.names.my_name_at or -1) > self.active_changed_at else None
        key = (self.names.my_name_at, self.active)
        if mine is not None and key != self.header_checked:
            self.header_checked = key
            if mine != self.active:
                kind = self.tell_correction()
                self.log("active_corrected", t, was=self.team[self.active].name, now=self.team[mine].name,
                         header=self.names.my_name, how=kind)
                self.switch_went_late(t, mine)
                self.corrected_from = (self.active, time.time())
                self.active = mine
                self.energy_read = self._energy_raw = None
                # the header has just said who is out: its type icons are not asked against it for 8 s either
                # (2026-11-22, 151353: corrected to Virizion by the header, then back to the fainted Feraligatr by the
                # icons 7 s later, and Virizion's bar was put to Feraligatr)
                self.header_confirmed_at = time.time()
            return
        if mine is not None and mine == self.active:
            # the header names the one we think is out: its type icons are not asked against it (2026-11-22, the last
            # Pokemon sent in after Feraligatr fainted: the header said Virizion, the type icons, misread, said the
            # fainted Feraligatr for 3 s, and the bot played Feraligatr's moves); nor for 8 s after, while the name is
            # not read again
            self.header_confirmed_at = time.time()
            return
        # Our header's type icons: in training the header shows nicknames, which can be the same for two of ours
        ts = getattr(self, "types_seen", None)
        if ts is not None and ts[1] > self.active_changed_at + 0.3 and (ts, self.active) != getattr(self, "types_checked", None) \
                and time.time() - getattr(self, "header_confirmed_at", 0.0) > 8.0:
            self.types_checked = (ts, self.active)
            down = sum(1 for m in self.tracker.me.team if m.hp <= 0)
            if ts[0] != self.active and self.tracker.me.team[ts[0]].hp <= 0 and self.my_left_seen <= len(self.team) - down:
                # fainted, and the count of ours left says so too: it cannot be out (2026-11-23, 205934: a faint the
                # count did not show, from a false replacement prompt, held the icons off Melmetal, out, for 7 s)
                self.log("types_ignored", t, said=self.team[ts[0]].name, why="fainted")
            elif ts[0] != self.active:
                kind = self.tell_correction()
                self.log("active_corrected", t, was=self.team[self.active].name, now=self.team[ts[0]].name, by="types",
                         how=kind)
                self.switch_went_late(t, ts[0])
                self.corrected_from = (self.active, time.time())
                self.active = ts[0]
                self.energy_read = self._energy_raw = None
            return
        at = self.names.labels_at
        if at is None or (at, self.active) == self.labels_checked or at <= self.active_changed_at:
            return
        self.labels_checked = (at, self.active)
        best = self.labels_say()
        if best is not None and best != self.active:
            kind = self.tell_correction()
            self.log("active_corrected", t, was=self.team[self.active].name, now=self.team[best].name, labels=self.names.labels,
                     how=kind)
            self.switch_went_late(t, best)
            self.active = best

    def switch_went_late(self, t: float, now_slot: int) -> None:
        """A correction to the one our last switch tap was for, within the switch timer of that tap, with no switch
        being checked: the switch went through after all, so our switch timer runs from that tap (2026-11-24, 173951:
        Snorlax tapped at 112.9 s as Mantine threw, judged not taken at 119.9 s, named by the header at 124.7 s; with
        no timer started, a switch at 142.8 s was tapped ten times while the game's ran)."""
        if self.switching is None and now_slot == getattr(self, "switch_tapped_to", None) \
                and 0.0 < time.time() - self.switch_last_tap < 45.0:
            self.switch_ready_at = max(self.switch_ready_at, self.switch_last_tap + 45)
            self.log("switch_seen_late", t, to=self.team[now_slot].name,
                     ready_in_s=round(self.switch_ready_at - time.time(), 1))

    def tell_correction(self) -> str | None:
        """Before a correction of which of ours is out: tell the tracker how the change came about, so it starts no
        switch timer for a change that was no switch of ours (Tracker.my_active_corrected). Within 6 s of a switch tap
        it is that switch, and the tracker takes it as one; within 15 s of a replacement tap the game sent in another
        than the one chosen ("none": the faint is counted); else the one believed out fainted and the game sent in
        the next: "faint" when that is the only other one alive (our last, sent in unasked), else "unsure", left to
        the counter of ours (2026-11-22: 12 corrections of this kind; the counter fell up to 10 s after the header,
        and meanwhile the tracker had the fainted one alive on the bench and a switch timer running)."""
        if self.switching is not None or time.time() - self.switch_last_tap < 6.0:
            return None
        if time.time() - self.replace_tapped < 15.0:
            kind = "none"
        else:
            others = [j for j in range(len(self.team)) if j != self.active and self.tracker.me.team[j].hp > 0]
            out = self.tracker.me.team[self.active]
            # a faint only where one was likely: the one believed out low, or their charged move just now (a replay of
            # 2026-11-22, 191031: a switch shown 8 s after its tap, Melmetal on 45%, would have been taken for its faint)
            likely = out.hp <= 0.35 * out.build.hp or time.time() - self.their_throw_at < 10.0
            kind = "faint" if len(others) == 1 and likely else "unsure"
        self.tracker.my_active_corrected(kind)
        return kind

    def header_now(self, look) -> tuple:
        if look.header and look.my_left and look.foe_left:
            self.history = (self.history + [(look.my_left, look.foe_left, look.my_shields, look.foe_shields)])[-5:]
        if not self.history:
            return None, None, None, None
        most = [max(set(col), key=col.count) for col in zip(*self.history)]
        if len(self.history) >= 2:
            # The counts only fall: two readings in a row agreeing on fewer are taken at once, not when three of five
            # do (on four battles' recordings, 2026-11-22: 31 falls seen 0.5 to 1.6 s sooner, none that did not hold;
            # their shields after a throw of ours are counted that much sooner)
            for k in range(4):
                a, b = self.history[-1][k], self.history[-2][k]
                if a is not None and a == b and most[k] is not None and a < most[k]:
                    most[k] = a
        return tuple(most)

    def check_switch(self, t: float, rgb) -> None:
        """Whether the switch tapped went through, from what only a switch changes: the buttons become the new
        Pokémon's moves. Its names under the buttons (read in the background, self.names) or an energy reading that
        fits its moves' costs and not the old one's, three frames running, say it went; the old one's names a second
        after the tap say it did not. The bench strip (pogo.android_screen.bench_strip) changes too, but so does any
        cut of the camera (2026-11-07: a tap during "Stunfisk used Mud Bomb!" was ignored, the cut to Gengar changed
        the strip, and the player took Vigoroth for out for 4.5 s). It decides only if neither has said anything in 5
        s: a change of over 45 held for 0.6 s, starting within 2 s of the tap. Until then no charged tap goes.
        The re-tap window, the "not taken" verdicts and the 5 s are counted in fight time (self.switch_fight_s: this
        runs on fighting frames only), not on the clock: the game ignores a switch tapped while a charged move plays
        out, and on the clock the window ran out in the close-up (2026-11-24, 174318: tapped 0.3 s after Stone Edge's
        minigame, ignored, no tap when the fight came back 3 s later, Snorlax in 6.4 s late; 173604 and 173951 the
        same, 4.7 and 2.9 s)."""
        slot, tapped, before, since, looked = self.switching
        looked += 1
        tapped_t = tapped - (self.t0 or tapped)  # the tap in battle time, as the label readings are timed
        last_tap_t = self.switch_last_tap - (self.t0 or self.switch_last_tap)
        now = time.time()
        if now - self.switch_fight_last > 0.5:
            # the fight back after time off the screen: the strip as it was at a tap in the move's animation is no
            # yardstick (the dry run of 174318: 40 and more from it all through the 3 s after the close-up, so no
            # re-tap); compared with the strip as the fight shows it now. A switch that went in the meantime has the
            # game's switch timer running, so a re-tap does nothing
            before, since = screen.bench_strip(rgb), None
        self.switch_fight_s += min(0.25, max(0.0, now - self.switch_fight_last))
        self.switch_fight_last = now
        window_done = self.switch_fight_s >= SWITCH_SPAM_S  # the re-taps have had their fight time
        old_costs = [m.energy for m in self.team[self.active].charged]
        new_costs = [m.energy for m in self.team[slot].charged]
        e_new, e_old = screen.my_energy(rgb, new_costs), screen.my_energy(rgb, old_costs)
        fits = "new" if e_new is not None and e_old is None else "old" if e_old is not None and e_new is None else None
        self._switch_fits = (self._switch_fits + [fits])[-3:] if looked > 1 else [fits]
        said = self.labels_say() if (self.names.labels_at or -1) > tapped_t + 0.3 else None
        header = self.header_says() if (self.names.my_name_at or -1) > tapped_t + 0.3 else None
        how = None
        if header == slot:
            how = "header"
        elif header is not None and header == self.active and (self.names.my_name_at or -1) > last_tap_t + 1.5 \
                and window_done:
            self.log("switch_not_taken", t, to=self.team[slot].name, by="header")
            self.switching = None
            if not self.switch_retried:
                self.switch_retried, self.switch_wanted = True, slot
            return
        elif said == slot:
            how = "names"
        elif self._switch_fits == ["new"] * 3 and time.time() - tapped > 1.0 and header is None:
            # the energy fitting the new one's costs is weaker evidence (2026-11-08: taken for a switch 0.7 s after
            # a tap the game ignored): only after a second, and only with no header name to go by
            how = "buttons"
        if how is not None:
            self.log("switch_seen", t, to=self.team[slot].name, after_tap_s=round(time.time() - tapped, 2), by=how)
            self.switch_wanted = None
            # gone through: a fast tap can no longer take its place, so the taps go on now, not at the 1.6 s hold's
            # end (2026-11-09: switches seen 0.86 s after the tap, the taps back 0.8 s later, every switch)
            self.hold_taps_until = 0.0
            self.active = slot
            self.switch_ready_at = tapped + 45  # switch timer: our own count, the tracker has its own
            self.switching = None
            self.energy_read = self._energy_raw = None  # those were the other Pokémon's buttons
            return
        if window_done and ((said == self.active and (self.names.labels_at or -1) > last_tap_t + 1.0) or
                            (self._switch_fits == ["old"] * 3 and now - self.switch_last_tap > 1.5)):
            self.log("switch_not_taken", t, to=self.team[slot].name, by="names" if said == self.active else "buttons")
            self.switching = None
            if not self.switch_retried:  # the game ignored it: once more
                self.switch_retried, self.switch_wanted = True, slot
            return
        strip_diff = float(np.abs(screen.bench_strip(rgb) - before).mean())
        if strip_diff > 45 and (since or time.time() - tapped < 2.0):
            since = since or time.time()
        else:
            since = None
        if SPAM_SWITCH and self.switch_point is not None and not window_done \
                and strip_diff < STRIP_SAME and time.time() - self.switch_last_tap >= 0.2:
            # Tapped again until it shows (the owner, 2026-11-22, as charged moves are since 11-18): in 71 league
            # battles of 2026-11-08 to 10, 35 switch taps were not taken (in 25 battles), and a switch showed a
            # median 1.5 s after its tap, 1 in 10 over 3 s, the longest 9 s. Only with the fight on the screen (this
            # is called on fighting frames) and the bench strip as at the tap: once it has changed the switch has
            # gone or the camera has cut, and a tap there could land on the field as a fast move, which takes the
            # switch's place. Fast taps stay held 1.6 s after each tap, as after the first.
            self.touch(self.switch_point, f"switch to {self.team[slot].name} again")
            self.log("switch_retap", t, to=self.team[slot].name, after_tap_s=round(time.time() - tapped, 2),
                     strip=round(strip_diff, 1))
            self.switch_last_tap = time.time()
            self.hold_taps_until = max(self.hold_taps_until, time.time() + 1.6)
        if self.switch_fight_s > 5.0 or now - tapped > 20.0:
            # Nothing said in 5 s of fight: taken as not taken. The bench strip alone was wrong (2026-11-08: "seen" at 14.9 s,
            # Jellicent still out); if it did go, the names under the buttons correct it (check_active).
            seen = False
            self.log("switch_seen" if seen else "switch_not_taken", t, to=self.team[slot].name, by="bench strip")
            if seen:
                self.active = slot
                self.switch_ready_at = tapped + 45
                self.energy_read = self._energy_raw = None
            self.switching = None
            return
        self.switching = (slot, tapped, before, since, looked)

    def read_energy(self, rgb, when: float) -> None:
        """Our energy from the buttons on this frame; kept when the frame before (under a quarter second earlier)
        read the same within 5 (single frames of a close-up can pass the buttons' own checks)."""
        costs = [m.energy for m in self.team[self.active].charged]
        e = screen.my_energy(rgb, costs)
        if e is None and self.energy_read is not None and when - self.energy_read[1] < 1.5:
            # one button alone (the other unreadable, Body Slam's grey over Snorlax's white most of all), only next to
            # a recent reading and no further from it than our fast moves could have taken us: a button flashing as
            # it becomes paid for read 100 from 62 (2026-11-18, on Snorlax's recordings)
            one = screen.my_energy_one(rgb, costs)
            if one is not None:
                fast = self.team[self.active].fast
                last, dt = self.energy_read[0], when - self.energy_read[1]
                if last - 6 <= one <= last + fast.energy_gain * math.ceil(dt / (fast.turns * 0.5) + 1) + 6:
                    e = one
        prev, self._energy_raw = self._energy_raw, ((e, when) if e is not None else None)
        if e is not None and prev is not None and when - prev[1] < 0.25 and abs(e - prev[0]) <= 5:
            last = self.energy_read
            if (last is None or when - last[1] > 1.5
                    or abs(e - self.reading_base) >= 0.5 * self.team[self.active].fast.energy_gain):
                self.reading_new_at, self.reading_base = when, e
            self.energy_read = (e, when)
            self.last_reading_t = when - (self.t0 or when)  # battle time of the last reading
        names = screen.button_labels(rgb)
        # Only with both buttons drawn, and not while our move's attack plays after its minigame (2026-11-08,
        # 231958: right after Surf's and Discharge's minigames the attack's white streaks filled the name boxes, both
        # "names" read, the low-health rule threw again with 30 and 21 energy, and the fast taps stopped 3 to 5 s
        # while it was not taken; the rims there read 2 to 9, a button drawn 10 or more).
        if time.time() < self.names_blocked_until or min(screen.button_rim(rgb, k) for k in (0, 1)) < 10:
            names = [None, None]
        if None not in names:
            prev, self._names_raw = self._names_raw, (tuple(names), when)
            if prev is not None and prev[0] == tuple(names) and when - prev[1] < 0.25:
                self.names_seen = (tuple(names), when)

    def paid_bounds(self):
        """(least, most) our energy can be by which moves' names show under the buttons in the last 0.6 s (a name
        shows exactly when its move is paid for), or None. The fill cannot be read while the buttons flash on
        becoming paid for; the names can (2026-11-07: Mud Bomb's name showed, the count said 43 of its 45, and the
        engine threw Discharge into Typhlosion instead)."""
        if self.names_seen is None or time.time() - self.names_seen[1] > 0.6:
            return None
        costs = [m.energy for m in self.team[self.active].charged]
        names = self.names_seen[0]
        least = max([c for c, n in zip(costs, names) if n], default=0)
        most = min([c - 1 for c, n in zip(costs, names) if not n], default=100)
        return (least, most) if least <= most else None

    def energy(self, look=None) -> float | None:
        """Our energy as the buttons showed it in the last 0.35 s, or None. The buttons flash as a move becomes paid
        for and give no reading then; an older reading is stale by a fast move or more."""
        if self.energy_read is not None and time.time() - self.energy_read[1] < 0.35:
            return self.energy_read[0]
        return None

    def at_our_hit(self, t: float) -> bool:
        """Our fast move has just landed (seen on their bar) and a charged move is paid for: a look and decision now,
        at the start of our next fast move, so a throw is tapped before that move ends and goes off when it does. The
        game has a charged move only at the end of the fast move under way; a tap that comes after that end waits a
        whole further fast move, as the fast taps have begun one (2026-11-18: with decisions every 0.5 s and 0.43 s
        from a decision to its tap, the owner: "a lot of stuff you can figure out in advance though")."""
        if not DECIDE_ON_HIT:
            return False
        at = getattr(self, "my_hit_at", None)
        if at is None or at <= self.last_look or t - at > 0.3:
            return False
        have = self.energy()
        if have is None and self.tracker.foe is not None:
            have = self.tracker.me.mon.energy
        return have is not None and have >= min(m.energy for m in self.team[self.active].charged)

    def energy_crossed(self) -> bool:
        """The buttons now read our energy at or over one of our charged moves' cost that the last look's reading was
        under: a look (and so a decision) now, not at the next half-second (2026-11-18: decisions came only at looks,
        0.5 s apart, so a throw waited 0.25 s on average after it was paid for, on top of 0.43 s from the decision's
        frame to the tap)."""
        e = self.energy()
        if e is None:
            return False
        before = getattr(self, "look_energy", None)
        costs = [m.energy for m in self.team[self.active].charged]
        return before is not None and any(before < c <= e for c in costs)

    def give_look(self, t: float, look, rgb) -> None:
        self.look_energy = self.energy()
        my_left, foe_left, my_sh, foe_sh = self.header_now(look)
        # The turns since the last look are the time the fight was on the screen, measured frame by frame: the
        # tracker takes 10 s off for each charged move, so that is given back (on this phone the fight is off for
        # less, and the turns at the start of each stretch were lost; real players attack the moment it is back).
        thrown = (self.pending_mine is not None) + self.pending_theirs
        paused = self.off_time - 10.0 * thrown if (self.off_time > 0 or thrown) else None
        self.off_time = 0.0
        if my_left is not None and my_left < self.my_left_seen:
            self.my_left_seen = my_left
            if my_left == 1 and time.time() - self.replace_tapped > 15.0:
                # One of ours fainted with no prompt answered: with one left the game sends it in itself
                # (2026-11-08: Jellicent fainted, Stunfisk came in unasked, and the player, still taking Jellicent
                # for out, threw "Bubble Beam" on Stunfisk's Mud Bomb button and hunted Water icons: Nice).
                # Which one went is told by who is out now, as last seen: our header's type icons (read in the last
                # 3 s), else its name, else a correction of who is out just made; the one out is alive and the
                # other is the one that fainted. Only with none of those, the one believed out. (2026-11-09: in 5 of
                # 8 battles the counter fell seconds after the game had sent our last one in, the belief already
                # corrected to it, and the one out, alive, was put at 0 HP: the engine then decided on a dead team.)
                ts = getattr(self, "types_seen", None)
                prev = getattr(self, "corrected_from", None)
                out_now, how = None, None
                if ts is not None and t - ts[1] < 3.0:
                    out_now, how = ts[0], "types"
                elif self.header_says() is not None:
                    out_now, how = self.header_says(), "header"
                elif prev is not None and time.time() - prev[1] < 10.0 and prev[0] != self.active:
                    out_now, how = self.active, "correction"
                alive = [j for j in range(len(self.team)) if self.tracker.me.team[j].hp > 0]
                gone = [j for j in alive if j != out_now] if out_now is not None else [self.active]
                if out_now is None or len(gone) == 1:
                    was = gone[0] if gone else self.active
                    self.tracker.me.team[was].hp = 0
                    if out_now is None:
                        alive = [j for j in range(len(self.team)) if self.tracker.me.team[j].hp > 0]
                        out_now = alive[0] if len(alive) == 1 else None
                    if out_now is not None and self.tracker.me.team[out_now].hp <= 0:
                        # out, so alive: the tracker had put it at 0 (230719: damage while who was out was unsure)
                        share = look.bars.get("mine") if look.bars else None
                        self.tracker.me.team[out_now].hp = max(1, round((share or 0.1) * self.team[out_now].hp))
                        self.log("hp_restored", t, who=self.team[out_now].name, hp=self.tracker.me.team[out_now].hp)
                    self.log("fainted_unprompted", t, was=self.team[was].name, left=my_left,
                             now=self.team[out_now].name if out_now is not None else None, by=how)
                    self.replacements += 1
                    if out_now is not None and out_now != self.active:
                        self.active = out_now
                        self.switching = self.switch_wanted = None
                        self.energy_read = self._energy_raw = None
        if foe_left is not None and foe_left < self.foe_left_seen:
            self.foe_left_seen = foe_left
        out_for = None
        if self.names.species is not None and self.names.species != self.foe_seen_species:
            self.foe_seen_species = self.names.species
            if self.names.read_at is not None:
                out_for = max(0.0, t - self.names.read_at)  # read from a frame that long ago
        with self.pending_lock:  # the "used" reading thread sets pending_theirs and foe_move_seen
            # Our bar is not credited to the one believed out while a switch is under way: it can be the one coming
            # in (2026-11-22, 181223: the game had Blastoise in at full health 2 s before the header named it, and
            # Melmetal, at 30%, was put at 186 of 187; 48 s later the engine sent it in against Walrein's Earthquake)
            mine_bar = look.bars.get("mine") if self.switching is None else None
            believed = self.tracker.me.team[self.active] if self.tracker.foe is not None else None
            if (mine_bar is not None and believed is not None and time.time() - self.switch_last_tap < 6.0
                    and getattr(self, "switch_tapped_to", self.active) != self.active
                    and mine_bar > believed.hp / believed.build.hp + 0.25):
                # Health does not come back: so far over the one believed out, soon after a switch tap to another, it is
                # the bar of the one coming in, the header behind it (2026-11-22, 191031: the switch to Skeledirge given
                # up on the header's word, Skeledirge's full bar was put to Melmetal on 24%). Not once the switch is seen:
                # the one out is the one tapped (2026-11-23, 205934: Skeledirge's own full bar refused 5 s)
                self.log("bar_not_ours", t, read=round(mine_bar, 3), believed=self.team[self.active].name)
                mine_bar = None
            obs = Observation(t=t, my_species=self.team[self.active].species_id, foe_species=self.names.species,
                              my_hp=mine_bar,
                              foe_hp=look.bars.get("theirs"), my_shields=my_sh,
                              foe_shields=foe_sh, my_left=my_left, foe_left=foe_left, my_energy=self.energy(look),
                              my_charged=self.pending_mine, foe_charged=self.pending_theirs, paused=paused,
                              foe_hits=self.hits_since_look, foe_move=self.foe_move_seen if self.pending_theirs else None,
                              my_hits=self.my_hits_since_look, foe_out_for=out_for)
            self.hits_since_look = self.my_hits_since_look = 0
            self.foe_move_seen = None
            self.pending_theirs = False  # handed to the tracker in this look
        before = (self.tracker.me.mon.energy, self.tracker.me.mon) if self.tracker.foe is not None else None
        try:
            self.tracker.update(obs)
            late, self.late_move = self.late_move, None
            if late is not None:
                self.tracker.their_move_named(t, late)
        except Exception as error:  # noqa: BLE001 - a bad look must not stop the battle
            self.log("tracker_error", t, error=str(error))
        if before is not None and obs.my_energy is None and self.tracker.me.mon is before[1]:
            # With no reading, ours rises only by the fast moves there was time for: fast taps on and the fight on
            # the screen. The tracker counts a fast move every so many turns, and while a throw waited to start, a
            # prompt was up or the buttons were hidden that ran on (2026-11-08: Vigoroth's count went 43 to 63 in a
            # 3 s wait with the taps off, two throws were tried on it and not taken, and it fainted with none thrown).
            mon_now = self.tracker.me.mon
            # Whole fast moves only, the part of one under way carried to the next look: rounded up at each look,
            # a 1 s fast move counted one a look (two a second), and on the count alone 37 of 87 throws were not
            # taken (2026-11-09, the third account's first 13 league battles; 1 of 27 tapped on a reading)
            dur = mon_now.build.fast.turns * 0.5
            moves = int((self.fast_carry + self.fast_time) / dur)
            self.fast_carry = self.fast_carry + self.fast_time - moves * dur
            cap = before[0] + moves * mon_now.build.fast.energy_gain
            if mon_now.energy > cap:
                mon_now.energy = min(100, cap)
        self.fast_time = 0.0
        if obs.my_energy is not None or before is None or self.tracker.me.mon is not before[1]:
            self.fast_carry = 0.0  # a reading, or another Pokémon: the count starts afresh
        if obs.my_energy is not None and self.tracker.foe is not None:
            # The buttons are the better witness: the count misses moves (a throw that went off after theirs),
            # turns lost between taps, and Pokémon seen coming in late. It takes the reading at once.
            mon_now = self.tracker.me.mon
            if abs(mon_now.energy - obs.my_energy) > 4:
                self.log("energy_read", t, counted=mon_now.energy, read=round(obs.my_energy, 1))
            mon_now.energy = int(round(obs.my_energy))
        bounds = self.paid_bounds()
        if bounds is not None and self.tracker.foe is not None:
            # The names only ever raise it: a name that shows says that move is paid for, but a name can be missing
            # without the move being unpaid (just after a charged move the buttons are dim and show no names:
            # 2026-11-08, Stunfisk with 49 was taken for 39 and did not throw).
            mon_now = self.tracker.me.mon
            kept = max(mon_now.energy, bounds[0])
            if kept != mon_now.energy:
                self.log("energy_from_names", t, counted=mon_now.energy, least=bounds[0], most=bounds[1])
                mon_now.energy = kept
        b = look.buttons
        f = self.tracker.foe
        self.log("look", t, obs={k: v for k, v in obs.__dict__.items() if v is not None},
                 buttons={k: [b[k]["fill"], int(b[k]["present"]), int(b[k]["ready"]), b[k].get("step"), b[k].get("level")]
                          for k in ("left", "right")} if b else None,
                 counted=self.tracker.me.mon.energy if f is not None else None,
                 # what the tracker believes of theirs, to check against the recording afterwards
                 foe=[f.mon.build.species_id, f.lo, f.hi, f.mon.build.fast.id, f.fast_from, f.clock,
                      self.tracker.turn] if f is not None else None)
        self.pending_mine, self.pending_theirs = None, False
        self.last_look = t

    def view(self):
        return self.tracker.view() if self.tracker.foe is not None else None

    def precompute(self, view) -> None:
        """Search ahead, on a copy of the engine in a thread, the position at the end of our fast move under way, as
        if both sides only fast-move (the imagined battle of pogo.realtime.predict): when the next decision comes
        there, its answer is ready (Player.precomputed). Only with a charged move of ours paid for or a fast move
        away, and not while a switch or a throw is under way. The owner, 2026-11-18: "a lot of stuff you can figure
        out in advance". A decision searched at its moment took a median 90 ms on the loop, a quarter of them the
        300 ms cap, with a throw waiting on it."""
        if not PRECOMPUTE or self.switching is not None or self.switch_wanted is not None or self.armed is not None:
            return
        if self.pre is not None and not self.pre["done"]:
            return  # one at a time
        mon = view.me.mon
        if mon.energy + mon.build.fast.energy_gain < min(m.energy for m in mon.build.charged):
            return
        import random
        from pogo.engine import imagine
        from pogo.realtime import _Quiet
        try:
            twin = imagine(view, random.Random(0), self.engine.pool, _Quiet(), _Quiet())
            active = [side.active for side in twin.sides]
            for _ in range(mon.build.fast.turns):
                twin.step()
                if twin.winner is not None or any(sd.mon.hp <= 0 or sd.active != a for sd, a in zip(twin.sides, active)):
                    return  # a faint first: nothing to search ahead
            ahead_view = twin.views[0]
            copy = self.engine.clone()
            ev = getattr(copy, "evaluator", None)
            if ev is not None and hasattr(ev, "model"):
                copy.evaluator = type(ev)(ev.model)  # its own caches: the two may search at once
        except Exception as error:  # noqa: BLE001
            self.log("precompute_error", self.now(), error=str(error))
            return
        copy.cap_ms = PRECOMPUTE_MS  # the fast move's time, not the moment's
        pre = {"done": False, "action": None, "engine": copy, "view": ahead_view, "calls": self.engine_calls,
               "active": self.active, "at": time.time(), "ms": None, "cap": self.engine.cap_ms}
        self.pre = pre

        def run():
            t1 = time.perf_counter()
            try:
                pre["action"] = copy.act(ahead_view)
            except Exception:  # noqa: BLE001
                pre["action"] = None
            pre["ms"] = round((time.perf_counter() - t1) * 1000)
            pre["done"] = True
        threading.Thread(target=run, daemon=True).start()

    def precomputed(self, view):
        """(action, the engine copy that chose it) when a search run ahead (Player.precompute) is done, no other call
        to the engine came since, the same Pokemon are out, and the position is the one imagined: shields, stat
        stages, the moves each side has paid for and the switch timers the same; health within 4%, energy within a
        fast move. Else None, and the engine searches as usual. The copy then stands in for the engine: it made the
        decision the engine would have, from the same state."""
        pre, self.pre = self.pre, None
        if pre is None or not pre["done"] or pre["action"] is None or pre["calls"] != self.engine_calls:
            return None
        if pre["active"] != self.active or time.time() - pre["at"] > 3.0:
            return None
        a, b = pre["view"], view
        ma, mb, fa, fb = a.me.mon, b.me.mon, a.foe, b.foe

        def paid(m):
            return tuple(m.energy >= c.energy for c in m.build.charged)
        checks = {
            "our active": a.me.active == b.me.active, "our shields": a.me.shields == b.me.shields,
            "our switch timer": (a.me.switch_wait > 0) == (b.me.switch_wait > 0),
            "our stages": (ma.atk_stage, ma.def_stage) == (mb.atk_stage, mb.def_stage),
            "our health": abs(ma.hp - mb.hp) <= 0.04 * mb.build.hp, "our moves paid": paid(ma) == paid(mb),
            "our energy": abs(ma.energy - mb.energy) <= mb.build.fast.energy_gain,
            "their species": fa.build.species_id == fb.build.species_id, "their shields": a.foe_shields == b.foe_shields,
            "their switch timer": (a.foe_switch_wait > 0) == (b.foe_switch_wait > 0),
            "their stages": (fa.atk_stage, fa.def_stage) == (fb.atk_stage, fb.def_stage),
            "their health": abs(fa.hp - fb.hp) <= 0.04 * fb.build.hp, "their moves paid": paid(fa) == paid(fb),
            "their energy": abs(fa.energy - fb.energy) <= fb.build.fast.energy_gain + 1}
        fails = {k for k, ok in checks.items() if not ok}
        loose = {"our moves paid", "our energy", "our health", "their health", "their moves paid", "their energy"}
        if any(paid(mb)):
            loose.discard("their health")  # with a throw to hand, their health decides farm down or throw
        if fails and fails <= loose and pre["action"] == FAST \
                and all(now <= then for now, then in zip(paid(mb), paid(ma))) \
                and all(now <= then for now, then in zip(paid(fb), paid(fa))) \
                and mb.hp >= ma.hp - 0.04 * mb.build.hp and fb.hp >= fa.hp - 0.04 * fb.build.hp \
                and fb.energy <= fa.energy + fb.build.fast.energy_gain + 1:
            # Imagined a fast move on, the readings still a hit behind (34 of 55 misses on two replays were our
            # moves paid, then their health and ours, 2026-11-18). A fast move chosen there stands when the position
            # is no further on for either side: no more moves paid for by either, neither lower in health, their
            # energy no higher. Throws and switches stay exact.
            fails = set()
        if fails:
            self.log("precompute_missed", self.now(), searched_ms=pre["ms"], why=sorted(fails),
                     ours=[ma.hp, mb.hp, ma.energy, mb.energy], theirs=[fa.hp, fb.hp, fa.energy, fb.energy],
                     age=round(time.time() - pre["at"], 2))
            return None
        if pre["action"] not in view.legal():
            return None
        pre["engine"].cap_ms = pre["cap"]  # back to the live limit, as the engine from here
        return pre["action"], pre["engine"]

    def act(self, t: float, look, rgb=None) -> None:
        view = self.view()
        if view is not None and t - self.last_look < 0.05:  # a decision at each look
            t0 = time.perf_counter()
            seen = None
            ready = None
            try:
                with self.engine_sees():
                    ready = self.precomputed(view)
                    if ready is not None:
                        self.decision, self.engine = ready
                    else:
                        self.decision = self.engine.act(view)
                    self.engine_calls += 1
                    if self.decision == FAST:
                        self.precompute(view)
                    if self.decision != FAST or ready is not None:  # the view as the engine saw it (their energy
                        # with the margin); also on answers searched ahead, to check them (scripts/live/engine_view.py)
                        try:
                            seen = view_record(view)
                        except Exception as error:  # noqa: BLE001
                            seen = {"error": str(error)}
            except Exception as error:  # noqa: BLE001
                self.log("engine_error", t, error=str(error))
                self.decision = FAST
            self.decided_for = self.active
            extra = {"view": seen} if seen is not None else {}
            if ready is not None:
                extra["precomputed"] = True
            self.log("decision", t, action=self.name(self.decision), ms=round((time.perf_counter() - t0) * 1000), **extra)
            if self.decision == FAST and self.slow_pause is None:
                self.pause_hold_until = 0.0  # decided on the energy as it is: the fast taps go on
            if self.decision == FAST:
                self.fast_decided_at = time.time()
                self.paid_fast_streak = getattr(self, "paid_fast_streak", 0) + 1 if self.slow_paid() else 0
            else:
                self.paid_fast_streak = 0
            self.no_weaker_move(t, view)
            self.owner_prefers(t, view)
            if self.armed is not None and self.decision != FAST:
                self.log("armed_replaced", t, by=self.name(self.decision))  # a switch now, or a move paid for now
                self.armed = None
            if self.decision == FAST and self.armed is None and self.switching is None and self.switch_wanted is None:
                self.look_ahead(t, view)
        mon = self.team[self.active]
        if self.decision != FAST and self.decided_for != self.active:
            # decided for the one that was out (2026-11-08: Shadow Ball chosen for Jellicent, the switch to
            # Stunfisk seen 0.2 s later, and Stunfisk's Discharge tapped with no energy)
            self.log("decision_dropped", t, was=self.name(self.decision), why="active changed")
            self.decision, self.armed = FAST, None
        if self.slow_pause is not None:
            slot, until, read0, since = self.slow_pause
            e = self.energy()
            bounds = self.paid_bounds()
            # risen by the reading, or a step down of their bar since the pause began (2026-11-23, 232848: the hit at
            # 83.7 s ignored as a flame's, the reading 27.8 to 36.9, short of half a move by 0.9: 3 s with no taps)
            step = max(getattr(self, "my_hit_at", None) or -1.0, getattr(self, "my_step_at", None) or -1.0)
            rose = (e is not None and e >= read0 + 0.5 * mon.fast.energy_gain) or (
                step >= 0 and self.t0 is not None and self.t0 + step > since)
            paid = bounds is not None and any(bounds[0] >= m.energy > read0 for m in mon.charged)
            why = ("switch" if slot != self.active or self.switching is not None else "decided" if self.decision != FAST
                   else "rose" if rose else "paid" if paid else "time" if time.time() > until else None)
            if why is not None:
                self.log("slow_pause_end", t, why=why, read=e, waited=round(time.time() - since, 2))
                self.slow_pause = None
                self.hold_ended_at = time.time()
                if why in ("rose", "paid"):  # a fast tap now could start the next Incinerate before the engine throws
                    self.pause_hold_until = time.time() + 0.6
        if self.unsure_hold is not None:
            slot, until, since = self.unsure_hold
            sure_now = self.energy() is not None or self.paid_bounds() is not None
            landed = getattr(self, "my_hit_at", None) is not None and self.t0 is not None and self.t0 + self.my_hit_at > since
            why = ("switch" if slot != self.active or self.switching is not None else "fast" if self.decision == FAST
                   else "read" if sure_now else "landed" if landed else "time" if time.time() > until else None)
            if why is not None:
                self.log("unsure_hold_end", t, why=why, waited=round(time.time() - since, 2))
                self.unsure_hold = None
                self.hold_ended_at = time.time()
        if self.armed is not None:
            k, until = self.armed
            e = self.energy()
            # The fast move under way has landed (the reading rose by half a fast move's energy or more) and the move
            # is still not paid for: the taps go on at once, not at the hold's end (2026-11-09: with Poison Sting
            # 12 holds of 17 ran out, 1.6 to 1.8 s of no fast taps each; those that paid threw within 0.34 s)
            rose = e is not None and e >= self.armed_read + 0.5 * mon.fast.energy_gain and e < mon.charged[k].energy
            # Not on a step of their bar: Incinerate's flames step it before the hit, and the reading lags the move
            # becoming paid; ended on them, the taps went on 0.3 to 0.7 s before Torch Song lit (2026-11-23, 234155)
            if time.time() > until or self.switching is not None or rose:
                self.log("armed_expired", t, move=mon.charged[k].id, read=e, rose=rose)
                self.armed = None
                self.hold_ended_at = time.time()
                self.decision = FAST
            else:
                self.decision = CHARGED[0] + k
        # Our energy as the buttons show it. In a fight they are always on screen, so unread buttons mostly mean no
        # fight (a close-up): no throw then. Only if they have been unread for 8 s of fighting (the reader failing,
        # say on a bright daytime map) does the count stand in.
        # Our energy: the buttons' reading; else the count (the last reading plus our hits seen landing on their bar
        # since, so it does not run on in close-ups); never less than the names under the buttons show paid for
        # (2026-11-08: Jellicent reached 53 at 4% health, the buttons flashed, the stale reading said 40, and it
        # fainted before its throw went in).
        have = self.energy()
        bounds = self.paid_bounds()
        counted = self.tracker.me.mon.energy if self.tracker.foe is not None else 0
        if have is None:
            have = counted
        if bounds is not None:
            have = max(have, bounds[0])
        if view is not None and (self.decision == FAST or self.armed is not None):
            # Never faint with a charged move in hand (the owner, 2026-11-07): when our health is low and a move is
            # paid for, throw the hardest-hitting one now, whatever the engine planned.
            recent = sorted(v for at, v in self.my_bar_seen if t - at < 0.4)
            hp_share = recent[len(recent) // 2] if len(recent) >= 3 else view.me.mon.hp / view.me.mon.build.hp
            affordable = [k for k, m in enumerate(mon.charged) if have >= m.energy]
            if hp_share < 0.35 and affordable and self.better_soon(t, view, mon, have, affordable, hp_share):
                pass  # the engine decides: a far better move is a few fast moves away and we live to throw it
            elif hp_share < 0.35 and affordable and not self.farm_down(view, mon, have, t, self.hardest(view, mon, affordable)):
                k = mon.charged.index(self.hardest(view, mon, affordable))
                self.decision = CHARGED[0] + k
                self.armed = None
                self.decided_for = self.active
                self.log("throw_before_fainting", t, move=mon.charged[k].id, hp=hp_share, view=view_record(view))
            elif (affordable and view.me.shields == 0 and self.tracker.foe is not None
                  and not self.farm_down(view, mon, have, t, self.hardest(view, mon, affordable))):
                # The owner, 2026-11-08 (Stunfisk held Discharge and Mud Bomb with no shields left, took Kabutops's
                # Water Pulse, and fainted with both): with no shield to block it, when they can throw a charged
                # move that would hurt (a third of our health or more), throw ours first.
                from pogo.battle import damage
                foe = self.tracker.foe
                ready = [m for m in foe.mon.build.charged if foe.hi + foe_margin(foe.mon.build.fast) >= m.energy]
                hurt = max((damage(foe.mon, m, view.me.mon) for m in ready), default=0)
                k = max(affordable, key=lambda j: damage(view.me.mon, mon.charged[j], view.foe))
                # Worth its energy: half the damage per energy of our best charged move or more, unless theirs would
                # knock us out (2026-11-09: Snorlax on 172 of 192 threw Body Slam, 20 damage, into Skeledirge, whose
                # Torch Song does 65, where Earthquake 25 energy later did 122; the owner: "you should be throwing
                # earthquake on the skeledirge")
                per = lambda m: damage(view.me.mon, m, view.foe) / m.energy
                worth = per(mon.charged[k]) >= 0.5 * max(per(m) for m in mon.charged)
                if hurt >= view.me.mon.hp or (hurt >= 0.33 * view.me.mon.build.hp and worth):
                    self.decision = CHARGED[0] + k
                    self.armed = None
                    self.decided_for = self.active
                    self.log("throw_before_theirs", t, move=mon.charged[k].id, foe_energy=[foe.lo, foe.hi], hurt=hurt,
                             view=view_record(view))
        if (view is not None and self.decision in CHARGED
                and self.farm_down(view, mon, have, t, mon.charged[self.decision - CHARGED[0]])):
            if time.time() - self.farm_logged > 1.0:
                self.log("farm_down", t, held=mon.charged[self.decision - CHARGED[0]].id, foe_hp=view.foe.hp)
                self.farm_logged = time.time()
            self.decision, self.armed = FAST, None
        if view is not None and self.switching is None and self.switch_wanted is None:
            slot = self.save_the_low_one(t, view, mon, have)
            if slot is not None:
                self.switch_wanted, self.decision, self.armed = slot, SWITCH[0] + slot, None
        if self.switching is not None:
            return  # which of ours is out is not settled: no charged tap until it is
        if self.decision in CHARGED and self.practise:
            # training: when the engine throws, the one that knows the practised move throws it instead (2026-11-08:
            # Jellicent threw Shadow Ball every time and Ice Beam's minigame was never seen)
            mine = [j for j, m in enumerate(mon.charged) if m.id in self.practise]
            p = min(mine, key=lambda j: (self.practised.get(mon.charged[j].id, 0), j)) if mine else None
            if p is not None and p != self.decision - CHARGED[0]:
                if time.time() - self.practise_logged > 1.0:
                    self.log("practise", t, was=mon.charged[self.decision - CHARGED[0]].id, now=mon.charged[p].id)
                    self.practise_logged = time.time()
                self.decision = CHARGED[0] + p
                if self.armed is not None:
                    self.armed = (p, self.armed[1])
        if self.decision in CHARGED:
            k = self.decision - CHARGED[0]
            # On the count alone (the buttons unread) a throw that came to nothing is not tried again for 3 s: each
            # try stops the fast moves for up to 2.4 s (2026-11-07: 16 tries in one battle, 12 for low health).
            # With no reading, the names under the buttons showing it paid for, or the count a fast move clear of the
            # cost: on the count alone at the cost, 9 of a battle's throws were not taken (2026-11-08, by day, when
            # the buttons read on a quarter of the frames), each stopping the fast taps for up to 3 s.
            cost = mon.charged[self.decision - CHARGED[0]].energy
            # On the count alone only when the buttons have gone unread 4 s (the reader failing), or ours is low
            # and waiting could mean fainting with the energy: tapped on the count, 6 of 9 throws were not taken
            # even after the count's fix (2026-11-09, 124910-130030; on a reading 1 of 24), a reading comes every
            # second or so, and each wrong tap stops the fast taps for the 2.3 s wait.
            stale = t - max(self.last_reading_t, self.active_changed_at) >= 4.0
            urgent = view is not None and self.hp_now(t, view) < 0.35
            # Or far over the cost: after the count's fix, count-only taps not taken were 4 to 31 over it, and one
            # held back at 43 over (134115: Snorlax on 83 to 91 for Body Slam's 40, the reading 90) let Lapras's
            # Sparkling Aria go first.
            sure = self.energy() is not None or (bounds is not None and bounds[0] >= cost) or (
                time.time() - self.last_not_taken > 3.0 and have >= cost + mon.fast.energy_gain
                and (stale or urgent or have >= cost + 40))
            if self.armed is not None:
                # armed: on the buttons' word only (the count runs ahead of them), the moment the button lights
                read = self.energy()
                sure = ((read is not None and read >= mon.charged[k].energy)
                        or (bounds is not None and bounds[0] >= mon.charged[k].energy))
            if have >= mon.charged[k].energy and sure:
                if self.armed is not None:
                    self.log("armed_fired", t, move=mon.charged[k].id, read=self.energy(),
                             waited=round(time.time() - self.armed_at, 2))
                self.armed = None
                # on the count alone: no reading and no name under the buttons saying it is paid for
                count_only = self.energy() is None and not (bounds is not None and bounds[0] >= mon.charged[k].energy)
                self.throw(t, k, mon.charged[k], count_only=count_only, stick=urgent)
                self.decision = FAST
                return
            if (mon.fast.turns >= SLOW_FAST_TURNS and have >= mon.charged[k].energy and self.unsure_hold is None
                    and self.armed is None and self.last_fast_tap > self.hold_ended_at
                    and time.time() - self.last_fast_tap < 0.6):
                # A throw decided on the count, the buttons not read yet: a fast tap now would put a whole Incinerate
                # before it (2026-11-22, 172017: Torch Song decided at 30.6 s with no reading, the taps went on 2 s
                # until one came, and the throw went 2.5 s after its tap). No fast taps until the buttons read, our
                # move lands, or one fast move's time.
                self.unsure_hold = (self.active, time.time() + mon.fast.turns * 0.5 + 0.3, time.time())
                self.tapping = False
                self.log("unsure_hold", t, move=mon.charged[k].id, have=have)
        # Not before 1.5 s: until then "GO!" is on the screen and the game takes no switch (2026-11-08: the opening
        # switch to Stunfisk at 0.8 s and 0.97 s was ignored both times).
        if self.open_with is not None and (self.open_with == self.active or self.tracker.me.team[self.open_with].hp <= 0):
            self.open_with = None  # out already, or fainted: the engine's switches stand
        if self.open_with is not None and self.decision in SWITCH:
            # training: the opening switch is to the one asked for (2026-11-08: the engine's switch to Umbreon at 1.1 s
            # went in instead of Gengar's, in 3 battles of 6)
            self.decision = SWITCH[0] + self.open_with
        if self.stay and self.open_with is None and self.decision in SWITCH:
            # training only (--stay): no switch but the opening one, so the one out throws its practised move
            # (2026-11-09: the engine switched Clodsire out at 2.9 s and Stone Edge was never thrown)
            self.decision, self.switch_wanted = FAST, None
        if self.decision in SWITCH and self.switch_wanted is None and (t < 1.5 or self.switching is not None):
            self.switch_wanted = self.decision - SWITCH[0]
        if self.switch_wanted is not None and self.switching is None and self.decision == FAST and t >= 1.5:
            self.decision = SWITCH[0] + self.switch_wanted  # still wanted: tap it now
        if getattr(self, "replace_unconfirmed", False) and (self.header_says() == self.active
                                                            or time.time() - self.replace_tapped > 8.0):
            self.replace_unconfirmed = False  # the header names who is in (the loop corrects self.active by it)
        if self.decision in SWITCH and time.time() >= self.switch_ready_at and t >= 1.5 \
                and not getattr(self, "replace_unconfirmed", False):
            slot = self.decision - SWITCH[0]
            order = [j for j in range(len(self.team)) if j != self.active and self.tracker.me.team[j].hp > 0]
            if slot not in order:
                self.switch_wanted = None
            if slot in order and rgb is not None:
                before = screen.bench_strip(rgb)
                self.clear_of_fast_taps()
                self.touch(BENCH[order.index(slot)], f"switch to {self.team[slot].name}")
                if slot == self.open_with:
                    self.open_with = None
                self.switch_wanted = None
                self.switching = (slot, time.time(), before, None, 0)  # self.active changes once it is seen
                self.switch_tapped_to = slot
                self.tracker.my_switch_tapped(t)
                self.switch_point, self.switch_last_tap = BENCH[order.index(slot)], time.time()
                self.switch_fight_s, self.switch_fight_last = 0.0, time.time()  # fight time since the tap (check_switch)
                # A switch, like a charged move, waits for the fast move under way to end, and a fast tap after it
                # takes its place (2026-11-08: Stunfisk's portrait tapped at 6.6 s, fast taps every 0.15 s after, no
                # switch). No fast taps for 1.6 s: the longest of our fast moves is 1.5 s.
                self.hold_taps_until = time.time() + 1.6
                self.decision = FAST
                return
        # fast moves: the tapping thread, while self.tapping

    def better_soon(self, t: float, view, mon, have: float, affordable: list, hp_share: float) -> bool:
        """Low on health with a move paid for: is a far better move (a knock-out, or 2.5 times the damage) only a few
        of our fast moves away, with their fast moves (one more for safety) leaving us alive till then, and no charged
        move of theirs paid for now while we have no shield? The owner, 2026-11-08: "we should have thrown bulldoze
        into the arcanine" (Vigoroth at 20% threw Body Slam, 38 damage and resisted, into Hisuian Arcanine; Bulldoze,
        five Scratches away, did 156 to its 129, and Snarl takes 3% a hit)."""
        from pogo.battle import damage
        foe = self.tracker.foe
        if foe is None:
            return False
        them, us = foe.mon, view.me.mon
        now = max(damage(us, mon.charged[j], them) for j in affordable)
        if now >= them.hp:
            return False  # the move in hand knocks them out already (docs/status.md, 2026-11-09 night: 230322 and
            # 230719, Body Slam held on a 22 HP Ninetales and Night Slash on a 24 HP Toxicroak, waiting for more)
        hp = hp_share * us.build.hp
        if view.me.shields == 0 and any(foe.hi >= m.energy and damage(them, m, us) >= hp for m in them.build.charged):
            return False  # they can knock us out with a charged move as it stands: throw ours first
        hit = damage(them, them.build.fast, us)
        for j, m in enumerate(mon.charged):
            if j in affordable:
                continue
            more = math.ceil(max(0.0, m.energy - have) / mon.fast.energy_gain)
            turns = more * mon.fast.turns
            # their hits until the bigger move is registered: our fast moves to pay for it, then the delay from our tap
            # to the game having the throw (docs/status.md 2026-11-18: Get Ready! 0.8 to 0.9 s after the tap with our
            # own fast move over, two turns), in place of the one hit added for safety
            hits = math.ceil((turns + THROW_DELAY_TURNS) / them.build.fast.turns)
            big = damage(us, m, them)
            # and no charged move of theirs reached meanwhile by the energy their fast moves bring (the same entry:
            # the check counted their fast moves' damage only; Mud Bomb, reached during the wait, took our last
            # shield): it costs a shield, or us
            reach = foe.hi + hits * them.build.fast.energy_gain
            if any(reach >= c.energy for c in them.build.charged):
                continue
            if (big >= them.hp or big >= 2.5 * now) and hits * hit < hp:
                self.log("waiting_for_better", t, move=m.id, now=now, then=big, fast_moves=more, their_hits=hits,
                         hp=round(hp, 1))
                return True
        return False

    def hp_now(self, t: float, view) -> float:
        """Our health as a share: the median of the bar's last readings, else the tracker's."""
        recent = sorted(v for at, v in self.my_bar_seen if t - at < 0.4)
        return recent[len(recent) // 2] if len(recent) >= 3 else view.me.mon.hp / view.me.mon.build.hp

    def hardest(self, view, mon, affordable: list):
        """Of the charged moves we can pay for, the one that hits their Pokémon hardest."""
        from pogo.battle import damage
        return mon.charged[max(affordable, key=lambda j: damage(view.me.mon, mon.charged[j], view.foe))]

    def farm_down(self, view, mon, have: float, t: float, move) -> bool:
        """Their Pokémon is three or fewer of our fast moves from fainting and ours outlives that, their fast moves
        and any charged move they could reach meanwhile included: farm it down and keep the energy (the owner,
        2026-11-08: Stunfisk threw Discharge into a Talonflame on 5% that three Thunder Shocks would have finished,
        Incinerate being resisted). Not when the throw costs nothing we need (energy for another charged move after
        it), not with a fast move that barely scratches it, and not for longer than the fast moves should take
        (2026-11-08, 204007: Jellicent held Surf for 17 s at 98 energy, the cap, against an Obstagoon on 1 to 5% that
        Hex, resisted twice, could not finish, and took a Night Slash)."""
        from pogo.battle import damage
        foe, me = view.foe, view.me.mon
        if foe is None or foe.hp <= 0 or self.tracker.foe is None:
            return False
        if have - move.energy >= min(m.energy for m in mon.charged):
            return False  # another charged move is paid for after this one: throwing keeps nothing back
        hit = damage(me, mon.fast, foe)
        if hit <= 0 or hit < 0.02 * foe.build.hp:
            return False  # our fast move barely scratches it
        n = -(-foe.hp // hit)  # our fast moves to finish it
        if n > 3:
            return False
        sid = foe.build.species_id
        if self.farm_for != sid:
            self.farm_for, self.farm_since = sid, t
        if t - self.farm_since > n * mon.fast.turns * 0.5 + 2.0:
            return False  # it should have fallen by now: the reading or the damage is off, so throw
        theirs = foe.build.fast
        landing = -(-(n * mon.fast.turns) // theirs.turns)  # their fast moves that can land meanwhile, at most
        incoming = landing * damage(foe, theirs, me)
        # Their energy: the top of the count plus one fast move. The count runs about a fast move behind at the moment
        # they throw (2026-11-22, 138 named throws of theirs in Ultra League: the top short of the move 36 times, by
        # more than one fast move 17); the bottom of the range, used here before, held Shadow Ball on Darmanitan at
        # 24 to 27 with Rock Slide (45) "out of reach" at 42, and it came.
        hi = self.tracker.foe.hi + (landing + 1) * theirs.energy_gain
        ready = [m for m in foe.build.charged if m.energy <= hi]
        if time.time() - self.farm_checked > 1.0:
            self.farm_checked = time.time()
            self.log("farm_down_check", self.now(), foe=foe.build.species_id, foe_hp=foe.hp, hit=hit, n=n,
                     incoming=incoming, our_hp=me.hp, their_energy_top=hi, ready=[m.id for m in ready],
                     shields=view.me.shields)
        if ready:
            # A charged move of theirs within reach before it falls: not farmed, whatever our shields. With a shield
            # up this used to farm, the shield taken to cover it (2026-11-22: 23 holds; in 10 they threw first, 9 of
            # them with the move already counted in reach: 5 shields spent, 5 hits taken, one of ours fainted with
            # Torch Song paid for).
            return False
        return incoming < me.hp

    def save_the_low_one(self, t: float, view, mon, have: float):
        """Their new Pokémon has just come in, ours is nearly out with no charged move near, and the switch is
        free: the healthy one of ours that does best against it, so this one is kept for later, to take a charged
        move (the owner, 2026-11-08: Stunfisk at 4% stayed in against a fresh Lickilicky, with Jellicent healthy
        behind it, and fainted farming). The slot to switch to, or None."""
        foe = self.tracker.foe
        sid = foe.mon.build.species_id if foe is not None else None
        if sid != self.foe_sid:
            self.foe_sid, self.foe_since = sid, t
        if sid is None or sid == self.saved_for or t - self.foe_since > 5.0:
            return None
        hp = self.hp_now(t, view)
        if hp >= 0.25:
            return None
        healthy = [j for j in view.me.bench() if view.me.team[j].hp > 0.5 * view.me.team[j].build.hp]
        why = ("the switch timer" if time.time() < self.switch_ready_at or view.me.switch_wait > 0 else
               "a charged move is near" if have + 2 * mon.fast.energy_gain >= min(m.energy for m in mon.charged) else
               "no healthy one on the bench" if not healthy else None)
        if why:
            if self.save_checked != sid:
                self.save_checked = sid
                self.log("save_the_low_one_not", t, against=sid, why=why, hp=round(hp, 3), energy=round(have, 1),
                         switch_in_s=round(self.switch_ready_at - time.time(), 1), switch_wait=view.me.switch_wait)
            return None
        from pogo.agents import duel
        best = max(healthy, key=lambda j: duel(view.me.team[j], view.foe, view.me.shields, view.foe_shields, coming_in=True))
        self.saved_for = sid
        self.log("save_the_low_one", t, out=self.team[self.active].name, to=self.team[best].name, against=sid,
                 hp=round(self.hp_now(t, view), 3), energy=round(have, 1))
        return best

    def no_weaker_move(self, t: float, view) -> None:
        """The engine's charged move, unless another we can pay for costs no more and hits harder: then that one
        (2026-11-08, the owner: "why are we throwing mud bombs at a ninjask?": with 45 energy the engine chose Mud
        Bomb, 15 damage to Ninjask, over Discharge, 79 and cheaper; it did so at any thinking time). Moves that raise
        or lower stats are left to the engine."""
        if self.decision not in CHARGED or self.tracker.foe is None:
            return
        from pogo.battle import damage
        mon = self.team[self.active]
        k = self.decision - CHARGED[0]
        if k >= len(mon.charged) or getattr(mon.charged[k], "buff_chance", 0):
            return
        have = self.energy()
        bounds = self.paid_bounds()
        have = max(have if have is not None else self.tracker.me.mon.energy, bounds[0] if bounds else 0)
        hit = {j: damage(view.me.mon, m, view.foe) for j, m in enumerate(mon.charged) if have >= m.energy}
        better = [j for j in hit if j != k and mon.charged[j].energy <= mon.charged[k].energy
                  and hit[j] > hit.get(k, damage(view.me.mon, mon.charged[k], view.foe))]
        if better:
            j = max(better, key=hit.get)
            self.log("move_dominated", t, chose=mon.charged[k].id, now=mon.charged[j].id,
                     damage=[hit.get(k), hit[j]])
            self.decision = CHARGED[0] + j

    def owner_prefers(self, t: float, view) -> None:
        """The owner's rule (2026-11-22, after Blastoise threw Skull Bash at Cresselia with Hydro Cannon paid for:
        "shouldnt we just throw hc unless its not very effective?"): the team file's preferred move, when paid for,
        in place of the engine's other charged move, unless it is not very effective on the one out. The engine's
        trained bot (Great League) chose Skull Bash 6 times in 6 there; its search rated Hydro Cannon higher, by less
        than the 0.03 it needs to overrule the bot."""
        from pogo.gamedata import effectiveness
        if self.decision not in CHARGED or self.tracker.foe is None:
            return
        mon = self.team[self.active]
        want = PREFER.get(mon.species_id)
        k = self.decision - CHARGED[0]
        if want is None or k >= len(mon.charged) or mon.charged[k].id == want:
            return
        have = self.energy()
        bounds = self.paid_bounds()
        have = max(have if have is not None else self.tracker.me.mon.energy, bounds[0] if bounds else 0)
        j = next((i for i, m in enumerate(mon.charged) if m.id == want), None)
        if j is None or have < mon.charged[j].energy or effectiveness(mon.charged[j].type, view.foe.build.types) < 1.0:
            return
        self.log("owner_prefers", t, chose=mon.charged[k].id, now=want, foe=view.foe.build.species_id)
        self.decision = CHARGED[0] + j

    def countdown_is_theirs(self) -> bool:
        """The countdown disc is told to the tracker as their throw only with no shield of ours left (a throw of theirs
        otherwise brings the prompt) and no throw of ours in the last 18 s: the same disc is up while they choose
        whether to shield ours. 2026-11-22: of 62 countdowns, 57 had no move of theirs named after, nearly all within
        13 s of our minigame, and each put their energy at nothing (Galarian Moltres from 42 to 0 at 85 s, after our
        Torch Song; its Payback, 60, came at 90 s with the count at 21). The one this keeps was a real throw."""
        now = time.time()
        return (not self.pending_theirs and now - max(self.prompt_seen, self.their_throw_at) > 10.0
                and self.tracker.me.shields == 0 and now - self.my_throw_at > 18.0)

    def foe_name_new(self) -> bool:
        """Their name has been read as another Pokémon since the tracker was last told."""
        return self.names.species is not None and self.names.species != self.foe_seen_species

    def foe_now(self, t: float, why: str) -> bool:
        """Hand a new name of theirs to the tracker now, between looks (Tracker.their_active_seen). 2026-11-22: 7 of 154
        changes of theirs were read before a charged move and reached the tracker only at the look after it, 7 to
        11 s on; meanwhile throws of ours went at the newcomer (Leaf Blade at Giratina, meant for Swampert), its hits
        were put to the one gone (Luxray's fast move "learned" from Magnezone's Sparks), and Talonflame's Flame Charge
        was met with Florges's count of 0. True when it changed."""
        if not self.foe_name_new() or self.tracker.foe is None:
            return False
        sp, at = self.names.species, self.names.read_at
        was = self.tracker.foe.mon.build.species_id
        out_for = max(0.0, t - at) if at is not None else None
        self.foe_seen_species = sp
        try:
            how = self.tracker.their_active_seen(t, sp, out_for)
        except Exception as error:  # noqa: BLE001 - a bad reading must not stop the battle
            self.log("tracker_error", t, error=str(error))
            return False
        self.log("foe_changed_between_looks", t, was=was, now=sp, how=how, why=why,
                 out_for=None if out_for is None else round(out_for, 2))
        return True

    @contextlib.contextmanager
    def at_their_throw(self, margin: int = 0):
        """Within it the tracker shows their energy as they throw (Tracker.their_energy_at_throw): the count at the
        last look, the fast move under way counted (a charged move goes only once it has ended), and the fast moves of
        the fight seen since that look, up to the last frame showing it. Replaying 2026-11-22, the count at the prompt
        was short of the move named at 18 of 91 throws (7 by more than a fast move); this way at 3 (1). The prompt's
        call has no margin added, so those went straight into shield calls."""
        foe = self.tracker.foe
        kept = (foe.mon.energy, foe.lo, foe.hi) if foe is not None else None
        try:
            if foe is not None:
                lo, hi = self.tracker.their_energy_at_throw(max(0.0, self.fight_frame_t - self.last_look))
                hi = min(100, hi + (foe_margin(foe.mon.build.fast) if margin else 0))
                foe.mon.energy, foe.lo, foe.hi = min(100, foe.mon.energy + hi - foe.hi), lo, hi
            yield
        finally:
            if kept is not None:
                foe.mon.energy, foe.lo, foe.hi = kept

    @contextlib.contextmanager
    def engine_sees(self):
        """Within it the tracker shows the engine their energy foe_margin() higher, and ours at least what
        the names under the buttons show paid for; both are put back after."""
        me, foe = self.tracker.me.mon, self.tracker.foe
        kept = (me.energy, foe.mon.energy, foe.lo, foe.hi) if foe is not None else (me.energy,)
        try:
            bounds = self.paid_bounds()
            if bounds is not None:
                me.energy = max(me.energy, bounds[0])
            if foe is not None:
                extra = foe_margin(foe.mon.build.fast)
                foe.mon.energy, foe.lo, foe.hi = (min(100, x + extra) for x in (foe.mon.energy, foe.lo, foe.hi))
            yield
        finally:
            me.energy = kept[0]
            if foe is not None:
                foe.mon.energy, foe.lo, foe.hi = kept[1:]

    def look_ahead(self, t: float, view) -> None:
        """Would the engine throw once the fast moves under way have paid for it? Then stop queuing more and throw
        the moment the button lights. Our energy rises as each fast move lands (the button lights then), and by
        then the fast taps have already queued the next one, which a charged tap cannot cut short: every throw went
        one fast move late (the owner, 2026-11-08: "you did 3 than threw ... given thundershock is a 2 turn move,
        you should've done two thundershocks than thrown"). Only for a move that the fast move under way pays for: a
        fast tap made during a move is not kept for after it (2026-11-08, battle 11: armed two moves ahead with one
        last tap, Jellicent's energy then stood at 37.6 for 3.6 s, twice), so the taps go on until the paying one."""
        mon = self.team[self.active]
        have = self.energy()
        bounds = self.paid_bounds()
        slow = mon.fast.turns >= SLOW_FAST_TURNS
        # Never again without a fast tap since the last hold ended, and only with one just made (a move in flight):
        # armed with none, Skeledirge stood 3 s for an Incinerate never begun and was armed again at once, from 60
        # to 66 s and on (2026-11-22, 170719)
        if self.last_fast_tap <= self.hold_ended_at or time.time() - self.last_fast_tap > (0.6 if slow else 1.0):
            return
        # A long fast move: nor before a fast tap a turn after the reading last moved or came back. The taps before
        # it were made during the move that has just landed, or before the fight was back, and none of them starts
        # the next one. Armed at the very reading that showed Incinerate landing, Skeledirge stood 2.9 s with no move
        # under way (2026-11-23, 235319, 70.8 s: 18 to 37, the buttons at 37 until the hold ran out); at 83.6 s, one
        # tap 0.1 s after the buttons came back from Hydro Cannon's close-up. Short fast moves land too often for this.
        if slow and self.last_fast_tap < self.reading_new_at + 0.5:
            return
        # The count stands in only with the buttons read in the last 1.5 s: with none since a charged move (the
        # fight not back, taps not taken), the count held the taps 3.5 s for a move never begun (2026-11-23, 232848,
        # 92.8 to 96.3 s, after Giratina's Ominous Wind)
        read_lately = self.energy_read is not None and time.time() - self.energy_read[1] < 1.5
        if have is None and slow and self.tracker.foe is not None and read_lately:
            # long fast moves: the count stands in (the buttons gave a reading on 1 frame in 10 for Skeledirge, and a
            # tap during the paying Incinerate costs 2.5 s); with the hits it counts debounced (watch_hits)
            have = float(self.tracker.me.mon.energy)
        if have is None:
            if self.tracker.me.mon.energy + mon.fast.energy_gain >= min(m.energy for m in mon.charged) > self.tracker.me.mon.energy:
                self.log("ahead_not_armed", t, read=None, counted=self.tracker.me.mon.energy)
            return  # only on the buttons' reading: the count can run a fast move or two ahead
        if bounds is not None:
            have = max(have, bounds[0])
        gain = mon.fast.energy_gain
        soon = min(100.0, have + gain)
        if not any(have < m.energy <= soon for m in mon.charged):
            return
        me = self.tracker.me.mon
        kept, cap = me.energy, self.engine.cap_ms
        me.energy, self.engine.cap_ms = int(soon), min(cap, 150)
        try:
            with self.engine_sees():
                ahead = self.engine.act(self.view())
                self.engine_calls += 1
        except Exception as error:  # noqa: BLE001
            self.log("engine_error", t, error=str(error), ahead=True)
            return
        finally:
            me.energy, self.engine.cap_ms = kept, cap
        if ahead not in CHARGED:
            self.log("ahead_not_armed", t, read=round(have, 1), soon=round(soon, 1), answer=self.name(ahead))
            self.slow_pause_for(t, mon, have, soon)
            return
        k = ahead - CHARGED[0]
        if not have < mon.charged[k].energy <= soon:
            self.log("ahead_not_armed", t, read=round(have, 1), soon=round(soon, 1), answer=self.name(ahead))
            self.slow_pause_for(t, mon, have, soon)
            return  # paid for already: the usual way
        # the move under way and a little: if the button has not lit by then, the fast taps go on
        self.armed = (k, time.time() + mon.fast.turns * 0.5 + 0.3)
        self.armed_at, self.armed_read = time.time(), have
        self.tapping = False
        self.log("armed", t, move=mon.charged[k].id, read=round(have, 1), soon=round(soon, 1),
                 since_new=round(time.time() - self.reading_new_at, 2),
                 tap_after_new=round(self.last_fast_tap - self.reading_new_at, 2))

    def slow_paid_wait(self) -> bool:
        """A long fast move and a charged move shown paid for (the buttons' reading, or the names under them): a fast
        tap only within 0.35 s of the engine answering 'fast'. With decisions every 0.5 s, the taps between the button
        lighting and the engine's throw started a whole Incinerate first (2026-11-22, 172555: Torch Song paid at
        56.8 s, decided at 57.5 s, fast taps at 57.51 and 57.67, the throw after them; again at 65.4 s)."""
        # Two 'fast' answers in a row on the energy paid, not one: the capped search flips between them, and each
        # 'fast' commits 2.5 s (2026-11-22, 174237: Torch Song paid at 73.7 s, 'fast' at 51 energy, three taps, the
        # throw 0.5 s later went after another Incinerate)
        return self.slow_paid() and (getattr(self, "paid_fast_streak", 0) < 2
                                     or time.time() - getattr(self, "fast_decided_at", 0.0) > 0.35)

    def slow_paid(self) -> bool:
        """A long fast move out and a charged move shown paid for (the buttons' reading or the names under them)."""
        mon = self.team[self.active]
        if mon.fast.turns < SLOW_FAST_TURNS:
            return False
        cheapest = min(m.energy for m in mon.charged)
        e = self.energy()
        bounds = self.paid_bounds()
        return (e is not None and e >= cheapest) or (bounds is not None and bounds[0] >= cheapest)

    def slow_pause_for(self, t: float, mon, have: float, soon: float) -> None:
        """A long fast move (Skeledirge's Incinerate: 5 turns, 2.5 s) under way pays for a charged move and the engine,
        asked ahead, would not throw it: no more fast taps until the button lights, then the engine decides on the
        energy paid. The owner, 2026-11-22: "skeledirge has 2.5s long fast moves so do not over tap". The last tap
        made during a move is the next action, so a fast tap late in the paying Incinerate puts a whole Incinerate
        (2.5 s) before the throw; the engine's answer asked ahead with a capped search flips between the fast move
        and the throw (2026-11-22, 165658: Torch Song at 47.7 energy, 'fast' 9 times and the throw twice in 3 s), so
        the pause does not wait on it. Only with the buttons read and fast taps under way (a move in flight)."""
        if mon.fast.turns < SLOW_FAST_TURNS or self.slow_pause is not None or time.time() - self.last_fast_tap > 0.6:
            return
        if not any(have < m.energy <= soon for m in mon.charged):
            return
        self.slow_pause = (self.active, time.time() + mon.fast.turns * 0.5 + 0.3, have, time.time())
        self.tapping = False
        self.log("slow_pause", t, read=round(have, 1), soon=round(soon, 1))

    def throw(self, t: float, k: int, move, count_only: bool = False, stick: bool = False) -> None:
        """stick: ours is low, so the move goes even if theirs changes before it starts (a look to decide again could
        come too late); otherwise a new name of theirs drops it, and the next look decides on the one out."""
        self.queued = None  # a new tap stands for any move still waiting
        self.practised[move.id] = self.practised.get(move.id, 0) + 1
        # No fast taps from here until the move starts: a tap on the field after the charged tap takes its place
        # in the queue (2026-11-07: Discharge, paid for, tapped four times 0.7 s apart with fast taps between, went
        # off only after the last; most "not taken" throws were this). The loop turns them on again.
        self.tapping = False
        # A paid-for button turns its type's light shade: with the button, that says which move this is, so which
        # of ours is out and which icons its minigame has (2026-11-07: after a switch the game ignored, "Bulldoze"
        # was tapped on Jellicent's Shadow Ball button and the minigame hunted Ground icons).
        rgb = self.phone.frame()[0]
        named = self.label_move(rgb, k)
        far = screen.paid_shades(rgb, k)
        # Only when the button is plainly not our move's colour: a wrong correction would do the harm it is for.
        # Never to another of ours when our header names the one believed out (2026-11-09, 124247: 0.7 s after the
        # header showed the switch to Thievul, its lit Night Slash button was taken for Snorlax's Body Slam, a dark
        # button lit up being near a normal one, and for 10 s Snorlax was believed out)
        header_agrees = self.header_says() == self.active
        if named is not None and named != (self.active, k) and far is not None and far.get(move.type, 99) > 45                 and not (header_agrees and named[0] != self.active):
            slot, j = named
            self.log("move_corrected", t, was=move.id, now=self.team[slot].charged[j].id, button=j + 1)
            self.active, k, move = slot, j, self.team[slot].charged[j]
            self.switching = None
            self.energy_read = self._energy_raw = None
        point = controls.CHARGED_BUTTONS[k]
        self.clear_of_fast_taps()
        now_rgb = self.phone.frame()[0]
        if screen.replace_prompt(now_rgb) or screen.shield_prompt(now_rgb):
            # A prompt came up: a tap at the button would land on it (2026-11-08: Bulldoze tapped as Vigoroth
            # fainted chose Jellicent on the replacement prompt, where Jellicent's portrait sits over the button).
            self.log("throw_cancelled", t, move=move.id, why="prompt")
            return
        if not stick and self.foe_name_new():
            # decided on the one that has gone: the next look (at once, see foe_name_new) decides on the one out
            self.log("throw_cancelled", t, move=move.id, why="their Pokémon changed", now=self.names.species)
            return
        self.touch(point, f"charged move {k + 1}: {move.name}")
        tapped = last_tap = time.time()
        costs = [m.energy for m in self.team[self.active].charged]
        short = 0  # frames in a row on which the buttons say the move is not paid for
        paid_seen, taps_sent = False, 1  # for the log: did the buttons ever say paid for, and taps sent
        # A tapped move waits for the fast move under way to end (1.5 s for Hex). The game says "Get Ready!" when our move starts and "Attack incoming!" for theirs, so the
        # box at the top is read until one shows. Fight bars going missing is not enough (ours hides behind
        # Jellicent often).
        since, last, started = None, 0.0, False
        icon_frames = 0  # frames in a row showing the minigame's icons
        # 3 s (2.3 s for one afternoon: 3 of 10 throws in a battle then started after the wait, 2.4 to 5 s after
        # the tap, and their minigames were found late)
        # 2.3 s on the count alone: of 826 throws started on 11-08 and 11-09, 2 to 8% by fast move came later than
        # that (2.9 s at most), and a late one is still watched for and swiped (watch_queued); a tap the count
        # wrongly said was paid for stopped the fast taps for the whole wait (37 times in 13 battles)
        wait = 2.3 if count_only else 3.0
        off_since = None  # the fight off the screen since (a frame time), with no word of theirs
        while time.time() - tapped < (4.0 if paid_seen else wait):  # paid for: it can start 3 s after the tap
            rgb, when = self.phone.next_frame(last, timeout=0.3)
            if when <= last:
                continue
            last = when
            if not stick and self.foe_name_new():
                # Theirs changed while ours waited (the game takes no move during a switch or a faint, so the taps
                # were not yet taken): no more taps, and fast taps again take the place of any it has. The next look
                # decides on the one out; a move that goes anyway is watched for and swiped (watch_queued), not
                # tapped again. 2026-11-22: Leaf Blade meant for Swampert went at Giratina, Shadow Ball at Magnezone
                # after 3 s of taps through Luxray's switch.
                self.log("throw_dropped", self.now(), move=move.id, why="their Pokémon changed",
                         now=self.names.species, taps=taps_sent, after_tap_s=round(time.time() - tapped, 2))
                self.queued, self.cue_found = (k, move, tapped, time.time() + 40, self.now()), None
                self.queued_retapped = True
                return
            # The top box is read (0.3 to 0.4 s a read) only once the fight is off the screen, as it is within a
            # tenth of a second of Get Ready!; meanwhile every frame gets the quick looks, so a re-tap is on time.
            bars = screen.bars(rgb)
            on = screen.header_visible(rgb) and len(bars) >= 1
            bt = when - (self.t0 or when)
            if self.frame_t is not None and not on:
                self.off_time += max(0.0, bt - self.frame_t)  # the turns while ours waits: the fight, if on screen
            self.frame_t = bt
            if on:  # their fast moves keep landing while ours waits to start (2026-11-08: two went uncounted)
                self.fight_frame_t = bt
                self.watch_hits(bt, bars)
                if not stick:
                    self.names.offer(rgb, bt)  # their name, read in the background: a change drops the move (above)
            if screen.replace_prompt(rgb):  # ours fainted first: the loop answers the prompt
                self.log("throw_fainted", self.now(), move=move.id)
                return
            # both buttons gone: a close-up, ours or theirs (the minigame keeps a health bar up, so `on` can stay true)
            hidden = screen.button_rim(rgb, 0) < 10 and screen.button_rim(rgb, 1) < 10
            said = "theirs" if screen.shield_prompt(rgb) else None if on and not hidden else screen.cue(self.names.ocr, rgb)
            if said == "theirs":
                # Theirs goes first; ours still waits and plays when theirs is over (2026-11-07: a Body Slam went
                # off after Plusle's Discharge, unswiped). The loop watches for its Get Ready!.
                self.log("throw_beaten", self.now(), move=move.id)
                self.queued, self.cue_found = (k, move, tapped, time.time() + 40, self.now()), None
                self.queued_retapped = False
                return
            if said == "mine":
                since, started = when, True
                break
            # The game does not always say Get Ready! (2026-11-22, Spark's Jolteon: three Leaf Blades with their
            # buttons paid for went off 2.5 to 3 s after the tap, the camera panning to the sky with no words, and went
            # unswiped; the minigame screen shows their health bar, so the fight looked on). Both buttons gone and their
            # bar alone for 0.8 s after a paid-for tap, with no prompt and no word of theirs, is our move.
            # ours shows their bar alone; theirs keeps both bars up (2026-11-22 recording: Jolteon's Thunder, 2 s of hidden
            # buttons with both bars, then the shield prompt; our Leaf Blade, only theirs at 0.949 throughout)
            ours_shown = hidden and "theirs" in bars and "mine" not in bars
            off_since = None if not ours_shown or said == "theirs" else (off_since or when)
            if paid_seen and off_since is not None and when - off_since >= 0.8 and time.time() - tapped > 0.5:
                since, started = off_since, True
                self.log("minigame_seen", self.now(), move=move.id, by="buttons gone, their bar alone 0.8 s")
                break
            if time.time() - tapped > 0.3:
                icon_frames = icon_frames + 1 if minigame_on(rgb, move) else 0
                if icon_frames >= 2:
                    since, started = when - first_icon_s(move.id), True
                    self.log("minigame_seen", self.now(), move=move.id, by="icons")
                    break
            # A tap on the button is sometimes not taken although the move is paid for (2026-11-07: Bulldoze at
            # 57 energy of 55, Discharge at 49 of 40, both shown by the buttons): tap again while they say so.
            e = screen.my_energy(rgb, costs) if on else None  # only with the fight on the screen
            named = screen.button_labels(rgb)[k] if on else None  # the name shows: paid for (readable in the flash)
            # Tapped again every 0.2 s while the button is drawn (the owner, 2026-11-18: "spam tap it until it's
            # confirmed"): 27% of the throws that went off had needed a second tap, 0.6 s later, and went off a median
            # 1.87 s after the first against 1.26 s. Only on the button drawn: hidden (a close-up, an animation), a
            # tap there would land on the field as a fast move and take the throw's place; and once the game has the
            # move the buttons go, which ends it. 0.2 s apart: touches within 0.1 s of another are dropped.
            drawn = screen.button_rim(rgb, k) >= 10
            # Not on an old frame, and not with ours low or its bar unread: as ours faints the replacement prompt comes
            # up, and its right card is where the right button is (2026-11-22, the owner's first Ultra League battle:
            # a Body Slam retap 0.05 s before the prompt was seen sent in Feraligatr, not the Virizion chosen)
            safe = time.time() - when < 0.12 and bars.get("mine", 0.0) >= 0.2
            if drawn and safe and time.time() - last_tap > (0.2 if SPAM_CHARGED else 0.6) and (
                    SPAM_CHARGED or (e is not None and e >= move.energy) or named):
                self.touch(point, f"charged move {k + 1} again: {move.name}")
                last_tap = time.time()
                taps_sent += 1
            paid_seen = paid_seen or bool(named) or (e is not None and e >= move.energy)
            short = short + 1 if e is not None and e < move.energy - 3 else 0
            if short >= 3:  # not paid for: no use waiting with the fast moves stopped
                break
        if not started:
            self.last_not_taken = time.time()
            # It may still go off a moment later (2026-11-07: four of 39 moves had Get Ready! up to half a second
            # after the wait, and went unswiped), or after theirs: the loop watches for it.
            self.queued, self.cue_found = (k, move, tapped, time.time() + 40, self.now()), None
            self.queued_retapped = False
            read = self.energy()
            self.log("throw_not_taken", self.now(), move=move.id, counted=self.tracker.me.mon.energy, count_only=count_only,
                     read=None if read is None else round(read, 1), paid_seen=paid_seen, taps=taps_sent)
            self.tracker.me.mon.energy = min(self.tracker.me.mon.energy, move.energy - 1)  # the button says not yet
            self.energy_read = None
            return
        self.pending_mine = k
        self.my_throw_at = time.time()
        self.log("throw_started", self.now(), move=move.id, after_tap_s=round(since - tapped, 2),
                 cue_t=round(since - (self.t0 or since), 3), count_only=count_only)
        self.minigame(k, move, since)

    def label_move(self, rgb, k: int):
        """(team slot, move index) of the move button k shows paid for, by the button's colour
        (pogo.android_screen.paid_type), or None when it cannot be told."""
        kind = screen.paid_type(rgb, k)
        if kind is None or kind == "normal":
            # Normal's grey is a button not lit up as well (2026-11-23: Melmetal's Dynamic Punch read as Blastoise's
            # Skull Bash 3 times in 10 training battles, Blastoise believed out for 10 s each time)
            return None
        hits = [(slot, k) for slot, b in enumerate(self.team) if len(b.charged) > k and b.charged[k].type == kind]
        return hits[0] if len(hits) == 1 else None

    def watch_queued(self, t: float, rgb, when: float, fighting: bool) -> bool:
        """Our move still to start: tapped as theirs came in (it plays when theirs is over), or tapped and not seen
        to start (it can go off just after the wait). Watch the top box for its Get Ready! and swipe it; the box is
        read only while the fight is off the screen (as it is during Get Ready!), at most five times a second, so
        the reading does not hold up the fight. Given up when the fight has been back for 2 s (a move still to go
        goes as soon as it is: 2026-11-07, one waited 20 s behind two Seed Bombs and their shields), when the buttons
        are back showing the move not paid for, or after 40 s. True when its minigame was played."""
        k, move, tapped, deadline, made = self.queued
        e = self.energy()
        # A move still to go would have gone within a couple of seconds of the fight being back (since this watch
        # began) with it paid for.
        # back: the fight with its buttons up (in our minigame the header and our bar stay up, the buttons do not)
        back = self.fight_since is not None and t - max(self.fight_since, made) > 2.0 and t - self.button_seen_t < 0.5
        if time.time() > deadline or back or (e is not None and self.energy_read[1] > tapped + 1.0 and e < move.energy - 5):
            self.log("queued_dropped", t, move=move.id, read=None if e is None else round(e, 1))
            self.queued = None
            return False
        if (fighting and not self.queued_retapped and self.fight_since is not None
                and t - max(self.fight_since, made) > 1.0 and (e is None or e >= move.energy)):
            # Theirs is over and ours has not gone: tap it again (2026-11-08, 231958: Discharge, beaten by their
            # Surf, waited 3.9 s with no fast taps after it, and went 1 s after the next tap)
            self.queued_retapped = True
            self.touch(controls.CHARGED_BUTTONS[k], f"charged move {k + 1} again (queued): {move.name}")
        if time.time() - self.queued_checked < 0.2:
            return False
        found = self.cue_found  # Get Ready! read on the thread below, from a frame with the fight off
        if found is not None and time.time() - found[1] <= 1.5:
            when = found[0]
            self.cue_found = None
        elif fighting:
            # the minigame can start with the header and our bar up and no Get Ready!: its icons say so
            if t - self.button_seen_t < 0.3:
                return False
            self.queued_checked = time.time()
            self.queued_icons = getattr(self, "queued_icons", 0) + 1 if minigame_on(rgb, move) else 0
            if self.queued_icons < 2:
                return False
            self.queued_icons = 0
            when = when - first_icon_s(move.id)
            self.log("minigame_seen", t, move=move.id, by="icons", queued=True)
        else:
            self.queued_checked = time.time()
            # Read on its own thread (0.3 to 0.5 s a read): on the loop it held up the frames, and with the fight
            # taken up only after three frames running, the fast taps came back 1.6 s after the fight did
            # (2026-11-09: after their Thunder Punch, and after a throw the game was slow to start)
            if not self.cue_busy:
                self.cue_busy = True
                frame, at = rgb.copy(), when

                def read():
                    try:
                        if screen.cue(self.names.ocr, frame) == "mine":
                            self.cue_found = (at, time.time())
                    except Exception:  # noqa: BLE001
                        pass
                    finally:
                        self.cue_busy = False
                threading.Thread(target=read, daemon=True).start()
            return False
        self.queued = None
        self.pending_mine = k
        self.my_throw_at = time.time()
        self.log("throw_started", self.now(), move=move.id, after_tap_s=round(when - tapped, 2), queued=True)
        self.minigame(k, move, when)
        return True

    def minigame(self, k: int, move, since: float) -> None:
        """Swipe the minigame of our move that started (Get Ready!) at time `since`."""
        try:
            self._minigame(k, move, since)
        finally:
            self.names_seen = self._names_raw = None  # the names read before the move no longer hold
            self.names_blocked_until = time.time() + 1.5  # its attack plays now, over the buttons

    def _minigame(self, k: int, move, since: float) -> None:
        self.tapping = False
        start, path = swipe_for(move)
        tapped = since  # the minigame is timed from the move itself, not from the tap
        while time.time() - tapped < start - 0.4:
            time.sleep(0.02)
        self.log("swipe", self.now(), move=move.id, type=move.type, points=len(path))
        if self.frames is not None:  # frames of the whole minigame and its outcome, to see how the swipe went
            folder = self.frames / f"minigame-{int(time.time())}-{move.id.lower()}"
            folder.mkdir(parents=True, exist_ok=True)

            def keep():
                from PIL import Image
                while time.time() - tapped < 9.0:
                    Image.fromarray(self.phone.frame()[0]).save(folder / f"{int((time.time() - tapped) * 1000):06d}.jpg", quality=80)
                    time.sleep(0.3)
            threading.Thread(target=keep, daemon=True).start()
        if self.live:
            with self.touch_lock:  # a fast tap under way ends first; none starts during the stroke
                trace = []
                # to 6.6 s after Get Ready! (icons show until 6.25 s; the rating is final by 6.8 s)
                others = {}  # our other moves' types, in case the icons say the minigame is one of theirs
                for b in self.team:
                    for m in b.charged:
                        if m.type != move.type and m.type not in others:
                            others[m.type] = m
                switched = []
                hunted = minigame_stroke(self.phone, seconds=path[-1][0] + 0.9, colour=icon_colour(move.type),
                                         zone=icon_zone(move.type), move_type=move.type, trace=trace,
                                         predicted=choreography(move.id, move.type), ready_at=since, move_id=move.id,
                                         alternatives=list(others.values()), switched=switched)
                if switched:
                    self.log("minigame_type_corrected", self.now(), was=move.id, now=switched[0][0].id,
                             at=switched[0][1], icons=switched[0][2])
            self.log("minigame", self.now(), move=move.id, icons_seen=hunted, trace=trace,
                     **({"swiped_as": switched[0][0].id} if self.live and switched else {}))
        # From Get Ready! to here the fight was off the screen: off-screen time for the turns, and the fight must
        # be seen three frames running again before it counts
        now_t = self.now()
        self.off_time += max(0.0, now_t - (self.frame_t if self.frame_t is not None else now_t))
        self.frame_t = now_t
        self.fight_frames = 0

    def on_shield_prompt(self, t: float, look) -> None:
        if self.prompt_answered and time.time() - self.prompt_seen > 1.5:
            # Gone for 1.5 s and back: their next charged move, not this one fading (2026-11-07: Garbodor's second
            # Seed Bomb in a row went unanswered, its prompt taken for the first's).
            self.prompt_answered = False
            self.log("prompt_again", t)
        self.prompt_seen = time.time()
        if self.prompt_answered:
            # A tap while the prompt is still fading in is ignored (game 6's recording: the prompt stayed up with
            # both shields after our shield tap), so the answer is tapped again until the prompt has gone.
            if time.time() - self.prompt_tapped > 0.4 and time.time() - self.prompt_first < 5.0:
                self.touch(SHIELD_YES if self.prompt_shield else SHIELD_NO, "shield again" if self.prompt_shield else "no shield again")
                self.prompt_tapped = time.time()
            return
        self.prompt_answered = True
        # their name read since the last look is the one throwing: the call is made on it (see foe_now)
        self.foe_now(t, "shield prompt")
        self.pending_theirs = True
        self.their_throw_at = time.time()
        counted = (self.tracker.foe.lo, self.tracker.foe.hi) if self.tracker.foe else None
        with self.at_their_throw(margin=FOE_MARGIN):
            self._prompt_call(t, look, counted)

    def _prompt_call(self, t: float, look, counted) -> None:
        """The shield call at their prompt, made on their energy as they throw (at_their_throw)."""
        view = self.view()
        shield = False
        last = self.replacements >= 2  # we have sent in both replacements: this is our last Pokémon
        if view is not None and view.me.shields > 0:
            # The engine's own call on the tracker's estimate of their energy as they throw (at_their_throw, with
            # FOE_MARGIN since 2026-11-23: with none, 8 of 91 throws came short) and no override (2026-11-08,
            # docs/status.md "Live shield calls measured": the owner withdrew the override that shielded any hit of
            # 35% or more, which cost 7 to 13 points in simulation)
            try:
                shield = bool(self.engine.shield(view, self.tracker.foe.hi))
                self.engine_calls += 1
            except Exception as error:  # noqa: BLE001
                self.log("engine_error", t, error=str(error))
                shield = True
        # The counts as the header showed them before the prompt: on the prompt's own frame the header is dimmed
        # and reads nothing (2026-11-09, 123923: Clodsire, our last, one shield up, took two Aerial Aces and the
        # Liquidation that ended it unshielded, the rule never firing)
        my_left_seen, _, my_sh_seen, _ = self.header_now(look)
        last = last or (my_left_seen is not None and int(my_left_seen) == 1)
        have_shield = (look.my_shields or 0) > 0 or (my_sh_seen is not None and int(my_sh_seen) > 0) or (
            view is not None and view.me.shields > 0)
        if last and have_shield:
            # The engine's own rule: with one Pokémon left there is nothing to save shields for. The tracker can
            # miss that our others have fainted (the header's count lags), so it is applied from our own count.
            shield = True
        seen = None
        if view is not None:
            try:
                seen = view_record(view)  # the view the engine's call was made on, to ask it again (engine_view.py)
            except Exception as error:  # noqa: BLE001
                seen = {"error": str(error)}
        self.log("shield_prompt", t, shield=shield, foe_energy=(self.tracker.foe.lo, self.tracker.foe.hi) if self.tracker.foe else None,
                 view=seen, foe_hi=self.tracker.foe.hi if self.tracker.foe else None, counted=counted)
        self.prompt_shield, self.prompt_tapped = shield, time.time()
        self.prompt_first = self.prompt_tapped  # answers are tapped again for 5 s at most
        if shield:
            self.tracker.my_shield_used()  # the header counts it seconds later
        self.touch(SHIELD_YES if shield else SHIELD_NO, "shield" if shield else "no shield")

    def settled_replacement(self, t: float, view, slot: int, bench: list) -> int:
        """The replacement the engine would not switch away from at once. Its replace search scores 'send in A, then
        switch to B' about as high as 'send in B', so it can pick A and want B a moment later, spending the switch
        (2026-11-22: Virizion sent in against Cobalion, and the engine, asked again 8 times on that view, wanted
        Feraligatr 7 times). So the engine is asked, as it will be once A is in, whether it would switch; if it would,
        to a Pokemon on the bench, that one is sent in instead."""
        try:
            from engine_view import LoggedView
            rec = view_record(view)
            rec["me"]["team"][self.active]["hp"] = 0  # the one that fainted
            rec["me"]["active"] = slot
            after = self.engine.act(LoggedView(self.gd, rec))
            self.engine_calls += 1
        except Exception as error:  # noqa: BLE001
            self.log("engine_error", t, error=f"settled_replacement: {error}")
            return slot
        if after in SWITCH and after - SWITCH[0] in bench and after - SWITCH[0] != slot:
            self.log("replace_changed", t, was=self.team[slot].name, now=self.team[after - SWITCH[0]].name)
            return after - SWITCH[0]
        return slot

    def replace_cards(self, rgb) -> list | None:
        """The replacement prompt's two cards, left to right, as team slots, by the names under them (read once a
        prompt). None unless both are read as two of ours (in training the cards can show nicknames)."""
        if rgb is None:
            return None
        canon = lambda s: "".join(ch for ch in s.upper() if ch.isalpha())
        h, w = rgb.shape[:2]
        crop = rgb[int(0.885 * h):int(0.945 * h), int(0.10 * w):int(0.90 * w)]
        try:
            res, _ = self.names.ocr(crop)
        except Exception:  # noqa: BLE001
            return None
        found = []
        for r in res or []:
            read = canon(r[1])
            slot = next((j for j, b in enumerate(self.team) if read and (canon(b.name) in read or read in canon(b.name))), None)
            if slot is not None:
                found.append(((r[0][0][0] + r[0][1][0]) / 2, slot))
        slots = [j for _, j in sorted(found)]
        return slots if len(slots) == 2 and slots[0] != slots[1] else None

    def on_replace_prompt(self, t: float, look, rgb=None) -> None:
        if self.replaced:
            if self.replace_point and time.time() - self.replace_tapped > 0.5:  # tapped again until the prompt goes
                self.touch(self.replace_point, "send in again")
                self.replace_tapped = time.time()
            return
        self.replaced = True
        # The prompt comes only with two of ours left to choose from (with one, the game sends it in itself): its two
        # cards are the bench, read by their names, and failing that the two not believed out, whatever the tracker
        # had (2026-11-23, 214336, and 2026-11-22, 191734: one of the two put down as fainted, the bot tapped for one
        # card 20 times between the two, and after 12 s the game sent in the one left off: Melmetal into Charizard).
        cards = self.replace_cards(rgb)
        if cards is not None and self.active in cards:
            gone = next(j for j in range(len(self.team)) if j not in cards)
            self.log("replace_active_fixed", t, was=self.team[self.active].name, now=self.team[gone].name)
            self.active = gone  # the one out was the one not on a card
        bench = cards or [j for j in range(len(self.team)) if j != self.active]
        for j in bench:
            if self.tracker.me.team[j].hp <= 0:  # on a card: alive
                self.tracker.me.team[j].hp = max(1, round(0.1 * self.tracker.me.team[j].build.hp))
                self.log("hp_restored", t, who=self.team[j].name, hp=self.tracker.me.team[j].hp, by="replacement card")
        # only a faint brings the prompt: the tracker must not take the change for a switch and start the switch
        # timer (2026-11-08: the counter of Pokémon left lagged, and the engine thought it could not switch for 45 s)
        self.tracker.my_fainted()
        view = self.view()
        slot = bench[0] if bench else None
        if view is not None:
            try:
                slot = self.engine.replace(view)
                self.engine_calls += 1
            except Exception as error:  # noqa: BLE001
                self.log("engine_error", t, error=str(error))
        if slot not in bench and bench:
            slot = bench[0]
        if slot is None:
            return
        if view is not None and len(bench) > 1:
            slot = self.settled_replacement(t, view, slot, bench)
        point = controls.REPLACE_ONE if len(bench) == 1 else controls.REPLACE_TWO[bench.index(slot)]
        self.log("replace", t, to=self.team[slot].name, bench=[self.team[j].name for j in bench])
        self.touch(point, f"send in {self.team[slot].name}")
        self.replace_point, self.replace_tapped = point, time.time()
        # No switch until the header shows who came in: a tap can choose for us (2026-11-22: a charged-move retap
        # chose Feraligatr; believing Virizion in, the bot switched 0.4 s later to 'Feraligatr' and sent Virizion
        # back in, the switch spent)
        self.switch_ready_at = max(self.switch_ready_at, time.time() + 2.5)
        self.replace_unconfirmed = True
        self.tracker.me.team[self.active].hp = 0  # the one that fainted, whatever the header said
        self.active = slot
        self.replacements += 1

    def result(self, rgb, t: float) -> str | None:
        """The result screen's big words, read when the fight has been off the screen for a while. The reading runs
        on its own thread (OCR takes 0.3 to 0.5 s here): read on the loop, it held up the frames, so the fight coming
        back was seen late or not at all (2026-11-08: 20 s of the last Pokémon's fight went unplayed)."""
        if self.result_seen:
            return self.result_seen
        if self.last_fight is None or t - self.last_fight < 2.5 or self.result_busy:
            return None
        self.result_busy = True
        crop = rgb[int(0.40 * rgb.shape[0]):int(0.60 * rgb.shape[0])].copy()

        def read():
            try:
                res, _ = self.names.ocr(crop)
                text = " ".join(r[1] for r in (res or [])).upper()
                self.log("result_check", t, text=text[:80])
                if "WIN" in text:
                    self.result_seen = "win"
                elif "GOOD" in text or "EFFORT" in text:
                    self.result_seen = "loss"
            except Exception:  # noqa: BLE001
                pass
            finally:
                time.sleep(0.3)
                self.result_busy = False
        threading.Thread(target=read, daemon=True).start()
        return None

    def name(self, action) -> str:
        if action == FAST:
            return "fast"
        if action in CHARGED:
            return "charged:" + self.team[self.active].charged[action - CHARGED[0]].id
        if action in SWITCH:
            return "switch:" + self.team[action - SWITCH[0]].species_id
        return str(action)


def git_head():
    """The commit checked out, read from the .git files (no git process: at a battle's start, on OneDrive, `git
    rev-parse` timed out after 30 s twice on 2026-11-09). A worktree's .git is a file naming its git directory."""
    git = ROOT / ".git"
    if git.is_file():
        git = Path(git.read_text(encoding="utf-8").split("gitdir:", 1)[1].strip())
    head = (git / "HEAD").read_text(encoding="utf-8").strip()
    if not head.startswith("ref:"):
        return head
    ref = head.split(":", 1)[1].strip()
    common = git
    if (git / "commondir").exists():
        common = (git / (git / "commondir").read_text(encoding="utf-8").strip()).resolve()
    for base in (git, common):
        if (base / ref).exists():
            return (base / ref).read_text(encoding="utf-8").strip()
    packed = common / "packed-refs"
    if packed.exists():
        for line in packed.read_text(encoding="utf-8").splitlines():
            if line.endswith(" " + ref):
                return line.split()[0]
    return None


def bot_version() -> tuple:
    """(the git commit the bot runs, whether the code or data it runs on had uncommitted changes, an error or None).
    The commit from the .git files; the changes by `git status`, given 20 s (None if it does not answer)."""
    import subprocess
    try:
        head = git_head()
    except Exception as error:  # noqa: BLE001
        return None, None, f"reading .git: {str(error)[:150]}"
    try:
        changed = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--", "pogo", "scripts", "data"],
                                 capture_output=True, text=True, timeout=20).stdout.strip()
        return head, bool(changed), None
    except Exception as error:  # noqa: BLE001
        return head, None, f"git status: {str(error)[:150]}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--serial")
    ap.add_argument("--team", default=str(ROOT / "data" / "alt_team.json"))
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--start-tap", type=float, nargs=2)
    ap.add_argument("--frames")
    ap.add_argument("--max-actions", type=int, default=1500)
    ap.add_argument("--practise", nargs="*", default=[], help="training only: move ids thrown in place of the engine's")
    ap.add_argument("--open-with", help="training only: the species switched in at the start (one rarely out)")
    ap.add_argument("--stay", action="store_true", help="training only: no switches but the opening one")
    # for the record (task 45), from train_loop.py and run_gbl.py: written into the log's start row
    ap.add_argument("--account", help="the account's key (data/accounts/), never a trainer name")
    ap.add_argument("--team-key", help="account/party, as in games/live/our_teams.json")
    ap.add_argument("--league", help="the league as read on screen")
    ap.add_argument("--season", help="the season as read on screen")
    ap.add_argument("--cp", type=int, default=1500, choices=(1500, 2500), help="the league's CP cap: 1500 Great, 2500 Ultra")
    ap.add_argument("--standing", help="rank and rating read just before, as JSON")
    a = ap.parse_args()
    gd = GameData(league=a.cp)  # the engine's opponents and the guessed movesets are the league's
    team = load_team(gd, Path(a.team))
    stamp = time.strftime("%Y%m%d-%H%M%S")
    log = Log(ROOT / "runs" / "live" / f"{stamp}.jsonl")
    record = None
    if a.frames:  # the whole battle's screen, next to the minigame frames (never in git)
        Path(a.frames).mkdir(parents=True, exist_ok=True)
        record = Path(a.frames) / f"battle-{stamp}"
    phone = Android(serial=a.serial, dry_run=not a.live, max_actions=a.max_actions, record=record)
    phone.start()
    player = Player(phone, gd, team, a.live, log, Path(a.frames) if a.frames else None)
    player.practise = set(a.practise)
    player.stay = a.stay
    commit, dirty, version_error = bot_version()
    player.start_info = {"commit": commit, "dirty": dirty, "version_error": version_error,
                         "account": a.account, "team_key": a.team_key,
                         "league": a.league, "season": a.season,
                         "standing": json.loads(a.standing) if a.standing else None}
    if a.open_with:
        player.switch_wanted = player.open_with = next(j for j, b in enumerate(team) if b.species_id == a.open_with)
    log("team", 0.0, team=[(b.species_id, b.fast.id, [m.id for m in b.charged], b.cp) for b in team])
    try:
        if a.start_tap:
            player.touch(tuple(a.start_tap), "start")
            player.start_point, player.start_tapped, player.start_retaps = tuple(a.start_tap), time.time(), 0
        result = player.run()
        log("end", player.now(), result=result, foes=player.tracker.order)
        print(json.dumps({"result": result, "opponents": player.tracker.order, "log": str(log.path),
                          "touches": phone.actions}))
    finally:
        player.done = True
        player.tracker.close()
        phone.close()


if __name__ == "__main__":
    main()
