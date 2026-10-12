#!/usr/bin/env python3
"""Try a change to the standard player against the standard player.

    python3 scripts/rule_trial.py "last_gasp=True" "timed_farm=True" "last_gasp=True,timed_farm=True" [--battles 4000] [--seed 41]

Each quoted setting is a set of Planner options. For each: head to head against the standard player on random
teams (each pair of teams played both ways), and against the usual crowd on the same battles as the standard
player. Also how much energy our fainted Pokémon took with them while a charged move was ready.
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pogo.agents import Planner, varied  # noqa: E402
from pogo.arena import compare, field_results, mean_and_margin  # noqa: E402
from pogo.battle import Battle  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.teamlist import drawer  # noqa: E402


def wasted(pool, draw, settings: dict, battles: int, seed: int) -> float:
    """Energy per battle left on our fainted Pokémon that had a charged move ready."""
    rng, total = random.Random(seed), 0
    for _ in range(battles):
        b = Battle(draw(rng), draw(rng), Planner(seed=rng.getrandbits(30), **settings), varied(rng, pool), seed=rng.getrandbits(32))
        b.run()
        total += sum(m.energy for m in b.sides[0].team if m.hp <= 0 and m.energy >= min(c.energy for c in m.build.charged))
    return total / battles


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("settings", nargs="+")
    parser.add_argument("--battles", type=int, default=4000)
    parser.add_argument("--seed", type=int, default=41)
    args = parser.parse_args()
    gd = GameData()
    pool = gd.meta(50)
    draw = drawer(gd, pool)
    crowd = lambda rng: varied(rng, pool)  # noqa: E731
    base = field_results(None, pool, lambda: Planner(), crowd, args.battles, args.seed + 1, draw=draw)
    mean, margin = mean_and_margin(base)
    print(f"battles: {args.battles}; seed: {args.seed}", flush=True)
    print(f"standard player against the crowd: {100 * mean:.1f}% ± {100 * margin:.1f}; energy thrown away with a move ready: {wasted(pool, draw, {}, 800, args.seed + 2):.1f} a battle", flush=True)
    for text in args.settings:
        settings = eval(f"dict({text})")  # noqa: S307 - our own command line
        head = compare(lambda: Planner(**settings), lambda: Planner(), pool, pairings=args.battles // 2, seed=args.seed)
        mine = field_results(None, pool, lambda: Planner(**settings), crowd, args.battles, args.seed + 1, draw=draw)
        mean, mine_margin = mean_and_margin(mine)
        diff, margin = mean_and_margin([a - b for a, b in zip(mine, base)])
        print(f"{text}: head to head {100 * head.score:.1f}% ± {100 * head.margin:.1f} | against the crowd {100 * mean:.1f}% ± {100 * mine_margin:.1f}, "
              f"{100 * diff:+.1f} ± {100 * margin:.1f} | energy thrown away {wasted(pool, draw, settings, 800, args.seed + 2):.1f} a battle", flush=True)


if __name__ == "__main__":
    main()
