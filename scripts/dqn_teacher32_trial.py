"""Bounded full-engine teacher data, shared-encoder imitation and Double DQN; validation only.

One numerical process. Both real selfplay teachers use the frozen full engine; only their public-state
Agent logs become demonstrations. Collection and RL clocks persist across recovery. An outer guard
enforces the six-hour and original overall deadlines during long games/evaluation blocks.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import random
import shutil
import sys
import time

for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS'):
    os.environ[name] = '1'
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from pogo.arena import low_priority
from pogo.dqn import Agent, Replay, transitions
from pogo.dqn_relational import Network
from scripts import double_dqn as trainer
from scripts.dqn_relational_trial import file_hash, invoke, remaining_rl

DEADLINE = 1793745649.6650429


def collect(f, reference, path, settings, should_stop):
    """Only complete real games are committed; restart draws are indexed by committed game number."""
    demos = Replay.load(path) if path.exists() else Replay(settings['capacity'])
    info = demos.info or {'games': 0, 'total_logged_positions': 0, 'settings': settings}
    if info['settings'] != settings:
        raise ValueError('Teacher collection identity changed')
    started = time.monotonic()
    while info['games'] < settings['maximum_games'] and not should_stop():
        episode = info['games']
        rng = random.Random(settings['seed'] + 1000003 * episode)
        a = trainer.draw_split(f.mixed_draw, rng, 'train')
        b = trainer.draw_split(f.mixed_draw, rng, 'train')
        seeds = [rng.getrandbits(32) for _ in range(3)]
        p = Agent(reference, seed=seeds[0], teacher=f.engine(seeds[0], settings['teacher_samples']), record=True)
        q = Agent(reference, seed=seeds[1], teacher=f.engine(seeds[1], settings['teacher_samples']), record=True)
        result, _ = f.game(a, b, p, q, seeds[2])
        demos.add(transitions(p.log, result))
        demos.add(transitions(q.log, -result))
        info.update(games=episode + 1, total_logged_positions=info['total_logged_positions'] + len(p.log) + len(q.log),
                    retained_positions=demos.size)
        demos.info = info
        if info['games'] % settings['checkpoint_every_games'] == 0:
            demos.save(path)
        row = {'event': 'teacher32_collection', 'games': info['games'], 'retained_positions': demos.size,
               'total_logged_positions': info['total_logged_positions'], 'teacher_samples': settings['teacher_samples'],
               'seconds_this_attempt': time.monotonic() - started}
        trainer.write_json(path.parent / 'collection_progress.json', row)
        print(json.dumps(row), flush=True)
    demos.info = info
    demos.save(path)
    return demos


def fit(reference, demos, path, settings, identity, should_stop):
    """Balanced masked CE, with exact complete-epoch optimizer/RNG recovery."""
    rng = np.random.default_rng(settings['seed'])
    if path.exists():
        net, meta, _ = Network.load(path)
        if meta['identity'] != identity or meta['settings'] != settings:
            raise ValueError('Teacher fit identity changed')
        first = meta['epoch']
        rng.bit_generator.state = meta['numpy_rng']
    else:
        net, first = copy.deepcopy(reference), 0
        net.steps = 0
        for moment in net.m + net.v:
            moment.fill(0)
    actions = demos.action[:demos.size]
    counts = np.bincount(actions, minlength=9).astype(float)
    for a, b in ((3, 4), (7, 8)):
        counts[a] = counts[b] = (counts[a] + counts[b]) / 2
    weights = 1 / np.sqrt(np.maximum(counts, 1))
    weights = np.clip(weights / np.mean(weights[actions]), .25, 4)
    for epoch in range(first, settings['epochs']):
        ids, losses = rng.permutation(demos.size), []
        for start in range(0, len(ids), settings['batch']):
            if should_stop():
                return None
            ix = ids[start:start + settings['batch']]
            losses.append(net.imitate(demos.x[ix], demos.mask[ix], demos.action[ix],
                                      weights[demos.action[ix]], rate=settings['rate']))
        meta = {'epoch': epoch + 1, 'numpy_rng': rng.bit_generator.state, 'settings': settings, 'identity': identity}
        net.save(path, meta)
        ix = np.arange(min(10000, demos.size))
        votes = np.where(demos.mask[ix], net.predict(demos.x[ix]), -np.inf).argmax(axis=1)
        row = {'event': 'teacher32_fit', 'epoch': epoch + 1, 'loss': float(np.mean(losses)),
               'training_agreement': float(np.mean(votes == demos.action[ix])), 'positions': demos.size}
        trainer.append(path.parent / 'fit_training.jsonl', row)
        print(json.dumps(row), flush=True)
    return net


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', default='teacher32-v1')
    args = parser.parse_args()
    if Path(args.run).name != args.run or args.run in ('.', '..'):
        parser.error('Use a simple run name')
    low_priority()
    run = ROOT / 'runs/double-dqn' / args.run
    proposal = json.loads((run / 'proposal.json').read_text())
    if proposal['absolute_deadline_unix'] != DEADLINE or proposal['final_tests_enabled']:
        raise ValueError('Original deadline and validation-only protocol must stay fixed')
    if (proposal['baseline_commit'] != trainer.BASE or proposal['collection']['teacher_samples'] != 32
            or proposal['selection']['pairs'] != 64 or proposal['selection']['seed'] != 38811
            or proposal['confirmation']['pairs'] != 128 or proposal['confirmation']['seed'] != 38812):
        raise ValueError('Frozen teacher and predeclared validation settings changed')
    if (ROOT / 'runs/double-dqn/final_test_lock.json').exists():
        raise ValueError('Final policy is locked; no further research')
    source = ROOT / 'runs/double-dqn' / proposal['reference_policy']
    if file_hash(source) != proposal['reference_sha256']:
        raise ValueError('Reference policy changed')
    plan = dict(proposal, status='registered_before_collection', proposal_sha256=file_hash(run / 'proposal.json'),
        source_sha256={str(p.relative_to(ROOT)): file_hash(p) for p in (Path(__file__),
            ROOT / 'scripts/dqn_relational_trial.py', ROOT / 'scripts/double_dqn_relational.py',
            ROOT / 'scripts/double_dqn.py', ROOT / 'pogo/dqn.py', ROOT / 'pogo/dqn_relational.py',
            ROOT / 'pogo/counterfactual.py')})
    plan_path = run / 'plan.json'
    if plan_path.exists() and json.loads(plan_path.read_text()) != plan:
        raise ValueError('Teacher experiment identity changed')
    trainer.write_json(plan_path, plan)
    state_path = run / 'state.json'
    state = json.loads(state_path.read_text()) if state_path.exists() else {
        'started_unix': time.time(), 'deadline_unix': min(DEADLINE, time.time() + 6 * 3600)}
    if state['deadline_unix'] > DEADLINE:
        raise ValueError('Original overall deadline changed')
    state['pid'] = os.getpid()

    def save(phase):
        state.update(phase=phase, updated_unix=time.time())
        trainer.write_json(state_path, state)
        print(json.dumps({'event': 'teacher32_phase', **state}), flush=True)

    def stop():
        if time.time() >= state['deadline_unix'] or (run / 'STOP').exists():
            save('stopped_with_checkpoints')
            return True
        return False

    if stop():
        return
    # Register the process-local backend before any bootstrap checkpoint can exist.
    invoke(['prepare', '--run', args.run, '--hidden', '64'])
    reference, _, _ = Network.load(source)
    if not (run / 'reference.npz').exists():
        shutil.copyfile(source, run / 'reference.npz')
    elif file_hash(run / 'reference.npz') != proposal['reference_sha256']:
        raise ValueError('Copied reference changed')
    data_path = run / 'demonstrations.npz'
    if 'data_sha256' not in state:
        if 'collection_deadline_unix' not in state:
            state['collection_deadline_unix'] = min(state['deadline_unix'], time.time() + 2 * 3600)
        save('collecting_teacher32')
        collection = {k: proposal['collection'][k] for k in
                      ('seed', 'maximum_games', 'capacity', 'checkpoint_every_games', 'teacher_samples')}
        collection.update(reference_sha256=proposal['reference_sha256'], baseline_commit=proposal['baseline_commit'],
                          split='train', players='two independent full frozen engine32 teachers; public Agent logs')
        demos = collect(trainer.frozen(), reference, data_path, collection,
                        lambda: stop() or time.time() >= state['collection_deadline_unix'])
        if stop():
            return
        if demos.size < proposal['collection']['minimum_retained_decisions']:
            save('insufficient_committed_teacher_data')
            return
        state.update(data_sha256=file_hash(data_path), teacher_games=demos.info['games'])
        trainer.write_json(run / 'collection.json', dict(demos.info, data_sha256=state['data_sha256'],
            collection_deadline_unix=state['collection_deadline_unix'], strength_evidence=False))
        save('teacher_data_sealed')
    else:
        if file_hash(data_path) != state['data_sha256']:
            raise ValueError('Sealed teacher data changed')
        demos = Replay.load(data_path)
    save('fitting_teacher32')
    fitted_path = run / 'teacher32_fit.npz'
    fitted = fit(reference, demos, fitted_path, proposal['fit'],
                 {'reference_sha256': proposal['reference_sha256'], 'dataset_sha256': state['data_sha256']}, stop)
    del demos
    if fitted is None or stop():
        return
    bootstrap = run / 'bootstrap.npz'
    if not bootstrap.exists():
        initial_rl = copy.deepcopy(fitted)
        for moment in initial_rl.m + initial_rl.v:
            moment.fill(0)
        initial_rl.steps = 0
        initial_rl.save(bootstrap, {'source_ce_sha256': file_hash(fitted_path), 'dataset_sha256': state['data_sha256']})
    else:
        old, meta, _ = Network.load(bootstrap)
        if meta['source_ce_sha256'] != file_hash(fitted_path) or meta['dataset_sha256'] != state['data_sha256']:
            raise ValueError('RL initialization changed')
        for a, b in zip(old.p, fitted.p):
            np.testing.assert_array_equal(a, b)
    if not state.get('rl_complete'):
        if 'rl_deadline_unix' not in state:
            state['rl_deadline_unix'] = min(state['deadline_unix'], time.time() + 3600)
        save('rl')
        seconds = remaining_rl(state, time.time())
        if seconds > 0:
            invoke(['train', '--run', args.run, '--hidden', '64', '--seed', '38803', '--hours', str(seconds / 3600),
                '--batch', '128', '--engine-share', '1', '--train-samples', '32', '--nstep', '3',
                '--epsilon', '.03', '--epsilon-min', '.005', '--epsilon-decay', '20000', '--mc-share', '.25',
                '--demo-margin', '1', '--rate', '.0001', '--updates', '4', '--target-every', '500',
                '--save-every', '25', '--eval-every', '1000000', '--validation-pairs', '64', '--validation-samples', '32',
                '--teacher', 'engine', '--teacher-samples', '32', '--demo-capacity', '200000'])
        if not (run / 'resume.json').exists():
            save('rl_allocation_exhausted_without_endpoint')
            return
        slot = json.loads((run / 'resume.json').read_text())['slot']
        shutil.copyfile(run / f'latest_{slot}.npz', run / 'endpoint.npz')
        state.update(rl_complete=True, endpoint_sha256=file_hash(run / 'endpoint.npz'))
        save('selecting')
    elif file_hash(run / 'endpoint.npz') != state['endpoint_sha256']:
        raise ValueError('Sealed RL endpoint changed')
    candidates = {'reference': run / 'reference.npz', 'teacher32_fit': fitted_path,
                  'last_complete_rl_endpoint': run / 'endpoint.npz'}
    reports = {}
    for name, checkpoint in candidates.items():
        if stop():
            return
        net, _, _ = Network.load(checkpoint)
        save('screening_' + name)
        reports[name] = trainer.evaluate(run, net, checkpoint, 'validation', 38811, 64, samples=32, tag='screen_' + name)
    selected = max(reports, key=lambda name: reports[name]['score'])
    checkpoint = candidates[selected]
    trainer.write_json(run / 'trial_selection.json', {'selected': selected, 'checkpoint': checkpoint.name,
        'model_sha256': file_hash(checkpoint), 'screens': reports, 'rule': proposal['selection']['rule']})
    if stop():
        return
    save('confirming_' + selected)
    net, _, _ = Network.load(checkpoint)
    confirmation = trainer.evaluate(run, net, checkpoint, 'validation', 38812, 128, samples=32, tag='confirmation')
    for moment in net.m + net.v:
        moment.fill(0)
    net.steps = 0
    net.save(run / 'policy.npz', {'selected': selected, 'source_sha256': file_hash(checkpoint)})
    restored, _, _ = Network.load(run / 'policy.npz')
    for a, b in zip(net.p, restored.p):
        np.testing.assert_array_equal(a, b)
    trainer.write_json(run / 'result.json', {'selected': selected, 'screens': reports, 'confirmation': confirmation,
        'selected_sha256': file_hash(checkpoint), 'policy_sha256': file_hash(run / 'policy.npz'),
        'data_sha256': state['data_sha256'], 'teacher_games': state['teacher_games'],
        'reliable_win_proven': False, 'final_test_opened': False})
    save('research_complete')


if __name__ == '__main__':
    main()
