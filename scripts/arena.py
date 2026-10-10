#!/usr/bin/env python3
"""Measure the players against each other in simulated Great League battles.

    python3 scripts/arena.py                 the Planner against the expert model, with sanity checks
    python3 scripts/arena.py --parts         each part of the Planner on its own, against the Masher
    python3 scripts/arena.py --learner runs/default/best.npz   a policy trained by scripts/selfplay.py
    python3 scripts/arena.py --pairings 200  fewer battles (each pairing is two battles)
    python3 scripts/arena.py --show 7        print one battle, seed 7, move by move
"""
from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pogo.agents import STYLES, Masher, Planner, expert  # noqa: E402
from pogo.arena import compare  # noqa: E402
from pogo.battle import DRAW, Battle  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402

PARTS = {
    "Planner (every part)": lambda: Planner(),
    "  move choice only": lambda: Planner(timing=False, bait="cheap", shields="always", switches=False),
    "  move choice with timing": lambda: Planner(bait="cheap", shields="always", switches=False),
    "  shields by threshold only": lambda: Planner(moves=False, shields="threshold", switches=False),
    "  shields by lookahead only": lambda: Planner(moves=False, shields="lookahead", switches=False),
    "  switching only": lambda: Planner(moves=False, shields="always"),
    "Masher (baseline, sanity check)": Masher,
}


def show(pool, seed: int) -> None:
    rng = random.Random(seed)
    teams = rng.sample(pool, 3), rng.sample(pool, 3)
    names = ("Planner", "Masher")
    for name, team in zip(names, teams):
        print(f"{name}: " + ", ".join(f"{b.name} ({b.fast.name} / {' / '.join(m.name for m in b.charged)})" for b in team))
    battle = Battle(*teams, Planner(), Masher(), seed=seed, record=True)
    winner = battle.run()
    print()
    for turn, side, text in battle.log:
        print(f"  {turn * 0.5:6.1f}s  {names[side]:8s} {text}")
    print("\nresult:", "draw" if winner == DRAW else f"{names[winner]} wins", f"after {battle.turn * 0.5:.0f}s")
    for name, side in zip(names, battle.sides):
        print(f"  {name}: {side.shields} shields left; " + ", ".join(repr(m) for m in side.team))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pairings", type=int, default=500, help="team pairings per comparison (two battles each)")
    parser.add_argument("--pool", type=int, default=50, help="draw teams from this many top-ranked Pokémon")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--show", type=int, metavar="SEED", help="print one battle instead")
    parser.add_argument("--parts", action="store_true", help="measure each part of the Planner against the Masher")
    parser.add_argument("--learner", metavar="FILE", help="test a trained policy, e.g. runs/default/best.npz")
    args = parser.parse_args()

    pool = GameData().meta(args.pool)
    if args.show is not None:
        show(pool, args.show)
        return

    print(f"Great League, random teams of 3 from the top {len(pool)} Pokémon, {2 * args.pairings} battles per row")
    print("Score is wins plus half of draws, with a 95% margin.\n")
    if args.learner:
        from pogo.learner import Learner, Policy
        policy = Policy.load(args.learner)
        trained = lambda: Learner(policy=policy)  # noqa: E731
        rows = [("Learner against the Planner", trained, Planner),
                ("Learner against the expert model", trained, lambda: expert(pool)),
                ("Learner against masher", trained, Masher)]
    elif args.parts:
        rows = [(label, make, Masher) for label, make in PARTS.items()]
    else:
        strong = lambda: expert(pool)  # noqa: E731
        rows = [("Planner against the expert model", Planner, strong),
                ("Expert model against itself", strong, strong)]
        rows += [(f"Planner against {name}", Planner, style) for name, style in STYLES.items()]
    for label, make, opponent in rows:
        t0 = time.perf_counter()
        result = compare(make, opponent, pool, pairings=args.pairings, seed=args.seed)
        rate = result.games / (time.perf_counter() - t0)
        print(f"{label:34s} {result}   {result.turns * 0.5:.0f}s avg, {rate:.0f} battles/s")


if __name__ == "__main__":
    main()
