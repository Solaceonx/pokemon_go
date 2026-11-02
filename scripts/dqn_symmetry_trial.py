"""Bench-permutation augmentation and invariant inference; validation-only experiment."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import statistics
import sys
import time

for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS'):
    os.environ[name] = '1'
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pogo.arena import low_priority
from pogo.dqn import Network
from pogo.counterfactual import imitate
from pogo.dqn_symmetry import augment, SymmetricPolicy
from scripts.double_dqn import evaluate, sha, write_json, append


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', default='symmetry-v5')
    parser.add_argument('--epochs', type=int, default=60)
    parser.add_argument('--screen-pairs', type=int, default=64)
    parser.add_argument('--confirm-pairs', type=int, default=128)
    parser.add_argument('--hours', type=float, default=4)
    parser.add_argument('--deadline', type=float, default=1793745649.6650429)
    args = parser.parse_args()
    if Path(args.run).name != args.run or min(args.epochs, args.screen_pairs, args.confirm_pairs) < 1:
        parser.error('Use a simple run name and positive counts')
    low_priority()
    run = ROOT / 'runs/double-dqn' / args.run
    run.mkdir(parents=True, exist_ok=True)
    demo_path = ROOT / 'runs/double-dqn/dqn-v2/demonstrations.npz'
    prior_path = ROOT / 'runs/double-dqn/refine-v3/policy.npz'
    source_path = ROOT / 'runs/double-dqn/dqn-v2/bootstrap.npz'
    with demo_path.open('rb') as file:
        demo_hash = hashlib.file_digest(file, 'sha256').hexdigest()
    plan = dict(vars(args), bootstrap_sha256=sha(source_path), prior_sha256=sha(prior_path),
        demonstrations_sha256=demo_hash, source_sha256={str(p.relative_to(ROOT)): sha(p) for p in
            (Path(__file__), ROOT / 'pogo/dqn_symmetry.py', ROOT / 'pogo/dqn.py', ROOT / 'pogo/counterfactual.py')},
        training={'seed': 38402, 'rate': .0001, 'batch': 256, 'temperature': .1,
                  'loss': 'balanced masked CE, tie bench action frequencies, random independent bench permutations'},
        screen={'seed': 38411, 'pairs': args.screen_pairs, 'opponent_samples': 32, 'split': 'validation'},
        confirmation={'seed': 38412, 'pairs': args.confirm_pairs, 'opponent_samples': 32, 'split': 'validation'},
        variants=['prior_direct', 'prior_average', 'augmented_direct', 'augmented_average'],
        selection='maximum screening win share, earliest variant wins ties', final_tests=False)
    if (run / 'plan.json').exists() and json.loads((run / 'plan.json').read_text()) != plan:
        raise ValueError('Experiment identity changed; do not reuse this run name')
    write_json(run / 'plan.json', plan)
    state_path = run / 'state.json'
    state = json.loads(state_path.read_text()) if state_path.exists() else {
        'deadline_unix': min(args.deadline, time.time() + args.hours * 3600)}
    state.update(pid=os.getpid(), status='fitting')
    write_json(state_path, state)
    def stop():
        return time.time() >= state['deadline_unix'] or (run / 'STOP').exists()
    def stopped():
        state['status'] = 'stopped_with_checkpoints'
        write_json(state_path, state)
    for source, name in ((prior_path, 'prior.npz'), (source_path, 'bootstrap.npz')):
        if not (run / name).exists():
            shutil.copyfile(source, run / name)
        elif sha(run / name) != sha(source):
            raise ValueError('Input policy changed')
    path = run / 'augmented.npz'
    rng = np.random.default_rng(38402)
    if path.exists():
        net, meta, _ = Network.load(path)
        first = meta['epoch']
        rng.bit_generator.state = meta['numpy_rng']
    else:
        net, _, _ = Network.load(run / 'bootstrap.npz')
        first = net.steps = 0
        for moment in (*net.m, *net.v):
            moment.fill(0)
    if first < args.epochs:
        with np.load(demo_path, allow_pickle=False) as data:
            x, masks, actions = data['x'], data['mask'], data['action']
        counts = np.bincount(actions, minlength=9).astype(float)
        counts[3] = counts[4] = (counts[3] + counts[4]) / 2
        counts[7] = counts[8] = (counts[7] + counts[8]) / 2
        weights = 1 / np.sqrt(np.maximum(counts, 1))
        weights = np.clip(weights / np.mean(weights[actions]), .25, 4)
        for epoch in range(first, args.epochs):
            if stop():
                stopped()
                return
            started, losses = time.monotonic(), []
            rows = rng.permutation(len(actions))
            for offset in range(0, len(rows), 256):
                ids = rows[offset:offset + 256]
                ax, am, aa = augment(x[ids], masks[ids], actions[ids], rng)
                losses.append(imitate(net, ax, am, aa, weights[aa], rate=.0001))
            net.save(path, {'epoch': epoch + 1, 'numpy_rng': rng.bit_generator.state,
                            'augmentation': 'independent ours/foes bench permutations'})
            row = {'epoch': epoch + 1, 'loss': float(np.mean(losses)), 'seconds': time.monotonic() - started}
            append(run / 'training.jsonl', row)
            print(json.dumps(row), flush=True)
        del x, masks, actions
    reports = {}
    for name in plan['variants']:
        if stop():
            stopped()
            return
        checkpoint = run / ('prior.npz' if name.startswith('prior_') else 'augmented.npz')
        net, _, _ = Network.load(checkpoint)
        policy = SymmetricPolicy(net) if name.endswith('_average') else net
        state.update(status='screening', variant=name)
        write_json(state_path, state)
        reports[name] = evaluate(run, policy, checkpoint, 'validation', 38411, args.screen_pairs,
                                 samples=32, tag=name)
        if name != 'prior_direct':
            change = [a - b for a, b in zip(reports[name]['pair_scores'], reports['prior_direct']['pair_scores'])]
            margin = 1.96 * statistics.stdev(change) / math.sqrt(len(change)) if len(change) > 1 else 0
            if margin == 0:
                margin = math.sqrt(2 * math.log(40) / len(change))
            write_json(run / (name + '_paired_change.json'),
                {'score_change': statistics.mean(change), 'margin95': margin, 'clusters': len(change)})
    selected = max(reports, key=lambda name: reports[name]['score'])
    checkpoint = run / ('prior.npz' if selected.startswith('prior_') else 'augmented.npz')
    write_json(run / 'selection.json', {'variant': selected, 'model_sha256': sha(checkpoint),
                                      'screen': reports[selected], 'rule': plan['selection']})
    if stop():
        stopped()
        return
    net, _, _ = Network.load(checkpoint)
    policy = SymmetricPolicy(net) if selected.endswith('_average') else net
    state.update(status='confirming', variant=selected)
    write_json(state_path, state)
    confirmation = evaluate(run, policy, checkpoint, 'validation', 38412, args.confirm_pairs,
                            samples=32, tag='confirmation')
    write_json(run / 'result.json', {'selected': selected, 'screens': reports,
                                   'confirmation': confirmation, 'final_test_opened': False})
    state['status'] = 'complete'
    write_json(state_path, state)


if __name__ == '__main__':
    main()
