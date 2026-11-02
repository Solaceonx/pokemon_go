#!/usr/bin/env python3
"""Bounded, unattended DQN-v2 experiment; no model/service in the learning loop.

Requires the immutable .dqn-cache/harness/v2 source bundle and an already-running bootstrap.
Runs at most two 12-hour training stages, selects on validation only, and tests once on locked seeds.
Writes a machine-readable verdict; never promotes a model, publishes, merges or sends a message.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
BASE = '59836c86f4c9ccf7e8d35ef7c94268e64c1a4ba9'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, data):
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
    tmp.replace(path)


def prepare_bundle(run_name):
    """Copy source once; directory links keep artifacts in the normal workspace.

    Existing bytes are checked rather than overwritten, so preparing cannot change a running job.
    """
    bundle = ROOT / '.dqn-cache/harness/v2'
    frozen = ROOT / '.dqn-cache' / BASE
    if not (frozen / 'manifest.json').exists():
        subprocess.run([sys.executable, str(ROOT / 'scripts/double_dqn.py'), 'prepare', '--run', run_name],
                       cwd=ROOT, check=True)
    for src in [*(ROOT / 'pogo').glob('*.py'), ROOT / 'scripts/double_dqn.py']:
        dst = bundle / src.relative_to(ROOT)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            if src.read_bytes() != dst.read_bytes():
                raise ValueError('Snapshot differs from current source; keep running jobs frozen: ' + str(dst))
        else:
            dst.write_bytes(src.read_bytes())
    for link, target in ((bundle / 'runs', ROOT / 'runs'), (bundle / 'data', frozen / 'data'),
                         (bundle / '.dqn-cache' / BASE, frozen)):
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.exists():
            if link.resolve() != target.resolve():
                raise ValueError('Snapshot directory points elsewhere: ' + str(link))
            continue
        if os.name == 'nt':
            # PowerShell literal quoting keeps paths as data, including apostrophes/metacharacters.
            quote = lambda value: "'" + str(value).replace("'", "''") + "'"
            code = ('New-Item -ItemType Junction -Path ' + quote(link) + ' -Target ' + quote(target)
                    + ' -ErrorAction Stop | Out-Null')
            subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', code], check=True)
        else:
            link.symlink_to(target, target_is_directory=True)
    return bundle


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', default='dqn-v2')
    p.add_argument('--max-hours', type=float, default=44.)
    p.add_argument('--stage-hours', type=float, default=12.)
    p.add_argument('--final-pairs', type=int, default=1000)
    p.add_argument('--smoke', action='store_true', help='Exercise all stages cheaply using validation teams only')
    p.add_argument('--prepare-only', action='store_true', help='Create and verify the immutable runtime source bundle')
    args = p.parse_args()
    if args.smoke:
        args.stage_hours, args.final_pairs = .0001, 2
    if Path(args.run).name != args.run or args.max_hours <= 0 or args.stage_hours <= 0 or args.final_pairs < 2:
        p.error('Invalid run, time budget or final pair count')
    run = ROOT / 'runs/double-dqn' / args.run
    run.mkdir(parents=True, exist_ok=True)
    bundle = prepare_bundle(args.run)
    if args.prepare_only:
        print(str(bundle), flush=True)
        return
    script = bundle / 'scripts/double_dqn.py'
    source = {str(path.relative_to(bundle)): digest(path)
              for path in (script, bundle / 'pogo/dqn.py', bundle / 'data/matchups_wide.json')}
    screen_pairs, full_pairs = (2, 2) if args.smoke else (100, 300)
    bootstrap_epoch = 1 if args.smoke else 80
    final_blocks = ([['mixed', 38991], ['mixed', 38992], ['standard', 38991]] if args.smoke
                    else [['mixed', 38091], ['mixed', 38092], ['standard', 38091]])
    plan = {'smoke_validation_only': args.smoke, 'source_sha256': source,
            'controller_sha256': digest(Path(__file__)),
            'bootstrap': {'games': 10 if args.smoke else 3000, 'epochs': bootstrap_epoch,
                          'teacher': 'learner' if args.smoke else 'engine4',
                          'hidden': 16 if args.smoke else 256, 'seed': 38002},
            'stage_hours': args.stage_hours, 'maximum_stages': 2,
            'screening': {'samples': 8, 'pairs': screen_pairs, 'seed': 38031},
            'full_engine_validation': {'samples': 32, 'pairs': full_pairs, 'seed': 38032},
            'selection': 'Best full-engine validation score among completed stages; earliest wins ties',
            'extra_stage_rule': 'Run second stage unless first full-engine validation lower95 > .5',
            'final_pairs_per_block': args.final_pairs,
            'final_blocks': final_blocks,
            'success': 'Both mixed lower95 > .5 and standard upper95 >= .5',
            'deadline_hours_from_start': args.max_hours, 'workers': 1,
            'training': {'samples': 32, 'engine_share': 1., 'epsilon': .03, 'epsilon_min': .005,
                         'epsilon_decay': 20000, 'nstep': 3, 'mc_share': .25,
                         'demo_margin': 1., 'rate': .0001, 'updates_per_game': 4}}
    plan_path = run / 'pipeline_plan.json'
    if plan_path.exists() and json.loads(plan_path.read_text()) != plan:
        raise ValueError('Pipeline plan differs from the existing run')
    write(plan_path, plan)
    state_path = run / 'pipeline_state.json'
    if state_path.exists():
        state = json.loads(state_path.read_text())
        if state['status'] == 'complete':
            return
    else:
        state = {'started_unix': time.time(), 'deadline_unix': time.time() + args.max_hours * 3600,
                 'completed_commands': [], 'status': 'running'}
    state['pid'], state['status'] = os.getpid(), 'running'
    write(state_path, state)

    def check():
        if time.time() >= state['deadline_unix']:
            raise TimeoutError('Work budget reached; saved checkpoints retained')
        if (run / 'STOP').exists():
            raise InterruptedError('STOP file requested; saved checkpoints retained')
        for name, expected in source.items():
            if digest(bundle / name) != expected:
                raise ValueError('Frozen experiment source changed: ' + name)

    def command(name, tail):
        check()
        if name in state['completed_commands']:
            return
        argv = [sys.executable, '-u', str(script), *tail, '--run', args.run]
        state.update(phase=name, command=argv)
        write(state_path, state)
        with (run / (name + '.out')).open('a', encoding='utf-8') as log:
            child = subprocess.Popen(argv, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
            state['child_pid'] = child.pid
            write(state_path, state)
            try:
                while child.poll() is None:
                    check()
                    time.sleep(5)
            except BaseException:
                child.terminate()
                child.wait(timeout=30)
                raise
            if child.returncode:
                raise RuntimeError(f'{name} exited {child.returncode}; see {name}.out')
        state['completed_commands'].append(name)
        state.pop('child_pid', None)
        write(state_path, state)

    # Keep the computer available for the authorized computation without changing saved power settings.
    kernel = None
    if os.name == 'nt':
        import ctypes
        kernel = ctypes.windll.kernel32
        kernel.SetThreadExecutionState(0x80000001)
    try:
        state['phase'] = 'waiting_for_bootstrap'
        write(state_path, state)
        warmup_log = ROOT / ('runs/dqn-pipeline-smoke-bootstrap.out' if args.smoke else 'runs/dqn-v2-bootstrap.out')
        while True:
            check()
            lines = warmup_log.read_text(encoding='utf-8').splitlines() if warmup_log.exists() else []
            if lines:
                if any('Traceback (most recent call last)' in line for line in lines[-20:]):
                    raise RuntimeError('Bootstrap failed; see runs/dqn-v2-bootstrap.out')
                try:
                    row = json.loads(lines[-1])
                except ValueError:
                    row = {}
                if row.get('event') == 'bootstrap' and row.get('epoch') == bootstrap_epoch:
                    break
            time.sleep(15)
        reports = []
        for stage in (1, 2):
            command(f'train_stage_{stage}', ['train', '--seed', '38002', '--hours', str(args.stage_hours),
                    '--engine-share', '1', '--train-samples', '32', '--epsilon', '.03',
                    '--epsilon-min', '.005', '--epsilon-decay', '20000', '--nstep', '3',
                    '--mc-share', '.25', '--demo-margin', '1', '--rate', '.0001',
                    '--eval-every', '2000', '--validation-pairs', str(screen_pairs), '--validation-samples', '8'])
            candidate = f'candidate_stage_{stage}.npz'
            candidate_path = run / candidate
            # Never replace a candidate once a validation command has been started.
            config = run / f'full_validation_stage_{stage}_config.json'
            if not candidate_path.exists():
                import shutil
                shutil.copyfile(run / 'best.npz', candidate_path)
            elif config.exists() and digest(candidate_path) != json.loads(config.read_text())['model_sha256']:
                raise ValueError('A staged candidate changed')
            command(f'full_validation_stage_{stage}', ['evaluate', '--checkpoint', candidate,
                    '--split', 'validation', '--seed', '38032', '--samples', '32', '--pairs', str(full_pairs),
                    '--tag', f'full_validation_stage_{stage}'])
            report = json.loads((run / f'full_validation_stage_{stage}_summary.json').read_text())
            reports.append((candidate, report))
            if stage == 1 and report['lower95'] > .5:
                break
        chosen, validation = max(reports, key=lambda item: item[1]['score'])
        policy = run / 'policy.npz'
        sys.path.insert(0, str(bundle))
        from pogo.dqn import Network
        net, _, _ = Network.load(run / chosen)
        if not policy.exists():
            # Deployment needs weights only. Zero Adam arrays compress to a few kilobytes.
            for array in net.m + net.v:
                array.fill(0)
            net.steps = 0
            net.save(policy, {'selected_source': chosen, 'algorithm': 'Double DQN',
                             'validation': validation, 'source_sha256': source})
        restored, _, _ = Network.load(policy)
        import numpy as np
        if not all(np.array_equal(a, b) for a, b in zip(net.p, restored.p)):
            raise ValueError('Compact policy differs from selected checkpoint')
        selection = {'candidate': chosen, 'candidate_sha256': digest(run / chosen),
                     'policy_sha256': digest(policy), 'criterion': plan['selection'], 'validation': validation}
        selection_path = run / 'final_selection.json'
        if selection_path.exists() and json.loads(selection_path.read_text()) != selection:
            raise ValueError('Final model selection is already frozen')
        write(selection_path, selection)
        final = []
        for field, seed in plan['final_blocks']:
            tag = f'test_{field}_{seed}'
            command(tag, ['evaluate', '--checkpoint', 'policy.npz', '--split', 'validation' if args.smoke else 'test',
                         '--seed', str(seed), '--samples', '32', '--pairs', str(args.final_pairs),
                         '--field', field, '--tag', tag])
            final.append(json.loads((run / f'{tag}_summary.json').read_text()))
        passed = (all(row['lower95'] > .5 for row in final if row['field'] == 'mixed')
                  and all(row['upper95'] >= .5 for row in final if row['field'] == 'standard')) if not args.smoke else None
        write(run / 'verdict.json', {'strength_target_met': passed, 'model_sha256': digest(policy),
                                   'validation': validation, 'final_tests': final,
                                   'completed_unix': time.time(), 'plan': plan})
        state.update(status='complete', phase='complete', strength_target_met=passed)
    except BaseException as exc:
        state.update(status='budget_stopped' if isinstance(exc, TimeoutError) else 'stopped' if isinstance(exc, InterruptedError)
                     else 'failed', error=str(exc))
        write(state_path, state)
        raise
    finally:
        write(state_path, state)
        if kernel is not None:
            kernel.SetThreadExecutionState(0x80000000)


if __name__ == '__main__':
    main()
