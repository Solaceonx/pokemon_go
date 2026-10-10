#!/usr/bin/env python3
"""Measure EndgameThrows (pogo/hybrid.py): our player, with PvPoke's throws in the final 1v1.

Each player is tested with and without it, against PvPoke's AI in 1v1 (where the port is
faithful) and against the old opponents in 3v3 (the varied crowd, the expert model, and the
Planner). Each pairing is two battles with the teams swapped.

    python3 scripts/check_endgame_throws.py                  Planner and the best Learner
    python3 scripts/check_endgame_throws.py --pairings 200   fewer battles
    python3 scripts/check_endgame_throws.py --seed 5         other battles

Note: in 1v1 the final one-on-one is the whole battle, so there EndgameThrows throws exactly
as PvPoke does and the score is close to a mirror match. The 3v3 columns are the check that it
costs nothing elsewhere.
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pogo.agents import Planner, expert, varied  # noqa: E402
from pogo.arena import compare  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.hybrid import EndgameThrows  # noqa: E402
from pogo.learner import Learner, QNet  # noqa: E402
from pogo.pvpoke_ai import PvpokeAI  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pairings", type=int, default=500, help="team pairings per 3v3 cell; 1v1 uses twice as many")
    parser.add_argument("--seed", type=int, default=101)
    parser.add_argument("--model", default="runs/general-decide", help="folder with the Learner's q.npz and margin.txt")
    args = parser.parse_args()

    pool = GameData().meta(50)
    folder = ROOT / args.model
    q = QNet.load(folder / "q.npz")
    margin = float((folder / "margin.txt").read_text())
    players = {
        "Planner": Planner,
        "Planner + EndgameThrows": lambda: EndgameThrows(Planner()),
        "Learner": lambda: Learner(q=q, margin=margin),
        "Learner + EndgameThrows": lambda: EndgameThrows(Learner(q=q, margin=margin)),
    }
    print(f"PvPoke 1v1: {4 * args.pairings} battles. 3v3: {2 * args.pairings} battles. Seed {args.seed}. "
          "Score is wins plus half of draws, with a 95% margin.\n")
    print(f"{'':26s} {'PvPoke 1v1':>14s} {'varied 3v3':>14s} {'expert 3v3':>14s} {'Planner 3v3':>14s}")
    for label, make in players.items():
        rng = random.Random(args.seed)
        cells = [
            compare(make, PvpokeAI, pool, pairings=2 * args.pairings, seed=args.seed, team_size=1),
            compare(make, lambda: varied(rng, pool), pool, pairings=args.pairings, seed=args.seed),
            compare(make, lambda: expert(pool), pool, pairings=args.pairings, seed=args.seed),
            compare(make, Planner, pool, pairings=args.pairings, seed=args.seed),
        ]
        print(f"{label:26s} " + " ".join(f"{100 * c.score:7.1f} ± {100 * c.margin:3.1f}" for c in cells), flush=True)


if __name__ == "__main__":
    main()
