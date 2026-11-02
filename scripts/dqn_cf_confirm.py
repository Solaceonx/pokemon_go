"""Finish the reserved fresh validation after the registered adaptive CF allocation stop.

The stopped trial's result is preserved unchanged; this separate receipt completes its confirmation.
Use only after the previous numerical worker and its serial controller have exited.
"""
import json
import os
from pathlib import Path
import sys
import time

for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS'):
    os.environ[name] = '1'
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pogo.arena import low_priority
from pogo.dqn import Network
from scripts.double_dqn import evaluate, read_rows, sha, write_json


def main():
    low_priority()
    run = ROOT / 'runs/double-dqn/counterfactual-v4'
    state = json.loads((run / 'state.json').read_text())
    result = json.loads((run / 'result.json').read_text())
    allocation = json.loads((run / 'allocation_plan.json').read_text())
    rounds = read_rows(run / 'rounds.jsonl')
    if (ROOT / 'runs/double-dqn/final_test_lock.json').exists():
        raise ValueError('Final policy already locked')
    if state['status'] != 'stopped_with_checkpoints' or result['confirmation'] is not None:
        raise ValueError('Expected a stopped research run with its reserved confirmation pending')
    if state['best_checkpoint'] != 'initial.npz' or len(rounds) < 3 or any(
            r['score'] > allocation['control_score'] for r in rounds):
        raise ValueError('Registered adaptive allocation condition not met')
    if time.time() >= min(allocation['trial_deadline_unix'], allocation['absolute_deadline_unix']):
        raise ValueError('Original confirmation allocation deadline reached')
    checkpoint = run / 'initial.npz'
    if sha(checkpoint) != allocation['control_sha256']:
        raise ValueError('Selected policy changed')
    expected = {'pairs': 128, 'seed': 38212, 'samples': 32, 'split': 'validation'}
    if allocation['fresh_confirmation'] != expected:
        raise ValueError('Reserved validation settings changed')
    plan = {'allocation_sha256': sha(run / 'allocation_plan.json'),
        'stopped_result_sha256': sha(run / 'result.json'), 'checkpoint_sha256': sha(checkpoint),
        'source_sha256': {str(p.relative_to(ROOT)): sha(p) for p in
            (Path(__file__), ROOT / 'scripts/double_dqn.py', ROOT / 'pogo/dqn.py')},
        'validation': expected, 'deadline_unix': allocation['trial_deadline_unix'],
        'absolute_deadline_unix': allocation['absolute_deadline_unix'], 'final_tests_enabled': False}
    plan_path = run / 'allocation_confirmation_plan.json'
    if plan_path.exists() and json.loads(plan_path.read_text()) != plan:
        raise ValueError('Confirmation identity changed')
    write_json(plan_path, plan)
    net, _, _ = Network.load(checkpoint)
    confirmation = evaluate(run, net, checkpoint, 'validation', 38212, 128, samples=32, tag='confirmation')
    if time.time() >= allocation['trial_deadline_unix']:
        raise ValueError('Original confirmation deadline exceeded; retain raw rows without completion claim')
    write_json(run / 'allocation_confirmation.json', {'confirmation': confirmation,
        'selected': 'initial.npz', 'model_sha256': sha(checkpoint), 'final_test_opened': False,
        'original_result_preserved_sha256': plan['stopped_result_sha256'], 'completed_unix': time.time()})


if __name__ == '__main__':
    main()
