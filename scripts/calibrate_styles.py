#!/usr/bin/env python3
"""Measure how each opponent style inside the engine's look-ahead shields and baits (docs/tasks.md, task 28).

    python3 scripts/calibrate_styles.py [--battles 2000] [--workers 64]

Each style (pogo.engine.STYLES: the trained bot, the bot with shifted habits, the human-like guess, PvPoke's AI) plays
the usual crowd on random teams. Counted: of the times it could shield, how often it did; of the times it threw with
both charged moves ready and of different cost, how often it threw the cheaper. Written to
data/opponent_styles.json, which the engine reads for its per-game profile (profile=True) instead of the guesses in
STYLES. The weights in the mix are kept as they are.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import random
import sys
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_v] = "1"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pogo.agents import varied  # noqa: E402
from pogo.arena import low_priority  # noqa: E402
from pogo.battle import CHARGED, Battle  # noqa: E402
from pogo.engine import STYLES, style_player  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.learner import QNet  # noqa: E402


class Counted:
    """Plays as `inner`, counting its shields and its choice of move when both are ready."""

    def __init__(self, inner):
        self.inner, self.shield_seen, self.bait_seen = inner, [0, 0], [0, 0]
        self.sees_move = getattr(inner, "sees_move", False)
        for hook in ("saw_throw", "saw_shield"):
            if hasattr(inner, hook):
                setattr(self, hook, getattr(inner, hook))

    def act(self, view):
        action = self.inner.act(view)
        mon = view.me.mon
        ready = [m for m in mon.build.charged if mon.energy >= m.energy]
        if action in CHARGED and len(ready) == 2 and ready[0].energy != ready[1].energy:
            move = mon.build.charged[action - CHARGED[0]]
            self.bait_seen[0] += move.energy == min(m.energy for m in ready)
            self.bait_seen[1] += 1
        return action

    def shield(self, view, energy, *move):
        answer = bool(self.inner.shield(view, energy, *move))
        if view.me.shields:
            self.shield_seen[0] += answer
            self.shield_seen[1] += 1
        return answer

    def replace(self, view):
        return self.inner.replace(view)


def job(task):
    name, start, count = task
    low_priority()
    gd = GameData()
    pool = gd.meta(50)
    net = QNet.load(str(ROOT / "runs" / "general-decide" / "q.npz"))
    shields, baits = [0, 0], [0, 0]
    for n in range(start, start + count):
        rng = random.Random(70_001 * n + 13)
        player = Counted(style_player(name, rng, net, 0.02, pool))
        Battle(rng.sample(pool, 3), rng.sample(pool, 3), player, varied(rng, pool), seed=rng.getrandbits(32)).run()
        shields = [a + b for a, b in zip(shields, player.shield_seen)]
        baits = [a + b for a, b in zip(baits, player.bait_seen)]
    return name, shields, baits


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--battles", type=int, default=2000)
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 4)
    args = parser.parse_args()
    chunk = 50
    tasks = [(name, s, min(chunk, args.battles - s)) for name in STYLES for s in range(0, args.battles, chunk)]
    totals = {name: {"shield": [0, 0], "bait": [0, 0]} for name in STYLES}
    with multiprocessing.get_context("spawn").Pool(args.workers) as pool:
        for name, shields, baits in pool.imap_unordered(job, tasks):
            for kind, got in (("shield", shields), ("bait", baits)):
                totals[name][kind] = [a + b for a, b in zip(totals[name][kind], got)]
    out = {}
    for name, t in totals.items():
        rates = {kind: t[kind][0] / t[kind][1] if t[kind][1] else STYLES[name][kind] for kind in ("shield", "bait")}
        out[name] = {"weight": STYLES[name]["weight"], **{k: round(v, 3) for k, v in rates.items()}}
        print(f"{name:7s} shields {100 * rates['shield']:.0f}% of {t['shield'][1]} chances; throws the cheaper move "
              f"{100 * rates['bait']:.0f}% of {t['bait'][1]} times both were ready")
    path = ROOT / "data" / "opponent_styles.json"
    path.write_text(json.dumps({"about": "Shield and bait rates of the engine's imagined opponent styles, measured by "
                                "scripts/calibrate_styles.py against the crowd.", "battles": args.battles, "styles": out},
                               indent=1) + "\n")
    print(f"written: {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
