#!/usr/bin/env python3
"""Standalone fitted policy iteration from paired, complete-game counterfactual returns.

The simulator may use its full state to generate training experience. The policy reads public View fields only.
No Planner or Engine runs inside the deployed policy. Final test compositions are never drawn here.
"""
from __future__ import annotations

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
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pogo.arena import low_priority
from pogo.dqn import Agent, Network, N_FEATURES
from pogo.counterfactual import (StepRecorder, isolated_clone, replay_choice, forward, backward,
                                 advantage_loss, classification_loss)
from scripts.double_dqn import frozen, draw_split, evaluate, write_json, append, sha


def save_labels(path, groups, info):
    temp = Path(str(path) + '.tmp')
    with temp.open('wb') as f:
        np.savez_compressed(f, x=np.asarray([g[0] for g in groups], np.float32).reshape(-1, N_FEATURES),
                            mask=np.asarray([g[1] for g in groups], bool).reshape(-1, 9),
                            returns=np.asarray([g[2] for g in groups], np.float32).reshape(-1, 9),
                            chosen=np.asarray([g[3] for g in groups], np.int64),
                            info=np.array(json.dumps(info)))
    temp.replace(path)


def collect(f, net, path, settings, should_stop):
    """Reservoir sample callbacks before consulting their outcomes, stratified by decision type.

    Replay from the START of the simulator step, then force the indexed callback. This handles shields and
    replacements without pretending that a mid-step snapshot is a legal start-of-turn state.
    """
    groups = []
    info = {'episodes': 0, 'signals': 0, 'matched_controls': 0, 'kinds': {}, 'settings': settings}
    if path.exists():
        with np.load(path, allow_pickle=False) as data:
            info = json.loads(str(data['info']))
            if info['settings'] != settings:
                raise ValueError('Counterfactual collection identity changed')
            groups = list(zip(data['x'], data['mask'], data['returns'], data['chosen']))
    start = time.monotonic()
    while ((len(groups) < settings['groups'] or info['signals'] < settings['min_signals'])
           and len(groups) < settings['max_groups'] and not should_stop()):
        episode = info['episodes']
        rng = random.Random(settings['seed'] + 1000003 * episode)
        a = draw_split(f.mixed_draw, rng, 'train')
        b = draw_split(f.mixed_draw, rng, 'train')
        side = episode % 2
        players = [None, None]
        players[side] = Agent(net, seed=rng.getrandbits(32))
        players[1 - side] = f.engine(rng.getrandbits(32), settings['samples'])
        recorder = StepRecorder(players[side])
        agents = list(players)
        agents[side] = recorder
        battle = f.modules['battle'].Battle(a, b, *agents, seed=rng.getrandbits(32))
        reservoir, counts = {}, {}
        while battle.winner is None:
            snapshot = (battle.clone(None, None), [isolated_clone(p) for p in players])
            recorder.calls.clear()
            battle.step()
            for index, call in enumerate(recorder.calls):
                if len(call['options']) < 2:
                    continue
                kind = call['kind']
                if kind == 'act':
                    kind = 'act_ready' if call['mask'][1:3].any() else 'act_other'
                counts[kind] = counts.get(kind, 0) + 1
                if rng.randrange(counts[kind]) == 0:
                    reservoir[kind] = (snapshot, index, copy.deepcopy(call))
        baseline = 0. if battle.winner == -1 else 1. if battle.winner == side else -1.
        # Which callbacks are labelled depends on callback types/counts and RNG, never the game outcome.
        chosen_kinds = rng.sample(sorted(reservoir), min(settings['per_game'], len(reservoir)))
        for kind in chosen_kinds:
            if should_stop():
                break
            snapshot, index, call = reservoir[kind]
            values = np.zeros(9, np.float32)
            for action, native in call['options'].items():
                values[action] = replay_choice(snapshot, index, native, side)
            control = float(values[call['choice']])
            if control != baseline:
                raise RuntimeError(f'Actual-choice replay disagrees: {kind}, episode={episode}, {control} != {baseline}')
            info['matched_controls'] += 1
            info['kinds'][kind] = info['kinds'].get(kind, 0) + 1
            info['signals'] += int(np.ptp(values[call['mask']]) > 0)
            groups.append((call['x'], call['mask'], values, call['choice']))
        info['episodes'] += 1
        save_labels(path, groups, info)
        row = {'event': 'counterfactual_collection', 'episodes': info['episodes'], 'groups': len(groups),
               'signals': info['signals'], 'matched_controls': info['matched_controls'],
               'seconds': time.monotonic() - start, 'kinds': info['kinds']}
        print(json.dumps(row), flush=True)
    return groups, info


def fit(net, groups, demo, epochs, rate, anchor, seed, path):
    x = np.stack([g[0] for g in groups])
    masks = np.stack([g[1] for g in groups])
    returns = np.stack([g[2] for g in groups])
    signal = np.array([np.ptp(g[2][g[1]]) > 0 for g in groups])
    keep = np.flatnonzero(signal)
    if not len(keep):
        raise ValueError('No policy-improvement signal in paired returns')
    rng = np.random.default_rng(seed)
    first = 0
    if path.exists():
        net, meta, _ = Network.load(path)
        first = meta['epoch']
        rng.bit_generator.state = meta['numpy_rng']
    else:
        # This loss has a different scale from classification; do not carry its Adam moments forward.
        for moment in (*net.m, *net.v):
            moment.fill(0)
        net.steps = 0
    dx, dm, da = demo
    for epoch in range(first, epochs):
        ids, losses = rng.permutation(keep), []
        for offset in range(0, len(ids), 64):
            rows = ids[offset:offset + 64]
            di = rng.integers(0, len(da), 64)
            inputs = np.concatenate([x[rows], dx[di]])
            a, b, q = forward(net, inputs)
            loss, dq = advantage_loss(q[:len(rows)], masks[rows], returns[rows])
            ce, dc = classification_loss(q[len(rows):], dm[di], da[di])
            combined = np.concatenate([dq, anchor * dc])
            backward(net, inputs, a, b, combined, rate)
            losses.append(loss + anchor * ce)
        net.save(path, {'epoch': epoch + 1, 'numpy_rng': rng.bit_generator.state,
                        'groups': len(groups), 'signals': len(keep), 'algorithm': 'paired full-game policy iteration'})
        print(json.dumps({'event': 'counterfactual_fit', 'epoch': epoch + 1, 'signals': len(keep),
                          'loss': float(np.mean(losses))}), flush=True)
    return net


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', default='counterfactual-v3')
    parser.add_argument('--refine-run', default='refine-v3')
    parser.add_argument('--wait', action='store_true')
    parser.add_argument('--rounds', type=int, default=6)
    parser.add_argument('--groups', type=int, default=300)
    parser.add_argument('--max-groups', type=int, default=1200)
    parser.add_argument('--min-signals', type=int, default=32)
    parser.add_argument('--per-game', type=int, default=2)
    parser.add_argument('--samples', type=int, default=32)
    parser.add_argument('--epochs', type=int, default=30)
    parser.add_argument('--rate', type=float, default=1e-4)
    parser.add_argument('--anchor', type=float, default=.01)
    parser.add_argument('--screen-pairs', type=int, default=64)
    parser.add_argument('--confirm-pairs', type=int, default=128)
    parser.add_argument('--collection-canary', action='store_true',
                        help='Only verify actual-choice replay against the frozen engine on training games')
    parser.add_argument('--hours', type=float, default=8)
    parser.add_argument('--deadline', type=float, default=1793745649.6650429)
    args = parser.parse_args()
    if any(Path(n).name != n for n in (args.run, args.refine_run)):
        parser.error('Use simple run directory names')
    if min(args.groups, args.max_groups, args.per_game, args.samples, args.epochs,
           args.screen_pairs, args.confirm_pairs, args.rounds) < 1 or args.groups > args.max_groups:
        parser.error('Positive counts and groups <= max-groups are required')
    low_priority()
    run = ROOT / 'runs/double-dqn' / args.run
    run.mkdir(parents=True, exist_ok=True)
    state_path = run / 'state.json'
    state = json.loads(state_path.read_text()) if state_path.exists() else {
        'round': 0, 'best_score': -1., 'started_unix': time.time(),
        'deadline_unix': min(args.deadline, time.time() + args.hours * 3600)}
    state.update(pid=os.getpid(), status='waiting_for_refinement' if args.wait else 'starting')
    write_json(state_path, state)
    prior = ROOT / 'runs/double-dqn' / args.refine_run
    while not (prior / 'result.json').exists():
        if not args.wait:
            raise ValueError('Complete controlled refinement before starting counterfactual RL')
        if time.time() >= args.deadline or (run / 'STOP').exists():
            state['status'] = 'stopped_before_start'
            write_json(state_path, state)
            return
        time.sleep(15)
    selected = json.loads((prior / 'result.json').read_text())['selected']
    source = prior / (selected + '.npz')
    plan = dict(vars(args), start_sha256=sha(source),
                source_sha256={str(p.relative_to(ROOT)): sha(p) for p in (Path(__file__), ROOT / 'pogo/counterfactual.py', ROOT / 'pogo/dqn.py')},
                final_tests=False, screening_seed=38211,
                confirmation_seed=38212, reset_optimizer_each_round=True,
                target='paired terminal win/draw/loss advantages, all legal choices, observed-choice replay must match',
                sampling='before consulting outcomes; callback-type reservoirs, wins and losses alike')
    if (run / 'plan.json').exists() and json.loads((run / 'plan.json').read_text()) != plan:
        raise ValueError('Counterfactual run identity changed')
    write_json(run / 'plan.json', plan)
    deadline = state['deadline_unix']
    def stop():
        return time.time() >= deadline or (run / 'STOP').exists()
    f = frozen()
    if not (run / 'initial.npz').exists():
        shutil.copyfile(source, run / 'initial.npz')
    if args.collection_canary:
        net, _, _ = Network.load(run / 'initial.npz')
        settings = {'seed': 38200, 'groups': args.groups, 'max_groups': args.max_groups,
                    'min_signals': 0, 'per_game': args.per_game, 'samples': args.samples,
                    'policy_sha256': sha(run / 'initial.npz')}
        groups, info = collect(f, net, run / 'canary_labels.npz', settings, stop)
        if len(groups) < args.groups or info['matched_controls'] != len(groups) or info['episodes'] < 2:
            raise RuntimeError('Incomplete replay canary; both player sides and all controls are required')
        state.update(status='canary_complete')
        write_json(state_path, state)
        write_json(run / 'result.json', dict(info, groups=len(groups),
                   status='canary_complete', strength_evidence=False, final_test_opened=False))
        return
    if state['best_score'] < 0:
        net, _, _ = Network.load(run / 'initial.npz')
        baseline = evaluate(run, net, run / 'initial.npz', 'validation', 38211, args.screen_pairs,
                            samples=32, tag='screen_initial')
        state.update(best_score=baseline['score'], best_checkpoint='initial.npz')
        write_json(state_path, state)
    with np.load(ROOT / 'runs/double-dqn/dqn-v2/demonstrations.npz', allow_pickle=False) as data:
        demo = data['x'], data['mask'], data['action']
    terminal_status = 'research_rounds_complete'
    for round_id in range(state['round'] + 1, args.rounds + 1):
        if stop():
            terminal_status = 'stopped_with_checkpoints'
            break
        net, _, _ = Network.load(run / state['best_checkpoint'])
        state.update(status='collecting', active_round=round_id)
        write_json(state_path, state)
        settings = {'seed': 38201 + 7919 * round_id, 'groups': args.groups, 'max_groups': args.max_groups,
                    'min_signals': args.min_signals, 'per_game': args.per_game, 'samples': args.samples,
                    'policy_sha256': sha(run / state['best_checkpoint'])}
        groups, info = collect(f, net, run / f'labels_{round_id:03d}.npz', settings, stop)
        write_json(run / f'collection_{round_id:03d}.json', dict(info, groups=len(groups)))
        if info['signals'] < 8:
            terminal_status = 'stopped_with_checkpoints' if stop() else 'insufficient_signal'
            state.update(status=terminal_status, reason='Fewer than eight paired action-changing positions')
            write_json(state_path, state)
            break
        if stop():
            terminal_status = 'stopped_with_checkpoints'
            break
        state['status'] = 'fitting'
        write_json(state_path, state)
        path = run / f'candidate_{round_id:03d}.npz'
        net = fit(net, groups, demo, args.epochs, args.rate, args.anchor, 38251 + round_id, path)
        if stop():
            terminal_status = 'stopped_with_checkpoints'
            break
        report = evaluate(run, net, path, 'validation', 38211, args.screen_pairs,
                          samples=32, tag=f'screen_{round_id:03d}')
        if report['score'] > state['best_score']:
            state.update(best_score=report['score'], best_checkpoint=path.name)
        state['round'] = round_id
        append(run / 'rounds.jsonl', {'round': round_id, 'signals': info['signals'], 'groups': len(groups),
                                    'score': report['score'], 'margin95': report['margin95'],
                                    'best_checkpoint': state['best_checkpoint']})
        write_json(state_path, state)
    confirmation = None
    if terminal_status == 'research_rounds_complete' and not stop():
        state['status'] = 'confirming_selected'
        write_json(state_path, state)
        selected_path = run / state['best_checkpoint']
        net, _, _ = Network.load(selected_path)
        confirmation = evaluate(run, net, selected_path, 'validation', 38212, args.confirm_pairs,
                                samples=32, tag='confirmation')
    elif stop():
        terminal_status = 'stopped_with_checkpoints'
    state['status'] = terminal_status
    write_json(state_path, state)
    # This is a research checkpoint, not final evidence. Final testing is separately locked only when warranted.
    write_json(run / 'result.json', {'best_checkpoint': state['best_checkpoint'], 'screen_score': state['best_score'],
                                   'rounds': state['round'], 'status': terminal_status,
                                   'confirmation': confirmation, 'final_test_opened': False})


if __name__ == '__main__':
    main()
