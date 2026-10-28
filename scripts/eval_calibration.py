#!/usr/bin/env python3
"""How accurate the website's "how the game is going" graph is (the owner asked).

    python3 scripts/eval_calibration.py [--battles 400] [--seed 21]

The graph plots the engine's learned evaluation (runs/eval/eval.npz, pogo.evaluation) from the person's side after
every turn. Here: the trained bot against the crowd on the mixed field, the evaluation from the bot's side every 10
turns, scored against how the battle ended: calibration by tenths (when it says 70%, how often does that side win?),
the Brier score and log loss against a constant 50% and against the base rate, and how good it is early, middle and
late in the battle. Also the website games (games/played/*-web.json), replayed from their logs, from the person's side.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
from pogo.agents import varied  # noqa: E402
from pogo.battle import DRAW, Battle  # noqa: E402
from pogo.evaluation import Evaluator  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.learner import Learner, QNet  # noqa: E402
from pogo.teamshape import mixed_field  # noqa: E402


def score(rows, label):
    if not rows:
        return
    n = len(rows)
    base = sum(y for _, y, _ in rows) / n
    brier = sum((p - y) ** 2 for p, y, _ in rows) / n
    ll = -sum(y * math.log(max(p, 1e-4)) + (1 - y) * math.log(max(1 - p, 1e-4)) for p, y, _ in rows) / n
    ll0 = -sum(y * math.log(base) + (1 - y) * math.log(1 - base) for _, y, _ in rows) / n if 0 < base < 1 else float("nan")
    right = sum((p > 0.5) == (y > 0.5) for p, y, _ in rows if p != 0.5 and y != 0.5) / max(1, sum(1 for p, y, _ in rows if p != 0.5 and y != 0.5))
    print(f"\n{label}: {n} positions; Brier {brier:.3f} (0.25 for always saying 50%), log loss {ll:.3f} (base rate alone "
          f"{ll0:.3f}); the side it favours wins {100 * right:.0f}% of the time")
    print("  it said     side won    positions")
    for lo in range(0, 100, 10):
        bucket = [(p, y) for p, y, _ in rows if lo / 100 <= p < (lo + 10) / 100 or (lo == 90 and p == 1.0)]
        if bucket:
            print(f"  {lo:2d}-{lo + 10:3d}%   {100 * sum(y for _, y in bucket) / len(bucket):5.0f}%      {len(bucket)}")
    for stage, (a, b) in (("first third", (0, 1 / 3)), ("middle third", (1 / 3, 2 / 3)), ("last third", (2 / 3, 1.01))):
        part = [(p, y) for p, y, f in rows if a <= f < b]
        if part:
            r = sum((p > 0.5) == (y > 0.5) for p, y in part if p != 0.5 and y != 0.5) / max(1, sum(1 for p, y in part if p != 0.5 and y != 0.5))
            print(f"  {stage}: favoured side wins {100 * r:.0f}% ({len(part)} positions)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--battles", type=int, default=400)
    parser.add_argument("--seed", type=int, default=21)
    args = parser.parse_args()
    gd = GameData()
    pool, draw = mixed_field(gd)
    net = QNet.load(str(ROOT / "runs" / "general-decide" / "q.npz"))
    model = Evaluator.load(ROOT / "runs" / "eval" / "eval.npz").model
    rng = random.Random(args.seed)
    rows = []
    for n in range(args.battles):
        a, b = draw(rng), draw(rng)
        battle = Battle(a, b, Learner(q=net, margin=0.02, seed=n), varied(rng, pool), seed=rng.getrandbits(32))
        ev = Evaluator(model)
        seen = []
        while battle.winner is None:
            battle.step()
            if battle.winner is None and battle.turn % 10 == 0 and battle.sides[0].mon.hp > 0 and battle.sides[1].mon.hp > 0:
                seen.append((float(ev(battle.views[0])), battle.turn))
        y = 1.0 if battle.winner == 0 else 0.5 if battle.winner == DRAW else 0.0
        rows += [(p, y, t / max(battle.turn, 1)) for p, t in seen]
    score(rows, f"{args.battles} simulated battles (the bot against the crowd, mixed field)")
    import losses as L
    L.setup()
    web = []
    for f in sorted(glob.glob(str(ROOT / "games" / "played" / "*-web.json"))):
        saved = json.loads(Path(f).read_text())
        if saved.get("evaluation"):
            y = 1.0 if saved["result"] == "win" else 0.5 if saved["result"] == "draw" else 0.0
            end = max(t for t, _ in saved["evaluation"]) or 1
            web += [(p, y, t / end) for t, p in saved["evaluation"]]
    score(web, "the website games, as their graphs showed them (the person's side)")


if __name__ == "__main__":
    main()
