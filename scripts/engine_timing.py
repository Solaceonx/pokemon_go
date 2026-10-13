#!/usr/bin/env python3
"""Can the engine think while its fast move plays out? How often that works, and whether it then has time enough.

    python3 scripts/engine_timing.py [--battles 300] [--workers 3] [--seed 401]

The engine (pogo.engine, the confirmed settings: the trained bot inside the look-ahead, 4 imagined battles per
option, 20 turns, edge 0.03) plays the usual crowd. Each time it starts a fast move it predicts, from what it can
see, the position when that move ends, assuming the opponent keeps fast-moving too: that is when it must choose
again, so that is the position it could be searching in the meantime. At its next decision the prediction is
checked against what really happened, and every decision it searched is timed.

A searched decision is ready in time if its search fits in what the fast move leaves: its turns at 500 ms, less
about 200 ms for seeing the screen and for the tap (scripts/latency.py's targets). Where the prediction fails it
failed for a reason the player sees: a charged move (the game pauses for it), a switch or a faint (an animation,
and after a faint a choice of replacement), and those decisions are reported separately.
"""
from __future__ import annotations

import argparse
import multiprocessing
import os
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pogo.agents import varied  # noqa: E402
from pogo.arena import low_priority  # noqa: E402
from pogo.battle import CHARGED, FAST, Battle  # noqa: E402
from pogo.engine import Engine  # noqa: E402
from pogo.evaluation import Evaluator  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.learner import QNet  # noqa: E402
from pogo.teamlist import drawer  # noqa: E402

TURN_MS = 500
SEE_AND_TAP_MS = 200


class _Quiet:
    """Both sides in the prediction: fast moves only."""

    def act(self, view):
        return FAST

    def shield(self, view, energy, *move):
        return False

    def replace(self, view):
        return view.me.bench()[0]


def key(view) -> tuple:
    """Everything about the position that the engine's decision depends on."""
    me, mon, foe = view.me, view.me.mon, view.foe
    return (view.turn, me.active, mon.hp, mon.energy, mon.atk_stage, mon.def_stage, me.shields, me.switch_wait,
            foe.build.uid, foe.hp, foe.energy, foe.atk_stage, foe.def_stage, view.foe_shields, view.foe_switch_wait,
            view.foe_busy)


class Timed(Engine):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rows: list = []
        self._last = "start"  # what our previous action was
        self._predicted = None  # the position expected at our next decision, or "faint" if one is coming

    def _predict(self, view) -> tuple | str:
        """Where our fast move ends, if both sides keep fast-moving. Uses only what this side can see: our
        team, their Pokémon in play (its health, energy and the state of its fast move) and both shields."""
        battle = view._battle
        side = battle.sides.index(view.me)
        twin = battle.clone(_Quiet(), _Quiet())
        for _ in range(view.me.mon.build.fast.turns):
            twin.step()
            if twin.winner is not None or any(s.mon.hp <= 0 or s.active != a for s, a in
                                              zip(twin.sides, (battle.sides[0].active, battle.sides[1].active))):
                return "faint"
        return key(twin.views[side])

    def _cause(self, view) -> str:
        if self._last != "fast":
            return self._last
        if self._predicted == "faint":
            return "a faint was coming"
        if self._predicted == key(view):
            return f"predicted, fast move of {view.me.mon.build.fast.turns}"
        if view.turn != self._predicted[0]:
            return "a charged move came"
        if view.foe.build.uid != self._predicted[8]:
            return "they switched"
        return "mispredicted"

    def act(self, view):
        cause = self._cause(view)
        looks, start = self.looks, time.perf_counter()
        action = super().act(view)
        ms = 1000 * (time.perf_counter() - start)
        if self.looks > looks:
            self.rows.append((cause, ms))
        if action == FAST:
            self._last, self._predicted = "fast", self._predict(view)
        elif action in CHARGED:
            self._last = "after our charged move"
        else:
            self._last = "after our switch"
        return action

    def replace(self, view):
        looks, start = self.looks, time.perf_counter()
        slot = super().replace(view)
        ms = 1000 * (time.perf_counter() - start)
        if self.looks > looks:
            self.rows.append(("replacing a fainted Pokémon", ms))
        self._last = "after a faint"
        return slot


def job(task) -> list:
    seed, count = task
    low_priority()
    gd = GameData()
    pool = gd.meta(50)
    draw = drawer(gd, pool)
    net = QNet.load(str(ROOT / "runs" / "general-decide" / "q.npz"))
    ev = Evaluator.load(ROOT / "runs" / "eval" / "eval.npz")
    rng = random.Random(seed)
    rows = []
    for _ in range(count):
        engine = Timed(ev, pool, rollout="bot", samples=4, edge=0.03, q=net, margin=0.02, seed=rng.getrandbits(32))
        Battle(draw(rng), draw(rng), engine, varied(rng, pool), seed=rng.getrandbits(32)).run()
        rows += engine.rows
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--battles", type=int, default=300)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--seed", type=int, default=401)
    args = parser.parse_args()
    per = -(-args.battles // args.workers)
    with multiprocessing.get_context("spawn").Pool(args.workers) as pool:
        parts = pool.map(job, [(args.seed * 1000 + w, per) for w in range(args.workers)])
    rows = [r for part in parts for r in part]
    by = defaultdict(list)
    for cause, ms in rows:
        by[cause].append(ms)
    every = np.array([ms for _, ms in rows])
    print(f"{len(rows)} searched decisions in {args.battles} battles; search time, all: median {np.median(every):.0f} ms, "
          f"90th percentile {np.percentile(every, 90):.0f}, 99th {np.percentile(every, 99):.0f}, worst {every.max():.0f}\n")
    print(f"{'what came before the decision':38} | share | median | 90th | 99th | worst | ready in time")
    fits_all = 0
    for cause, values in sorted(by.items(), key=lambda kv: -len(kv[1])):
        v = np.array(values)
        line = (f"{cause:38} | {100 * len(v) / len(rows):4.0f}% | {np.median(v):6.0f} | {np.percentile(v, 90):4.0f} | "
                f"{np.percentile(v, 99):4.0f} | {v.max():5.0f} |")
        if cause.startswith("predicted"):
            room = int(cause.rsplit(" ", 1)[1]) * TURN_MS - SEE_AND_TAP_MS
            fits = int((v <= room).sum())
            fits_all += fits
            line += f" {100 * fits / len(v):.1f}% within {room} ms"
        print(line)
    print(f"\npredicted and ready in time: {100 * fits_all / len(rows):.1f}% of all searched decisions")


if __name__ == "__main__":
    main()
