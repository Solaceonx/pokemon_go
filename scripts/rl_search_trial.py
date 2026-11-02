#!/usr/bin/env python3
"""Compare independent learned-policy planning with its pure-policy control on held-out validation teams.

All opponents use the full frozen 32-sample engine. This script never opens final test compositions.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import random
import statistics
import sys
import time

for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS'):
    os.environ[name] = '1'
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pogo.arena import low_priority
from pogo.dqn import Agent, Network
from pogo.rl_search import RolloutAgent
from scripts.double_dqn import frozen, draw_split, write_json, append, read_rows, sha, ci


def measure(run, name, net, opponents, samples, seed, pairings):
    f = frozen()
    path = run / ('rows_' + name + '.jsonl')
    identity = {'samples': samples, 'seed': seed, 'pairings': pairings, 'split': 'validation',
                'opponent_samples': 32, 'actor_sha256': sha(run / 'actor.npz'),
                'predictors': [sha(run / ('opponent_' + str(i) + '.npz')) for i in range(len(opponents))]}
    config = run / (name + '_config.json')
    if config.exists() and json.loads(config.read_text()) != identity:
        raise ValueError('Search evaluation identity changed')
    write_json(config, identity)
    done = {r['pair']: r for r in read_rows(path)}
    rng = random.Random(seed)
    started = time.monotonic()
    for i in range(pairings):
        a, b = draw_split(f.mixed_draw, rng, 'validation'), draw_split(f.mixed_draw, rng, 'validation')
        seeds = [rng.getrandbits(32) for _ in range(6)]
        if i in done:
            continue
        points, stats, elapsed = [], [], []
        for orientation, (mine, theirs) in enumerate(((a, b), (b, a))):
            player = (RolloutAgent(net, f.pool, opponents, samples=samples, edge=.03, stride=8,
                                   seed=seeds[3 * orientation]) if samples else Agent(net, seed=seeds[3 * orientation]))
            enemy = f.engine(seeds[3 * orientation + 1], 32)
            before = time.monotonic()
            result, _ = f.game(mine, theirs, player, enemy, seeds[3 * orientation + 2], side=(i + orientation) % 2)
            points.append((result + 1) / 2)
            elapsed.append(time.monotonic() - before)
            stats.append(getattr(player, 'stats', {}))
        row = {'pair': i, 'scores': points, 'mean': statistics.mean(points), 'seconds': elapsed, 'search': stats,
               'teams': [[m.home or m.species_id for m in t] for t in (a, b)]}
        append(path, row)
        done[i] = row
        if (i + 1) % 8 == 0 or i + 1 == pairings:
            print(json.dumps({'event': 'search_trial', 'variant': name, 'pairs': len(done),
                              'score': statistics.mean(r['mean'] for r in done.values()),
                              'seconds': time.monotonic() - started}), flush=True)
    values = [done[i]['mean'] for i in range(pairings)]
    result = dict(identity, **ci(values), pair_scores=values,
                  mean_battle_seconds=statistics.mean(s for row in done.values() for s in row['seconds']))
    write_json(run / (name + '_summary.json'), result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', default='search-v3')
    parser.add_argument('--refine-run', default='refine-v3')
    parser.add_argument('--pairs', type=int, default=64)
    parser.add_argument('--confirm-pairs', type=int, default=128)
    parser.add_argument('--samples', type=int, nargs='+', default=[8, 16])
    parser.add_argument('--wait', action='store_true')
    args = parser.parse_args()
    if any(Path(n).name != n for n in (args.run, args.refine_run)):
        parser.error('Use run directory names')
    low_priority()
    run = ROOT / 'runs/double-dqn' / args.run
    run.mkdir(parents=True, exist_ok=True)
    state = {'pid': os.getpid(), 'status': 'waiting_for_refinement'}
    write_json(run / 'state.json', state)
    prior = ROOT / 'runs/double-dqn' / args.refine_run
    while not (prior / 'result.json').exists():
        if not args.wait:
            raise ValueError('Complete controlled refinement first')
        if (run / 'STOP').exists():
            return
        time.sleep(15)
    selected = json.loads((prior / 'result.json').read_text())['selected']
    import shutil
    if not (run / 'actor.npz').exists():
        shutil.copyfile(prior / (selected + '.npz'), run / 'actor.npz')
    for i, name in enumerate(('ce', 'balanced_ce')):
        path = run / ('opponent_' + str(i) + '.npz')
        if not path.exists():
            shutil.copyfile(prior / (name + '.npz'), path)
    net, _, _ = Network.load(run / 'actor.npz')
    opponents = [Network.load(run / ('opponent_' + str(i) + '.npz'))[0] for i in range(2)]
    plan = {'actor_sha256': sha(run / 'actor.npz'), 'sample_grid': [0] + args.samples,
            'screen': {'pairs': args.pairs, 'seed': 38311, 'opponent_samples': 32, 'split': 'validation'},
            'confirm': {'pairs': args.confirm_pairs, 'seed': 38312, 'opponent_samples': 32, 'split': 'validation'},
            'edge': .03, 'stride': 8, 'selection': 'maximum screening score, earliest wins ties',
            'runtime': 'independent full-game Monte Carlo with neural policies; no existing rule/search player',
            'source_sha256': {str(p.relative_to(ROOT)): sha(p) for p in
                               (Path(__file__), ROOT / 'pogo/rl_search.py', ROOT / 'pogo/counterfactual.py', ROOT / 'pogo/dqn.py')},
            'baseline_commit': '59836c86f4c9ccf7e8d35ef7c94268e64c1a4ba9', 'final_tests': False}
    if (run / 'plan.json').exists() and json.loads((run / 'plan.json').read_text()) != plan:
        raise ValueError('Search trial identity changed')
    write_json(run / 'plan.json', plan)
    scores = []
    for samples in [0] + args.samples:
        name = 'policy' if not samples else 'mc' + str(samples)
        state.update(status='screening', variant=name)
        write_json(run / 'state.json', state)
        report = measure(run, name, net, opponents, samples, 38311, args.pairs)
        scores.append((samples, report))
    selected_samples, screen = max(scores, key=lambda item: item[1]['score'])
    write_json(run / 'selection.json', {'samples': selected_samples, 'screen': screen, 'rule': plan['selection']})
    state.update(status='confirmation', variant='mc' + str(selected_samples))
    write_json(run / 'state.json', state)
    confirmed = measure(run, 'confirmation', net, opponents, selected_samples, 38312, args.confirm_pairs)
    write_json(run / 'result.json', {'selected_samples': selected_samples,
                                   'screens': {str(k): v for k, v in scores}, 'confirmation': confirmed,
                                   'final_test_opened': False})
    state['status'] = 'complete'
    write_json(run / 'state.json', state)


if __name__ == '__main__':
    main()
