#!/usr/bin/env python3
"""Read-only audit of a complete 128-pair offline-return validation decision."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.audit_standalone_final import pairing_values, check_statistics, require
from scripts.offline_returns_rl import sources
from scripts.select_capacity_candidate import paired_difference
from pogo.rl_experiment import atomic_json, digest, FrozenRuntime, schedule, stream_seed, team_split
from pogo.standalone_rl_v2 import ActorCritic
import numpy as np


def audit(run):
    require(Path(run).name == run and run not in ('.', '..'), 'run must be one directory name')
    folder = ROOT / 'runs/standalone-rl' / run
    parent = folder.parent / 'mc-ppo-v3'
    read = lambda path: json.loads(path.read_text(encoding='utf-8-sig'))
    config, decision = (read(folder / name) for name in ('experiment.json', 'decision.json'))
    cursor = decision['cursor']
    round_index = max(1, cursor['epoch'] + int(cursor['position'] > 0))
    log = folder / f'validation_{round_index:05d}_greedy.jsonl'
    result = read(folder / f'validation_summary_{round_index:05d}_greedy.json')
    records = [json.loads(s) for s in log.read_text().splitlines()]
    old = [json.loads(s) for s in (parent / 'validation_00104_greedy.jsonl').read_text().splitlines()]
    require(config['sources'] == sources(), 'source mismatch')
    require(digest(folder / 'offline_data.json') == config['offline_data_sha256'], 'data manifest mismatch')
    values, counts = pairing_values(records[1:], 128)
    old_values, _ = pairing_values(old[1:], 128)
    header = records[0]
    require(header == result['header'], 'summary header mismatch')
    require(header['opponent'] == 'engine' and header['samples'] == 32 and header['greedy'] is True,
            'validation opponent/mode mismatch')
    require(header['frozen_commit'] == config['commit'], 'frozen opponent mismatch')
    require(all(result[k] == v for k, v in counts.items()), 'counts mismatch')
    bootstrap_seed = check_statistics(values, result, header['schedule_sha256'])
    cases = read(folder / 'validation_schedule_mixed.json')
    require(cases == read(parent / 'validation_schedule_mixed.json'), 'parent schedule mismatch')
    require(cases == schedule(FrozenRuntime(ROOT / config['snapshot']), 'validation', 'mixed',
                              stream_seed(config['seed'], 'validation'), 128), 'regenerated schedule mismatch')
    require(all(team_split(t) == 'validation' for case in cases for t in case['teams']), 'partition mismatch')
    require(hashlib.sha256(json.dumps(cases, sort_keys=True).encode()).hexdigest() == header['schedule_sha256'],
            'schedule hash mismatch')

    for name in ('candidate.npz', 'best.npz'):
        model, _ = ActorCritic.load(folder / name)
        fingerprint = hashlib.sha256(b''.join(model.params[k].tobytes() for k in sorted(model.params))).hexdigest()
        require(fingerprint == header['weights_sha256'], 'weights mismatch')
        require(all(np.isfinite(v).all() for group in (model.params, model.m, model.v) for v in group.values()),
                'nonfinite parameters or optimizer')
    require(digest(folder / 'candidate.npz') == header['metadata']['checkpoint_sha256'], 'candidate digest mismatch')
    require(digest(folder / 'best.npz') == decision['checkpoint_sha256'], 'best digest mismatch')
    parent_path = Path(config['initialization']['checkpoint'])
    parent_path = parent_path if parent_path.is_absolute() else ROOT / parent_path
    require(digest(parent_path) == config['initialization']['sha256'], 'parent artifact mismatch')
    model, _ = ActorCritic.load(parent_path)
    fingerprint = hashlib.sha256(b''.join(model.params[k].tobytes() for k in sorted(model.params))).hexdigest()
    require(old[0]['weights_sha256'] == fingerprint and old[0]['samples'] == 32
            and old[0]['greedy'] is True and old[0]['frozen_commit'] == config['commit'], 'parent provenance mismatch')
    require(old[0]['schedule_sha256'] == header['schedule_sha256'], 'pair schedule mismatch')
    paired = paired_difference(old[1:], records[1:])
    require(paired == decision['paired_difference'], 'paired statistic mismatch')
    require(decision['score'] == result['score'] and decision['ci95'] == result['ci95'], 'decision statistic mismatch')
    qualified = result['ci95'][0] > .5 and paired['ci95'][0] > 0
    require(decision['validation_qualified'] == qualified, 'qualification mismatch')
    require(decision['enter_final'] == (qualified and decision['enough_final_time']), 'promotion mismatch')
    return dict(scope='Complete offline-return validation audit', run=run, result=result,
                paired_difference=paired, parent_score=float(np.mean(old_values)), sources_verified=True,
                validation_schedule_regenerated=True, score_mapping_checked=True, statistics_recomputed=True,
                bootstrap_seed_string=bootstrap_seed, best_checkpoint_sha256=digest(folder / 'best.npz'),
                candidate_checkpoint_sha256=digest(folder / 'candidate.npz'),
                pairing_log_sha256=digest(log), enter_final=decision['enter_final'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    report = audit(args.run)
    atomic_json(args.output, report)
    print(json.dumps(dict(score=report['result']['score'], ci95=report['result']['ci95'],
                         paired=report['paired_difference'], enter_final=report['enter_final'], audit_passed=True)))
