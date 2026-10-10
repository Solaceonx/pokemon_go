#!/usr/bin/env python3
"""Look for teams that do better than a given one, in simulation.

    python3 scripts/better_teams.py [--top 8] [--swaps 12] [--battles 400] [--finals 1200] [--workers 4]

Candidates are the given team (the owner's, with their real moves), the best teams from the team search
(data/teams.json), and the given team with one Pokémon changed for another from the top 50. Every candidate
plays the same battles, piloted by the best bot, against the usual crowd of opponents on teams drawn half from
the good-team list and half at random. The few that come out ahead are then played again on fresh battles,
each with every choice of lead, and only that second round is reported: picking the best of many from one round
flatters the pick.
"""
from __future__ import annotations

import argparse
import itertools
import json
import multiprocessing
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pogo.agents import Planner, varied  # noqa: E402
from pogo.arena import field_results, mean_and_margin  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.teamlist import drawer  # noqa: E402

OWNER = {  # the owner's team as they run it
    "melmetal": ["THUNDER_SHOCK", "DOUBLE_IRON_BASH", "DYNAMIC_PUNCH"],
    "altaria": ["DRAGON_BREATH", "SKY_ATTACK", "FLAMETHROWER"],
    "jellicent": ["HEX", "SURF", "SHADOW_BALL"],
}
_state: dict = {}


def build(gd: GameData, species: str):
    return gd.build(species, OWNER[species]) if species in OWNER else gd.default(species)


def setup() -> None:
    gd = GameData()
    pool = gd.meta(50)
    q = ROOT / "runs" / "general-decide" / "q.npz"
    if q.exists():
        from pogo.learner import Learner, QNet
        net = QNet.load(str(q))
        pilot = lambda: Learner(q=net, margin=0.02)  # noqa: E731
    else:
        pilot = lambda: Planner()  # noqa: E731
    _state.update(gd=gd, pool=pool, pilot=pilot, draw=drawer(gd, pool))


def play(job):
    team, battles, seed = job
    s = _state
    mine = [build(s["gd"], sp) for sp in team]
    return team, field_results(mine, s["pool"], s["pilot"], lambda rng: varied(rng, s["pool"]), battles, seed, draw=s["draw"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--team", nargs=3, default=list(OWNER), metavar="SPECIES", help="lead first")
    parser.add_argument("--top", type=int, default=8, help="teams to take from the team search")
    parser.add_argument("--swaps", type=int, default=12, help="one-change versions of the team to try")
    parser.add_argument("--battles", type=int, default=400)
    parser.add_argument("--finals", type=int, default=1200)
    parser.add_argument("--keep", type=int, default=4)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    setup()
    gd, pool = _state["gd"], _state["pool"]
    ref = tuple(args.team)
    listed = [tuple(e["team"]) for e in json.loads((ROOT / "data" / "teams.json").read_text())["teams"]]
    candidates = [ref] + [t for t in listed if set(t) != set(ref)][:args.top]

    # One-change versions, picked by the quick score the team search uses: its best two answers to each opponent.
    from teams import matchups
    everyone = pool + [build(gd, sp) for sp in ref if sp not in {b.species_id for b in pool}]
    table = matchups(everyone)
    index = {b.species_id: k for k, b in enumerate(everyone)}
    dex = {b.species_id: gd.species[b.species_id]["dex"] for b in everyone}

    def quick(team) -> float:
        return sum(sum(sorted(table[index[sp]][o] for sp in team)[1:]) / 2 for o in range(len(pool))) / len(pool)

    swaps = []
    for slot, new in itertools.product(range(3), [b.species_id for b in pool]):
        team = tuple(new if k == slot else sp for k, sp in enumerate(ref))
        if new not in ref and len({dex[sp] for sp in team}) == 3:
            swaps.append(team)
    swaps.sort(key=quick, reverse=True)
    candidates += [t for t in swaps[:args.swaps] if t not in candidates]
    print(f"{len(candidates)} teams, {args.battles} battles each; pilot: {'the trained bot' if (ROOT / 'runs/general-decide/q.npz').exists() else 'the Planner'}", flush=True)

    with multiprocessing.Pool(args.workers, initializer=setup) as workers:
        first = dict(workers.map(play, [(t, args.battles, args.seed) for t in candidates]))
        base = first[ref]
        ranked = sorted(candidates, key=lambda t: -sum(first[t]))
        print("first round (the same battles for every team):")
        for t in ranked:
            mean, margin = mean_and_margin(first[t])
            diff, dm = mean_and_margin([a - b for a, b in zip(first[t], base)])
            print(f"  {' / '.join(t):52s} {100 * mean:5.1f}% ± {100 * margin:.1f}   {100 * diff:+5.1f} ± {100 * dm:.1f} against the given team", flush=True)
        finalists = [ref] + [t for t in ranked if t != ref][:args.keep]
        jobs = [(order, args.finals, args.seed + 1000) for t in finalists for order in itertools.permutations(t) if order[1] < order[2] or True]
        jobs = [(t[k:] + t[:k], args.finals, args.seed + 1000) for t in finalists for k in range(3)]  # each one as lead
        second = dict(workers.map(play, jobs))
    best = {t: max((t[k:] + t[:k] for k in range(3)), key=lambda order: sum(second[order])) for t in finalists}
    base = second[best[ref]]
    print(f"second round, fresh battles, {args.finals} each, every lead tried (best lead first in each line):")
    for t in sorted(finalists, key=lambda t: -sum(second[best[t]])):
        order = best[t]
        mean, margin = mean_and_margin(second[order])
        diff, dm = mean_and_margin([a - b for a, b in zip(second[order], base)])
        leads = ", ".join(f"{o[0]} {100 * sum(second[o]) / len(second[o]):.1f}" for o in (t[k:] + t[:k] for k in range(3)))
        print(f"  {' / '.join(order):52s} {100 * mean:5.1f}% ± {100 * margin:.1f}   {100 * diff:+5.1f} ± {100 * dm:.1f} against the given team | by lead: {leads}")


if __name__ == "__main__":
    main()
