#!/usr/bin/env python3
"""Controlled unweighted/balanced CE warm-up experiments before counterfactual RL.

python scripts/dqn_refine.py --run refine-v3 --epochs 60
Uses training compositions only, selects on validation; never opens final tests.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import time

for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS'):
    os.environ[name] = '1'
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pogo.arena import low_priority
from pogo.dqn import Network
from pogo.counterfactual import imitate
from scripts.double_dqn import evaluate, sha, write_json, append


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', default='refine-v3')
    parser.add_argument('--epochs', type=int, default=60)
    parser.add_argument('--rate', type=float, default=1e-4)
    parser.add_argument('--screen-pairs', type=int, default=64)
    parser.add_argument('--confirm-pairs', type=int, default=128)
    args = parser.parse_args()
    if Path(args.run).name != args.run:
        parser.error('Use a run directory name')
    low_priority()
    run = ROOT / 'runs/double-dqn' / args.run
    run.mkdir(parents=True, exist_ok=True)
    source = ROOT / 'runs/double-dqn/dqn-v2'
    plan = {'hypothesis': 'Overall imitation hides low charged-action recall; test CE and balanced CE with equal epochs',
            'source_model_sha256': sha(source / 'bootstrap.npz'), 'seed': 38101,
            'source_code_sha256': {str(p.relative_to(ROOT)): sha(p) for p in
                                   (Path(__file__), ROOT / 'pogo/counterfactual.py', ROOT / 'pogo/dqn.py')},
            'epochs': args.epochs, 'rate': args.rate, 'batch': 256,
            'balance': 'inverse square root of training action frequencies, normalized and clipped .25..4',
            'screen': {'seed': 38111, 'pairs': args.screen_pairs, 'samples': 8, 'split': 'validation'},
            'confirm': {'seed': 38112, 'pairs': args.confirm_pairs, 'samples': 32, 'split': 'validation'},
            'selection': 'maximum screening win share, earliest variant wins ties', 'final_tests': False}
    if (run / 'plan.json').exists() and json.loads((run / 'plan.json').read_text()) != plan:
        raise ValueError('Refinement plan changed')
    write_json(run / 'plan.json', plan)
    with np.load(source / 'demonstrations.npz', allow_pickle=False) as data:
        x, masks, actions = data['x'], data['mask'], data['action']
    frequencies = np.bincount(actions, minlength=9)
    balanced = 1 / np.sqrt(np.maximum(frequencies, 1))
    balanced /= np.mean(balanced[actions])
    balanced = np.clip(balanced, .25, 4)
    reports = []
    for kind in ('baseline', 'ce', 'balanced_ce'):
        path = run / (kind + '.npz')
        if kind == 'baseline':
            if not path.exists():
                shutil.copyfile(source / 'bootstrap.npz', path)
            net, _, _ = Network.load(path)
        else:
            if path.exists():
                net, meta, _ = Network.load(path)
                first = meta['epoch']
                rng = np.random.default_rng()
                rng.bit_generator.state = meta['numpy_rng']
            else:
                net, _, _ = Network.load(source / 'bootstrap.npz')
                net.steps = 0
                for p in net.m + net.v:
                    p.fill(0)
                first, rng = 0, np.random.default_rng(38101)
            for epoch in range(first, args.epochs):
                start = time.monotonic()
                ids = rng.permutation(len(actions))
                losses = []
                for offset in range(0, len(ids), 256):
                    rows = ids[offset:offset + 256]
                    weights = balanced[actions[rows]] if kind == 'balanced_ce' else None
                    losses.append(imitate(net, x[rows], masks[rows], actions[rows], weights, rate=args.rate))
                ix = np.arange(min(20000, len(actions)))
                vote = np.where(masks[ix], net.predict(x[ix]), -np.inf).argmax(axis=1)
                recalls = {str(a): float(np.mean(vote[actions[ix] == a] == a)) for a in range(9)}
                meta = {'epoch': epoch + 1, 'variant': kind, 'numpy_rng': rng.bit_generator.state,
                        'training_agreement': float(np.mean(vote == actions[ix])), 'training_recall': recalls}
                net.save(path, meta)
                row = dict(meta, numpy_rng=None, loss=float(np.mean(losses)), seconds=time.monotonic() - start)
                append(run / 'training.jsonl', row)
                print(json.dumps(row), flush=True)
        report = evaluate(run, net, path, 'validation', 38111, args.screen_pairs, samples=8, tag='screen_' + kind)
        reports.append((kind, report))
    selected, screen = max(reports, key=lambda item: item[1]['score'])
    write_json(run / 'selection.json', {'variant': selected, 'sha256': sha(run / (selected + '.npz')),
                                      'screen': screen, 'rule': plan['selection']})
    net, _, _ = Network.load(run / (selected + '.npz'))
    confirmation = evaluate(run, net, run / (selected + '.npz'), 'validation', 38112, args.confirm_pairs,
                            samples=32, tag='confirmation')
    write_json(run / 'result.json', {'selected': selected, 'screening': dict(reports), 'confirmation': confirmation,
                                   'final_test_opened': False})


if __name__ == '__main__':
    main()
