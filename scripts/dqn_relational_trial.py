"""Run the predeclared shared-matchup trial serially; validation only, original absolute deadline.

An outer controller must enforce the absolute deadline during the unchanged trainer's long phases.
All checkpoints and evaluation journals survive interruption. The one-hour RL allocation is persistent.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time

for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS'):
    os.environ[name] = '1'
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from pogo.arena import low_priority
from pogo.dqn_relational import Network
from scripts import double_dqn as trainer
from scripts.double_dqn_relational import relational_backend, main as backend_main

DEADLINE = 1793745649.6650429


def file_hash(path):
    with Path(path).open('rb') as file:
        return hashlib.file_digest(file, 'sha256').hexdigest()


def remaining_rl(state, now):
    """Recovery never grants another hour, even if the worker died before its first checkpoint."""
    return max(0., min(state['rl_deadline_unix'], state['deadline_unix']) - now)


def invoke(arguments):
    previous = sys.argv
    sys.argv = [str(ROOT / 'scripts/double_dqn_relational.py'), *arguments]
    try:
        backend_main()
    finally:
        sys.argv = previous


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', default='relational-v1')
    args = parser.parse_args()
    if Path(args.run).name != args.run or args.run in ('.', '..'):
        parser.error('Use a simple run name')
    low_priority()
    run = ROOT / 'runs/double-dqn' / args.run
    proposal = json.loads((run / 'proposal.json').read_text())
    if (ROOT / 'runs/double-dqn/final_test_lock.json').exists():
        raise ValueError('Final policy is already locked; no further research')
    if proposal['absolute_deadline_unix'] != DEADLINE or proposal['final_tests_enabled']:
        raise ValueError('Original deadline and validation-only protocol must be preserved')
    source = ROOT / 'runs/double-dqn' / proposal['demonstrations']['source_run'] / 'demonstrations.npz'
    expected = proposal['demonstrations']['sha256']
    if file_hash(source) != expected:
        raise ValueError('Source demonstration hash changed')
    plan = dict(proposal, status='registered_before_fitting', proposal_sha256=file_hash(run / 'proposal.json'),
        source_sha256={str(p.relative_to(ROOT)): file_hash(p) for p in
            (Path(__file__), ROOT / 'scripts/double_dqn_relational.py', ROOT / 'scripts/double_dqn.py',
             ROOT / 'pogo/dqn_relational.py', ROOT / 'pogo/dqn.py')},
        rl_clock='One persistent wall-clock hour including unchanged trainer internal bootstrap validation',
        selection_endpoint='Last complete atomic checkpoint, including the ordinary end-of-training save')
    plan_path = run / 'trial_plan.json'
    if plan_path.exists() and json.loads(plan_path.read_text()) != plan:
        raise ValueError('Trial identity changed; use a new run')
    trainer.write_json(plan_path, plan)
    state_path = run / 'trial_state.json'
    state = json.loads(state_path.read_text()) if state_path.exists() else {
        'deadline_unix': DEADLINE, 'started_unix': time.time(), 'phase': 'bootstrap'}
    if state['deadline_unix'] != DEADLINE:
        raise ValueError('Saved original deadline changed')
    state['pid'] = os.getpid()

    def save(phase):
        state.update(phase=phase, updated_unix=time.time())
        trainer.write_json(state_path, state)
        print(json.dumps({'event': 'relational_trial_phase', **state}), flush=True)

    def stop():
        if time.time() >= DEADLINE or (run / 'STOP').exists():
            save('stopped_with_checkpoints')
            return True
        return False

    if stop():
        return
    destination = run / 'demonstrations.npz'
    if destination.exists():
        if file_hash(destination) != expected:
            raise ValueError('Copied demonstration hash changed')
    else:
        temporary = destination.with_suffix('.copying')
        shutil.copyfile(source, temporary)
        if file_hash(temporary) != expected:
            raise ValueError('Demonstration copy mismatch')
        temporary.replace(destination)
    base = ['--run', args.run, '--hidden', '64', '--batch', '128']
    save('bootstrap')
    invoke(['bootstrap', *base, '--seed', '38002', '--games', '3000', '--epochs', '80',
            '--teacher', 'engine', '--teacher-samples', '4', '--rate', '.0003'])
    if stop():
        return
    if not state.get('rl_complete'):
        if 'rl_deadline_unix' not in state:
            state['rl_deadline_unix'] = min(DEADLINE, time.time() + 3600)
        save('rl')
        seconds = remaining_rl(state, time.time())
        if seconds > 0:
            invoke(['train', *base, '--seed', '38501', '--hours', str(seconds / 3600),
                '--engine-share', '1', '--train-samples', '32', '--nstep', '3',
                '--epsilon', '.03', '--epsilon-min', '.005', '--epsilon-decay', '20000',
                '--mc-share', '.25', '--demo-margin', '1', '--rate', '.0001',
                '--updates', '4', '--target-every', '500', '--save-every', '25',
                '--eval-every', '1000000', '--validation-pairs', '64', '--validation-samples', '32'])
        if not (run / 'resume.json').exists():
            save('rl_budget_exhausted_without_endpoint')
            return
        slot = json.loads((run / 'resume.json').read_text())['slot']
        shutil.copyfile(run / f'latest_{slot}.npz', run / 'endpoint.npz')
        state['rl_complete'] = True
        state['endpoint_sha256'] = file_hash(run / 'endpoint.npz')
        save('selecting')
    elif file_hash(run / 'endpoint.npz') != state['endpoint_sha256']:
        raise ValueError('Retained endpoint changed')
    reports = {}
    with relational_backend():
        for candidate in ('bootstrap', 'endpoint'):
            if stop():
                return
            save('screening_' + candidate)
            checkpoint = run / (candidate + '.npz')
            net, _, _ = Network.load(checkpoint)
            reports[candidate] = trainer.evaluate(run, net, checkpoint, 'validation', 38511, 64,
                                                   samples=32, tag='screen_' + candidate)
        selected = max(reports, key=lambda name: reports[name]['score'])
        checkpoint = run / (selected + '.npz')
        trainer.write_json(run / 'trial_selection.json', {'selected': selected,
            'model_sha256': file_hash(checkpoint), 'screens': reports,
            'criterion': proposal['selection']['rule']})
        if stop():
            return
        save('confirming_' + selected)
        net, _, _ = Network.load(checkpoint)
        confirmation = trainer.evaluate(run, net, checkpoint, 'validation', 38512, 128,
                                         samples=32, tag='confirmation')
    compact = copy.deepcopy(net)
    for moment in compact.m + compact.v:
        moment.fill(0)
    compact.steps = 0
    compact.save(run / 'policy.npz', {'source_sha256': file_hash(checkpoint), 'selected': selected})
    restored, _, _ = Network.load(run / 'policy.npz')
    for before, after in zip(net.p, restored.p):
        np.testing.assert_array_equal(before, after)
    trainer.write_json(run / 'result.json', {'selected': selected, 'screens': reports,
        'confirmation': confirmation, 'selected_sha256': file_hash(checkpoint),
        'policy_sha256': file_hash(run / 'policy.npz'), 'architecture': proposal['architecture'],
        'reliable_win_proven': False, 'final_test_opened': False})
    save('research_complete')


if __name__ == '__main__':
    main()
