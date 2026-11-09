"""From the bot's decisions to touches on the phone's battle screen (docs/tasks.md, task 13).

Positions are shares of the screen's width (x) and height (y), measured on the owner's iPhone recordings
(1206 x 2622, portrait; scripts/recording/contact_sheet.py and overlay_controls.py show them on real frames):

- fast move: a tap on the open field, clear of every button and panel;
- charged move: a tap on its button at the bottom (scripts/recording/buttons.py measured the discs); the minigame
  that follows is pogo.minigame's;
- switch: a tap on the bench Pokémon's portrait at the right edge, the earlier team slot on top;
- shield prompt ("Attack incoming! Use a Protect Shield?"): the shield in the middle, or "Not now" below it;
- after a faint ("Switch in a new Pokémon?"): the two choices side by side in team order, or one in the middle.

Nothing here touches the phone by itself: `Controller` sends gestures through pogo.phone.Phone, in dry run unless
told otherwise, and refuses any point inside KEEP_OUT (the flee button, which forfeits the battle, and the top bar).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from .battle import CHARGED, FAST, SWITCH

FIELD = (0.50, 0.45)  # open field above the Pokémon, below the health bars
CHARGED_BUTTONS = ((0.3093, 0.893), (0.6907, 0.893))
BENCH = ((0.915, 0.585), (0.915, 0.67))  # portraits at the right edge, earlier team slot on top
SHIELD_YES, SHIELD_NO = (0.50, 0.815), (0.50, 0.952)
REPLACE_TWO = ((0.33, 0.865), (0.67, 0.865))
REPLACE_ONE = (0.50, 0.865)
# The flee button in the fight, measured on this phone's recordings (2026-11-09): centre (0.078, 0.145), about 0.035
# of the width in radius. It is not drawn in a charged move's minigame, whose icons (Stone Edge's above all) come up
# in that corner. A minigame stroke ("stroke" gestures) keeps FLEE_CLEAR from its centre, distances in widths (the
# screen is 2.2 times taller than wide), in place of KEEP_OUT's first circle; a drag does not press a button it passes
# over (the stroke goes down and up on the open field).
FLEE, FLEE_CLEAR, ASPECT = (0.078, 0.145), 0.09, 2.2


def clear_of_flee(x: float, y: float) -> tuple:
    """The point, or the nearest point FLEE_CLEAR from the flee button's centre."""
    dx, dy = x - FLEE[0], (y - FLEE[1]) * ASPECT
    d = (dx * dx + dy * dy) ** 0.5
    if d >= FLEE_CLEAR:
        return x, y
    if d < 1e-9:
        dx, dy, d = 0.0, 1.0, 1.0
    k = (FLEE_CLEAR + 1e-6) / d
    return FLEE[0] + dx * k, FLEE[1] + dy * k / ASPECT


KEEP_OUT = [  # (centre, radius): never touched
    ((0.075, 0.18), 0.08),  # the run icon top left: flee, which forfeits the battle
    ((0.50, 0.03), 0.06),   # the top bar of the phone
]


class UnsafeTouch(ValueError):
    pass


@dataclass
class Gesture:
    """One touch: a tap at points[0], or a drag along the points over `ms` milliseconds."""

    kind: str
    points: list
    ms: int = 0
    note: str = ""

    def check(self) -> Gesture:
        for x, y in self.points:
            if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
                raise UnsafeTouch(f"{self.note}: point {x:.3f}, {y:.3f} is off the screen")
            for k, ((cx, cy), r) in enumerate(KEEP_OUT):
                if k == 0 and self.kind == "stroke":
                    if ((x - FLEE[0]) ** 2 + ((y - FLEE[1]) * ASPECT) ** 2) ** 0.5 < FLEE_CLEAR:
                        raise UnsafeTouch(f"{self.note}: point {x:.3f}, {y:.3f} is too near the flee button")
                    continue
                if (x - cx) ** 2 + (y - cy) ** 2 < r * r:
                    raise UnsafeTouch(f"{self.note}: point {x:.3f}, {y:.3f} is in a keep-out zone")
        return self


def tap(point, note: str) -> Gesture:
    return Gesture("tap", [point], 0, note).check()


def bench_order(view) -> list[int]:
    """Team slots of the Pokémon on the bench that are still standing, top portrait first."""
    return [j for j in range(len(view.me.team)) if j != view.me.active and view.me.team[j].hp > 0]


def for_action(action: int, view) -> list[Gesture]:
    """The touches for an action of pogo.battle (FAST, CHARGED[k], SWITCH[slot]) taken from this view."""
    if action == FAST:
        return [tap(FIELD, "fast move")]
    if action in CHARGED:
        k = action - CHARGED[0]
        return [tap(CHARGED_BUTTONS[k], f"charged move {k + 1}: {view.me.mon.build.charged[k].name}")]
    if action in SWITCH:
        slot = action - SWITCH[0]
        order = bench_order(view)
        if slot not in order:
            raise UnsafeTouch(f"switch to slot {slot}, which is not on the bench {order}")
        return [tap(BENCH[order.index(slot)], f"switch to {view.me.team[slot].build.name}")]
    raise ValueError(f"unknown action {action}")


def for_shield(shield: bool) -> list[Gesture]:
    return [tap(SHIELD_YES, "shield")] if shield else [tap(SHIELD_NO, "no shield")]


def for_replace(slot: int, view) -> list[Gesture]:
    """After a faint: the choice for this team slot. The fainted Pokémon is still the active one when asked."""
    order = [j for j in range(len(view.me.team)) if j != view.me.active and view.me.team[j].hp > 0]
    if slot not in order:
        raise UnsafeTouch(f"replacement slot {slot} is not among {order}")
    point = REPLACE_ONE if len(order) == 1 else REPLACE_TWO[order.index(slot)]
    return [tap(point, f"send in {view.me.team[slot].build.name}")]


@dataclass
class Controller:
    """Sends gestures to the phone (pogo.phone.Phone), in dry run unless live=True, with a cap on touches per
    battle. Every gesture is logged with the time it was sent, so a battle can be checked afterwards."""

    phone: object = None
    live: bool = False
    max_touches: int = 2000
    log: list = field(default_factory=list)

    def send(self, gestures: list[Gesture]) -> None:
        for g in gestures:
            g.check()
            if len(self.log) >= self.max_touches:
                raise UnsafeTouch(f"more than {self.max_touches} touches in one battle")
            self.log.append((time.time(), g.kind, g.points, g.ms, g.note, self.live))
            if not self.live or self.phone is None:
                continue
            if g.kind == "tap":
                self.phone.tap(*g.points[0])
            else:
                self.phone.path(g.points, ms=g.ms)  # one unbroken touch
