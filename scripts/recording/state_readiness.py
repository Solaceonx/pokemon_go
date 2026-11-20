"""Separate usable observations, reviewed event counts and full-state readiness.

A consistency pass cannot certify source accuracy. Unknown/pending values and
missing time stay in the denominator. Reference verification is bound to the
exact exported files, so a later replay cannot inherit an old approval.
"""
import argparse
from collections import Counter
import gzip
import hashlib
import json
import math
from pathlib import Path

def known(field,at):
    return (field.get('value') is not None and field.get('status') in {'observed','estimated','inferred','retained','constrained'}
        and field.get('state_validity') not in {'pending','pending_change','before_faint','unconfirmed','unconfirmed_at_exit'}
        and not field.get('pending') and all(isinstance(t,(int,float)) and not isinstance(t,bool)
            and math.isfinite(t) and t<=at for t in
            [field.get('observed_at_seconds',at),field.get('confirmed_at_seconds',at)]))


def interval(field,at,lo,hi,width,integer=False):
    if not known(field,at):return False
    value=field['value'];value=value if isinstance(value,list) else [value,value]
    return (len(value)==2 and all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in value)
        and lo<=value[0]<=value[1]<=hi and value[1]-value[0]<=width
        and (not integer or all(int(v)==v for v in value)))


def available_fields(state,at):
    result={}
    for side in ['mine','opponent']:
        team=state.get('sides',{}).get(side,{})
        active=team.get('active');mon=team.get('pokemon',{}).get(active,{})
        active_known=team.get('active_status') in ['observed','retained'] and known(mon.get('species',{}),at)
        result[side+'.active_identity']=bool(active_known and known(mon.get('cp',{}),at))
        result[side+'.party']=interval(team.get('left',{}),at,0,3,0,True)
        result[side+'.shields']=interval(team.get('shields',{}),at,0,2,0,True)
        result[side+'.health_fraction']=bool(active_known and interval(mon.get('health',{}),at,0,1,.1))
        result[side+'.energy']=bool(active_known and interval(mon.get('energy',{}),at,0,100,15,True))
        for field in ['attack_stage','defense_stage']:
            result[side+'.'+field]=bool(active_known and interval(mon.get(field,{}),at,-4,4,0,True))
        result[side+'.form']=bool(active_known and known(mon.get('form',{}),at))
    result['battle_clock']=interval(state.get('battle_clock',{}),at,0,100000,.5)
    result['switch_cooldown']=known(state.get('switch_cooldown',{}),at)
    return result


def verified_events(folder,reference):
    if not reference:return dict(counts_ready=False,timing_ready=False,shield_decisions_ready=False,reason='No source-reviewed reference for this exported record')
    hashes=reference.get('prediction_sha256',{})
    required={'source.json','timeline.json','continuity.jsonl.gz','source-events.jsonl.gz'}
    if not required.issubset(hashes) or not all((folder/name).is_file() and
            hashlib.sha256((folder/name).read_bytes()).hexdigest()==digest for name,digest in hashes.items()):
        return dict(counts_ready=False,timing_ready=False,shield_decisions_ready=False,reason='Reference hashes do not match this export')
    events=reference.get('events',{})
    complete=(reference.get('processing_complete') is True and set(events)=={'charged','shield','faint'}
              and all(e.get('fp')==0 and e.get('fn')==0 for e in events.values()))
    timing=complete and all(e.get('timing',{}).get('matches_by_tolerance_seconds',{}).get('1')==e.get('tp')
        and e.get('timing',{}).get('matched_with_timing_uncertainty_over_one_second',0)==0 for e in events.values())
    choices=reference.get('shield_decisions',{})
    decisions=complete and choices.get('reference_charges',0)>0 and choices.get('correct')==choices.get('reference_charges')
    return dict(counts_ready=bool(complete),timing_ready=bool(timing),shield_decisions_ready=bool(decisions),
        reason='Source-reviewed visible events only; edited or unseen events and decision-state accuracy are not certified',
        timing_tolerance_seconds=1)


def assess(folder,reference=None):
    path=folder/'continuity.jsonl.gz'
    with gzip.open(path,'rt',encoding='utf8') as f:rows=[json.loads(line) for line in f if line.strip()]
    coverage=Counter();missing=Counter();longest=Counter();total=0.;full=0.;gaps=0.
    for row,after in zip(rows,rows[1:]):
        delta=after['t']-row['t']
        if delta<=0:raise ValueError('Continuity timestamps do not increase')
        fields=available_fields(row['game_state'],row['t']);total+=delta
        if delta>.25:gaps+=delta;fields={key:False for key in fields}
        if fields and all(fields.values()):full+=delta
        for key,available in fields.items():
            if available:coverage[key]+=delta;missing[key]=0.
            else:missing[key]+=delta;longest[key]=max(longest[key],missing[key])
    keys=list(available_fields({},0))
    verification=verified_events(folder,reference)
    return dict(schema='source-state-readiness-v1',record=folder.name,channel=folder.parent.name,
        interval_scope='Complete saved clip including pre/post-battle margins',duration_seconds=round(total,6),
        unobserved_gap_seconds=round(gaps,6),
        observable_field_coverage={key:dict(available_seconds=round(coverage[key],6),
            fraction=coverage[key]/total if total else 0,longest_unavailable_seconds=round(longest[key],6)) for key in keys},
        available_full_state_fraction=full/total if total else 0,
        reviewed_visible_events=verification,full_game_state_ready=False,
        blockers=['Continuous HP accuracy, useful energy, forms, stages and clocks have not been independently verified.',
            'Sampled/reference event success cannot certify every state between the checked frames.',
            'Unseen or edited starts/endings remain unresolved.'],
        policy=dict(max_health_fraction_width=.1,max_energy_interval_width=15,exact_stages_required=True,
            pending_and_unknown_count_as_available=False,consistency_verdict_used_as_accuracy=False),
        provenance=dict(continuity_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            assessor_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()))


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--root',type=Path,required=True)
    ap.add_argument('--reference-report',type=Path,action='append',default=[]);ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args();references={};sources=[]
    for path in args.reference_report:
        report=json.loads(path.read_text(encoding='utf8'))
        if report.get('event_source')!='source':raise ValueError('Readiness requires source-event evaluation, not default-model events')
        sources.append(dict(report_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),truth_sha256=report['truth_sha256']))
        for record in report['details']:references[(record['channel'],record['record'])]=record
    records=[assess(p.parent,references.get((p.parent.parent.name,p.parent.name))) for p in sorted(args.root.glob('*/*/continuity.jsonl.gz'))]
    output=dict(schema='source-state-readiness-collection-v1',records=records,total_records=len(records),
        counts_verified=sum(r['reviewed_visible_events']['counts_ready'] for r in records),
        timing_verified=sum(r['reviewed_visible_events']['timing_ready'] for r in records),
        shield_decisions_verified=sum(r['reviewed_visible_events']['shield_decisions_ready'] for r in records),
        full_game_state_ready=sum(r['full_game_state_ready'] for r in records),references=sources)
    args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_bytes((json.dumps(output,indent=2)+'\n').encode('utf8'))
    print(json.dumps({k:v for k,v in output.items() if k not in ['records','references']}))


if __name__=='__main__':main()
