#!/usr/bin/env python3
"""Test the owner's rule: keep farming energy until the opponent is about to get a charged move,
as long as it does not cost too much health (Planner(hold=True, hold_cost=...)).

    python3 scripts/hold_rule.py [--battles 3000] [--seed 11]

For each setting of hold_cost (the share of current health their fast moves may take while we wait):
  - head to head against the same player without the rule, random teams, each pair of teams played both ways;
  - against the usual crowd of opponents, on the same battles as the player without the rule.
The setting that looks best is then played again on fresh battles, because picking the best of several flatters it.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pogo.agents import Planner, varied  # noqa: E402
from pogo.arena import compare, field_results, mean_and_margin  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.teamlist import drawer  # noqa: E402


def trial(pool, draw, cost: float, battles: int, seed: int) -> tuple[str, float]:
    head = compare(lambda: Planner(hold=True, hold_cost=cost), lambda: Planner(), pool, pairings=battles // 2, seed=seed)
    crowd = lambda rng: varied(rng, pool)  # noqa: E731
    plain = field_results(None, pool, lambda: Planner(), crowd, battles, seed + 1, draw=draw)
    held = field_results(None, pool, lambda: Planner(hold=True, hold_cost=cost), crowd, battles, seed + 1, draw=draw)
    diff, margin = mean_and_margin([a - b for a, b in zip(held, plain)])
    text = (f"head to head {100 * head.score:5.1f}% ± {100 * head.margin:.1f} | against the crowd {100 * sum(held) / len(held):5.1f}% "
            f"(without the rule {100 * sum(plain) / len(plain):5.1f}%), difference {100 * diff:+.1f} ± {100 * margin:.1f}")
    return text, (head.score - 0.5) + diff


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--battles", type=int, default=3000)
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--costs", type=float, nargs="+", default=[0.1, 0.2, 0.3, 0.5, 1.0])
    args = parser.parse_args()
    gd = GameData()
    pool = gd.meta(50)
    draw = drawer(gd, pool)
    best = None
    for cost in args.costs:
        text, gain = trial(pool, draw, cost, args.battles, args.seed)
        print(f"may cost {cost:4.0%} of health: {text}", flush=True)
        if best is None or gain > best[1]:
            best = (cost, gain)
    text, _ = trial(pool, draw, best[0], 2 * args.battles, args.seed + 5000)
    print(f"again on fresh battles, {best[0]:.0%}: {text}")


if __name__ == "__main__":
    main()
