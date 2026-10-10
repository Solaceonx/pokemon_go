#!/usr/bin/env python3
"""Exact-endgame checks, timing and a held-out paired comparison with the best bot."""
import argparse
import os
from pathlib import Path
import random
import sys
import time

for var in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[var] = '1'
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from test_endgame import position, brute_one_turn, brute_no_shields
from pogo.arena import mean_and_margin
from pogo.battle import Battle
from pogo.endgame import Solver, SolveLimit, EndgamePlayer
from pogo.gamedata import GameData
from pogo.learner import Learner, QNet


def checks(args):
    count = 0
    for shields in range(3):
        for energy in (0, 40, 60, 100):
            b = position(shields)
            b.sides[0].mon.energy = energy
            assert abs(Solver(seconds=30).solve(b).value - brute_one_turn(b)) < 1e-9
            count += 1
    print(f'Independent brute-force agreement: {count}/{count} (tolerance 1e-9)', flush=True)
    for size in ((1, 1), (2, 1), (2, 2)):
        b = position(0, size, turns=2)
        assert abs(Solver(seconds=30).solve(b).value - brute_no_shields(b)) < 1e-9
    print('Independent multi-turn brute-force agreement: 3/3 (1v1, 2v1, 2v2)', flush=True)
    count = 0
    for size in ((1, 1), (2, 1), (2, 2)):
        for shields in range(3):
            b = position(shields, size, turns=2)
            a = Solver(seconds=30).solve(b).value
            c = Solver(seconds=30, memo=False).solve(b).value
            assert abs(a - c) < 1e-9
            count += 1
    print(f'Uncached exhaustive-tree agreement: {count}/{count} (1v1, 2v1, 2v2)', flush=True)
    for size in ((1, 1), (2, 1), (2, 2)):
        for shields in range(3):
            b = position(shields, size, turns=480)
            solver = Solver(max_nodes=args.solve_nodes, seconds=args.solve_seconds)
            start = time.perf_counter()
            try:
                result = solver.solve(b)
                label = f'value={result.value:.6f}'
            except SolveLimit:
                label = 'LIMIT (no exact answer)'
            print(f'Timing {size[0]}v{size[1]} shields={shields}/{shields}: '
                  f'{time.perf_counter()-start:.6f}s nodes={solver.nodes} {label}', flush=True)


def measure(args):
    q = QNet.load(ROOT / args.model)
    pool = GameData().meta(50)
    rng = random.Random(args.seed)
    scores, baselines, deltas = [], [], []
    solved = limited = 0
    start = time.perf_counter()
    for pair in range(args.pairings):
        teams = rng.sample(pool, 3), rng.sample(pool, 3)
        points, controls = [], []
        for mine, theirs in (teams, teams[::-1]):
            dice, pilot_seed, opponent_seed = [rng.getrandbits(32) for _ in range(3)]
            player = EndgamePlayer(q=q, margin=.02, seed=pilot_seed,
                                   seconds=args.seconds, max_nodes=args.max_nodes)
            best = lambda seed: Learner(q=q, margin=.02, seed=seed)
            winner = Battle(mine, theirs, player, best(opponent_seed), seed=dice).run()
            control = Battle(mine, theirs, best(pilot_seed), best(opponent_seed), seed=dice).run()
            points.append(.5 if winner == -1 else float(winner == 0))
            controls.append(.5 if control == -1 else float(control == 0))
            solved += player.solved
            limited += player.limited
        scores.append(sum(points)/2)
        baselines.append(sum(controls)/2)
        deltas.append(scores[-1] - baselines[-1])
        if (pair + 1) % 25 == 0:
            print(f'Progress: {pair+1}/{args.pairings} pairings, '
                  f'{time.perf_counter()-start:.1f}s', flush=True)
    for label, values in [('Endgame vs best', scores), ('Learner vs best, same battles', baselines),
                          ('Paired improvement (points)', deltas)]:
        mean, margin = mean_and_margin(values)
        print(f'{label}: {100*mean:.3f} +/- {100*margin:.3f} (95%)', flush=True)
    print(f'{2*args.pairings} battles per player; seed={args.seed}; '
          f'solved decisions={solved}; capped decisions={limited}; '
          f'elapsed={time.perf_counter()-start:.3f}s', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--measure', action='store_true')
    parser.add_argument('--solve-nodes', type=int, default=20000)
    parser.add_argument('--solve-seconds', type=float, default=5)
    parser.add_argument('--pairings', type=int, default=150)
    parser.add_argument('--seed', type=int, default=90261019)
    parser.add_argument('--seconds', type=float, default=.05)
    parser.add_argument('--max-nodes', type=int, default=1000)
    parser.add_argument('--model', default='runs/general-decide/q.npz')
    args = parser.parse_args()
    if args.measure:
        if args.pairings < 2:
            parser.error('at least two pairings required for a margin')
        measure(args)
    else:
        checks(args)
