"""Authorized continuation in a fresh run; never rewrite the completed experiment.

One immutable worker resumes full DDQN state, selects on validation, then locks a new
policy before testing unused compositions. The registered 48-hour deadline never resets.
"""
import argparse
import base64
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import struct
import subprocess
import sys
import time
from types import SimpleNamespace

for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS'):
    os.environ[name] = '1'
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pogo.dqn_relational import Network, ARCHITECTURE
from scripts import double_dqn as trainer, dqn_final as final
from scripts.double_dqn_relational import relational_backend

RUN = 'continue-v1'
PLAN_SHA = '157f94a88e075598524518a2f1a9bc3cb7f0c1e6e1f2c2f4d5b0a8bc49b5d1f3'
RECIPE = dict(mode='direct', samples=0, edge=.03, stride=8, network=ARCHITECTURE)


def team_key(team):
    names = [m if isinstance(m, str) else (m.home or m.species_id) for m in team]
    return hashlib.sha256(('dqn-final-exclusion-v1:' + '|'.join(sorted(names))).encode()).digest()


def exclusions(path):
    value = json.loads(path.read_text())
    teams = base64.b64decode(value['team_sha256_base64'], validate=True)
    seeds = base64.b64decode(value['game_seeds_u32be_base64'], validate=True)
    if len(teams) != 32 * value['team_count'] or len(seeds) != 4 * value['seed_count']:
        raise ValueError('Malformed exclusion set')
    team_set = {teams[i:i+32] for i in range(0, len(teams), 32)}
    seed_set = set(struct.unpack('>' + 'I' * value['seed_count'], seeds))
    if len(team_set) != value['team_count'] or len(seed_set) != value['seed_count']:
        raise ValueError('Duplicate exclusion identities')
    return team_set, seed_set


@contextmanager
def fresh_evaluation(excluded_teams, excluded_seeds):
    """Scope fresh draws to this evaluation; never alter the original global lock."""
    original_draw, original_random = final.draw_split, final.random

    class FreshRandom(random.Random):
        def getrandbits(self, k):
            value = super().getrandbits(k)
            while k == 32 and value in excluded_seeds:
                value = super().getrandbits(k)
            return value

    def draw(drawer, rng, split):
        for _ in range(100000):
            team = original_draw(drawer, rng, split)
            if split != 'test' or team_key(team) not in excluded_teams:
                return team
        raise RuntimeError('No unused test composition drawn')

    final.draw_split, final.random = draw, SimpleNamespace(Random=FreshRandom)
    try:
        yield
    finally:
        final.draw_split, final.random = original_draw, original_random


def remaining_stage(stage, plan, now):
    return max(0., min(stage['deadline_unix'], plan['research_cutoff_unix'] - 3600,
                       plan['absolute_deadline_unix']) - now)


@contextmanager
def worker_lease(path):
    file = path.open('a+b')
    try:
        file.seek(0)
        if os.name == 'nt':
            import msvcrt
            if path.stat().st_size == 0:
                file.write(b'0'); file.flush(); file.seek(0)
            msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        file.close()


def seed_run(run, plan):
    source = ROOT / 'runs/double-dqn' / plan['source_run']
    for name, digest in plan['source_sha256'].items():
        if trainer.sha(source / name) != digest:
            raise ValueError('Original continuation input changed: ' + name)
    identity = dict(plan_sha256=PLAN_SHA, source_sha256=plan['source_sha256'])
    if (run / 'initialization.json').exists():
        if json.loads((run / 'initialization.json').read_text()) != identity:
            raise ValueError('Continuation initialization changed')
        return
    copies = {'initial.npz': 'endpoint.npz', 'bootstrap.npz': 'endpoint.npz',
              'latest_0.npz': 'endpoint.npz', 'replay_0.npz': 'replay_0.npz',
              'resume.json': 'resume.json', 'demonstrations.npz': 'demonstrations.npz'}
    for target, original in copies.items():
        path = run / target
        if path.exists() and trainer.sha(path) != plan['source_sha256'][original]:
            raise ValueError('Partial initialization differs: ' + target)
        if not path.exists():
            temp = path.with_suffix(path.suffix + '.copying')
            shutil.copyfile(source / original, temp)
            if trainer.sha(temp) != plan['source_sha256'][original]:
                raise ValueError('Continuation copy mismatch')
            temp.replace(path)
    trainer.write_json(run / 'initialization.json', identity)


def repair_training_tail(run):
    slot = json.loads((run / 'resume.json').read_text())['slot']
    _, meta, _ = Network.load(run / f'latest_{slot}.npz')
    path = run / 'training_games.jsonl'
    rows = trainer.read_rows(path)
    committed = [r for r in rows if r['game'] <= meta['games']]
    abandoned = [r for r in rows if r['game'] > meta['games']]
    if abandoned:
        for row in abandoned:
            trainer.append(run / 'uncommitted_training_attempts.jsonl', row)
        temp = path.with_suffix('.recovering')
        temp.write_text(''.join(json.dumps(r) + '\n' for r in committed))
        temp.replace(path)
    return meta


def prepare(run, plan):
    bundle = ROOT / '.dqn-cache/harness/continue-v1'
    scripts = ['double_dqn.py', 'double_dqn_relational.py', 'dqn_final.py', 'dqn_continue.py']
    sources = [*(ROOT / 'pogo').glob('*.py'), *(ROOT / 'scripts' / s for s in scripts)]
    manifest = {}
    for source in sources:
        relative = source.relative_to(ROOT)
        target = bundle / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.read_bytes() != source.read_bytes():
            raise ValueError('Never overwrite an existing runtime: ' + str(target))
        if not target.exists():
            target.write_bytes(source.read_bytes())
        manifest[str(relative)] = trainer.sha(target)
    frozen_path, _ = trainer.freeze()
    for link, target in ((bundle/'runs', ROOT/'runs'), (bundle/'data', frozen_path/'data'),
                         (bundle/'.dqn-cache'/trainer.BASE, frozen_path)):
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.exists():
            if link.resolve() != target.resolve():
                raise ValueError('Runtime junction changed')
        elif os.name == 'nt':
            quote = lambda p: "'" + str(p).replace("'", "''") + "'"
            subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                'New-Item -ItemType Junction -Path ' + quote(link) + ' -Target ' + quote(target) + ' | Out-Null'], check=True)
        else:
            link.symlink_to(target, target_is_directory=True)
    final.lock(bundle/'source_manifest.json', manifest)
    final.lock(run/'source_manifest.json', manifest)
    guard = ROOT/'.dqn-cache/harness/launch-continue-v1/scripts/run_dqn_continue.ps1'
    guard.parent.mkdir(parents=True, exist_ok=True)
    source = ROOT/'scripts/run_dqn_continue.ps1'
    if guard.exists() and guard.read_bytes() != source.read_bytes():
        raise ValueError('Never overwrite existing guard runtime')
    if not guard.exists():
        guard.write_bytes(source.read_bytes())
    activation = dict(plan_sha256=PLAN_SHA, runtime=str(bundle.relative_to(ROOT)),
        source_manifest_sha256=trainer.sha(bundle/'source_manifest.json'),
        guard=str(guard.relative_to(ROOT)), guard_sha256=trainer.sha(guard),
        training_cutoff_unix=plan['research_cutoff_unix']-3600,
        note='Reserve the last research hour for fixed validation/confirmation; no additional allocation')
    final.lock(run/'activation.json', activation)
    return activation


def execute(run, plan):
    activation = json.loads((run/'activation.json').read_text())
    manifest = json.loads((run/'source_manifest.json').read_text())
    if trainer.sha(ROOT/'source_manifest.json') != activation['source_manifest_sha256']:
        raise ValueError('Immutable runtime manifest changed')
    for name, digest in manifest.items():
        if trainer.sha(ROOT/name) != digest:
            raise ValueError('Immutable runtime source changed: ' + name)
    old_lock = ROOT/'runs/double-dqn/final_test_lock.json'
    old_verdict = ROOT/'runs/double-dqn/final-teacher32-v1/verdict.json'
    if (trainer.sha(old_lock) != plan['previous_global_lock_sha256']
            or trainer.sha(old_verdict) != plan['previous_verdict_sha256']):
        raise ValueError('Prior completed benchmark changed')
    if trainer.sha(run/'holdout_exclusions.json') != plan['holdout_exclusions_sha256']:
        raise ValueError('Reserved holdout changed')
    excluded_teams, excluded_seeds = exclusions(run/'holdout_exclusions.json')
    f = trainer.frozen()
    if f.manifest['commit'] != plan['baseline_commit']:
        raise ValueError('Frozen baseline changed')
    seed_run(run, plan)
    state_path = run/'state.json'
    state = json.loads(state_path.read_text()) if state_path.exists() else {
        'deadline_unix': plan['absolute_deadline_unix'], 'stages': [], 'started_unix': time.time()}
    if state['deadline_unix'] != plan['absolute_deadline_unix']:
        raise ValueError('Continuation deadline changed')

    def save(phase):
        state.update(phase=phase, updated_unix=time.time(), pid=os.getpid())
        trainer.write_json(state_path, state)
        print(json.dumps({'event':'continuation_phase', 'phase':phase, 'pid':os.getpid()}), flush=True)

    def stopped(limit=None):
        return time.time() >= min(plan['absolute_deadline_unix'], limit or float('inf')) or (run/'STOP').exists()

    def evaluate(label, model, field, seed, pairs, split, limit=None):
        directory = run/label
        directory.mkdir(exist_ok=True)
        config = dict(model_sha256=trainer.sha(model), plan_sha256=PLAN_SHA,
            exclusion_sha256=plan['holdout_exclusions_sha256'], field=field, seed=seed,
            pairs=pairs, split=split, samples=32)
        final.lock(directory/'config.json', config)
        net, _, _ = final.load_network(model)
        with fresh_evaluation(excluded_teams, excluded_seeds):
            return final.measure(directory, f, net, [], RECIPE, field, seed, pairs, split,
                                 lambda: stopped(limit))

    choice_path = run/'choice.json'
    if not choice_path.exists():
        save('validating_initial')
        initial = evaluate('screen_initial', run/'initial.npz', 'mixed', 39011, 64, 'validation', plan['research_cutoff_unix'])
        if not (run/'selection.json').exists():
            trainer.write_json(run/'selection.json', dict(checkpoint='initial.npz', sha256=trainer.sha(run/'initial.npz'),
                criterion='External fixed validation only; trainer internal evaluation disabled', validation=initial))
        candidates = [dict(model='initial.npz', sha256=trainer.sha(run/'initial.npz'), report=initial)]
        for index in range(1, plan['training']['maximum_stages']+1):
            if stopped(plan['research_cutoff_unix']-3600) and len(state['stages']) < index:
                break
            if len(state['stages']) < index:
                state['stages'].append(dict(index=index, started_unix=time.time(),
                    deadline_unix=min(time.time()+plan['training']['stage_hours']*3600, plan['research_cutoff_unix']-3600),
                    starting_games=repair_training_tail(run)['games'], trained=False))
            stage = state['stages'][index-1]
            endpoint = run/f'stage_{index}.npz'
            if not stage['trained']:
                save(f'training_stage_{index}')
                repair_training_tail(run)
                seconds = remaining_stage(stage, plan, time.time())
                if seconds > 0 and not stopped():
                    cfg = plan['training']
                    arguments = {k:v for k,v in cfg.items() if k not in ('stage_hours','maximum_stages','clock')}
                    arguments.update(hours=seconds/3600, eval_every=10**9, validation_pairs=64, validation_samples=32)
                    with relational_backend():
                        trainer.train(SimpleNamespace(**arguments), run)
                slot = json.loads((run/'resume.json').read_text())['slot']
                shutil.copyfile(run/f'latest_{slot}.npz', endpoint)
                _, meta, _ = Network.load(endpoint)
                stage.update(trained=True, model_sha256=trainer.sha(endpoint), games=meta['games'], completed_unix=time.time())
                save(f'checkpoint_stage_{index}')
            elif trainer.sha(endpoint) != stage['model_sha256']:
                raise ValueError('Completed stage checkpoint changed')
            if stage['games'] <= stage['starting_games']:
                continue
            if stopped(plan['research_cutoff_unix']):
                break
            save(f'validating_stage_{index}')
            try:
                report = evaluate(f'screen_stage_{index}', endpoint, 'mixed', 39011, 64, 'validation', plan['research_cutoff_unix'])
            except TimeoutError:
                if (run/'STOP').exists():
                    raise
                break
            candidates.append(dict(model=endpoint.name, sha256=trainer.sha(endpoint), report=report))
        selected = max(candidates, key=lambda c:c['report']['score'])
        choice = dict(selected=selected, candidates=candidates, plan_sha256=PLAN_SHA,
                      rule=plan['selection']['candidates'])
        final.lock(choice_path, choice)
    choice = json.loads(choice_path.read_text())
    model = run/choice['selected']['model']
    if trainer.sha(model) != choice['selected']['sha256']:
        raise ValueError('Locked selected endpoint changed')
    save('confirming_selected')
    confirmation = evaluate('confirmation', model, 'mixed', 39012, 128, 'validation')
    package = run/'final'
    package.mkdir(exist_ok=True)
    final.compact(model, package/'policy.npz')
    base = dict(plan_sha256=PLAN_SHA, source_manifest_sha256=activation['source_manifest_sha256'],
        source_model_sha256=trainer.sha(model), policy_sha256=trainer.sha(package/'policy.npz'),
        choice_sha256=trainer.sha(choice_path), exclusion_sha256=plan['holdout_exclusions_sha256'],
        baseline=f.manifest, recipe=RECIPE, confirmation=confirmation,
        deadline_unix=plan['absolute_deadline_unix'])
    final.lock(run/'selection_lock.json', base)
    save('validation_canary')
    canary_reports=[]
    for field, seed in plan['canary']['blocks']:
        canary_reports.append(evaluate(f'canary_{field}_{seed}', package/'policy.npz', field, seed, 2, 'validation'))
    final.lock(run/'canary.json', dict(base, blocks=canary_reports, strength_target_met=None))
    protocol = dict(base, canary_sha256=trainer.sha(run/'canary.json'),
        blocks=plan['final_blocks'], pairs_per_block=1000, split='test')
    final.lock(run/'test_lock.json', protocol)
    final.lock(package/'protocol.json', protocol)
    reports=[]
    for field, seed in plan['final_blocks']:
        save(f'final_{field}_{seed}')
        reports.append(evaluate(f'final_{field}_{seed}', package/'policy.npz', field, seed, 1000, 'test'))
    verdict=dict(strength_target_met=all(r['lower95']>.5 for r in reports[:2]) and reports[2]['upper95']>=.5,
        final_tests=reports, protocol_sha256=trainer.sha(package/'protocol.json'),
        policy_sha256=trainer.sha(package/'policy.npz'), completed_unix=time.time())
    final.lock(run/'verdict.json', verdict)
    save('complete')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare-only', action='store_true')
    args=parser.parse_args()
    run=ROOT/'runs/double-dqn'/RUN
    if trainer.sha(run/'plan.json') != PLAN_SHA:
        raise ValueError('Registered continuation plan changed')
    plan=json.loads((run/'plan.json').read_text())
    if time.time() >= plan['absolute_deadline_unix']:
        raise TimeoutError('Authorized continuation deadline reached; no restart or extension')
    if args.prepare_only:
        print(json.dumps(prepare(run, plan)), flush=True)
        return
    with worker_lease(run/'worker.lock'):
        if (run/'verdict.json').exists():
            return
        execute(run, plan)


if __name__ == '__main__':
    main()
