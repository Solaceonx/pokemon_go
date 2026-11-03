"""Locked final evaluation of the exact selected direct, invariant or planning policy.

Production always uses three predeclared 1,000-pairing blocks against frozen engine32. A canary uses
only validation compositions and separate seeds; it never writes the production lock or claims strength.
Run from an immutable source snapshot, with no other numerical worker for this experiment.
"""
import argparse
import json
import math
import os
from pathlib import Path
import random
import statistics
import sys
import time

for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS'):
    os.environ[name] = '1'
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pogo.arena import low_priority
from pogo.dqn import Agent, Network
from pogo.dqn_relational import ARCHITECTURE, Network as RelationalNetwork
from pogo.dqn_symmetry import SymmetricPolicy
from pogo.rl_search import RolloutAgent
from scripts.double_dqn import BASE, ci, frozen, draw_split, sha, write_json, append, read_rows

DEADLINE = 1793745649.6650429
BLOCKS = (('mixed', 38091), ('mixed', 38092), ('standard', 38091))


def lock(path, value):
    if path.exists():
        if json.loads(path.read_text()) != value:
            raise ValueError('Final selection is locked; changed policy, recipe, source or sample count rejected')
    else:
        write_json(path, value)


def validate_measurement(report, digest, seed, pairs, baseline=BASE):
    """Verify identity and paired outcomes independently of the promotion decision."""
    values = report.get('pair_scores', [])
    if (report.get('split') != 'validation' or report.get('field', 'mixed') != 'mixed'
            or report.get('seed') != seed or len(values) != pairs or report.get('clusters') != pairs
            or report.get('pairs', pairs) != pairs or report.get('battles', 2 * pairs) != 2 * pairs
            or any(value not in (0., .25, .5, .75, 1.) for value in values)
            or report.get('opponent_samples', report.get('samples')) != 32
            or report.get('actor_sha256', report.get('model_sha256')) != digest or baseline != BASE
            or report.get('baseline_commit', BASE) != BASE):
        raise ValueError('Missing matching fresh full-engine validation evidence')
    computed = ci(values)
    for key in ('score', 'margin95', 'lower95', 'upper95'):
        if not math.isclose(computed[key], report[key], rel_tol=0, abs_tol=1e-12):
            raise ValueError('Validation confidence interval does not match its paired outcomes')
    return computed


def validate_confirmation(report, digest, seed, baseline=BASE, *, require_competitive=True):
    """Require fresh full-engine validation and recompute its interval before spending final evidence."""
    computed = validate_measurement(report, digest, seed, 128, baseline)
    if require_competitive and computed['lower95'] <= .5:
        raise ValueError('Validation target not met; preserve final teams and continue research')


def selection(source_name, canary, *, require_competitive=True):
    source = ROOT / 'runs/double-dqn' / source_name
    result = json.loads((source / 'result.json').read_text())
    plan_path = source / ('trial_plan.json' if source_name == 'relational-v1' else 'plan.json')
    plan = json.loads(plan_path.read_text())
    if source_name == 'search-v3':
        samples = result['selected_samples']
        winner = max(plan['sample_grid'], key=lambda n: result['screens'][str(n)]['score'])
        if samples != winner or result['confirmation']['samples'] != samples:
            raise ValueError('Planning selection or confirmation recipe changed')
        model, mode, seed = source / 'actor.npz', 'planning' if samples else 'direct', 38312
        opponents = [source / f'opponent_{i}.npz' for i in range(2)] if samples else []
        if samples and [sha(p) for p in opponents] != result['confirmation']['predictors']:
            raise ValueError('Planning opponent ensemble changed after validation')
        if plan['edge'] != .03 or plan['stride'] != 8:
            raise ValueError('Planning compute recipe differs from validated settings')
    elif source_name == 'symmetry-v5':
        chosen = result['selected']
        if chosen not in ('prior_direct', 'prior_average', 'augmented_direct', 'augmented_average'):
            raise ValueError('Unknown selected symmetry recipe')
        if chosen != max(plan['variants'], key=lambda name: result['screens'][name]['score']):
            raise ValueError('Symmetry selection changed after screening')
        model = source / ('prior.npz' if chosen.startswith('prior_') else 'augmented.npz')
        mode, seed, samples, opponents = ('average' if chosen.endswith('_average') else 'direct'), 38412, 0, []
    elif source_name == 'counterfactual-v4':
        chosen = result['best_checkpoint']
        if Path(chosen).name != chosen:
            raise ValueError('Checkpoint must be inside its run')
        model, mode, seed, samples, opponents = source / chosen, 'direct', 38212, 0, []
    elif source_name in ('relational-v1', 'teacher32-v1'):
        candidates = ({'bootstrap': 'bootstrap.npz', 'endpoint': 'endpoint.npz'}
            if source_name == 'relational-v1' else {'reference': 'reference.npz',
            'teacher32_fit': 'teacher32_fit.npz', 'last_complete_rl_endpoint': 'endpoint.npz'})
        screen_seed, seed = (38511, 38512) if source_name == 'relational-v1' else (38811, 38812)
        if (set(result['screens']) != set(candidates) or plan['selection']['pairs'] != 64
                or plan['selection']['seed'] != screen_seed or plan['confirmation']['pairs'] != 128
                or plan['confirmation']['seed'] != seed or plan.get('baseline_commit', BASE) != BASE
                or plan['selection'].get('opponent_samples') != 32
                or plan['confirmation'].get('opponent_samples') != 32
                or plan['selection'].get('split') != 'validation'
                or plan['confirmation'].get('split') != 'validation'):
            raise ValueError('Shared-network selection protocol changed')
        for name, filename in candidates.items():
            validate_measurement(result['screens'][name], sha(source / filename), screen_seed, 64)
        chosen = max(candidates, key=lambda name: result['screens'][name]['score'])
        model = source / candidates[chosen]
        if (result['selected'] != chosen or result['selected_sha256'] != sha(model)
                or result['policy_sha256'] != sha(source / 'policy.npz')):
            raise ValueError('Shared-network selected checkpoint or compact policy changed')
        selected_net, _, _ = load_network(model)
        published_net, _, _ = load_network(source / 'policy.npz')
        if not isinstance(selected_net, RelationalNetwork) or not same_parameters(selected_net, published_net):
            raise ValueError('Shared-network compact policy changed predictions or architecture')
        mode, samples, opponents = 'direct', 0, []
    elif canary and source_name == 'refine-v3':
        model, mode, seed, samples, opponents = source / 'policy.npz', 'average', 38112, 0, []
    else:
        raise ValueError('Unsupported selected experiment')
    if not canary or not require_competitive:
        for relative, digest in plan['source_sha256'].items():
            if sha(ROOT / relative) != digest:
                raise ValueError('Validated runtime source changed: ' + relative)
        validate_confirmation(result['confirmation'], sha(model), seed, plan.get('baseline_commit', BASE),
                              require_competitive=require_competitive)
    recipe = {'mode': mode, 'samples': samples, 'edge': .03, 'stride': 8}
    if source_name in ('relational-v1', 'teacher32-v1'):
        # Bind the whole selection record, not only the winning checkpoint's bytes.
        recipe.update(network=ARCHITECTURE, selection_plan_sha256=sha(plan_path),
                      selection_result_sha256=sha(source / 'result.json'))
        validate_measurement(result['confirmation'], sha(model), seed, 128)
    return model, opponents, recipe, result['confirmation']


def load_network(path):
    """Dispatch only declared checkpoint formats, without process-global backend mutation."""
    with np.load(path, allow_pickle=False) as data:
        architecture = str(data['architecture']) if 'architecture' in data else None
    if architecture not in (None, ARCHITECTURE):
        raise ValueError('Unsupported standalone policy architecture')
    return (RelationalNetwork if architecture == ARCHITECTURE else Network).load(path)


def same_parameters(before, after):
    return (type(before) is type(after) and len(before.p) == len(after.p)
            and all(np.array_equal(a, b) for a, b in zip(before.p, after.p)))


def compact(source, target):
    net, _, _ = load_network(source)
    for moment in (*net.m, *net.v):
        moment.fill(0)
    net.steps = 0
    metadata = {'source_sha256': sha(source), 'weights_only': True}
    if not target.exists():
        net.save(target, metadata)
    restored, receipt, _ = load_network(target)
    if receipt != metadata or not same_parameters(net, restored):
        raise ValueError('Exported policy differs from selected source')
    return restored


def validate_canary(directory, protocol):
    receipt_path, verdict_path = directory / 'protocol.json', directory / 'verdict.json'
    if not receipt_path.exists() or not verdict_path.exists():
        raise ValueError('Run the matching validation-only frozen-engine canary before final tests')
    receipt, verdict = json.loads(receipt_path.read_text()), json.loads(verdict_path.read_text())
    keys = ('source_run', 'source_model_sha256', 'recipe', 'artifacts', 'source_sha256', 'baseline',
            'confirmation', 'budget_finalization')
    blocks = [('mixed', 38995), ('mixed', 38996), ('standard', 38995)]
    if (any(receipt.get(key) != protocol.get(key) for key in keys) or not receipt.get('canary')
            or receipt.get('split') != 'validation' or receipt.get('pairs_per_block') != 2
            or receipt.get('blocks') != [list(b) for b in blocks]
            or not verdict.get('canary') or verdict.get('strength_target_met') is not None
            or verdict.get('protocol_sha256') != sha(receipt_path) or len(verdict.get('final_tests', [])) != 3):
        raise ValueError('Canary does not match the selected policy, method, sources and artifacts')
    for report, (field, seed) in zip(verdict['final_tests'], blocks):
        if (report['field'] != field or report['seed'] != seed or report['split'] != 'validation'
                or report['pairs'] != 2 or report['opponent_samples'] != 32
                or len(report['pair_scores']) != 2
                or report['raw_sha256'] != sha(directory / f'rows_{field}_{seed}.jsonl')):
            raise ValueError('Incomplete or changed frozen-engine canary evidence')


def player(net, opponents, recipe, pool, seed):
    if recipe['mode'] == 'planning':
        return RolloutAgent(net, pool, opponents, samples=recipe['samples'], edge=recipe['edge'],
                            stride=recipe['stride'], seed=seed)
    return Agent(SymmetricPolicy(net) if recipe['mode'] == 'average' else net, seed=seed)


def validate_pairing(row, index, teams, seeds):
    scores = row.get('scores', [])
    if (row.get('pair') != index or row.get('teams') != teams or row.get('game_seeds') != seeds
            or row.get('player_sides') != [(index + o) % 2 for o in range(2)]
            or len(scores) != 2 or any(score not in (0., .5, 1.) for score in scores)
            or not math.isclose(row.get('mean', -1), statistics.mean(scores), abs_tol=1e-12)):
        raise ValueError('Pairing journal differs from its locked teams, seeds, sides or complete outcomes')


def measure(run, f, net, opponents, recipe, field, seed, pairs, split, stop):
    tag = f'{field}_{seed}'
    path = run / f'rows_{tag}.jsonl'
    rows = read_rows(path)
    done = {row['pair']: row for row in rows}
    if len(rows) != len(done) or any(i not in range(pairs) for i in done):
        raise ValueError('Duplicate or out-of-range final pairing')
    rng = random.Random(seed)
    for i in range(pairs):
        draw = f.mixed_draw if field == 'mixed' else f.standard_draw
        a, b = draw_split(draw, rng, split), draw_split(draw, rng, split)
        seeds = [rng.getrandbits(32) for _ in range(6)]
        teams = [[m.home or m.species_id for m in team] for team in (a, b)]
        if i in done:
            validate_pairing(done[i], i, teams, seeds)
            continue
        points, times = [], []
        for orientation, (mine, theirs) in enumerate(((a, b), (b, a))):
            if stop():
                raise TimeoutError('Stopped at original deadline; complete pairing rows and checkpoints retained')
            pilot = player(net, opponents, recipe, f.pool, seeds[3 * orientation])
            enemy = f.engine(seeds[3 * orientation + 1], 32)
            started = time.monotonic()
            score, _ = f.game(mine, theirs, pilot, enemy, seeds[3 * orientation + 2], side=(i + orientation) % 2)
            points.append((score + 1) / 2)
            times.append(time.monotonic() - started)
        row = {'pair': i, 'scores': points, 'mean': statistics.mean(points), 'seconds': times,
               'teams': teams, 'game_seeds': seeds, 'player_sides': [(i + o) % 2 for o in range(2)]}
        validate_pairing(row, i, teams, seeds)
        append(path, row)
        done[i] = row
        if (i + 1) % 10 == 0 or i + 1 == pairs:
            print(json.dumps({'event': 'locked_evaluation', 'block': tag, 'pairs': len(done)}), flush=True)
    summary = dict(ci([done[i]['mean'] for i in range(pairs)]), field=field, seed=seed, split=split,
        pairs=pairs, battles=2 * pairs, opponent_samples=32, recipe=recipe, raw_sha256=sha(path),
        pair_scores=[done[i]['mean'] for i in range(pairs)])
    write_json(run / (tag + '_summary.json'), summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-run', required=True,
        choices=['search-v3', 'symmetry-v5', 'counterfactual-v4', 'refine-v3',
                 'relational-v1', 'teacher32-v1'])
    parser.add_argument('--canary', action='store_true')
    args = parser.parse_args()
    execute(args.source_run, args.canary)


def execute(source_name, canary, budget_receipt=None):
    """The budget driver supplies a separately registered, verified allocation receipt."""
    low_priority()
    model, predictors, recipe, confirmation = selection(source_name, canary,
        require_competitive=budget_receipt is None)
    f = frozen()
    if sha(ROOT / 'pogo/battle.py') != f.manifest['files']['pogo/battle.py']:
        raise ValueError('Planning simulator mechanics differ from the frozen engine simulator')
    if sha(ROOT / 'data/matchups_wide.json') != f.manifest['files']['data/matchups_wide.json']:
        raise ValueError('Inference feature data differs from frozen baseline data')
    run = ROOT / 'runs/double-dqn' / (('canary-final-' if canary else 'final-') + source_name)
    run.mkdir(parents=True, exist_ok=True)
    net = compact(model, run / 'policy.npz')
    opponents = [compact(path, run / f'opponent_{i}.npz') for i, path in enumerate(predictors)]
    artifacts = {path.name: sha(path) for path in [run / 'policy.npz',
        *(run / f'opponent_{i}.npz' for i in range(len(opponents)))]}
    sources = [*(ROOT / 'pogo').glob('*.py'), Path(__file__), ROOT / 'scripts/double_dqn.py']
    if budget_receipt is not None:
        sources.append(ROOT / 'scripts/dqn_budget_final.py')
    blocks = (('mixed', 38995), ('mixed', 38996), ('standard', 38995)) if canary else BLOCKS
    pairs, split = (2, 'validation') if canary else (1000, 'test')
    protocol = {'source_run': source_name, 'source_model_sha256': sha(model), 'recipe': recipe,
        'artifacts': artifacts, 'source_sha256': {str(p.relative_to(ROOT)): sha(p) for p in sources},
        'baseline': f.manifest, 'pairs_per_block': pairs, 'blocks': [list(b) for b in blocks], 'split': split,
        'confirmation': confirmation, 'canary': canary, 'deadline_unix': DEADLINE}
    if budget_receipt is not None:
        protocol['budget_finalization'] = budget_receipt
    if not canary:
        validate_canary(ROOT / 'runs/double-dqn' / ('canary-final-' + source_name), protocol)
    # A single production lock across this chat's candidate runs prevents a second choice after final outcomes.
    lock(run / 'protocol.json' if canary else ROOT / 'runs/double-dqn/final_test_lock.json', protocol)
    lock(run / 'protocol.json', protocol)
    state = {'pid': os.getpid(), 'status': 'evaluating', 'canary': canary}
    write_json(run / 'state.json', state)
    try:
        reports = []
        for field, seed in blocks:
            reports.append(measure(run, f, net, opponents, recipe, field, seed, pairs, split,
                lambda: time.time() >= DEADLINE or (run / 'STOP').exists()))
        passed = (all(r['lower95'] > .5 for r in reports if r['field'] == 'mixed')
                  and all(r['upper95'] >= .5 for r in reports if r['field'] == 'standard'))
        write_json(run / 'verdict.json', {'strength_target_met': None if canary else passed,
            'canary': canary, 'protocol_sha256': sha(run / 'protocol.json'), 'final_tests': reports,
            'artifacts': artifacts, 'completed_unix': time.time()})
        state['status'] = 'complete'
    except BaseException as error:
        state.update(status='stopped_with_artifacts', error=str(error))
        raise
    finally:
        write_json(run / 'state.json', state)


if __name__ == '__main__':
    main()
