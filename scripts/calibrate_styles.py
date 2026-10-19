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
import hashlib
import json
import math
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
    name, start, count, human = task
    gd = GameData()
    pool = gd.meta(50)
    net = QNet.load(str(ROOT / "runs" / "general-decide" / "q.npz"))
    shields, baits = [0, 0], [0, 0]
    squares = {kind: [0, 0, 0] for kind in ("shield", "bait")}
    for n in range(start, start + count):
        rng = random.Random(70_001 * n + 13)
        player = Counted(style_player(name, rng, net, 0.02, pool, human))
        Battle(rng.sample(pool, 3), rng.sample(pool, 3), player, varied(rng, pool), seed=rng.getrandbits(32)).run()
        shields = [a + b for a, b in zip(shields, player.shield_seen)]
        baits = [a + b for a, b in zip(baits, player.bait_seen)]
        for kind, (k, opportunities) in (("shield", player.shield_seen), ("bait", player.bait_seen)):
            squares[kind] = [a + b for a, b in zip(squares[kind], (k * k, opportunities * opportunities, k * opportunities))]
    return name, start, shields, baits, squares


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--battles", type=int, default=2000)
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 4)
    parser.add_argument("--tag", default="styles", help="checkpoint tag; rerun the same command to resume")
    parser.add_argument("--output", type=Path, default=ROOT / "data/opponent_styles.json")
    parser.add_argument("--human-settings", default="{}", help="JSON object of existing human-style rule settings")
    args = parser.parse_args()
    if args.battles < 2 or args.workers < 1:
        parser.error("at least two battles and one worker are required")
    chunk = 50
    human = json.loads(args.human_settings)
    if not isinstance(human, dict):
        parser.error("--human-settings must be a JSON object")
    tasks = [(name, s, min(chunk, args.battles - s), human) for name in STYLES for s in range(0, args.battles, chunk)]
    totals = {name: {"shield": [0, 0], "bait": [0, 0]} for name in STYLES}
    squares = {name: {kind: [0, 0, 0] for kind in ("shield", "bait")} for name in STYLES}
    inputs = ["scripts/calibrate_styles.py", "pogo/engine.py", "pogo/agents.py", "pogo/learner.py",
              "pogo/battle.py", "pogo/gamedata.py", "pogo/pvpoke_ai.py", "data/gamemaster.json",
              "data/matchups.json", "runs/general-decide/q.npz"]
    hashes = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in inputs}
    checkpoint = ROOT / "runs/calibrate_styles" / f"{args.tag}.json"
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    saved = json.loads(checkpoint.read_text()) if checkpoint.exists() else dict(
        hashes=hashes, battles=args.battles, human_settings=human, chunks={})
    if saved["hashes"] != hashes or saved["battles"] != args.battles or saved["human_settings"] != human:
        raise SystemExit("calibration inputs changed; use a new --tag")
    pending = [t for t in tasks if f"{t[0]}:{t[1]}" not in saved["chunks"]]
    print(f"{len(pending)} calibration chunks to run on {args.workers} workers", flush=True)
    if pending:
        with multiprocessing.get_context("spawn").Pool(args.workers, initializer=low_priority) as pool:
            for name, start, shields, baits, sq in pool.imap_unordered(job, pending):
                saved["chunks"][f"{name}:{start}"] = [name, shields, baits, sq]
                checkpoint.write_text(json.dumps(saved))
    for name, shields, baits, sq in saved["chunks"].values():
        for kind, got in (("shield", shields), ("bait", baits)):
            totals[name][kind] = [a + b for a, b in zip(totals[name][kind], got)]
            squares[name][kind] = [a + b for a, b in zip(squares[name][kind], sq[kind])]
    out = {}
    measurements = {}
    for name, t in totals.items():
        rates = {kind: t[kind][0] / t[kind][1] if t[kind][1] else STYLES[name][kind] for kind in ("shield", "bait")}
        out[name] = {"weight": STYLES[name]["weight"], **{k: round(v, 3) for k, v in rates.items()}}
        measurements[name] = {}
        for kind, rate in rates.items():
            k2, n2, kn = squares[name][kind]
            # Ratio-estimate uncertainty, clustering all opportunities within a battle.
            variance = max(0, k2 - 2 * rate * kn + rate * rate * n2)
            margin = 1.96 * math.sqrt(args.battles / (args.battles - 1) * variance) / max(t[kind][1], 1)
            measurements[name][kind] = dict(rate=rate, margin95=margin, events=t[kind][0], opportunities=t[kind][1])
        print(f"{name:7s} " + "; ".join(f"{kind} {100 * rates[kind]:.1f}% ± "
              f"{100 * measurements[name][kind]['margin95']:.1f} ({t[kind][0]}/{t[kind][1]})" for kind in ("shield", "bait")))
    path = args.output
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"about": "Shield and bait rates of the engine's imagined opponent styles, measured by "
                                "scripts/calibrate_styles.py against the crowd; 95% margins cluster by battle.",
                                "battles": args.battles, "styles": out, "measurements": measurements, "hashes": hashes,
                                "human_settings": human},
                               indent=1) + "\n")
    print(f"written: {path}")


if __name__ == "__main__":
    main()
