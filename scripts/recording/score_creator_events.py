"""Score source-reviewed events against exported tracker events, without tuning.

One-to-one matches require the correct side, charged move/actor or fainted
species, and a timestamp within the annotated interval plus three seconds.
Shield use is scored separately from a damage-block message. Timing-free
identity counts are diagnostic only, never substituted for the timed score.
"""
import argparse
import bisect
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import random
import re
import sys
from visible_vocabulary import species_key

ROOT = Path(__file__).resolve().parents[2]
KINDS = ('charged', 'shield', 'faint')


def canon(text):
    return re.sub('[^a-z]', '', (text or '').lower())


def move_name(text):
    """Keep a displayed enhanced-move suffix significant when scoring labels."""
    label = (text or '').replace('\uff0b', '+').strip().rstrip('!\uff01').strip()
    suffix = re.search(r'\++$', label)
    return canon(label)+(suffix.group() if suffix else '')


def species_name(text):
    # The reference grades the visible header species, not unannotated forms.
    return species_key(text).lower()


def rows(path):
    if not path.exists():
        path = path.with_name(path.name+'.gz')
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rt', encoding='utf-8') as stream:
        return [json.loads(line) for line in stream if line.strip()]


def predictions(folder):
    timeline = json.loads((folder/'timeline.json').read_text(encoding='utf-8'))
    states = rows(folder/'states.jsonl')
    times = [s['t'] for s in states]
    result = []
    for event in rows(folder/'events.jsonl'):
        name = event['event']
        if name not in ('my_charged', 'foe_charged', 'my_faint', 'foe_faint'):
            continue
        side = 'mine' if name.startswith('my_') else 'theirs'
        faint = name.endswith('faint')
        index = (bisect.bisect_left(times, event['t']) if faint else
                 bisect.bisect_right(times, event['t']))-1
        species = event.get('species') if faint else None
        if not species and 0 <= index < len(states):
            team = states[index]['me' if side == 'mine' else 'opponent']
            active = team.get('active')
            if active is not None and 0 <= active < len(team['pokemon']):
                species = team['pokemon'][active]['name']
        row = {'kind': 'faint' if faint else 'charged', 'side': side, 'pokemon': species,
               'move': event.get('move'), 't': event['t']+timeline['clip_origin_seconds'],
               'shielded': bool(event.get('shielded')) if not faint else None}
        result.append(row)
        if not faint and event.get('shielded'):
            result.append({'kind': 'shield', 'side': 'theirs' if side == 'mine' else 'mine',
                           't': row['t'], 'associated_attack': row})
    return result


def references(battle):
    out = []
    for event in battle['events']:
        if event['kind'] not in ('charged', 'faint'):
            continue
        out.append(event)
        if event['kind'] == 'charged' and event['shielded']:
            out.append({'kind': 'shield', 'side': 'theirs' if event['side'] == 'mine' else 'mine',
                        'window': event['window'], 'associated_attack': event['move']})
    return out


def compatible(truth, prediction, timed=True, tolerance=3):
    if truth['kind'] != prediction['kind'] or truth['side'] != prediction['side']:
        return False
    if timed and not truth['window'][0]-tolerance <= prediction['t'] <= truth['window'][1]+tolerance:
        return False
    if truth['kind'] in ('charged', 'faint') and species_name(truth['pokemon']) != species_name(prediction['pokemon']):
        return False
    if truth['kind'] == 'charged':
        expected, actual = move_name(truth['move']), move_name(prediction['move'])
        # A visible generic Weather Ball name does not establish its variant.
        if expected == 'weatherball':
            return actual.startswith(expected) and not actual.endswith('+')
        return expected == actual
    return True


def match(truth, predicted, timed=True, tolerance=3):
    edges = [[j for j, p in enumerate(predicted) if compatible(t, p, timed,tolerance)] for t in truth]
    owners = {}

    def augment(i, seen):
        for j in edges[i]:
            if j in seen:
                continue
            seen.add(j)
            if j not in owners or augment(owners[j], seen):
                owners[j] = i
                return True
        return False
    for i in range(len(truth)):
        augment(i, set())
    paired = sorted((i, j) for j, i in owners.items())
    return {'tp': len(paired), 'fp': len(predicted)-len(paired), 'fn': len(truth)-len(paired),
            'matches': paired, 'missed': [i for i in range(len(truth)) if i not in owners.values()],
            'extra': [j for j in range(len(predicted)) if j not in owners]}


def rates(counts):
    tp, fp, fn = (counts.get(k, 0) for k in ('tp', 'fp', 'fn'))
    return {**{k: counts.get(k, 0) for k in ('tp', 'fp', 'fn')},
            'precision': tp/(tp+fp) if tp+fp else None,
            'recall': tp/(tp+fn) if tp+fn else None,
            'f1': 2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None}


def censored_prediction(prediction, cues):
    return prediction['kind'] == 'charged' and any(
        prediction['side'] == cue['side'] and canon(prediction['pokemon']) == canon(cue['pokemon']) and
        cue['window'][0]-3 <= prediction['t'] <= cue['window'][1]+3 for cue in cues)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--truth', type=Path, default=ROOT/'data/creator_ground_truth_v1.json')
    ap.add_argument('--before', type=Path, required=True, help='Private baseline root, grouped channel/record')
    ap.add_argument('--after', type=Path, default=ROOT/'games/creators')
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--baseline-ref', help='Recorded Git revision supplying the before packages')
    a = ap.parse_args()
    truth = json.loads(a.truth.read_text(encoding='utf-8'))
    details = []
    for battle in truth['battles']:
        ref = references(battle)
        record = {'channel': battle['channel'], 'record': battle['record'],
                  'development_example': battle['development_example'], 'reference_events': ref}
        for phase, base in [('before', a.before), ('after', a.after)]:
            predicted = predictions(base/battle['channel']/battle['record'])
            # A release hidden by an edit is unscorable, not a guessed true or false event.
            censored = [e for e in battle['events'] if e['kind'] == 'charged_cue']
            ignored = [p for p in predicted if censored_prediction(p, censored)]
            predicted = [p for p in predicted if p not in ignored]
            record[phase] = {'predictions': predicted, 'unscorable_release_predictions': ignored, 'scores': {}}
            for kind in KINDS:
                ts, ps = [t for t in ref if t['kind'] == kind], [p for p in predicted if p['kind'] == kind]
                measured = match(ts, ps)
                record[phase]['scores'][kind] = {**rates(measured), 'detail': measured,
                    'identity_only': rates(match(ts, ps, timed=False))}
                if kind == 'charged':
                    correct = sum(ts[i]['shielded'] == ps[j]['shielded'] for i, j in measured['matches'])
                    record[phase]['shield_decisions'] = {'correct': correct, 'matched_charges': len(measured['matches']),
                        'reference_charges': len(ts), 'missing_charges': measured['fn']}
        details.append(record)
    groups = {'all_six': details, 'excluding_development_example': [r for r in details if not r['development_example']]}
    groups.update({c: [r for r in details if r['channel'] == c] for c in sorted({r['channel'] for r in details})})
    aggregate = {}
    for group, battles in groups.items():
        aggregate[group] = {'battles': len(battles)}
        for phase in ('before', 'after'):
            aggregate[group][phase] = {}
            decisions = Counter()
            for row in battles:
                decisions.update(row[phase]['shield_decisions'])
            aggregate[group][phase]['shield_decisions'] = {**dict(decisions),
                'correct_fraction_all_reference_charges': decisions['correct']/decisions['reference_charges'] if decisions['reference_charges'] else None,
                'correct_fraction_matched_charges': decisions['correct']/decisions['matched_charges'] if decisions['matched_charges'] else None}
            for kind in KINDS:
                count = Counter()
                for row in battles:
                    count.update({k: row[phase]['scores'][kind][k] for k in ('tp', 'fp', 'fn')})
                score = rates(count)
                # Resample whole battles, not correlated events within a battle.
                rng = random.Random(46)
                boot = []
                for _ in range(2000):
                    drawn = rng.choices(battles, k=len(battles))
                    values = Counter()
                    for row in drawn:
                        values.update({k: row[phase]['scores'][kind][k] for k in ('tp', 'fp', 'fn')})
                    f1 = rates(values)['f1']
                    if f1 is not None:
                        boot.append(f1)
                boot.sort()
                score['descriptive_f1_interval95_by_battle'] = [boot[int(.025*len(boot))], boot[min(len(boot)-1,int(.975*len(boot)))]] if boot else None
                aggregate[group][phase][kind] = score
    report = {'schema': 'creator-event-accuracy-v1', 'truth_file': a.truth.resolve().relative_to(ROOT).as_posix(),
              'truth_sha256': hashlib.sha256(a.truth.read_bytes()).hexdigest(),
              'scorer_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'baseline_git_ref': a.baseline_ref,
              'method': 'Maximum one-to-one matching; correct side, actor/species and move; annotated video-time interval +/- 3 seconds.',
              'scope': 'Six manually reviewed diagnostic clips, all used for current debugging. Regression scores, not heldout accuracy; no independent-human adjudication.',
              'historical_development_flag': 'The exclusion group preserves the original Henry-only development marker. The other five clips are now also used for debugging, so neither group is held out.',
              'identity_scope': 'Visible species header names; unannotated form suffixes and generic Weather Ball variants are not graded.',
              'interval_caveat': 'Battle-cluster bootstrap intervals are descriptive; two battles per channel cannot support population accuracy.',
              'aggregate': aggregate, 'battles': details}
    write = json.dumps(report, indent=2)+'\n'
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(write, encoding='utf-8')
    print(json.dumps(aggregate['all_six']))


if __name__ == '__main__':
    main()
