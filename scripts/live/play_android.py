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
import json
import math
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402

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
TYPE_SWIPE = {"ghost": "dark", "ground": "rock", "dragon": "flying", "psychic": "fairy"}  # types the library lacks


def load_team(gd: GameData, path: Path):
    by_name = {m.name: m.id for m in gd.moves.values()}
    team = []
    for entry in json.loads(path.read_text(encoding="utf-8"))["pokemon"]:
        sid = next(k for k, v in gd.species.items() if v["speciesName"] == entry["species"])
        team.append(gd.build(sid, [by_name[entry["fast"]], *(by_name[m] for m in entry["charged"])]))
    return team


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
               "normal": None}
ICON_ZONE = {"ground": ((0.50, 0.70), (0.31, 0.05)), "water": ((0.86, 0.42), (0.10, 0.11)),
             "electric": ((0.49, 0.58), (0.22, 0.10)), "ghost": ((0.60, 0.71), (0.24, 0.11)),
             "normal": ((0.53, 0.60), (0.29, 0.16))}


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
             "water": (0.05, 0.98, 0.27, 0.90)}
SWEEP_ONLY: set = set()  # types whose icons no detector finds: the predicted ones and the sweep alone


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
        # Normal's grey icons: a grey disc with a white ring symbol in the middle (normal_icons, on a half-size frame,
        # about 23 ms); outlines and grey rings matched Vigoroth's white fur everywhere (2026-11-08)
        from normal_icons import normal_icons
        return [(x, y) for x, y, v in normal_icons(rgb[::2, ::2], scales=(0.8, 1.0, 1.25, 1.6)) if 0.15 < y < 0.95]
    icons = [(x, y) for x, y, r in raw_circles(rgb) if 0.15 < y < 0.92 and ring_matches(rgb, x, y, r, colour, 45)]
    if move_type in COLOUR_BLOBS:
        icons += [(x, y) for x, y, r in minigame.detect_colour(rgb, colour) if 0.045 <= r < 0.17
                  and abs(x - cx) < 2.5 * spx + 0.05 and abs(y - cy) < 2.5 * spy + 0.05]
    return icons


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


def choreography(move_id: str) -> list:
    """The icons a move's minigame is known to show, (t0, t1, x, y, share): seconds after Get Ready!, where, and in
    what share of the recorded minigames (scripts/live/learn_choreography.py, data/minigame/android/<move>.json)."""
    path = ROOT / "data" / "minigame" / "android" / f"{move_id.lower()}.json"
    if not path.exists():
        return []
    return [tuple(x) for x in json.loads(path.read_text(encoding="utf-8"))["icons"]]


def minigame_stroke(phone: Android, seconds: float = 4.6, speed: float = 6.5, colour=None, zone=None,
                    move_type: str = "", trace: list | None = None, predicted: list | None = None,
                    ready_at: float | None = None) -> int:
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
    route = sweep_path(sweep_box(move_type, zone or ((cx, cy), (spx, spy))))
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
    while (now := time.perf_counter()) - start < seconds:
        if now - last_seen >= 0.05:
            last_seen = now
            try:
                rgb = phone.frame()[0]
                if screen.shield_prompt(rgb):
                    phone._send(UP, x, y)
                    return -1
                # Anywhere on screen: a round disc of icon size whose ring is the type's colour (grey for Normal).
                # Water's icons stream right across the screen, over Jellicent's body, which is the same blue but
                # not a disc of that size; Ghost's sit on a Jellicent dark with smoke.
                icons = [] if move_type in SWEEP_ONLY else find_icons(rgb, colour, move_type, zone or ((cx, cy), (spx, spy)))
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
        sx, sy = min(0.995, max(0.02, x)), min(0.90, max(0.15, y))
        if sy < 0.32:  # never near the run button at the top left (it forfeits): pogo.controls.KEEP_OUT, with room
            sx = max(sx, 0.22)
        trail.append((now, sx, sy))
        if trace is not None and (not trace or now - start - trace[-1][0] >= 0.05):
            trace.append((round(now - start, 2), round(sx, 3), round(sy, 3), int(target is not None)))
        controls.Gesture("tap", [(sx, sy)], 0, "minigame stroke").check()
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
        # Their energy from their hits seen landing (counted frame by frame, HitSteps), not from a rhythm that
        # assumes they never pause; the rhythm stays the ceiling when they throw (Tracker, energy="hits").
        self.tracker = Tracker(gd, team, energy="hits")
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
        self.hold_taps_until = 0.0  # no fast taps before this (after a switch tap)
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
        self.late_move = None  # a move of theirs named after its throw was already counted  # the last "used" text read for theirs, and when: it stays up a second or two
        self.my_move_names = {"".join(ch for ch in m.name.upper() if ch.isalpha()) for b in team for m in b.charged}
        self.my_names = {"".join(ch for ch in b.name.upper() if ch.isalpha()) for b in team}
        charged_ids = {i for sp in gd.species.values() for i in sp.get("chargedMoves", [])}
        self.used_names = {n: [i for i in ids if i in charged_ids] for n, ids in self.used_names.items()}
        self.used_names = {n: ids for n, ids in self.used_names.items() if ids}
        ev = Evaluator.load(ROOT / "runs" / "eval" / "eval.npz")
        self.engine = RealTime(Evaluator(ev.model), gd.meta(50), q=QNet.load(str(ROOT / "runs" / "general-decide" / "q.npz")),
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
        self.last_fast_tap = 0.0
        self.switch_ready_at = 0.0
        self.my_left_seen, self.foe_left_seen = 3, 3
        self.history = []  # recent header readings, for a majority
        self.fight_since = None  # since when the fight has been on screen without a break
        self.labels_checked = None
        self.replacements = 0  # replacement prompts answered: our faints
        self.prompt_shield, self.prompt_tapped = False, 0.0  # the answer to the shield prompt up now, and when tapped
        self.prompt_first = 0.0
        self.replace_point, self.replace_tapped = None, 0.0
        # Our energy read from the buttons (pogo.android_screen.my_energy): (energy, time) when two frames in a row
        # agree, and the last frame's own reading. The count from our fast moves drifts 20 to 50 off (2026-11-07).
        self.energy_read = None
        self._energy_raw = None
        self.queued = None  # (button, move, time tapped, deadline, battle time set): a move of ours still to start
        # A switch tapped and not yet seen: (slot, time tapped, bench strip before, since when it differs, fighting
        # frames looked at). The game sometimes ignores the tap (2026-11-07: Jellicent stayed out; the player took
        # Stunfisk for out for 36 s and pressed Stunfisk's moves on Jellicent's buttons).
        self.switching = None
        self._switch_fits = []  # which Pokémon's costs the energy reading fitted, the last three frames of a switch check
        self.last_not_taken = 0.0  # when a charged tap last came to nothing
        self.fight_frames = 0  # frames in a row with the fight on screen
        self.unread_since = None  # since when the fight has been on with the buttons unread
        self.prompt_seen = 0.0  # the last frame with a shield prompt
        # Which moves' names show under the buttons (shown = paid for): (names, time) when two frames in a row agree
        self.names_seen = None
        self._names_raw = None
        self.queued_checked = 0.0
        # Their fast moves landing on our bar, frame by frame (HitSteps): the times of those in the current unbroken
        # stretch of fighting, and every gap between hits so far for each of their Pokémon. The gaps tell the tracker
        # how many turns their fast move takes.
        self.their_steps = HitSteps()
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
        threading.Thread(target=self._tap_fast, daemon=True).start()

    # touching

    def touch(self, point, note: str) -> None:
        controls.tap(point, note)  # refuses keep-out zones
        with self.touch_lock:
            self.log("tap", self.now(), point=point, note=note, live=self.live)
            if self.live:
                self.phone.tap(*point)

    def clear_of_fast_taps(self) -> None:
        """Stop the fast taps and wait until 0.25 s have passed since the last began. The game drops a touch that
        starts just after another ends: over both days' logs, of the switch taps sent within 0.1 s of a fast tap
        about 20 in 23 were ignored, and of those sent 0.13 s or more after one nearly all went through (2026-11-08;
        charged taps "sometimes not taken" were most likely the same)."""
        self.tapping = False
        with self.touch_lock:  # a fast tap under way ends first
            wait = 0.25 - (time.time() - self.last_fast_tap)
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
                if look.header and len(look.bars) == 2 and not look.shield_prompt and not look.replace_prompt:
                    self.t0 = when
                    self.log("start", 0.0, epoch=round(when, 3))  # lines the log up with the recording's .times
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
                self.fight_frames = 0
                self.fight_since = None
                self.on_shield_prompt(t, look)
                continue
            if look.replace_prompt:
                self.tapping = False
                self.fight_frames = 0
                self.queued = None  # our Pokémon fainted: a move it had waiting went with it
                self.switching = self.switch_wanted = None
                self.fight_since = None
                self.on_replace_prompt(t, look)
                continue
            # The fight is on screen after three frames in a row with the header and a bar: in close-ups and
            # changes of Pokémon a false bar shows on a frame or two (2026-11-07, GO Battle League: looks given then
            # counted fast moves that were not happening, and a Shadow Ball was tapped on 53 counted, 16 real).
            self.fight_frames = self.fight_frames + 1 if look.header and len(look.bars) >= 1 else 0
            fighting = self.fight_frames >= 3
            if fighting:
                self.fight_frame_t = t
            # A frame or two without the bars in the middle of the fight (they are missed now and then) does not stop
            # the fast taps: they go on until the fight has been off for 0.4 s. Prompts stop them at once (above).
            self.tapping = (bool(fighting) or (self.tapping and t - self.fight_frame_t < 0.4)) \
                and time.time() >= self.hold_taps_until
            if fighting:
                self.watch_hits(t, look.bars)
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
                self.check_active(t)
                if self.last_fight is not None and t - self.last_fight > 2.0 and self.pending_mine is None and not self.pending_theirs:
                    # the fight stood still with no prompt and no throw of ours: their charged move, with no shield of ours to offer
                    if (look.my_shields or 0) == 0 and look.my_left == self.my_left_seen and look.foe_left == self.foe_left_seen:
                        self.pending_theirs = True
                        self.log("their_charged_unprompted", t, gap=round(t - self.last_fight, 2))
                if t - self.last_look >= LOOK:
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
            if not self.pending_theirs and time.time() - self.prompt_seen < 10.0:
                # The words of a throw whose shield prompt the tracker has already had (the fight showed between):
                # the same throw, not another.
                self.log("their_charged_named", t, move=move, text=text[:40], counted_already=True)
                self.late_move = move  # its name still tells the move, and the form (given at the next look)
                return
            self.foe_move_seen = move
            self.log("their_charged_named", t, move=move, text=text[:40], prompted=self.pending_theirs)
            self.pending_theirs = True

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
        if theirs is not None and foe is not None and self.my_steps.add(t, theirs * screen.BAR_INSIDE) is not None:
            self.my_hits_since_look += 1
        px = bars.get("mine")
        if px is None or foe is None:
            return
        size = self.their_steps.add(t, px * screen.BAR_INSIDE)
        if size is None:
            return
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
        at = self.names.labels_at
        if at is None or at == self.labels_checked or self.switching is not None:
            return
        self.labels_checked = at
        best = self.labels_say()
        if best is not None and best != self.active:
            self.log("active_corrected", t, was=self.team[self.active].name, now=self.team[best].name, labels=self.names.labels)
            self.active = best

    def header_now(self, look) -> tuple:
        if look.header and look.my_left and look.foe_left:
            self.history = (self.history + [(look.my_left, look.foe_left, look.my_shields, look.foe_shields)])[-5:]
        if not self.history:
            return None, None, None, None
        return tuple(max(set(col), key=col.count) for col in zip(*self.history))

    def check_switch(self, t: float, rgb) -> None:
        """Whether the switch tapped went through, from what only a switch changes: the buttons become the new
        Pokémon's moves. Its names under the buttons (read in the background, self.names) or an energy reading that
        fits its moves' costs and not the old one's, three frames running, say it went; the old one's names a second
        after the tap say it did not. The bench strip (pogo.android_screen.bench_strip) changes too, but so does any
        cut of the camera (2026-11-07: a tap during "Stunfisk used Mud Bomb!" was ignored, the cut to Gengar changed
        the strip, and the player took Vigoroth for out for 4.5 s). It decides only if neither has said anything in 5
        s: a change of over 45 held for 0.6 s, starting within 2 s of the tap. Until then no charged tap goes."""
        slot, tapped, before, since, looked = self.switching
        looked += 1
        tapped_t = tapped - (self.t0 or tapped)  # the tap in battle time, as the label readings are timed
        old_costs = [m.energy for m in self.team[self.active].charged]
        new_costs = [m.energy for m in self.team[slot].charged]
        e_new, e_old = screen.my_energy(rgb, new_costs), screen.my_energy(rgb, old_costs)
        fits = "new" if e_new is not None and e_old is None else "old" if e_old is not None and e_new is None else None
        self._switch_fits = (self._switch_fits + [fits])[-3:] if looked > 1 else [fits]
        said = self.labels_say() if (self.names.labels_at or -1) > tapped_t + 0.3 else None
        how = None
        if said == slot:
            how = "names"
        elif self._switch_fits == ["new"] * 3 and time.time() - tapped > 0.3:
            how = "buttons"
        if how is not None:
            self.log("switch_seen", t, to=self.team[slot].name, after_tap_s=round(time.time() - tapped, 2), by=how)
            self.switch_wanted = None
            self.active = slot
            self.switch_ready_at = tapped + 45  # switch timer: our own count, the tracker has its own
            self.switching = None
            self.energy_read = self._energy_raw = None  # those were the other Pokémon's buttons
            return
        if (said == self.active and (self.names.labels_at or -1) > tapped_t + 1.0) or \
                (self._switch_fits == ["old"] * 3 and time.time() - tapped > 1.5):
            self.log("switch_not_taken", t, to=self.team[slot].name, by="names" if said == self.active else "buttons")
            self.switching = None
            if not self.switch_retried:  # the game ignored it: once more
                self.switch_retried, self.switch_wanted = True, slot
            return
        if float(np.abs(screen.bench_strip(rgb) - before).mean()) > 45 and (since or time.time() - tapped < 2.0):
            since = since or time.time()
        else:
            since = None
        if time.time() - tapped > 5.0:
            # Nothing said in 5 s: taken as not taken. The bench strip alone was wrong (2026-11-08: "seen" at 14.9 s,
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
        prev, self._energy_raw = self._energy_raw, ((e, when) if e is not None else None)
        if e is not None and prev is not None and when - prev[1] < 0.25 and abs(e - prev[0]) <= 5:
            self.energy_read = (e, when)
        names = screen.button_labels(rgb)
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

    def give_look(self, t: float, look, rgb) -> None:
        my_left, foe_left, my_sh, foe_sh = self.header_now(look)
        paused = None
        if self.last_fight is not None and t - self.last_fight > 1.2:
            gap = t - self.last_fight
            paused = max(0.0, gap - 10.0 * ((self.pending_mine is not None) + self.pending_theirs))
        if my_left is not None and my_left < self.my_left_seen:
            self.my_left_seen = my_left
            alive_after = [j for j in range(len(self.team)) if j != self.active and self.tracker.me.team[j].hp > 0]
            if my_left == 1 and len(alive_after) == 1 and time.time() - self.replace_tapped > 15.0:
                # One of ours fainted with no prompt answered: with one left the game sends it in itself
                # (2026-11-08: Jellicent fainted, Stunfisk came in unasked, and the player, still taking Jellicent
                # for out, threw "Bubble Beam" on Stunfisk's Mud Bomb button and hunted Water icons: Nice).
                self.tracker.me.team[self.active].hp = 0
                alive = [j for j in range(len(self.team)) if self.tracker.me.team[j].hp > 0]
                self.log("fainted_unprompted", t, was=self.team[self.active].name, left=my_left,
                         now=self.team[alive[0]].name if len(alive) == 1 else None)
                self.replacements += 1
                if len(alive) == 1:
                    self.active = alive[0]
                    self.switching = self.switch_wanted = None
                    self.energy_read = self._energy_raw = None
        if foe_left is not None and foe_left < self.foe_left_seen:
            self.foe_left_seen = foe_left
        with self.pending_lock:  # the "used" reading thread sets pending_theirs and foe_move_seen
            obs = Observation(t=t, my_species=self.team[self.active].species_id, foe_species=self.names.species,
                              my_hp=look.bars.get("mine"), foe_hp=look.bars.get("theirs"), my_shields=my_sh,
                              foe_shields=foe_sh, my_left=my_left, foe_left=foe_left, my_energy=self.energy(look),
                              my_charged=self.pending_mine, foe_charged=self.pending_theirs, paused=paused,
                              foe_hits=self.hits_since_look, foe_move=self.foe_move_seen if self.pending_theirs else None,
                              my_hits=self.my_hits_since_look)
            self.hits_since_look = self.my_hits_since_look = 0
            self.foe_move_seen = None
            self.pending_theirs = False  # handed to the tracker in this look
        try:
            self.tracker.update(obs)
            late, self.late_move = self.late_move, None
            if late is not None:
                self.tracker.their_move_named(t, late)
        except Exception as error:  # noqa: BLE001 - a bad look must not stop the battle
            self.log("tracker_error", t, error=str(error))
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

    def act(self, t: float, look, rgb=None) -> None:
        view = self.view()
        if view is not None and t - self.last_look < 0.05:  # a decision at each look
            t0 = time.perf_counter()
            try:
                self.decision = self.engine.act(view)
            except Exception as error:  # noqa: BLE001
                self.log("engine_error", t, error=str(error))
                self.decision = FAST
            self.log("decision", t, action=self.name(self.decision), ms=round((time.perf_counter() - t0) * 1000))
        mon = self.team[self.active]
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
        if view is not None and self.decision == FAST:
            # Never faint with a charged move in hand (the owner, 2026-11-07): when our health is low and a move is
            # paid for, throw the hardest-hitting one now, whatever the engine planned.
            hp_share = look.bars.get("mine", view.me.mon.hp / view.me.mon.build.hp)
            affordable = [k for k, m in enumerate(mon.charged) if have >= m.energy]
            if hp_share < 0.35 and affordable:
                from pogo.battle import damage
                k = max(affordable, key=lambda j: damage(view.me.mon, mon.charged[j], view.foe))
                self.decision = CHARGED[0] + k
                self.log("throw_before_fainting", t, move=mon.charged[k].id, hp=hp_share)
            elif affordable and view.me.shields == 0 and self.tracker.foe is not None:
                # The owner, 2026-11-08 (Stunfisk held Discharge and Mud Bomb with no shields left, took Kabutops's
                # Water Pulse, and fainted with both): with no shield to block it, when they can throw a charged
                # move that would hurt (a third of our health or more), throw ours first.
                from pogo.battle import damage
                foe = self.tracker.foe
                ready = [m for m in foe.mon.build.charged if foe.hi + foe.mon.build.fast.energy_gain >= m.energy]
                hurt = max((damage(foe.mon, m, view.me.mon) for m in ready), default=0)
                if hurt >= 0.33 * view.me.mon.build.hp or hurt >= view.me.mon.hp:
                    k = max(affordable, key=lambda j: damage(view.me.mon, mon.charged[j], view.foe))
                    self.decision = CHARGED[0] + k
                    self.log("throw_before_theirs", t, move=mon.charged[k].id, foe_energy=[foe.lo, foe.hi], hurt=hurt)
        if self.switching is not None:
            return  # which of ours is out is not settled: no charged tap until it is
        if self.decision in CHARGED:
            k = self.decision - CHARGED[0]
            # On the count alone (the buttons unread) a throw that came to nothing is not tried again for 3 s: each
            # try stops the fast moves for up to 2.4 s (2026-11-07: 16 tries in one battle, 12 for low health).
            sure = self.energy() is not None or time.time() - self.last_not_taken > 3.0
            if have >= mon.charged[k].energy and sure:
                self.throw(t, k, mon.charged[k])
                self.decision = FAST
                return
        # Not before 1.5 s: until then "GO!" is on the screen and the game takes no switch (2026-11-08: the opening
        # switch to Stunfisk at 0.8 s and 0.97 s was ignored both times).
        if self.decision in SWITCH and self.switch_wanted is None and (t < 1.5 or self.switching is not None):
            self.switch_wanted = self.decision - SWITCH[0]
        if self.switch_wanted is not None and self.switching is None and self.decision == FAST and t >= 1.5:
            self.decision = SWITCH[0] + self.switch_wanted  # still wanted: tap it now
        if self.decision in SWITCH and time.time() >= self.switch_ready_at and t >= 1.5:
            slot = self.decision - SWITCH[0]
            order = [j for j in range(len(self.team)) if j != self.active and self.tracker.me.team[j].hp > 0]
            if slot not in order:
                self.switch_wanted = None
            if slot in order and rgb is not None:
                before = screen.bench_strip(rgb)
                self.clear_of_fast_taps()
                self.touch(BENCH[order.index(slot)], f"switch to {self.team[slot].name}")
                self.switch_wanted = None
                self.switching = (slot, time.time(), before, None, 0)  # self.active changes once it is seen
                # A switch, like a charged move, waits for the fast move under way to end, and a fast tap after it
                # takes its place (2026-11-08: Stunfisk's portrait tapped at 6.6 s, fast taps every 0.15 s after, no
                # switch). No fast taps for 1.6 s: the longest of our fast moves is 1.5 s.
                self.hold_taps_until = time.time() + 1.6
                self.decision = FAST
                return
        # fast moves: the tapping thread, while self.tapping

    def throw(self, t: float, k: int, move) -> None:
        self.queued = None  # a new tap stands for any move still waiting
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
        if named is not None and named != (self.active, k) and far is not None and far.get(move.type, 99) > 45:
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
        self.touch(point, f"charged move {k + 1}: {move.name}")
        tapped = last_tap = time.time()
        costs = [m.energy for m in self.team[self.active].charged]
        short = 0  # frames in a row on which the buttons say the move is not paid for
        # A tapped move waits for the fast move under way to end (1.5 s for Hex). The game says "Get Ready!" when our move starts and "Attack incoming!" for theirs, so the
        # box at the top is read until one shows. Fight bars going missing is not enough (ours hides behind
        # Jellicent often).
        since, last, started = None, 0.0, False
        while time.time() - tapped < 3.0:
            rgb, when = self.phone.next_frame(last, timeout=0.3)
            if when <= last:
                continue
            last = when
            # The top box is read (0.3 to 0.4 s a read) only once the fight is off the screen, as it is within a
            # tenth of a second of Get Ready!; meanwhile every frame gets the quick looks, so a re-tap is on time.
            bars = screen.bars(rgb)
            on = screen.header_visible(rgb) and len(bars) >= 1
            if on:  # their fast moves keep landing while ours waits to start (2026-11-08: two went uncounted)
                self.watch_hits(when - (self.t0 or when), bars)
            if screen.replace_prompt(rgb):  # ours fainted first: the loop answers the prompt
                self.log("throw_fainted", self.now(), move=move.id)
                return
            said = "theirs" if screen.shield_prompt(rgb) else None if on else screen.cue(self.names.ocr, rgb)
            if said == "theirs":
                # Theirs goes first; ours still waits and plays when theirs is over (2026-11-07: a Body Slam went
                # off after Plusle's Discharge, unswiped). The loop watches for its Get Ready!.
                self.log("throw_beaten", self.now(), move=move.id)
                self.queued = (k, move, tapped, time.time() + 40, self.now())
                return
            if said == "mine":
                since, started = when, True
                break
            # A tap on the button is sometimes not taken although the move is paid for (2026-11-07: Bulldoze at
            # 57 energy of 55, Discharge at 49 of 40, both shown by the buttons): tap again while they say so.
            e = screen.my_energy(rgb, costs)
            named = screen.button_labels(rgb)[k] if on else None  # the name shows: paid for (readable in the flash)
            if ((e is not None and e >= move.energy) or named) and time.time() - last_tap > 0.6:
                self.touch(point, f"charged move {k + 1} again: {move.name}")
                last_tap = time.time()
            short = short + 1 if e is not None and e < move.energy - 3 else 0
            if short >= 3:  # not paid for: no use waiting with the fast moves stopped
                break
        if not started:
            self.last_not_taken = time.time()
            # It may still go off a moment later (2026-11-07: four of 39 moves had Get Ready! up to half a second
            # after the wait, and went unswiped), or after theirs: the loop watches for it.
            self.queued = (k, move, tapped, time.time() + 40, self.now())
            read = self.energy()
            self.log("throw_not_taken", self.now(), move=move.id, counted=self.tracker.me.mon.energy,
                     read=None if read is None else round(read, 1))
            self.tracker.me.mon.energy = min(self.tracker.me.mon.energy, move.energy - 1)  # the button says not yet
            self.energy_read = None
            return
        self.pending_mine = k
        self.my_throw_at = time.time()
        self.log("throw_started", self.now(), move=move.id, after_tap_s=round(since - tapped, 2),
                 cue_t=round(since - (self.t0 or since), 3))
        self.minigame(k, move, since)

    def label_move(self, rgb, k: int):
        """(team slot, move index) of the move button k shows paid for, by the button's colour
        (pogo.android_screen.paid_type), or None when it cannot be told."""
        kind = screen.paid_type(rgb, k)
        if kind is None:
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
        back = self.fight_since is not None and t - max(self.fight_since, made) > 2.0
        if time.time() > deadline or back or (e is not None and self.energy_read[1] > tapped + 1.0 and e < move.energy - 5):
            self.log("queued_dropped", t, move=move.id, read=None if e is None else round(e, 1))
            self.queued = None
            return False
        if fighting or time.time() - self.queued_checked < 0.2:
            return False
        self.queued_checked = time.time()
        if screen.cue(self.names.ocr, rgb) != "mine":
            return False
        self.queued = None
        self.pending_mine = k
        self.my_throw_at = time.time()
        self.log("throw_started", self.now(), move=move.id, after_tap_s=round(when - tapped, 2), queued=True)
        self.minigame(k, move, when)
        return True

    def minigame(self, k: int, move, since: float) -> None:
        """Swipe the minigame of our move that started (Get Ready!) at time `since`."""
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
                hunted = minigame_stroke(self.phone, seconds=path[-1][0] + 0.9, colour=icon_colour(move.type),
                                         zone=icon_zone(move.type), move_type=move.type, trace=trace,
                                         predicted=choreography(move.id), ready_at=since)
            self.log("minigame", self.now(), move=move.id, icons_seen=hunted, trace=trace)

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
        self.pending_theirs = True
        view = self.view()
        shield = False
        last = self.replacements >= 2  # we have sent in both replacements: this is our last Pokémon
        if view is not None and view.me.shields > 0:
            try:
                shield = bool(self.engine.shield(view, self.tracker.foe.hi))
            except Exception as error:  # noqa: BLE001
                self.log("engine_error", t, error=str(error))
                shield = True
        if last and (look.my_shields or 0) > 0:
            # The engine's own rule: with one Pokémon left there is nothing to save shields for. The tracker can
            # miss that our others have fainted (the header's count lags), so it is applied from our own count.
            shield = True
        if not shield and view is not None and view.me.shields > 0 and self.tracker.foe is not None:
            # The owner's call after watching (2026-11-07): the website engine saves shields far more than a player
            # would (16 of 20 prompts unshielded over three lost games). Shield a hit that would knock us out or
            # take a third of our health, unless we are nearly gone anyway.
            from pogo.battle import damage
            mon, foe = view.me.mon, self.tracker.foe.mon
            moves = [m for m in foe.build.charged if m.energy <= max(self.tracker.foe.hi, min(x.energy for x in foe.build.charged))]
            worst = max((damage(foe, m, mon) for m in moves), default=0)
            nearly_gone = mon.hp <= 2 * damage(foe, foe.build.fast, mon)
            if not nearly_gone and (worst >= mon.hp or worst >= 0.35 * mon.build.hp):
                shield = True
                self.log("shield_override", t, worst=worst, hp=mon.hp, max_hp=mon.build.hp)
        self.log("shield_prompt", t, shield=shield, foe_energy=(self.tracker.foe.lo, self.tracker.foe.hi) if self.tracker.foe else None)
        self.prompt_shield, self.prompt_tapped = shield, time.time()
        self.prompt_first = self.prompt_tapped  # answers are tapped again for 5 s at most
        self.touch(SHIELD_YES if shield else SHIELD_NO, "shield" if shield else "no shield")

    def on_replace_prompt(self, t: float, look) -> None:
        if self.replaced:
            if self.replace_point and time.time() - self.replace_tapped > 0.5:  # tapped again until the prompt goes
                self.touch(self.replace_point, "send in again")
                self.replace_tapped = time.time()
            return
        self.replaced = True
        bench = [j for j in range(len(self.team)) if j != self.active and self.tracker.me.team[j].hp > 0]
        view = self.view()
        slot = bench[0] if bench else None
        if view is not None:
            try:
                slot = self.engine.replace(view)
            except Exception as error:  # noqa: BLE001
                self.log("engine_error", t, error=str(error))
        if slot not in bench and bench:
            slot = bench[0]
        if slot is None:
            return
        point = controls.REPLACE_ONE if len(bench) == 1 else controls.REPLACE_TWO[bench.index(slot)]
        self.log("replace", t, to=self.team[slot].name, bench=[self.team[j].name for j in bench])
        self.touch(point, f"send in {self.team[slot].name}")
        self.replace_point, self.replace_tapped = point, time.time()
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--serial")
    ap.add_argument("--team", default=str(ROOT / "data" / "alt_team.json"))
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--start-tap", type=float, nargs=2)
    ap.add_argument("--frames")
    ap.add_argument("--max-actions", type=int, default=1500)
    a = ap.parse_args()
    gd = GameData()
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
    log("team", 0.0, team=[(b.species_id, b.fast.id, [m.id for m in b.charged], b.cp) for b in team])
    try:
        if a.start_tap:
            player.touch(tuple(a.start_tap), "start")
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
