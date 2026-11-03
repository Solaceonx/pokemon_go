"""Independent saved-evidence audit for the newly authorized continuation. No games run."""
import argparse
import base64
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
import struct
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.double_dqn import BASE, bucket, draw_split, frozen, sha, write_json
from scripts.dqn_final import load_network, same_parameters

PLAN_SHA = '157f94a88e075598524518a2f1a9bc3cb7f0c1e6e1f2c2f4d5b0a8bc49b5d1f3'


def fingerprint(names):
    return hashlib.sha256(('dqn-final-exclusion-v1:'+'|'.join(sorted(names))).encode()).digest()


def audit_block(directory, report, f, field, seed, pairs, split, old_teams, old_seeds,
                model_sha, exclusion_sha, plan_sha=PLAN_SHA):
    config = json.loads((directory/'config.json').read_text())
    expected = dict(model_sha256=model_sha, plan_sha256=plan_sha, exclusion_sha256=exclusion_sha,
                    field=field, seed=seed, pairs=pairs, split=split, samples=32)
    raw = directory/f'rows_{field}_{seed}.jsonl'
    if (config != expected or report['raw_sha256'] != sha(raw) or report['field'] != field
            or report['seed'] != seed or report['pairs'] != pairs or report['split'] != split
            or report['battles'] != 2*pairs or report['opponent_samples'] != 32
            or report['recipe'] != dict(mode='direct',samples=0,edge=.03,stride=8,network='shared-matchup-v1')):
        raise ValueError('Block identity/count/model/raw hash changed')
    if json.loads((directory/f'{field}_{seed}_summary.json').read_text()) != report:
        raise ValueError('Saved summary changed')
    rows = [json.loads(line) for line in raw.read_text().splitlines()]
    indexed = {row['pair']:row for row in rows}
    if len(rows) != pairs or set(indexed) != set(range(pairs)):
        raise ValueError('Missing/duplicate/incomplete pairings')
    rng, values = random.Random(seed), []
    for index in range(pairs):
        teams=[]
        for _ in range(2):
            for attempt in range(100000):
                draw = f.mixed_draw if field == 'mixed' else f.standard_draw
                team = draw_split(draw,rng,split)
                names=[m.home or m.species_id for m in team]
                if split != 'test' or fingerprint(names) not in old_teams:
                    teams.append(names); break
            else:
                raise ValueError('No unused team drawn')
        seeds=[]
        for _ in range(6):
            while True:
                value=rng.getrandbits(32)
                if value not in old_seeds:
                    seeds.append(value); break
        row=indexed[index]
        points=row.get('scores',[])
        if (row['teams'] != teams or any(bucket(t) != split for t in teams)
                or row['game_seeds'] != seeds or row['player_sides'] != [(index+o)%2 for o in range(2)]
                or len(points) != 2 or any(v not in (0.,.5,1.) for v in points)
                or row['mean'] != statistics.mean(points) or len(row.get('seconds',[])) != 2
                or any(not math.isfinite(t) or t<0 for t in row['seconds'])):
            raise ValueError('Raw pairing differs from fresh draw/seeds/sides/outcomes')
        values.append(row['mean'])
    score=statistics.mean(values)
    margin=1.96*statistics.stdev(values)/math.sqrt(pairs)
    if margin==0: margin=math.sqrt(math.log(40)/(2*pairs))
    interval=dict(score=score,margin95=margin,lower95=max(0.,score-margin),upper95=min(1.,score+margin),clusters=pairs)
    if report['pair_scores'] != values or any(not math.isclose(report[k],v,abs_tol=1e-12,rel_tol=0) for k,v in interval.items()):
        raise ValueError('Paired outcomes or independent confidence interval changed')
    return dict(interval,field=field,seed=seed,pairs=pairs,raw_sha256=sha(raw))


def audit(run_name):
    if run_name != 'continue-v1': raise ValueError('Use the registered continuation run')
    run=ROOT/'runs/double-dqn'/run_name
    if sha(run/'plan.json') != PLAN_SHA: raise ValueError('Registered plan changed')
    plan=json.loads((run/'plan.json').read_text())
    if (plan['baseline_commit'] != BASE or plan['absolute_deadline_utc'] != '2026-11-05T20:59:47Z'
            or plan['final_blocks'] != [['mixed',39091],['mixed',39092],['standard',39091]]
            or plan['final_pairings_per_block'] != 1000): raise ValueError('Fixed protocol changed')
    old=ROOT/'runs/double-dqn/final-teacher32-v1'
    if (sha(ROOT/'runs/double-dqn/final_test_lock.json') != plan['previous_global_lock_sha256']
            or sha(old/'verdict.json') != plan['previous_verdict_sha256']): raise ValueError('Prior benchmark changed')
    path=run/'holdout_exclusions.json'
    if sha(path) != plan['holdout_exclusions_sha256']: raise ValueError('Exclusions changed')
    exclusion=json.loads(path.read_text())
    packed=base64.b64decode(exclusion['team_sha256_base64'],validate=True)
    old_teams={packed[i:i+32] for i in range(0,len(packed),32)}
    old_seeds=set(struct.unpack('>'+'I'*exclusion['seed_count'],base64.b64decode(exclusion['game_seeds_u32be_base64'],validate=True)))
    reconstructed_teams,reconstructed_seeds=set(),set()
    for relative,digest in exclusion['source_journals_sha256'].items():
        journal=ROOT/relative
        if sha(journal) != digest: raise ValueError('Prior raw identity journal changed')
        for line in journal.read_text().splitlines():
            row=json.loads(line)
            reconstructed_teams.update(fingerprint(t) for t in row['teams'])
            reconstructed_seeds.update(row['game_seeds'])
    if (old_teams != reconstructed_teams or old_seeds != reconstructed_seeds
            or len(old_teams) != plan['excluded_compositions'] or len(old_seeds) != plan['excluded_game_seeds']):
        raise ValueError('Exclusion population differs from all prior final games')
    activation=json.loads((run/'activation.json').read_text())
    if activation['plan_sha256'] != PLAN_SHA or sha(ROOT/activation['guard']) != activation['guard_sha256']:
        raise ValueError('Guard or activation identity changed')
    runtime=ROOT/activation['runtime']
    if sha(runtime/'source_manifest.json') != activation['source_manifest_sha256']: raise ValueError('Runtime manifest changed')
    manifest=json.loads((runtime/'source_manifest.json').read_text())
    for name,digest in manifest.items():
        if sha(runtime/name) != digest: raise ValueError('Runtime changed: '+name)
    for name,digest in plan['source_sha256'].items():
        if sha(ROOT/'runs/double-dqn'/plan['source_run']/name) != digest: raise ValueError('Original checkpoint/data changed')
    if sha(run/'initial.npz') != plan['source_sha256']['endpoint.npz']:
        raise ValueError('Continuation did not start from the exact full saved state')
    f=frozen()
    choice=json.loads((run/'choice.json').read_text())
    if choice['plan_sha256'] != PLAN_SHA or choice['rule'] != plan['selection']['candidates']:
        raise ValueError('Selection protocol changed')
    state=json.loads((run/'state.json').read_text())
    if state['deadline_unix'] != plan['absolute_deadline_unix'] or len(state['stages'])>4:
        raise ValueError('Saved allocation changed')
    previous_games=plan['source_games']
    for index,stage in enumerate(state['stages'],1):
        if (stage['index'] != index or stage['starting_games'] != previous_games or not stage['trained']
                or stage['started_unix'] < plan['authorized_start_unix']
                or stage['deadline_unix'] > min(stage['started_unix']+8*3600+.1,plan['research_cutoff_unix']-3600)
                or stage['completed_unix'] > plan['research_cutoff_unix']):
            raise ValueError('Stage clock, ordering or checkpoint state changed')
        checkpoint=run/f'stage_{index}.npz'
        if sha(checkpoint) != stage['model_sha256']: raise ValueError('Stage checkpoint changed')
        _,meta,_=load_network(checkpoint)
        if meta['games'] != stage['games']: raise ValueError('Stage game count changed')
        previous_games=stage['games']
    candidates=choice['candidates']
    if not candidates or candidates[0]['model'] != 'initial.npz': raise ValueError('Initial candidate missing')
    expected_names=['initial.npz']+[f'stage_{i}.npz' for i in range(1,5) if (run/f'screen_stage_{i}/mixed_39011_summary.json').exists()]
    if [c['model'] for c in candidates] != expected_names: raise ValueError('Complete candidate omitted/reordered')
    for candidate in candidates:
        name=candidate['model']
        if Path(name).name != name or sha(run/name) != candidate['sha256']: raise ValueError('Candidate checkpoint changed')
        label='screen_initial' if name=='initial.npz' else 'screen_'+Path(name).stem
        audit_block(run/label,candidate['report'],f,'mixed',39011,64,'validation',old_teams,old_seeds,candidate['sha256'],sha(path))
    selected=max(candidates,key=lambda c:c['report']['score'])
    if choice['selected'] != selected: raise ValueError('Validation-only selection rule changed')
    model=run/selected['model']
    package=run/'final'
    protocol=json.loads((package/'protocol.json').read_text())
    if ((run/'test_lock.json').read_bytes() != (package/'protocol.json').read_bytes()
            or protocol['plan_sha256'] != PLAN_SHA or protocol['choice_sha256'] != sha(run/'choice.json')
            or protocol['source_model_sha256'] != sha(model) or protocol['policy_sha256'] != sha(package/'policy.npz')
            or protocol['baseline'] != f.manifest or protocol['blocks'] != plan['final_blocks']
            or protocol['pairs_per_block'] != 1000 or protocol['split'] != 'test'
            or protocol['exclusion_sha256'] != sha(path) or protocol['deadline_unix'] != plan['absolute_deadline_unix']
            or protocol['source_manifest_sha256'] != activation['source_manifest_sha256']): raise ValueError('New policy/protocol lock changed')
    full,_,_=load_network(model)
    compact,meta,_=load_network(package/'policy.npz')
    if (not same_parameters(full,compact) or any(not np.isfinite(p).all() for p in compact.p)
            or meta['source_sha256'] != sha(model)
            or compact.steps != 0 or any(m.any() for m in compact.m+compact.v)): raise ValueError('Compact parameters changed')
    confirmation=json.loads((run/'confirmation/mixed_39012_summary.json').read_text())
    if confirmation != protocol['confirmation']: raise ValueError('Fresh confirmation changed')
    audit_block(run/'confirmation',confirmation,f,'mixed',39012,128,'validation',old_teams,old_seeds,sha(model),sha(path))
    canary=json.loads((run/'canary.json').read_text())
    if sha(run/'canary.json') != protocol['canary_sha256'] or canary['strength_target_met'] is not None: raise ValueError('Real canary missing')
    for key in ('plan_sha256','source_manifest_sha256','source_model_sha256','policy_sha256','choice_sha256','exclusion_sha256','baseline','recipe','confirmation','deadline_unix'):
        if canary[key] != protocol[key]: raise ValueError('Canary identity differs from locked policy')
    if len(canary['blocks']) != 3: raise ValueError('Canary blocks missing')
    for report,(field,seed) in zip(canary['blocks'],plan['canary']['blocks']):
        audit_block(run/f'canary_{field}_{seed}',report,f,field,seed,2,'validation',old_teams,old_seeds,sha(package/'policy.npz'),sha(path))
    verdict=json.loads((run/'verdict.json').read_text())
    if (len(verdict['final_tests']) != 3 or verdict['protocol_sha256'] != sha(package/'protocol.json')
            or verdict['policy_sha256'] != sha(package/'policy.npz') or verdict['completed_unix'] > plan['absolute_deadline_unix']): raise ValueError('Incomplete, changed or late final verdict')
    reports=[audit_block(run/f'final_{field}_{seed}',report,f,field,seed,1000,'test',old_teams,old_seeds,sha(package/'policy.npz'),sha(path))
             for report,(field,seed) in zip(verdict['final_tests'],plan['final_blocks'])]
    passed=all(r['lower95']>.5 for r in reports[:2]) and reports[2]['upper95']>=.5
    if verdict['strength_target_met'] is not passed: raise ValueError('Fixed reliable-win criterion changed')
    return dict(evidence_verified=True,strength_target_met=passed,pairings=3000,battles=6000,
        excluded_compositions_verified=len(old_teams),excluded_game_seeds_verified=len(old_seeds),
        runtime_source_files_verified=len(manifest),baseline_files_verified=len(f.manifest['files']),
        blocks=reports,policy_sha256=sha(package/'policy.npz'),verdict_sha256=sha(run/'verdict.json'),
        protocol_sha256=sha(package/'protocol.json'),auditor_sha256=sha(Path(__file__)))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',default='continue-v1')
    args=parser.parse_args()
    result=audit(args.run)
    write_json(ROOT/'runs/double-dqn'/args.run/'audit.json',result)
    print(json.dumps(result))
