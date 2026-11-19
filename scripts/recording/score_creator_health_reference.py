"""Score native-pixel HP references without rewriting frozen coarse labels."""
import argparse
import hashlib
import json
from pathlib import Path
import random

from evaluate_creator_fullstate import snapshot_at, usable
from score_creator_events import canon, rows


def count_fields(fields):
    return dict(possible=len(fields), reference_measured=sum(f['reference_measured'] for f in fields),
                usable=sum(f['usable'] for f in fields),
                scorable_usable=sum(f['usable'] and f['reference_measured'] for f in fields),
                correct=sum(f['usable'] and f['correct'] is True for f in fields))


def metrics(counts):
    return dict(usable_accuracy=counts['correct']/counts['scorable_usable'] if counts['scorable_usable'] else None,
                usable_coverage=counts['usable']/counts['possible'] if counts['possible'] else None,
                verified_correct_coverage=counts['correct']/counts['possible'] if counts['possible'] else None)


def score(reference, truth, predictions):
    anchors={(b['record'],a['t']):a for b in truth['battles'] for a in b['state_anchors']}
    details=[]
    for item in reference['frames']:
        folder=predictions/item['channel']/item['record']
        snapshots=rows(folder/'continuity.jsonl')
        at=item['native_witness']['source_seconds']
        state=snapshot_at(snapshots,at)
        fields=[]
        for side,expected in item['sides'].items():
            team=state.get('sides',{}).get('mine' if side=='mine' else 'opponent',{})
            mon=team.get('pokemon',{}).get(team.get('active'),{})
            health=mon.get('health',{})
            value=health.get('value')
            numeric=(isinstance(value,list) and len(value)==2 and all(isinstance(v,(float,int)) and not isinstance(v,bool) for v in value))
            reported=numeric and usable(health) and team.get('active_status') in ('observed','retained')
            measured=expected['status']=='measured'
            reference_species=anchors[(item['record'],item['requested_seconds'])]['expected'][side+'.species']
            identity_correct=canon(mon.get('species',{}).get('value'))==canon(reference_species)
            correct=None
            if measured:
                lo,hi=expected['fraction_interval']
                correct=bool(numeric and identity_correct and 0<=value[1]-value[0]<=.2 and value[0]<=hi and value[1]>=lo)
            fields.append(dict(side=side,reference_measured=measured,expected=expected.get('fraction_interval'),actual=value,
                reference_species=reference_species,actual_species=mon.get('species',{}).get('value'),identity_correct=identity_correct,
                usable=bool(reported),correct=correct,observed_at_seconds=health.get('observed_at_seconds'),state_validity=health.get('state_validity')))
        details.append(dict(record=item['record'],channel=item['channel'],t=at,fields=fields))
    totals=count_fields([f for d in details for f in d['fields']]);totals.update(metrics(totals))
    battles=sorted({(d['channel'],d['record']) for d in details})
    clusters=[count_fields([f for d in details if (d['channel'],d['record'])==b for f in d['fields']]) for b in battles]
    samples={k:[] for k in metrics(totals)};rng=random.Random(46)
    for _ in range(4000):
        selected=[rng.choice(clusters) for _ in clusters]
        counts={k:sum(c[k] for c in selected) for k in ('possible','reference_measured','usable','scorable_usable','correct')}
        for key,value in metrics(counts).items():
            if value is not None:samples[key].append(value)
    for key,values in samples.items():
        values.sort();totals[key+'_battle_bootstrap_95']=[values[int((len(values)-1)*q)] for q in (.025,.975)] if values else None
    return dict(schema='creator-native-health-score-v1',battles=len(battles),counts=totals,details=details,
        limitations=['Post-prediction development reference correction; not an independent test.',
            'Unknown source HP stays in coverage denominator but cannot establish accuracy.',
            'Interval overlap with pixel uncertainty is not exact integer HP accuracy.',
            'Assistant source review has not been independently human adjudicated.'])


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--reference',type=Path,required=True);ap.add_argument('--truth',type=Path,required=True)
    ap.add_argument('--predictions',type=Path,required=True);ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args();reference=json.loads(args.reference.read_text(encoding='utf8'))
    truth_sha=hashlib.sha256(args.truth.read_bytes()).hexdigest()
    if truth_sha!=reference['original_truth_sha256']:raise ValueError('Reference belongs to a different frozen truth file')
    result=score(reference,json.loads(args.truth.read_text(encoding='utf8')),args.predictions)
    result.update(reference_sha256=hashlib.sha256(args.reference.read_bytes()).hexdigest(),original_truth_sha256=truth_sha,
        evaluation_code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    result['prediction_sha256']={f'{channel}/{record}':hashlib.sha256((args.predictions/channel/record/'continuity.jsonl.gz').read_bytes()).hexdigest()
        for channel,record in sorted({(d['channel'],d['record']) for d in result['details']})}
    args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print(json.dumps(result['counts']))


if __name__=='__main__':main()
