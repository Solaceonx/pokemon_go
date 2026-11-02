#!/usr/bin/env python3
"""Resumable independent Double DQN experiment; standard library + NumPy only.

python scripts/double_dqn.py prepare --run trial
python scripts/double_dqn.py bootstrap --run trial --games 5000 --epochs 25
python scripts/double_dqn.py train --run trial --hours 12 --engine-share .25
python scripts/double_dqn.py evaluate --run trial --checkpoint selected.npz --split test --seed 38091 --pairs 1000

One worker, low OS priority. Training uses only training teams; validation chooses checkpoints.
Final test checkpoints are locked before any test outcome is generated. Never tune on final test.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import random
import shutil
import statistics
import subprocess
import sys
import tarfile
import time

for _var in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[_var] = '1'

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pogo.arena import low_priority
from pogo.dqn import Agent, Network, Replay, double_targets, transitions, N_FEATURES

BASE = '59836c86f4c9ccf7e8d35ef7c94268e64c1a4ba9'
ALGORITHM = 'Double DQN, 8-step replay, prioritized sampling, demonstration margin, MC auxiliary'
TEST_SEEDS = (38091, 38092)
_frozen = None


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path = Path(path)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    temp.replace(path)


def append(path, value):
    with Path(path).open('a', encoding='utf-8') as f:
        f.write(json.dumps(value) + '\n')


def bucket(team):
    """All lead/bench permutations of a species composition always share one split."""
    names = sorted(b if isinstance(b, str) else (b.home or b.species_id) for b in team)
    value = int(hashlib.sha256(('dqn-team-v1:' + '|'.join(names)).encode()).hexdigest()[:16], 16) % 10
    return 'train' if value < 8 else 'validation' if value == 8 else 'test'


def draw_split(draw, rng, split):
    for _ in range(100000):
        team = draw(rng)
        if bucket(team) == split:
            return team
    raise RuntimeError('Unable to draw a team for ' + split)


def freeze():
    dest = ROOT / '.dqn-cache' / BASE
    receipt = dest / 'manifest.json'
    if not receipt.exists():
        dest.mkdir(parents=True, exist_ok=True)
        archive = subprocess.check_output(['git', 'archive', BASE, 'pogo', 'data',
                                           'runs/general-decide/q.npz', 'runs/eval/eval.npz'], cwd=ROOT)
        hashes = {}
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            for item in tar:
                if not item.isfile():
                    continue
                path = dest / item.name
                if not path.resolve().is_relative_to(dest.resolve()):
                    raise ValueError('Archive path escapes frozen directory')
                path.parent.mkdir(parents=True, exist_ok=True)
                data = tar.extractfile(item).read()
                path.write_bytes(data)
                hashes[item.name] = hashlib.sha256(data).hexdigest()
        write_json(receipt, {'commit': BASE, 'files': hashes})
    manifest = json.loads(receipt.read_text(encoding='utf-8'))
    for name, digest in manifest['files'].items():
        if sha(dest / name) != digest:
            raise ValueError('Frozen source or data changed: ' + name)
    return dest, manifest


class Frozen:
    def __init__(self):
        self.path, self.manifest = freeze()
        spec = importlib.util.spec_from_file_location('dqn_frozen_pogo', self.path / 'pogo/__init__.py',
                                                      submodule_search_locations=[str(self.path / 'pogo')])
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        self.modules = {name: importlib.import_module('dqn_frozen_pogo.' + name)
                        for name in ('battle', 'gamedata', 'learner', 'engine', 'evaluation', 'teamshape', 'teamlist', 'agents', 'realtime')}
        self.gd = self.modules['gamedata'].GameData()
        self.pool = self.gd.meta(50)
        self.mixed_pool, self.mixed_draw = self.modules['teamshape'].mixed_field(self.gd)
        self.standard_draw = self.modules['teamlist'].drawer(self.gd, self.pool)
        self.q = self.modules['learner'].QNet.load(self.path / 'runs/general-decide/q.npz')
        self.value = self.modules['evaluation'].Evaluator.load(self.path / 'runs/eval/eval.npz').model

    def engine(self, seed, samples=32):
        # Immutable weights may be shared; evaluator and outlook caches must be per player/game.
        return self.modules['engine'].Engine(self.modules['evaluation'].Evaluator(self.value), self.pool,
                                             rollout='bot', samples=samples, horizon=20, edge=.03,
                                             q=self.q, margin=.02, seed=seed)

    def learner(self, seed):
        return self.modules['learner'].Learner(q=self.q, margin=.02, seed=seed)

    def game(self, a, b, pilot, opponent, seed, side=0):
        args = (a, b, pilot, opponent) if side == 0 else (b, a, opponent, pilot)
        battle = self.modules['battle'].Battle(*args, seed=seed)
        winner = battle.run()
        result = 0. if winner == -1 else 1. if winner == side else -1.
        return result, battle


def frozen():
    global _frozen
    if _frozen is None:
        _frozen = Frozen()
    return _frozen


def receipt(run):
    f = frozen()
    body = {'algorithm': ALGORITHM, 'baseline_commit': BASE, 'baseline_files': f.manifest['files'],
            'engine': {'class': 'Engine', 'samples': 32, 'horizon': 20, 'rollout': 'bot', 'edge': .03,
                       'margin': .02, 'deadlines': False, 'pool': 'frozen GameData.meta(50)'},
            'split': 'sha256(dqn-team-v1:sorted home species), modulo 10: 0..7 train, 8 validation, 9 test',
            'test_seeds': list(TEST_SEEDS), 'success': 'Both fresh-seed mixed tests lower 95% bounds > 0.5; standard cross-check',
            'features': N_FEATURES, 'workers': 1, 'numpy_threads': 1, 'python': sys.version, 'numpy': np.__version__,
            'prior_work': 'PR #10 reviewed: energy cap rollback/forms, tracked probabilities, paired camera diagnostic; no tracker training here',
            'parallel_algorithm': 'PPO in PR #11; this branch uses replay-based Double DQN'}
    path = run / 'protocol.json'
    if path.exists():
        old = json.loads(path.read_text(encoding='utf-8'))
        if old['baseline_files'] != body['baseline_files']:
            raise ValueError('Baseline changed')
    else:
        write_json(path, body)


def checkpoint(run, net, target, replay, meta):
    slot = (int(meta.get('snapshot', -1)) + 1) % 2
    meta['snapshot'] = slot
    net.save(run / f'latest_{slot}.npz', meta, target)
    replay.save(run / f'replay_{slot}.npz')
    write_json(run / 'resume.json', {'slot': slot})


def load_training(run, seed):
    if (run / 'resume.json').exists():
        slot = json.loads((run / 'resume.json').read_text())['slot']
        net, meta, target = Network.load(run / f'latest_{slot}.npz')
        replay = Replay.load(run / f'replay_{slot}.npz')
        rng = np.random.default_rng()
        rng.bit_generator.state = meta['numpy_rng']
    else:
        net, meta, _ = Network.load(run / 'bootstrap.npz')
        target, replay, rng = copy.deepcopy(net), Replay(), np.random.default_rng(seed)
        meta = {'games': 0, 'seed': seed, 'batches': 0, 'best_validation': -1., 'train_seconds': 0.}
    return net, meta, target, replay, rng


def ci(scores):
    if len(scores) < 2:
        return {'score': statistics.mean(scores) if scores else None, 'margin95': None,
                'lower95': 0., 'upper95': 1., 'clusters': len(scores)}
    mean = statistics.mean(scores)
    margin = 1.96 * statistics.stdev(scores) / math.sqrt(len(scores))
    # Normal clustered interval is the repository convention; bounded Hoeffding guard for zero variance.
    if margin == 0:
        margin = math.sqrt(math.log(40) / (2 * len(scores)))
    return {'score': mean, 'margin95': margin, 'lower95': max(0., mean - margin),
            'upper95': min(1., mean + margin), 'clusters': len(scores)}


def evaluate(run, net, checkpoint_path, split, seed, pairs, field='mixed', samples=32, tag='evaluation', resume=True):
    f = frozen()
    draw = f.mixed_draw if field == 'mixed' else f.standard_draw
    digest = sha(checkpoint_path)
    key = {'model_sha256': digest, 'split': split, 'seed': seed, 'pairs': pairs,
           'field': field, 'samples': samples, 'baseline_commit': BASE}
    path = run / f'evaluation_{tag}.jsonl'
    config = run / f'{tag}_config.json'
    if config.exists() and json.loads(config.read_text()) != key:
        raise ValueError('Evaluation identity changed; choose a new tag')
    write_json(config, key)
    completed = {}
    if resume and path.exists():
        for line in path.read_text().splitlines():
            row = json.loads(line)
            completed[row['pair']] = row
    rng = random.Random(seed)
    begin = time.monotonic()
    for i in range(pairs):
        a, b = draw_split(draw, rng, split), draw_split(draw, rng, split)
        seeds = [rng.getrandbits(32) for _ in range(6)]
        if i in completed:
            continue
        scores, decisions = [], []
        for orientation, (mine, theirs) in enumerate(((a, b), (b, a))):
            player = Agent(net, seed=seeds[orientation * 3])
            opponent = f.engine(seeds[orientation * 3 + 1], samples)
            result, battle = f.game(mine, theirs, player, opponent, seeds[orientation * 3 + 2], side=(i + orientation) % 2)
            scores.append((result + 1) / 2)
            decisions.append(opponent.looks)
        row = {'pair': i, 'teams': [[m.home or m.species_id for m in t] for t in (a, b)],
               'scores': scores, 'mean': statistics.mean(scores), 'engine_searches': decisions}
        append(path, row)
        completed[i] = row
        if (i + 1) % 10 == 0 or i + 1 == pairs:
            current = ci([r['mean'] for r in completed.values()])
            print(json.dumps({'event': 'eval_progress', 'tag': tag, 'pairs': len(completed),
                              'score': current['score'], 'seconds': time.monotonic() - begin}), flush=True)
    summary = dict(key, **ci([completed[i]['mean'] for i in range(pairs)]),
                   battles=2 * pairs, pair_scores=[completed[i]['mean'] for i in range(pairs)],
                   seconds_this_invocation=time.monotonic() - begin)
    write_json(run / f'{tag}_summary.json', summary)
    print(json.dumps({'event': 'evaluation', 'tag': tag, **summary}), flush=True)
    return summary


def bootstrap(args, run):
    f = frozen()
    demo_path = run / 'demonstrations.npz'
    state_path = run / 'demonstrations.json'
    demos = Replay.load(demo_path) if demo_path.exists() else Replay(args.demo_capacity)
    done = json.loads(state_path.read_text())['games'] if state_path.exists() else 0
    net = Network(args.seed, hidden=args.hidden)
    rng = random.Random(args.seed)
    begin = time.monotonic()
    for i in range(args.games):
        a, b = draw_split(f.mixed_draw, rng, 'train'), draw_split(f.mixed_draw, rng, 'train')
        seeds = [rng.getrandbits(32) for _ in range(3)]
        if i < done:
            continue
        p = Agent(net, seed=seeds[0], teacher=f.learner(seeds[0]), record=True)
        q = Agent(net, seed=seeds[1], teacher=f.learner(seeds[1]), record=True)
        result, _ = f.game(a, b, p, q, seeds[2])
        demos.add(transitions(p.log, result))
        demos.add(transitions(q.log, -result))
        if (i + 1) % 250 == 0 or i + 1 == args.games:
            demos.save(demo_path)
            write_json(state_path, {'games': i + 1, 'seed': args.seed, 'transitions': demos.size})
            print(json.dumps({'event': 'demo', 'games': i + 1, 'rows': demos.size,
                              'seconds': time.monotonic() - begin}), flush=True)
    order = np.random.default_rng(args.seed)
    if (run / 'bootstrap.npz').exists():
        net, meta, _ = Network.load(run / 'bootstrap.npz')
        first_epoch = meta.get('epoch', 0)
        if 'numpy_rng' in meta:
            order.bit_generator.state = meta['numpy_rng']
    else:
        first_epoch = 0
    for epoch in range(first_epoch, args.epochs):
        ids = order.permutation(demos.size)
        losses = []
        for start in range(0, len(ids), args.batch):
            ix = ids[start:start + args.batch]
            loss, _ = net.update(demos.x[ix], demos.action[ix], .2 * demos.mc[ix], demos.mask[ix],
                                 imitation=1., rate=args.rate)
            losses.append(loss)
        # Training agreement is diagnostic only; it does not select the best policy.
        ix = np.arange(min(10000, demos.size))
        votes = np.where(demos.mask[ix], net.predict(demos.x[ix]), -np.inf).argmax(axis=1)
        row = {'event': 'bootstrap', 'epoch': epoch + 1, 'loss': float(np.mean(losses)),
               'train_agreement': float(np.mean(votes == demos.action[ix])), 'games': args.games}
        meta = dict(row, numpy_rng=order.bit_generator.state, seed=args.seed)
        net.save(run / 'bootstrap.npz', meta)
        append(run / 'experiments.jsonl', row)
        print(json.dumps(row), flush=True)


def train(args, run):
    if (run / 'test_lock.json').exists():
        raise ValueError('Final-test selection locked; use a new run for further training')
    f = frozen()
    net, meta, target, replay, rng = load_training(run, args.seed)
    demos = Replay.load(run / 'demonstrations.npz')
    start, block = time.monotonic(), time.monotonic()
    last_eval = meta.get('last_eval', 0)
    settings = {k: v for k, v in vars(args).items() if k not in ('command', 'run')}
    settings_path = run / 'training_settings.json'
    if settings_path.exists():
        old = json.loads(settings_path.read_text())
        # Duration may change when resuming; all learning/distribution settings remain fixed.
        if {k: v for k, v in old.items() if k != 'hours'} != {k: v for k, v in settings.items() if k != 'hours'}:
            raise ValueError('Training settings changed on resume')
    write_json(settings_path, settings)
    while time.monotonic() - start < args.hours * 3600:
        game_id = meta['games']
        episode_rng = random.Random(meta['seed'] + 1000003 * game_id)
        a, b = draw_split(f.mixed_draw, episode_rng, 'train'), draw_split(f.mixed_draw, episode_rng, 'train')
        epsilon = max(args.epsilon_min, args.epsilon * math.exp(-game_id / args.epsilon_decay))
        player = Agent(net, seed=episode_rng.getrandbits(32), epsilon=epsilon, record=True)
        if episode_rng.random() < args.engine_share:
            opponent = f.engine(episode_rng.getrandbits(32), args.train_samples)
            opponent_name = f'engine{args.train_samples}'
        else:
            opponent = f.learner(episode_rng.getrandbits(32))
            opponent_name = 'learner'
        result, _ = f.game(a, b, player, opponent, episode_rng.getrandbits(32), side=game_id % 2)
        replay.add(transitions(player.log, result, args.nstep))
        losses = []
        if replay.size >= args.batch:
            for _ in range(args.updates):
                ix, weights = replay.sample(rng, args.batch)
                td = double_targets(net, target, replay.next_x[ix], replay.next_mask[ix], replay.reward[ix], replay.discount[ix])
                targets = (1 - args.mc_share) * td + args.mc_share * replay.mc[ix]
                loss, errors = net.update(replay.x[ix], replay.action[ix], targets, rate=args.rate, weights=weights)
                replay.priority[ix] = errors + .01
                di = rng.integers(0, demos.size, args.batch // 4)
                # Demo Q labels are whole-game returns. The small supervised term stabilizes action ordering.
                net.update(demos.x[di], demos.action[di], demos.mc[di], demos.mask[di],
                           imitation=args.demo_margin, rate=args.rate)
                meta['batches'] += 1
                if meta['batches'] % args.target_every == 0:
                    target.p = [p.copy() for p in net.p]
                losses.append(loss)
        meta['games'] += 1
        append(run / 'training_games.jsonl', {'game': meta['games'], 'opponent': opponent_name,
                                             'result': result, 'decisions': len(player.log), 'epsilon': epsilon,
                                             'loss': float(np.mean(losses)) if losses else None})
        if meta['games'] % args.save_every == 0:
            meta['numpy_rng'] = rng.bit_generator.state
            meta['train_seconds'] += time.monotonic() - block
            checkpoint(run, net, target, replay, meta)
            row = {'event': 'training', 'games': meta['games'], 'batches': meta['batches'],
                   'replay': replay.size, 'train_seconds': meta['train_seconds'], 'epsilon': epsilon}
            append(run / 'experiments.jsonl', row)
            print(json.dumps(row), flush=True)
            block = time.monotonic()
        if meta['games'] - last_eval >= args.eval_every:
            name = f'checkpoint_{meta["games"]:06d}.npz'
            net.save(run / name, meta, target)
            report = evaluate(run, net, run / name, 'validation', 38031, args.validation_pairs,
                              samples=args.validation_samples, tag=f'validation_{meta["games"]:06d}')
            if report['score'] > meta['best_validation']:
                meta['best_validation'] = report['score']
                meta['best_checkpoint'] = name
                shutil.copyfile(run / name, run / 'best.npz')
                write_json(run / 'selection.json', {'checkpoint': name, 'sha256': sha(run / name),
                                                  'criterion': 'maximum validation win share; earliest checkpoint wins ties',
                                                  'validation': report})
            last_eval = meta['last_eval'] = meta['games']
            block = time.monotonic()
    meta['numpy_rng'] = rng.bit_generator.state
    meta['train_seconds'] += time.monotonic() - block
    checkpoint(run, net, target, replay, meta)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('command', choices=('prepare', 'bootstrap', 'train', 'evaluate'))
    parser.add_argument('--run', default='dqn-v1')
    parser.add_argument('--seed', type=int, default=38001)
    parser.add_argument('--games', type=int, default=5000)
    parser.add_argument('--epochs', type=int, default=25)
    parser.add_argument('--hidden', type=int, default=128)
    parser.add_argument('--demo-capacity', type=int, default=100000)
    parser.add_argument('--batch', type=int, default=256)
    parser.add_argument('--rate', type=float, default=3e-4)
    parser.add_argument('--hours', type=float, default=12)
    parser.add_argument('--engine-share', type=float, default=.25)
    parser.add_argument('--train-samples', type=int, default=4)
    parser.add_argument('--nstep', type=int, default=8)
    parser.add_argument('--updates', type=int, default=4)
    parser.add_argument('--target-every', type=int, default=500)
    parser.add_argument('--mc-share', type=float, default=.5)
    parser.add_argument('--demo-margin', type=float, default=.1)
    parser.add_argument('--epsilon', type=float, default=.15)
    parser.add_argument('--epsilon-min', type=float, default=.02)
    parser.add_argument('--epsilon-decay', type=float, default=10000)
    parser.add_argument('--save-every', type=int, default=100)
    parser.add_argument('--eval-every', type=int, default=2000)
    parser.add_argument('--validation-pairs', type=int, default=100)
    parser.add_argument('--validation-samples', type=int, default=8)
    parser.add_argument('--checkpoint', default='best.npz')
    parser.add_argument('--split', choices=('validation', 'test'), default='validation')
    parser.add_argument('--field', choices=('mixed', 'standard'), default='mixed')
    parser.add_argument('--samples', type=int, default=32)
    parser.add_argument('--pairs', type=int, default=1000)
    parser.add_argument('--tag', default='manual')
    args = parser.parse_args()
    if not 0 <= args.engine_share <= 1 or args.pairs < 2 or args.batch < 4 or args.hours <= 0:
        parser.error('invalid engine share, pair count, batch size, or duration')
    if Path(args.run).name != args.run:
        parser.error('--run must be a directory name')
    low_priority()
    run = ROOT / 'runs/double-dqn' / args.run
    run.mkdir(parents=True, exist_ok=True)
    receipt(run)
    append(run / 'invocations.jsonl', {'argv': sys.argv, 'utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())})
    if args.command == 'bootstrap':
        bootstrap(args, run)
    elif args.command == 'train':
        train(args, run)
    elif args.command == 'evaluate':
        path = run / args.checkpoint
        net, _, _ = Network.load(path)
        if args.split == 'test':
            if args.samples != 32 or args.seed not in TEST_SEEDS:
                parser.error('final tests require 32 samples and predeclared seeds 38091 or 38092')
            lock = run / 'test_lock.json'
            body = {'sha256': sha(path), 'checkpoint': args.checkpoint,
                    'seeds': list(TEST_SEEDS), 'pairs_per_seed': args.pairs}
            if lock.exists() and json.loads(lock.read_text()) != body:
                raise ValueError('Final-test checkpoint or sample size already locked')
            write_json(lock, body)
        evaluate(run, net, path, args.split, args.seed, args.pairs, args.field, args.samples, args.tag)
    else:
        print(json.dumps({'event': 'prepared', 'run': str(run), 'baseline': BASE}), flush=True)


if __name__ == '__main__':
    main()
