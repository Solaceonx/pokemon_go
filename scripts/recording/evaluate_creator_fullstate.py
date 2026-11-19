"""Score frozen source labels, including failed runs and unknown state fields.

No source media or labels are consumed by the production detector. This offline
evaluator uses causal snapshots (at or before each reference time), never the
nearest future snapshot. A consistency pass is reported separately from accuracy.
"""
import argparse
import bisect
from collections import Counter
import hashlib
import json
from pathlib import Path
import random
import statistics

from score_creator_events import KINDS, canon, match, predictions, rates, references, rows


def visible_species(name, species_table):
    """The labels grade header names, not an unannotated regional form."""
    return species_table.get(name, name)


def snapshot_at(snapshots, t):
    index = bisect.bisect_right([r['t'] for r in snapshots], t)-1
    return snapshots[index].get('game_state', {}) if index >= 0 else {}


def usable(field):
    return (field.get('value') is not None and field.get('status') not in
            ('unknown', 'stale', 'historical', 'contradictory', 'pending') and
            not field.get('pending') and field.get('state_validity') not in
            ('pending', 'pending_change', 'before_faint', 'unconfirmed_at_exit', 'unconfirmed'))


def anchor_fields(state, anchor):
    out = []
    for key, expected in anchor['expected'].items():
        side, name = key.split('.')
        current = state.get('sides', {}).get('mine' if side == 'mine' else 'opponent', {})
        if name == 'species':
            field = current.get('pokemon', {}).get(current.get('active'), {}).get('species', {})
            valid = usable(field) and current.get('active_status') in ('observed','retained')
            same = canon(field.get('value')) == canon(expected)
        else:
            field = current.get('left' if name == 'party' else name, {})
            valid = usable(field)
            same = field.get('value') == expected
        out.append(dict(field=key, expected=expected, actual=field.get('value'),
                        status=field.get('status', 'unknown'), reported=field.get('value') is not None,
                        usable=valid, correct=same))
    for side, expected in anchor.get('fraction_annotations', {}).items():
        current = state.get('sides', {}).get('mine' if side == 'mine' else 'opponent', {})
        field = current.get('pokemon', {}).get(current.get('active'), {}).get('health', {})
        actual = field.get('value')
        numeric = (isinstance(actual, list) and len(actual) == 2 and
                   all(isinstance(v, (float, int)) and not isinstance(v, bool) for v in actual))
        overlap = numeric and actual[0] <= expected[1] and actual[1] >= expected[0]
        informative = numeric and 0 <= actual[1]-actual[0] <= .2
        out.append(dict(field=side+'.health_fraction', expected=expected, actual=actual,
                        status=field.get('status', 'unknown'), reported=numeric,
                        usable=usable(field) and current.get('active_status') in ('observed','retained'),
                        correct=bool(overlap and informative), interval_overlap=bool(overlap),
                        informative=informative))
    return out


def field_counts(details):
    result = {}
    for record in details:
        for anchor in record['anchors']:
            for f in anchor['fields']:
                group = f['field'].split('.')[1]
                count = result.setdefault(group, Counter())
                count['total'] += 1
                count['reported'] += f['reported']
                count['reported_correct'] += f['reported'] and f['correct']
                count['usable'] += f['usable']
                count['usable_correct'] += f['usable'] and f['correct']
    return {k: dict(v) for k, v in result.items()}


def timing_diagnostics(expected,actual):
    """Expose tight timing without changing the primary three-second score.

    Distance is to the labelled interval, not an invented exact time. Shield
    times here grade attack association; the ledger retains actual spend time.
    """
    primary=match(expected,actual)
    distances=[]
    for i,j in primary['matches']:
        lo,hi=expected[i]['window'];at=actual[j]['t']
        distances.append(at-hi if at>hi else at-lo if at<lo else 0.)
    absolute=sorted(abs(v) for v in distances)
    wide=[actual[j] for i,j in primary['matches'] if
          actual[j].get('timing_interval_seconds') and actual[j]['timing_interval_seconds'][1]-actual[j]['timing_interval_seconds'][0]>1
          or actual[j].get('timing_uncertainty_seconds',0) is not None and actual[j].get('timing_uncertainty_seconds',0)>1]
    return dict(matches_by_tolerance_seconds={str(t):match(expected,actual,tolerance=t)['tp'] for t in [0,1,3]},
        matched_events=len(distances),matched_with_timing_uncertainty_over_one_second=len(wide),early_outside_interval=sum(v<0 for v in distances),
        late_outside_interval=sum(v>0 for v in distances),
        median_absolute_distance_seconds=statistics.median(absolute) if absolute else None,
        maximum_absolute_distance_seconds=max(absolute) if absolute else None,
        p95_absolute_distance_seconds=absolute[int(.95*(len(absolute)-1))] if absolute else None,
        signed_distances_seconds=[round(v,6) for v in distances])


def shield_decision_accuracy(expected,actual):
    paired=match(expected,actual)
    result=dict(reference_charges=len(expected),matched_charges=paired['tp'],
                missing_charges=paired['fn'],correct=0,incorrect=0,unknown=0)
    for i,j in paired['matches']:
        value=actual[j].get('shielded')
        if not isinstance(value,bool):result['unknown']+=1
        elif value is expected[i]['shielded']:result['correct']+=1
        else:result['incorrect']+=1
    return result


def bootstrap_event(battles, kind, metric, *, seed=46, repetitions=4000):
    rng = random.Random(seed)
    samples = []
    for _ in range(repetitions):
        counts = Counter()
        for _ in battles:
            record = rng.choice(battles)
            counts.update({k: record['events'][kind][k] for k in ('tp', 'fp', 'fn')})
        value = rates(counts)[metric]
        if value is not None:
            samples.append(value)
    samples.sort()
    return [samples[int((len(samples)-1)*q)] for q in (.025, .975)] if samples else None


def field_metrics(details, *, seed=46, repetitions=4000):
    """Battle-cluster margins for usable accuracy and coverage, including gaps."""
    totals=field_counts(details)
    by_battle=[field_counts([record]) for record in details]
    for field,total in totals.items():
        total['usable_accuracy']=total['usable_correct']/total['usable'] if total['usable'] else None
        total['usable_coverage']=total['usable']/total['total'] if total['total'] else None
        rng=random.Random(seed)
        samples={'usable_accuracy':[],'usable_coverage':[]}
        for _ in range(repetitions):
            count=Counter()
            for _ in by_battle:count.update(rng.choice(by_battle).get(field,{}))
            if count['usable']:samples['usable_accuracy'].append(count['usable_correct']/count['usable'])
            if count['total']:samples['usable_coverage'].append(count['usable']/count['total'])
        for metric,values in samples.items():
            values.sort()
            total[metric+'_battle_bootstrap_95']=([values[int((len(values)-1)*q)] for q in [.025,.975]] if values else None)
    return totals


def evaluate(truth, base, *, event_source='model'):
    gm = json.loads((Path(__file__).resolve().parents[2]/'data/gamemaster.json').read_text(encoding='utf8'))
    species_table = {p['speciesId']: p['speciesName'].split(' (')[0] for p in gm['pokemon']}
    details = []
    for b in truth['battles']:
        folder = base/b['channel']/b['record']
        complete = all((folder/name).exists() or (folder/(name+'.gz')).exists()
                       for name in ('events.jsonl', 'states.jsonl', 'timeline.json', 'continuity.jsonl'))
        predicted = predictions(folder) if complete else []
        if event_source == 'source':
            ledger = folder/'source-events.jsonl.gz'
            predicted = rows(ledger) if complete and ledger.exists() else []
            for e in predicted:
                # The reference annotates shield use on the associated release,
                # while the ledger additionally dates the actual counter spend.
                if e['kind'] == 'shield':
                    e['counter_first_visible_seconds'] = e['t']
                    e['t'] = e['associated_attack_seconds']
        for event in predicted:
            event['pokemon'] = visible_species(event.get('pokemon'), species_table)
        snapshots = rows(folder/'continuity.jsonl') if complete else []
        ref = references(b)
        record = dict(channel=b['channel'], record=b['record'], processing_complete=complete,
                      events={}, anchors=[])
        record['prediction_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for name in
            ['source.json','timeline.json','continuity.jsonl.gz','source-events.jsonl.gz','events.jsonl.gz','states.jsonl.gz']
            if (p:=folder/name).is_file()}
        record['shield_decisions']=shield_decision_accuracy(
            [e for e in ref if e['kind']=='charged'],[e for e in predicted if e['kind']=='charged'])
        for kind in KINDS:
            expected = [e for e in ref if e['kind'] == kind]
            actual = [e for e in predicted if e['kind'] == kind]
            scored = match(expected, actual)
            record['events'][kind] = {**rates(scored),
                'missing': [expected[i] for i in scored['missed']],
                'extra': [actual[i] for i in scored['extra']],
                'timing':timing_diagnostics(expected,actual)}
        for anchor in b.get('state_anchors',[]):
            at = anchor.get('native_witness', {}).get('source_seconds', anchor['t'])
            record['anchors'].append(dict(t=at, requested_seconds=anchor['t'],
                fields=anchor_fields(snapshot_at(snapshots, at), anchor)))
        record['all_reference_events_correct'] = complete and all(
            s['fp'] == 0 and s['fn'] == 0 for s in record['events'].values())
        details.append(record)
    totals = {}
    for kind in KINDS:
        counts = Counter()
        for record in details:
            counts.update({k: record['events'][kind][k] for k in ('tp', 'fp', 'fn')})
        totals[kind] = rates(counts)
        for metric in ('precision', 'recall'):
            totals[kind][metric+'_battle_bootstrap_95'] = bootstrap_event(details, kind, metric)
    shield_decisions=dict(Counter({key:sum(r['shield_decisions'][key] for r in details)
                                   for key in details[0]['shield_decisions']})) if details else {}
    return dict(schema='creator-fullstate-evaluation-v1', battles=len(details),
                primary_event_tolerance_seconds=3,
                event_source=event_source,
                completed_runs=sum(r['processing_complete'] for r in details),
                all_reference_events_correct=sum(r['all_reference_events_correct'] for r in details),
                events=totals, shield_decisions=shield_decisions,fields=field_metrics(details), details=details,
                limitations=['Six battles from three source archives; clustered intervals are unstable at this size.',
                    'Assistant-reviewed source labels have not been independently adjudicated.',
                    'HP score is overlap with broad visual annotation bounds and predicted width <=0.2, not exact HP accuracy.',
                    'Unknown, stale and pending fields do not count as usable; missing runs remain in every denominator.',
                    'Energy, clock and stage accuracy not established; event scores do not establish full-state readiness.'])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--truth', type=Path, required=True)
    ap.add_argument('--predictions', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--event-source', choices=['model','source'], default='model')
    args = ap.parse_args()
    result = evaluate(json.loads(args.truth.read_text(encoding='utf8')), args.predictions,event_source=args.event_source)
    result['truth_sha256'] = hashlib.sha256(args.truth.read_bytes()).hexdigest()
    result['predictions_root'] = str(args.predictions)
    result['evaluation_code_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in
        [Path(__file__),Path(__file__).with_name('score_creator_events.py')]}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes((json.dumps(result, indent=2)+'\n').encode('utf8'))
    print(json.dumps({k: v for k, v in result.items() if k not in ('details', 'limitations')}))


if __name__ == '__main__':
    main()
