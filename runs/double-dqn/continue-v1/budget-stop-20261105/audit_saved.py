"""Audit deadline-stopped evidence without games or a reduced-sample strength claim.

Run from the experiment checkout. This is a terminal evidence artifact, never a
numerical-worker import. The full three-block verdict auditor is deliberately not run.
"""
import os
for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS'):
    os.environ[key] = '1'
import base64
import copy
import datetime
import json
import math
from pathlib import Path
import random
import statistics
import struct
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from scripts import check_dqn_continue as checker


def validate_partial_row(row, index, teams, seeds):
    points = row.get('scores', [])
    if (row.get('pair') != index or row.get('teams') != teams
            or row.get('game_seeds') != seeds
            or row.get('player_sides') != [(index + o) % 2 for o in range(2)]
            or len(points) != 2 or any(v not in (0., .5, 1.) for v in points)
            or row.get('mean') != statistics.mean(points)
            or len(row.get('seconds', [])) != 2
            or any(not math.isfinite(v) or v < 0 for v in row['seconds'])):
        raise ValueError('Partial saved row differs from locked draw/seeds/sides/outcomes')


def main():
    run = ROOT / 'runs/double-dqn/continue-v1'
    closure = Path(__file__).resolve().parent
    plan = json.loads((run / 'plan.json').read_text())
    assert checker.sha(run / 'plan.json') == checker.PLAN_SHA
    assert plan['absolute_deadline_unix'] == 1793912387
    assert not (run / 'verdict.json').exists(), 'Use full verdict audit for a complete benchmark'
    terminal = json.loads((closure / 'controller_state.json').read_text())
    absence = json.loads((closure / 'process_absence.json').read_text(encoding='utf-8-sig'))
    assert terminal['phase'] == 'stopped_with_checkpoints' and terminal['worker_pid'] is None
    stopped = datetime.datetime.fromisoformat(terminal['updated_utc'].replace('Z', '+00:00'))
    assert 0 <= stopped.timestamp() - plan['absolute_deadline_unix'] < 5.1
    assert absence['both_recorded_pids_absent'] and not absence['new_numerical_worker_started']

    exclusion_path = run / 'holdout_exclusions.json'
    assert checker.sha(exclusion_path) == plan['holdout_exclusions_sha256']
    exclusion = json.loads(exclusion_path.read_text())
    packed = base64.b64decode(exclusion['team_sha256_base64'], validate=True)
    old_teams = {packed[i:i+32] for i in range(0, len(packed), 32)}
    old_seeds = set(struct.unpack('>' + 'I' * exclusion['seed_count'],
        base64.b64decode(exclusion['game_seeds_u32be_base64'], validate=True)))
    rebuilt_teams, rebuilt_seeds = set(), set()
    for relative, digest in exclusion['source_journals_sha256'].items():
        journal = ROOT / relative
        assert checker.sha(journal) == digest
        for line in journal.read_text().splitlines():
            row = json.loads(line)
            rebuilt_teams.update(checker.fingerprint(t) for t in row['teams'])
            rebuilt_seeds.update(row['game_seeds'])
    assert old_teams == rebuilt_teams and old_seeds == rebuilt_seeds
    assert len(old_teams) == 1380 and len(old_seeds) == 17751

    activation = json.loads((run / 'activation.json').read_text())
    runtime = ROOT / activation['runtime']
    assert checker.sha(runtime / 'source_manifest.json') == activation['source_manifest_sha256']
    manifest = json.loads((runtime / 'source_manifest.json').read_text())
    for name, digest in manifest.items():
        assert checker.sha(runtime / name) == digest, name
    assert checker.sha(ROOT / activation['guard']) == activation['guard_sha256']
    checker.verify_inputs(run, plan)
    frozen = checker.frozen()
    protocol = json.loads((run / 'final/protocol.json').read_text())
    assert protocol['baseline'] == frozen.manifest
    assert (run / 'test_lock.json').read_bytes() == (run / 'final/protocol.json').read_bytes()
    assert checker.sha(run / 'test_lock.json') == '69d59dd349b7990e32c90db078f64cb28dc91d88f90aaaa57a421379e2a35b62'
    assert checker.sha(run / 'final/policy.npz') == protocol['policy_sha256']
    assert checker.sha(run / 'choice.json') == protocol['choice_sha256']
    assert protocol['pairs_per_block'] == 1000 and protocol['deadline_unix'] == 1793912387
    assert protocol['blocks'] == [['mixed', 39091], ['mixed', 39092], ['standard', 39091]]
    assert checker.sha(ROOT / 'runs/double-dqn/final_test_lock.json') == plan['previous_global_lock_sha256']
    assert checker.sha(ROOT / 'runs/double-dqn/final-teacher32-v1/verdict.json') == plan['previous_verdict_sha256']
    state = json.loads((run / 'state.json').read_text())
    for stage in state['stages']:
        assert checker.sha(run / f"stage_{stage['index']}.npz") == stage['model_sha256']
    selected = run / 'stage_1.npz'
    assert checker.sha(selected) == protocol['source_model_sha256']
    full, _, _ = checker.load_network(selected)
    compact, metadata, _ = checker.load_network(run / 'final/policy.npz')
    assert checker.same_parameters(full, compact)
    assert metadata == {'source_sha256': checker.sha(selected), 'weights_only': True}
    assert compact.steps == 0 and not any(m.any() for m in compact.m + compact.v)

    first_receipt = json.loads((run / 'first_final_block_artifacts.json').read_text())
    retained = dict(first_receipt['retained_receipt_hashes'])
    for name, digest in retained.items():
        assert checker.sha(run / name) == digest, name
    block_reports = []
    for seed in (39091, 39092):
        directory = run / f'final_mixed_{seed}'
        report = json.loads((directory / f'mixed_{seed}_summary.json').read_text())
        block_reports.append(checker.audit_block(directory, report, frozen, 'mixed', seed,
            1000, 'test', old_teams, old_seeds, protocol['policy_sha256'], checker.sha(exclusion_path)))

    directory = run / 'final_standard_39091'
    config = json.loads((directory / 'config.json').read_text())
    assert config == dict(model_sha256=protocol['policy_sha256'], plan_sha256=checker.PLAN_SHA,
        exclusion_sha256=checker.sha(exclusion_path), field='standard', seed=39091,
        pairs=1000, split='test', samples=32)
    assert not (directory / 'standard_39091_summary.json').exists()
    journal = directory / 'rows_standard_39091.jsonl'
    data = journal.read_bytes()
    rows, committed = [], 0
    lines = data.splitlines(keepends=True)
    for index, line in enumerate(lines):
        try:
            row = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            assert index == len(lines) - 1 and not line.endswith(b'\n')
            break
        rows.append(row)
        committed += len(line)
    assert 0 < len(rows) < 1000 and [r['pair'] for r in rows] == list(range(len(rows)))
    rng = random.Random(39091)
    first_expected = None
    for index, row in enumerate(rows):
        teams = []
        for _ in range(2):
            for attempt in range(100000):
                team = checker.draw_split(frozen.standard_draw, rng, 'test')
                names = [m.home or m.species_id for m in team]
                if checker.fingerprint(names) not in old_teams:
                    teams.append(names)
                    break
            else:
                raise ValueError('Unable to reproduce unused test draw')
        seeds = []
        for _ in range(6):
            while True:
                value = rng.getrandbits(32)
                if value not in old_seeds:
                    seeds.append(value)
                    break
        assert all(checker.bucket(t) == 'test' for t in teams)
        validate_partial_row(row, index, teams, seeds)
        if first_expected is None:
            first_expected = (teams, seeds)
    rejected = []
    for kind in ('team', 'seed', 'side', 'outcome'):
        altered = copy.deepcopy(rows[0])
        if kind == 'team': altered['teams'][0][0] += '-corrupt'
        elif kind == 'seed': altered['game_seeds'][0] ^= 1
        elif kind == 'side': altered['player_sides'][0] ^= 1
        else: altered['scores'][0] = 2.
        try:
            validate_partial_row(altered, 0, *first_expected)
        except ValueError:
            rejected.append(kind)
        else:
            raise ValueError('Partial audit accepted corruption: ' + kind)

    retained.update({name: checker.sha(run / name) for name in (
        'first_final_block_artifacts.json', 'second_final_block_artifacts.json',
        'plan.json', 'choice.json', 'test_lock.json', 'selection_lock.json', 'canary.json',
        'final/policy.npz', 'final/protocol.json', 'initialization.json', 'resume.json',
        'stage_1.npz', 'stage_2.npz', 'stage_3.npz', 'stage_4.npz')})
    slot = json.loads((run / 'resume.json').read_text())['slot']
    assert checker.sha(run / f'latest_{slot}.npz') == state['stages'][-1]['model_sha256']
    for name in (f'latest_{slot}.npz', f'replay_{slot}.npz', 'demonstrations.npz', 'initial.npz'):
        retained[name] = checker.sha(run / name)
    checks = {'tests': 323, 'optional_skips': 7, 'pvpoke_exact': 108,
        'unittest_log_sha256': checker.sha(ROOT / 'runs/continue-v1-final-tests.out'),
        'pvpoke_log_sha256': checker.sha(ROOT / 'runs/continue-v1-final-pvpoke.out')}
    test_log = (ROOT / 'runs/continue-v1-final-tests.out').read_text(encoding='utf-8-sig')
    assert 'Ran 323 tests' in test_log and 'OK (skipped=7)' in test_log
    assert '108 of 108 PvPoke battles reproduced exactly' in (ROOT / 'runs/continue-v1-final-pvpoke.out').read_text(encoding='utf-8-sig')
    result = dict(audited_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        scope='Deadline-stopped partial benchmark; not a complete three-block verdict audit',
        saved_evidence_verified=True, complete_benchmark=False, strength_target_met=False,
        required_total_pairings=3000, required_total_games=6000,
        saved_complete_pairings=2000 + len(rows), saved_complete_games=4000 + 2 * len(rows),
        complete_blocks=block_reports,
        partial_standard=dict(field='standard', seed=39091, required_pairings=1000,
            saved_complete_pairings=len(rows), saved_complete_games=2 * len(rows),
            raw_sha256=checker.sha(journal), raw_bytes=len(data),
            trailing_uncommitted_fragment_bytes=len(data) - committed,
            draws_seeds_folds_sides_legal_outcomes_verified=True,
            score_and_interval=None, interpretation='Incomplete fixed sample; no registered standard-field strength estimate'),
        corruption_checks_rejected=rejected, runtime_source_files_verified=len(manifest),
        baseline_files_verified=len(frozen.manifest['files']), excluded_compositions_verified=len(old_teams),
        excluded_game_seeds_verified=len(old_seeds), original_inputs_verified=True,
        copied_teacher_and_initial_state_verified=True, selected_compact_parameters_verified=True,
        deadline_unix=1793912387, controller_stopped_utc=terminal['updated_utc'],
        deadline_polling_latency_seconds=stopped.timestamp() - plan['absolute_deadline_unix'],
        deadline_extended=False, new_numerical_worker_started=False,
        further_training_or_selection=False, full_final_auditor_run=False, final_verdict_present=False,
        terminal_checks=checks, artifact_hashes=retained,
        terminal_artifact_hashes={p.name: checker.sha(p) for p in closure.iterdir() if p.is_file() and p.name != 'audit.json'},
        auditor_sha256=checker.sha(Path(__file__)))
    checker.write_json(closure / 'audit.json', result)
    print(json.dumps({k: result[k] for k in ('saved_evidence_verified', 'complete_benchmark',
        'strength_target_met', 'saved_complete_pairings', 'saved_complete_games', 'partial_standard',
        'corruption_checks_rejected', 'terminal_checks')}, indent=2))


if __name__ == '__main__':
    main()
