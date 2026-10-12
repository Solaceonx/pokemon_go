"""Does it pay to treat the opponent's moves as chances rather than as their usual set?

    python3 scripts/moveset_odds.py [--battles 600] [--seed 1]

Opponents get movesets drawn from GameData.move_odds, so they often carry a move outside the usual set. Our
player sees only what a screen shows (it plays from the Tracker's picture, which learns a charged move when it
is thrown). The same battles are played twice: once deciding shields as if their usual two moves were certain,
once weighing every move they may have by its chance (Planner(odds=True)). Reports both win rates and the
difference with its margin.
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_tracker  # noqa: E402
from pogo.agents import Planner  # noqa: E402
from pogo.arena import mean_and_margin  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402


def drawn(gd: GameData, build, rng: random.Random):
    """The same Pokémon with a moveset drawn from the odds for its species."""
    odds = gd.move_odds(build.species_id)
    fast = rng.choices(list(odds["fast"]), weights=list(odds["fast"].values()))[0]
    pool, charged = dict(odds["charged"]), []
    while pool and len(charged) < 2:
        pick = rng.choices(list(pool), weights=list(pool.values()))[0]
        charged.append(pick)
        del pool[pick]
    return gd.build(build.species_id, [fast, *charged])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--battles", type=int, default=600)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    gd = GameData()
    pool = [gd.default(b.species_id) for b in gd.meta(40)]
    rng = random.Random(args.seed)
    wins = {False: [], True: []}
    unusual = total = 0
    for k in range(args.battles):
        mine = rng.sample(pool, 3)
        theirs = [drawn(gd, b, rng) for b in rng.sample(pool, 3)]
        for b in theirs:
            usual = gd.default(b.species_id)
            total += 1
            unusual += {m.id for m in b.charged} != {m.id for m in usual.charged} or b.fast.id != usual.fast.id
        seed = rng.getrandbits(32)
        for use_odds in (False, True):
            agents = (check_tracker.ViaTracker(Planner(seed=seed, odds=use_odds)), Planner(seed=seed))
            winner = check_tracker.play(gd, (mine, theirs), agents, seed, check_tracker.CAMERAS["perfect"], None, random.Random(seed))
            wins[use_odds].append(1.0 if winner == 0 else 0.5 if winner == check_tracker.DRAW else 0.0)
    print(f"{args.battles} battles; {100 * unusual / total:.0f}% of opposing Pokémon carried something other than the usual moveset")
    for use_odds, label in ((False, "their usual moves taken as certain"), (True, "every move they may have, by its chance")):
        mean, margin = mean_and_margin(wins[use_odds])
        print(f"  {label:42s} {100 * mean:.1f}% ± {100 * margin:.1f}")
    mean, margin = mean_and_margin([b - a for a, b in zip(wins[False], wins[True])])
    print(f"  difference {100 * mean:+.1f} ± {100 * margin:.1f} points (same battles for both)")


if __name__ == "__main__":
    main()
