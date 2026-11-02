#!/usr/bin/env python3
"""Audit fitted actions by decision type; this is training diagnosis, never playing-strength evidence."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS'):
    os.environ[name] = '1'
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pogo.arena import low_priority
from pogo.dqn import Network


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', default='dqn-v2')
    parser.add_argument('--sample', type=int, default=20000)
    args = parser.parse_args()
    low_priority()
    run = ROOT / 'runs/double-dqn' / args.run
    with np.load(run / 'demonstrations.npz', allow_pickle=False) as data:
        n = int(data['size'])
        ids = np.random.default_rng(38051).choice(n, min(args.sample, n), replace=False)
        x, mask, action = data['x'][ids], data['mask'][ids], data['action'][ids]
    slot = json.loads((run / 'resume.json').read_text())['slot']
    models = ['bootstrap.npz', 'candidate_stage_1.npz', f'latest_{slot}.npz']
    result = {'purpose': 'Training-data action audit, not held-out strength', 'sample': len(ids), 'models': {}}
    for name in models:
        net, meta, _ = Network.load(run / name)
        predictions = []
        for start in range(0, len(ids), 1024):
            votes = net.predict(x[start:start + 1024])
            predictions.extend(np.where(mask[start:start + 1024], votes, -np.inf).argmax(axis=1))
        predicted = np.asarray(predictions)
        confusion = np.zeros((9, 9), dtype=int)
        np.add.at(confusion, (action, predicted), 1)
        row = {'games': meta.get('games'), 'agreement': float(np.mean(predicted == action)),
               'confusion_teacher_rows_predicted_columns': confusion.tolist(), 'heads': {}, 'actions': {}}
        for kind, feature in (('act', 10), ('shield', 11), ('replace', 12)):
            pick = x[:, feature] > .5
            row['heads'][kind] = {'n': int(pick.sum()), 'agreement': float(np.mean(predicted[pick] == action[pick]))}
        for a in range(9):
            pick = action == a
            row['actions'][str(a)] = {'teacher_n': int(pick.sum()), 'predicted_n': int((predicted == a).sum()),
                                      'recall': float(np.mean(predicted[pick] == a)) if pick.any() else None}
        result['models'][name] = row
        print(json.dumps({'model': name, 'games': row['games'], 'agreement': row['agreement'],
                          'heads': row['heads'], 'actions': row['actions']}), flush=True)
    (run / 'action_audit.json').write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
