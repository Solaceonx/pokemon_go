"""Validation-only output-bias calibration on completed counterfactual training batches.

Search fits a one-decision return proxy. Only fresh whole games can establish policy strength.
An outer controller must enforce the original absolute deadline during evaluation blocks.
"""
import argparse
import copy
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
from pogo.dqn import Network
from pogo.dqn_calibration import fit, statistics
from scripts.double_dqn import evaluate, write_json
from scripts.dqn_residual_trial import digest, load_positions


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    low_priority()
    run = ROOT / 'runs/double-dqn/calibration-v1'
    proposal = json.loads((run / 'proposal.json').read_text())
    if (ROOT / 'runs/double-dqn/final_test_lock.json').exists():
        raise ValueError('Final policy is locked; no further research')
    state_path = run / 'state.json'
    state = json.loads(state_path.read_text()) if state_path.exists() else {
        'started_unix': time.time(), 'deadline_unix': min(1793745649.6650429, time.time() + 7200)}
    state['pid'] = os.getpid()
    if state['deadline_unix'] > 1793745649.6650429:
        raise ValueError('Original absolute deadline changed')

    def save(phase):
        state.update(phase=phase, updated_unix=time.time())
        write_json(state_path, state)

    def stop():
        if time.time() >= state['deadline_unix'] or (run / 'STOP').exists():
            save('stopped_with_checkpoints')
            return True
        return False

    if stop():
        return
    prior = ROOT / 'runs/double-dqn/counterfactual-v4'
    original = prior / 'initial.npz'
    if digest(original) != proposal['reference_sha256']:
        raise ValueError('Reference policy changed')
    reference, _, _ = Network.load(original)
    x, mask, returns, receipts = load_positions(prior, reference, proposal['reference_sha256'])
    plan = dict(proposal, proposal_sha256=digest(run / 'proposal.json'), training_inputs=receipts,
        source_sha256={str(p.relative_to(ROOT)): digest(p) for p in (Path(__file__),
            ROOT / 'pogo/dqn_calibration.py', ROOT / 'pogo/dqn.py',
            ROOT / 'scripts/dqn_residual_trial.py', ROOT / 'scripts/double_dqn.py')})
    plan_path = run / 'plan.json'
    if plan_path.exists() and json.loads(plan_path.read_text()) != plan:
        raise ValueError('Calibration trial identity changed')
    write_json(plan_path, plan)
    save('fitting')
    # Match the batched reference-decision check used when the three collections are loaded.
    q = np.concatenate([reference.predict(x[start:start + 300]) for start in range(0, len(x), 300)])
    chosen = np.where(mask, q, -np.inf).argmax(axis=1)
    fitted = fit(q, mask, returns, chosen)
    variants = [('reference', None), ('unpenalized', '0.0'), ('penalized', '0.25')]
    for name, key in variants[1:]:
        candidate = copy.deepcopy(reference)
        candidate.p[5] += np.asarray(fitted[key]['offsets'], np.float32)
        for moment in candidate.m + candidate.v:
            moment.fill(0)
        candidate.steps = 0
        for a, b in zip(reference.p[:5], candidate.p[:5]):
            np.testing.assert_array_equal(a, b)
        path = run / (name + '.npz')
        candidate.save(path, {'source_sha256': digest(original), 'fit': fitted[key]})
        actual_q = np.concatenate([candidate.predict(x[start:start + 300]) for start in range(0, len(x), 300)])
        fitted[key]['exported_proxy'] = statistics(actual_q, mask, returns, chosen, np.zeros(9))
        fitted[key]['checkpoint_sha256'] = digest(path)
    write_json(run / 'fit.json', {'variants': fitted, 'reference_sha256': digest(original),
        'positions': len(x), 'strength_evidence': False, 'note': 'One callback changes then old continuation; whole-game policy strength unmeasured'})
    reports = {}
    completed_offsets = []
    for name, key in variants:
        if stop():
            return
        path = original if key is None else run / (name + '.npz')
        offsets = np.zeros(9) if key is None else np.asarray(fitted[key]['offsets'])
        alias = next((other for other, before in completed_offsets if np.array_equal(before, offsets)), None)
        if alias is not None:
            # Exact bias duplicates have the same deterministic inference; retain the first variant on ties.
            reports[name] = dict(reports[alias], alias_of=alias)
            continue
        net, _, _ = Network.load(path)
        save('screening_' + name)
        reports[name] = evaluate(run, net, path, 'validation', 38711, 64, samples=32, tag='screen_' + name)
        completed_offsets.append((name, offsets))
    selected = max(reports, key=lambda name: reports[name]['score'])
    path = original if selected == 'reference' else run / (selected + '.npz')
    write_json(run / 'selection.json', {'selected': selected, 'screens': reports,
        'model_sha256': digest(path), 'rule': 'Maximum score; reference, then unpenalized wins ties'})
    if stop():
        return
    save('confirming_' + selected)
    net, _, _ = Network.load(path)
    confirmation = evaluate(run, net, path, 'validation', 38712, 128, samples=32, tag='confirmation')
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
