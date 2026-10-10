#!/usr/bin/env python3
"""Measure how long the bot's own steps take, against the latency targets.

    python3 scripts/latency.py

Covers the two parts that exist in software: the battle tracker's update for one look at
the screen (target 5 ms) and the decision (target 10 ms), for the hand-written Planner
and for the Planner with learned decisions. Screen capture, recognition and input are
not measured here; they need the phone.
"""
from __future__ import annotations

import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_tracker  # noqa: E402
from pogo.agents import Planner, varied  # noqa: E402
from pogo.battle import Battle  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.learner import Learner, QNet  # noqa: E402
from pogo.tracker import Tracker, state  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


class Timed:
    """Passes everything through to a player, timing each kind of decision."""

    def __init__(self, inner, times: dict):
        self.inner, self.times = inner, times

    def _time(self, kind: str, call, *args):
        start = time.perf_counter()
        answer = call(*args)
        self.times.setdefault(kind, []).append(1000 * (time.perf_counter() - start))
        return answer

    def act(self, view):
        return self._time("choose an action", self.inner.act, view)

    def shield(self, view, foe_energy):
        return self._time("shield or not", self.inner.shield, view, foe_energy)

    def replace(self, view):
        return self._time("choose a replacement", self.inner.replace, view)

    def saw_throw(self, *args):
        self.inner.saw_throw(*args)

    def saw_shield(self, *args):
        self.inner.saw_shield(*args)


def report(label: str, samples: list[float], target: float) -> None:
    samples = sorted(samples)
    n = len(samples)
    within = sum(s <= target for s in samples) / n
    print(f"  {label:34s} {n:7d} calls  median {samples[n // 2]:6.2f} ms  99th {samples[int(0.99 * n)]:7.2f} ms  "
          f"worst {samples[-1]:7.2f} ms  within {target:g} ms: {100 * within:.2f}%")


def main() -> None:
    gd = GameData()
    pool = gd.meta(50)
    battles = 200
    pilots = {"Planner": lambda: Planner()}
    model = ROOT / "runs" / "general-decide" / "q.npz"
    if model.exists():
        q = QNet.load(model)
        pilots["Planner with learned decisions"] = lambda: Learner(q=q, margin=0.02)

    print(f"decision time over {battles} battles each (target 10 ms)")
    for name, make in pilots.items():
        rng, times = random.Random(0), {}
        for _ in range(battles):
            Battle(rng.sample(pool, 3), rng.sample(pool, 3), Timed(make(), times), varied(rng, pool), seed=rng.getrandbits(32)).run()
        print(name)
        for kind, samples in times.items():
            report(kind, samples, 10.0)
        report("every decision together", [s for v in times.values() for s in v], 10.0)

    updates, snapshots = [], []
    original = Tracker.update

    def timed_update(self, obs):
        start = time.perf_counter()
        original(self, obs)
        updates.append(1000 * (time.perf_counter() - start))
        start = time.perf_counter()
        state(self)
        snapshots.append(1000 * (time.perf_counter() - start))

    Tracker.update = timed_update
    rng = random.Random(1)
    defaults = [gd.default(b.species_id) for b in pool]
    for _ in range(60):
        teams = rng.sample(defaults, 3), rng.sample(defaults, 3)
        check_tracker.play(gd, teams, (check_tracker.ViaTracker(Planner()), Planner()), rng.getrandbits(32),
                           check_tracker.CAMERAS["rough"], None, rng)
    Tracker.update = original
    print("\ntracker, one look at a time over 60 battles (target 5 ms)")
    report("update from one look", updates, 5.0)
    report("write out the full game state", snapshots, 5.0)


if __name__ == "__main__":
    main()
