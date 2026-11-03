"""Audit a completed standalone DQN benchmark from saved evidence, without rerunning battles.

python scripts/check_dqn_verdict.py --run final-teacher32-v1

Requires the saved local raw journals, immutable runtime and selected checkpoints. A completed verdict
is required; partial evaluations cannot produce a successful audit. Writes only the small audit.json.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.double_dqn import BASE, bucket, draw_split, frozen
from scripts.dqn_final import BLOCKS, load_network, same_parameters

ALLOCATION_SHA256 = '3ae02e8740f2b9e4d2ec111655b37d3ca8ea3877e10060738a4256b831571f74'


def sha(path):
    with Path(path).open('rb') as file:
        return hashlib.file_digest(file, 'sha256').hexdigest()


def paired_interval(values):
    if len(values) < 2 or any(v not in (0., .25, .5, .75, 1.) for v in values):
        raise ValueError('Missing complete legal paired outcomes')
    score = statistics.mean(values)
    margin = 1.96 * statistics.stdev(values) / math.sqrt(len(values))
    if margin == 0:
        margin = math.sqrt(math.log(40) / (2 * len(values)))
    return dict(score=score, margin95=margin, lower95=max(0., score - margin),
                upper95=min(1., score + margin), clusters=len(values))


def audit_block(directory, report, f, field, seed, pairs, split):
    raw = directory / f'rows_{field}_{seed}.jsonl'
    if (report['field'] != field or report['seed'] != seed or report['split'] != split
            or report['pairs'] != pairs or report['battles'] != 2 * pairs
            or report['opponent_samples'] != 32 or report['raw_sha256'] != sha(raw)):
        raise ValueError('Block identity, count, full-engine setting or raw hash changed')
    if json.loads((directory / f'{field}_{seed}_summary.json').read_text()) != report:
        raise ValueError('Saved block summary differs from its verdict report')
    rows = [json.loads(line) for line in raw.read_text().splitlines()]
    indexed = {row['pair']: row for row in rows}
    if len(rows) != pairs or set(indexed) != set(range(pairs)):
        raise ValueError('Missing, duplicate or out-of-range complete pairings')
    rng = random.Random(seed)
    values = []
    for i in range(pairs):
        draw = f.mixed_draw if field == 'mixed' else f.standard_draw
        teams = [draw_split(draw, rng, split), draw_split(draw, rng, split)]
        expected = [[m.home or m.species_id for m in team] for team in teams]
        seeds = [rng.getrandbits(32) for _ in range(6)]
        row = indexed[i]
        scores = row.get('scores', [])
        if (any(bucket(team) != split for team in teams) or row['teams'] != expected
                or row['game_seeds'] != seeds or row['player_sides'] != [(i + o) % 2 for o in range(2)]
                or len(scores) != 2 or any(score not in (0., .5, 1.) for score in scores)
                or row['mean'] != statistics.mean(scores)
                or len(row.get('seconds', [])) != 2
                or any(not math.isfinite(s) or s < 0 for s in row['seconds'])):
            raise ValueError('Pairing differs from locked draw, seeds, sides or legal complete outcomes')
        values.append(row['mean'])
    if values != report['pair_scores']:
        raise ValueError('Summary outcomes differ from the complete raw journal')
    interval = paired_interval(values)
    for key, value in interval.items():
        if not math.isclose(report[key], value, rel_tol=0, abs_tol=1e-12):
            raise ValueError('Reported confidence interval differs from independent paired calculation')
    return dict(interval, field=field, seed=seed, pairs=pairs, raw_sha256=sha(raw))


def audit(run_name):
    if Path(run_name).name != run_name or not run_name.startswith('final-'):
        raise ValueError('Use one completed final-<source> run name')
    directory = ROOT / 'runs/double-dqn' / run_name
    protocol_path = directory / 'protocol.json'
    protocol = json.loads(protocol_path.read_text())
    verdict = json.loads((directory / 'verdict.json').read_text())
    global_lock = ROOT / 'runs/double-dqn/final_test_lock.json'
    if (json.loads(global_lock.read_text()) != protocol or protocol['canary'] or verdict['canary']
            or protocol['split'] != 'test' or protocol['pairs_per_block'] != 1000
            or protocol['blocks'] != [list(b) for b in BLOCKS]
            or verdict['protocol_sha256'] != sha(protocol_path)
            or verdict['artifacts'] != protocol['artifacts'] or len(verdict['final_tests']) != 3):
        raise ValueError('Missing matching complete production verdict and global policy lock')
    budget = ROOT / 'runs/double-dqn/budget-finalization-v1'
    queue = json.loads((budget / 'queue.json').read_text())
    runtime = ROOT / queue['runtime']
    for relative, digest in json.loads((runtime / 'source_manifest.json').read_text()).items():
        if sha(runtime / relative) != digest:
            raise ValueError('Immutable numerical runtime changed: ' + relative)
    if sha(runtime / 'source_manifest.json') != queue['source_manifest_sha256']:
        raise ValueError('Numerical manifest differs from the saved queue')
    for relative, digest in protocol['source_sha256'].items():
        if sha(runtime / relative) != digest:
            raise ValueError('Locked inference source differs from its numerical runtime')
    f = frozen()
    if f.manifest != protocol['baseline'] or f.manifest['commit'] != BASE:
        raise ValueError('Frozen baseline evidence changed')
    allocation = protocol['budget_finalization']
    decision = json.loads((budget / 'selection.json').read_text())
    plan = json.loads((budget / 'plan.json').read_text())
    if (sha(budget / 'plan.json') != ALLOCATION_SHA256 or allocation['plan_sha256'] != ALLOCATION_SHA256
            or decision['plan_sha256'] != ALLOCATION_SHA256
            or allocation['selection_sha256'] != sha(budget / 'selection.json')
            or decision['selected_source'] != protocol['source_run']
            or decision['selected_model_sha256'] != protocol['source_model_sha256']
            or decision['selected_recipe'] != protocol['recipe']):
        raise ValueError('Budget selection differs from the locked policy/method')
    if protocol['deadline_unix'] != plan['absolute_deadline_unix']:
        raise ValueError('Original benchmark deadline changed')
    candidates = decision['candidates']
    if [c['source_run'] for c in candidates] != plan['candidate_order']:
        raise ValueError('Candidate order changed from the registered selection rule')
    if not plan['registered_unix'] <= decision['decided_unix'] < plan['absolute_deadline_unix']:
        raise ValueError('Selection was not within the registered original allocation')
    for candidate in candidates:
        if candidate['status'] != 'complete':
            if (candidate['source_run'] != 'teacher32-v1'
                    or decision['decided_unix'] < plan['research_cutoff_unix']):
                raise ValueError('A required completed candidate was omitted before the research cutoff')
            continue
        candidate_source = ROOT / 'runs/double-dqn' / candidate['source_run']
        result = json.loads((candidate_source / 'result.json').read_text())
        plan_name = 'trial_plan.json' if candidate['source_run'] == 'relational-v1' else 'plan.json'
        if (sha(candidate_source / 'result.json') != candidate['result_sha256']
                or sha(candidate_source / plan_name) != candidate['plan_sha256']
                or result['confirmation']['score'] != candidate['score']):
            raise ValueError('Candidate evidence changed after budget selection')
        confirmation = result['confirmation']
        seeds = {'teacher32-v1': 38812, 'relational-v1': 38512, 'search-v3': 38312, 'symmetry-v5': 38412}
        if (confirmation['split'] != 'validation' or confirmation['seed'] != seeds[candidate['source_run']]
                or len(confirmation['pair_scores']) != 128 or confirmation['clusters'] != 128
                or confirmation.get('opponent_samples', confirmation.get('samples')) != 32
                or confirmation.get('actor_sha256', confirmation.get('model_sha256')) != candidate['model_sha256']):
            raise ValueError('Budget candidate lacks matching selected-only fresh full-engine validation')
        independent = paired_interval(confirmation['pair_scores'])
        for key in ('score', 'margin95', 'lower95', 'upper95'):
            if not math.isclose(candidate[key], independent[key], rel_tol=0, abs_tol=1e-12):
                raise ValueError('Candidate validation interval changed after selection')
        mode = candidate['recipe']['mode']
        if mode not in ('planning', 'direct', 'average'):
            raise ValueError('Unsupported selected inference method')
        forecast = plan['runtime_forecast']
        seconds = forecast['planning_seconds_per_battle'] if mode == 'planning' else forecast['direct_or_average_seconds_per_battle']
        predicted = ((forecast['final_battles'] + forecast['canary_battles']) * seconds
                     * forecast['safety_multiplier'] + forecast['closing_reserve_seconds'])
        if not math.isclose(candidate['forecast_seconds'], predicted, rel_tol=0, abs_tol=1e-9):
            raise ValueError('Recorded runtime forecast differs from the registered budget rule')
    eligible = [c for c in candidates if c['status'] == 'complete'
                and c['forecast_seconds'] <= plan['absolute_deadline_unix'] - decision['decided_unix']]
    if not eligible or max(eligible, key=lambda c: c['score'])['source_run'] != protocol['source_run']:
        raise ValueError('Locked choice violates the registered budget-constrained selection rule')
    source = ROOT / 'runs/double-dqn' / protocol['source_run']
    selected = next(c for c in decision['candidates'] if c['source_run'] == protocol['source_run'])
    if Path(selected['model']).name != selected['model']:
        raise ValueError('Selected checkpoint must be inside its source run')
    model = source / selected['model']
    if sha(model) != protocol['source_model_sha256']:
        raise ValueError('Selected full checkpoint changed')
    expected_artifacts = {'policy.npz', 'opponent_0.npz', 'opponent_1.npz'} if protocol['recipe']['mode'] == 'planning' else {'policy.npz'}
    if set(protocol['artifacts']) != expected_artifacts:
        raise ValueError('Inference package omitted or added a policy/ensemble artifact')
    for name, digest in protocol['artifacts'].items():
        if Path(name).name != name or sha(directory / name) != digest:
            raise ValueError('Compact policy/ensemble artifact changed')
        full = model if name == 'policy.npz' else source / name
        original, _, _ = load_network(full)
        compact, meta, _ = load_network(directory / name)
        if (not same_parameters(original, compact) or meta.get('source_sha256') != sha(full)
                or compact.steps != 0 or any(moment.any() for moment in compact.m + compact.v)):
            raise ValueError('Exported artifact differs from its selected inference parameters')
    canary_directory = ROOT / 'runs/double-dqn' / ('canary-final-' + protocol['source_run'])
    canary_protocol = json.loads((canary_directory / 'protocol.json').read_text())
    canary_verdict = json.loads((canary_directory / 'verdict.json').read_text())
    for key in ('source_run', 'source_model_sha256', 'recipe', 'artifacts', 'source_sha256',
                'baseline', 'confirmation', 'budget_finalization', 'deadline_unix'):
        if canary_protocol[key] != protocol[key]:
            raise ValueError('Canary policy, recipe, sources or allocation changed')
    canary_blocks = [('mixed', 38995), ('mixed', 38996), ('standard', 38995)]
    if (not canary_protocol['canary'] or not canary_verdict['canary']
            or canary_protocol['split'] != 'validation' or canary_protocol['pairs_per_block'] != 2
            or canary_protocol['blocks'] != [list(b) for b in canary_blocks]
            or canary_verdict['strength_target_met'] is not None
            or canary_verdict['artifacts'] != protocol['artifacts']
            or canary_verdict['protocol_sha256'] != sha(canary_directory / 'protocol.json')
            or len(canary_verdict['final_tests']) != 3):
        raise ValueError('Missing complete validation-only game canary')
    for name, digest in protocol['artifacts'].items():
        if sha(canary_directory / name) != digest:
            raise ValueError('Canary inference artifact differs from its locked package')
    for report, (field, seed) in zip(canary_verdict['final_tests'], canary_blocks):
        audit_block(canary_directory, report, f, field, seed, 2, 'validation')
    reports = [audit_block(directory, report, f, field, seed, 1000, 'test')
               for report, (field, seed) in zip(verdict['final_tests'], BLOCKS)]
    passed = all(r['lower95'] > .5 for r in reports[:2]) and reports[2]['upper95'] >= .5
    if verdict['strength_target_met'] is not passed:
        raise ValueError('Reported reliable-win verdict differs from the fixed criterion')
    return {'evidence_verified': True, 'strength_target_met': passed, 'pairings': 3000,
            'battles': 6000, 'protocol_sha256': sha(protocol_path),
            'verdict_sha256': sha(directory / 'verdict.json'),
            'auditor_sha256': sha(Path(__file__)), 'blocks': reports}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True)
    args = parser.parse_args()
    result = audit(args.run)
    target = ROOT / 'runs/double-dqn' / args.run / 'audit.json'
    target.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
