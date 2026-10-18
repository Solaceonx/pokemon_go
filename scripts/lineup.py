#!/usr/bin/env python3
"""Win chance of one team against another, both known, before the first turn.

    python3 scripts/lineup.py melmetal altaria jellicent --vs corviknight tinkaton mandibuzz [--battles 400]

Teams are lead first. Our Pokémon use the owner's own IVs and moves where the owner has them
(data/owner_team.json, data/owner_roster.json), theirs the usual ones. Both sides are played by the trained
bot with its habits shifted a little each battle (pogo.lineup). Also shows the chance with each of our three
leading against their lead, the decision a player makes before the battle.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pogo.gamedata import GameData  # noqa: E402
from pogo.learner import QNet  # noqa: E402
from pogo.lineup import win_chance  # noqa: E402
from pogo.roster import builds  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mine", nargs=3, metavar="OURS")
    parser.add_argument("--vs", nargs=3, required=True, metavar="THEIRS")
    parser.add_argument("--battles", type=int, default=400)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    gd = GameData()
    pool = gd.meta(50)
    owned = builds(gd)
    net = QNet.load(str(ROOT / "runs" / "general-decide" / "q.npz"))
    mine = [owned.get(s) or gd.default(s) for s in args.mine]
    theirs = [gd.default(s) for s in args.vs]
    names = lambda team: " / ".join(b.name for b in team)  # noqa: E731
    chance, margin = win_chance(net, pool, mine, theirs, args.battles, args.seed)
    print(f"{names(mine)} against {names(theirs)}: {100 * chance:.0f}% ± {100 * margin:.0f} ({args.battles} battles)")
    for k in range(1, 3):
        order = [mine[k]] + [b for j, b in enumerate(mine) if j != k]
        c, m = win_chance(net, pool, order, theirs, args.battles, args.seed)
        print(f"  leading with {mine[k].name} instead: {100 * c:.0f}% ± {100 * m:.0f}")


if __name__ == "__main__":
    main()
