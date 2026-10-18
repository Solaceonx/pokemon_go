"""The engine in real time: every search gets only the time the game would give it.

The engine (pogo.engine) needs about 45 ms for a typical searched decision and up to about 400 ms. Live, a
decision is due the moment our fast move ends, but most of the time the position it will be made in is known
well before that, or the game is paused while it is made:

- Our fast move. When we start one, the position at its end is known whenever the opponent only fast-moves
  (the timing of both fast moves is on screen), so the search can run while the move plays out: its turns at
  500 ms, less 200 ms for seeing the screen and the tap. A 5-turn move such as Incinerate leaves 2.3 s.
- A charged move, ours or theirs. The game stops for it; once the outcome is on screen (shielded or not, the
  damage), the position at the next decision is known and the rest of the animation is time to think.
- A faint. The replacement is chosen on its own screen, and the next decision follows the entry animation.
- The start: the countdown.
- Unforeseen: their switch, our own switch, or a prediction that failed. The decision is searched when it is
  due, with a short limit, since acting late costs part of a turn.

`RealTime` is the engine with a deadline on each search, set by which of these came before the decision. When
the deadline comes it decides on the rounds of imagined battles it completed; with none, it plays the trained
bot's own pick (pogo.engine). In simulation the search runs at the decision itself: when the prediction held,
the position is the one that would have been searched in advance, so the choice is the same and the wait at
the decision is nil. Live, that search has to run in another process during the fast move.

The pause lengths are measured from 49 tracked battles (scripts/recording/pause_lengths.py, status.md "Real pause
lengths"): a charged move shows its damage 9.4 s after it starts and play resumes 0.9 s later (0.4 s at the 10th
percentile); after a faint, play resumes 1.2 s after the replacement is in (0.4 s at the 10th percentile); the
replacement itself is chosen over seconds. The defaults are those 10th percentiles. A charged move leaves about
9 s before its outcome shows, with only the shield and the move unknown: searching those few outcomes while the
move plays would give the search far more time than the 0.4 s left once the outcome is on screen (task 23).
"""
from __future__ import annotations

import random
import time

from .battle import CHARGED, FAST
from .engine import Engine, imagine

PREDICTED, PAUSE, UNFORESEEN = "predicted", "pause", "unforeseen"


def key(view) -> tuple:
    """Everything about the position that the engine's decision depends on."""
    me, mon, foe = view.me, view.me.mon, view.foe
    return (view.turn, me.active, mon.hp, mon.energy, mon.atk_stage, mon.def_stage, me.shields, me.switch_wait,
            foe.build.uid, foe.hp, foe.energy, foe.atk_stage, foe.def_stage, view.foe_shields, view.foe_switch_wait,
            view.foe_busy)


class _Quiet:
    """Both sides in the prediction: fast moves only."""

    def act(self, view):
        return FAST

    def shield(self, view, energy, *move):
        return False

    def replace(self, view):
        return view.me.bench()[0]


def predict(view, pool: list):
    """The position when our fast move, started now, ends, if both sides keep fast-moving; "faint" if someone
    faints before then. Built from what this side sees (pogo.engine.imagine), not from the battle itself."""
    twin = imagine(view, random.Random(0), pool, _Quiet(), _Quiet())
    active = [side.active for side in twin.sides]
    for _ in range(view.me.mon.build.fast.turns):
        twin.step()
        if twin.winner is not None or any(s.mon.hp <= 0 or s.active != a for s, a in zip(twin.sides, active)):
            return "faint"
    return key(twin.views[0])


class RealTime(Engine):
    def __init__(self, *args, turn_ms: float = 500, see_and_tap_ms: float = 200, unforeseen_ms: float = 300,
                 after_charged_ms: float = 400, after_faint_ms: float = 350, replace_ms: float = 2000,
                 start_ms: float = 1000, cap_ms: float | None = None, clock=time.process_time, **kwargs):
        super().__init__(*args, **kwargs)
        self.turn_ms, self.see_and_tap_ms, self.unforeseen_ms = turn_ms, see_and_tap_ms, unforeseen_ms
        self.after_charged_ms, self.after_faint_ms, self.replace_ms, self.start_ms = (
            after_charged_ms, after_faint_ms, replace_ms, start_ms)
        self.cap_ms, self.clock = cap_ms, clock  # cap_ms: no search longer than this, whatever the situation allows
        # One row per decision that was searched: (what came before, kind of time, budget ms, spent ms,
        # wait at the decision ms, searched rounds were cut short, fell back to the trained bot's pick).
        self.rows: list = []
        self._last, self._predicted = "start", None

    def clone(self) -> RealTime:
        twin = super().clone()
        twin.rows = []
        return twin

    def _cause(self, view) -> tuple[str, str, float]:
        """What came before this decision, the kind of time it had, and how many milliseconds."""
        last = self._last
        if last == "fast":
            if self._predicted == "faint":
                return "a faint came", PAUSE, self.after_faint_ms
            if self._predicted == key(view):
                turns = view.me.mon.build.fast.turns
                return f"predicted, fast move of {turns}", PREDICTED, turns * self.turn_ms - self.see_and_tap_ms
            if view.turn != self._predicted[0]:
                return "a charged move came", PAUSE, self.after_charged_ms
            if view.foe.build.uid != self._predicted[8]:
                return "they switched", UNFORESEEN, self.unforeseen_ms
            return "mispredicted", UNFORESEEN, self.unforeseen_ms
        if last == "charged":
            return "after our charged move", PAUSE, self.after_charged_ms
        if last == "faint":
            return "after a faint", PAUSE, self.after_faint_ms
        if last == "start":
            return "start", PAUSE, self.start_ms
        return "after our switch", UNFORESEEN, self.unforeseen_ms

    def _timed(self, decide, cause: str, kind: str, budget_ms: float):
        if self.cap_ms is not None:
            budget_ms = min(budget_ms, self.cap_ms)
        looks, cut, fell_back = self.looks, self.cut, self.fell_back
        start = self.clock()
        self._deadline = start + budget_ms / 1000
        try:
            choice = decide()
        finally:
            self._deadline = None
        if self.looks > looks:
            spent = 1000 * (self.clock() - start)
            wait = spent if kind == UNFORESEEN else max(0.0, spent - budget_ms)
            self.rows.append((cause, kind, budget_ms, spent, wait, self.cut > cut, self.fell_back > fell_back))
        return choice

    def act(self, view):
        cause, kind, budget = self._cause(view)
        action = self._timed(lambda: super(RealTime, self).act(view), cause, kind, budget)
        if action == FAST:
            self._last, self._predicted = "fast", predict(view, self.pool)
        elif action in CHARGED:
            self._last = "charged"
        else:
            self._last = "switch"
        return action

    def replace(self, view):
        slot = self._timed(lambda: super(RealTime, self).replace(view), "replacing a fainted Pokémon", PAUSE, self.replace_ms)
        self._last = "faint"
        return slot
