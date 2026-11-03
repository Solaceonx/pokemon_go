"""Reference-anchored fitted policy improvement from three completed training-only CF batches.

Validation-only; two fixed correction sizes, one shared screening draw, one fresh selected confirmation.
No new rollout collection, inference rule, hidden feature or engine call inside the policy.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import time

for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS'):
    os.environ[name] = '1'
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from pogo.arena import low_priority
from pogo.counterfactual import forward, backward
from pogo.dqn import Network
from pogo.dqn_residual import centered_residual_loss
from scripts.double_dqn import append, evaluate, write_json


def digest(path):
    with Path(path).open('rb') as file:
        return hashlib.file_digest(file, 'sha256').hexdigest()


def fit(reference, x, mask, returns, demo, step, checkpoint, stop, epochs=30, seed=38601,
        rate=.0001, anchor=1., batch=128):
    """Resume only from a complete epoch, with exact optimizer and sampling state."""
    rng = np.random.default_rng(seed)
    if checkpoint.exists():
        net, meta, _ = Network.load(checkpoint)
        if meta['step'] != step:
            raise ValueError('Residual correction size changed')
        first = meta['epoch']
        rng.bit_generator.state = meta['numpy_rng']
    else:
        net, first = copy.deepcopy(reference), 0
        net.steps = 0
        for moment in net.m + net.v:
            moment.fill(0)
    dx, dm = demo
    for epoch in range(first, epochs):
        ids, losses = rng.permutation(len(x)), []
        for offset in range(0, len(ids), batch):
            if stop():
                return None
            rows = ids[offset:offset + batch]
            di = rng.integers(0, len(dx), batch)
            inputs = np.concatenate([x[rows], dx[di]])
            old_q = reference.predict(inputs)
            a, b, q = forward(net, inputs)
            loss, dq = centered_residual_loss(q[:len(rows)], mask[rows], old_q[:len(rows)],
                                               returns[rows], step)
            regularizer, dr = centered_residual_loss(q[len(rows):], dm[di], old_q[len(rows):])
            backward(net, inputs, a, b, np.concatenate([dq, anchor * dr]), rate)
            losses.append(loss + anchor * regularizer)
        net.save(checkpoint, {'epoch': epoch + 1, 'numpy_rng': rng.bit_generator.state, 'step': step,
            'objective': 'centered residual-return Huber plus reference-score anchor on demo states'})
        row = {'event': 'residual_fit', 'variant': checkpoint.stem, 'epoch': epoch + 1,
               'loss': float(np.mean(losses)), 'positions': len(x), 'optimizer_steps': net.steps}
        append(checkpoint.parent / (checkpoint.stem + '_training.jsonl'), row)
        print(json.dumps(row), flush=True)
    return net


def load_positions(directory, reference, reference_sha):
    xs, masks, values, receipts = [], [], [], []
    for number in (1, 2, 3):
        path = directory / f'labels_{number:03d}.npz'
        collection = directory / f'collection_{number:03d}.json'
        info = json.loads(collection.read_text())
        with np.load(path, allow_pickle=False) as data:
            x, mask, returns, chosen = data['x'], data['mask'], data['returns'], data['chosen']
            embedded = json.loads(str(data['info']))
        if (info['groups'] != 300 or len(x) != 300 or info['matched_controls'] != 300
                or info['settings']['policy_sha256'] != reference_sha
                or info['settings']['samples'] != 32 or embedded['settings'] != info['settings']
                or embedded['matched_controls'] != 300):
            raise ValueError('Expected the three complete, control-matched, same-policy training batches')
        if (x.shape != (300, 400) or mask.shape != (300, 9) or returns.shape != (300, 9)
                or not mask.any(axis=1).all() or not np.isfinite(x).all()
                or not np.isin(returns[mask], [-1., 0., 1.]).all()):
            raise ValueError('Malformed completed training positions')
        votes = np.where(mask, reference.predict(x), -np.inf).argmax(axis=1)
        if not np.array_equal(votes, chosen):
            raise ValueError('Label behavior choices differ from the immutable reference policy')
        signals = int(sum(np.ptp(y[m]) > 0 for m, y in zip(mask, returns)))
        if signals != info['signals']:
            raise ValueError('Signal count differs from completed collection receipt')
        xs.append(x)
        masks.append(mask)
        values.append(returns)
        receipts.append({'labels': path.name, 'sha256': digest(path), 'collection_sha256': digest(collection),
                         'positions': 300, 'signals': signals, 'matched_controls': 300})
    return np.concatenate(xs), np.concatenate(masks), np.concatenate(values), receipts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', default='residual-v1')
    args = parser.parse_args()
    if Path(args.run).name != args.run or args.run in ('.', '..'):
        parser.error('Use a simple run name')
    low_priority()
    run = ROOT / 'runs/double-dqn' / args.run
    proposal_path = run / 'proposal.json'
    proposal = json.loads(proposal_path.read_text())
    if (ROOT / 'runs/double-dqn/final_test_lock.json').exists():
        raise ValueError('Final policy is locked; no further research')
    prior = ROOT / 'runs/double-dqn/counterfactual-v4'
    checkpoint = prior / 'initial.npz'
    if digest(checkpoint) != proposal['reference_sha256']:
        raise ValueError('Reference policy changed')
    reference, _, _ = Network.load(checkpoint)
    x, mask, returns, receipts = load_positions(prior, reference, proposal['reference_sha256'])
    demo_path = ROOT / 'runs/double-dqn/dqn-v2/demonstrations.npz'
    if digest(demo_path) != proposal['demonstrations_sha256']:
        raise ValueError('Demonstration file changed')
    plan = dict(proposal, proposal_sha256=digest(proposal_path), training_inputs=receipts,
        source_sha256={str(p.relative_to(ROOT)): digest(p) for p in
            (Path(__file__), ROOT / 'pogo/dqn_residual.py', ROOT / 'pogo/counterfactual.py',
             ROOT / 'pogo/dqn.py', ROOT / 'scripts/double_dqn.py')})
    plan_path = run / 'plan.json'
    if plan_path.exists() and json.loads(plan_path.read_text()) != plan:
        raise ValueError('Residual trial identity changed')
    write_json(plan_path, plan)
    state_path = run / 'state.json'
    state = json.loads(state_path.read_text()) if state_path.exists() else {
        'started_unix': time.time(), 'deadline_unix': min(1793745649.6650429, time.time() + 7200)}
    state['pid'] = os.getpid()

    def save(phase):
        state.update(phase=phase, updated_unix=time.time())
        write_json(state_path, state)

    def stop():
        if time.time() >= state['deadline_unix'] or (run / 'STOP').exists():
            save('stopped_with_checkpoints')
            return True
        return False

    with np.load(demo_path, allow_pickle=False) as data:
        demo = data['x'], data['mask']
    reports = {}
    candidates = [('reference', None), ('residual_010', .10), ('residual_025', .25)]
    for name, step in candidates:
        if stop():
            return
        path = checkpoint if step is None else run / (name + '.npz')
        if step is not None:
            save('fitting_' + name)
            net = fit(reference, x, mask, returns, demo, step, path, stop)
            if net is None:
                return
        else:
            net = reference
        if stop():
            return
        save('screening_' + name)
        reports[name] = evaluate(run, net, path, 'validation', 38611, 64, samples=32, tag='screen_' + name)
    selected = max(reports, key=lambda name: reports[name]['score'])
    path = checkpoint if selected == 'reference' else run / (selected + '.npz')
    write_json(run / 'selection.json', {'selected': selected, 'screens': reports, 'model_sha256': digest(path),
        'rule': 'maximum 64-pair screening score; reference, then smaller correction wins ties'})
    if stop():
        return
    save('confirming_' + selected)
    net, _, _ = Network.load(path)
    confirmation = evaluate(run, net, path, 'validation', 38612, 128, samples=32, tag='confirmation')
    for moment in net.m + net.v:
        moment.fill(0)
    net.steps = 0
    net.save(run / 'policy.npz', {'selected': selected, 'source_sha256': digest(path)})
    restored, _, _ = Network.load(run / 'policy.npz')
    for a, b in zip(net.p, restored.p):
        np.testing.assert_array_equal(a, b)
    write_json(run / 'result.json', {'selected': selected, 'screens': reports, 'confirmation': confirmation,
        'selected_sha256': digest(path), 'policy_sha256': digest(run / 'policy.npz'),
        'reliable_win_proven': False, 'final_test_opened': False})
    save('research_complete')


if __name__ == '__main__':
    main()
