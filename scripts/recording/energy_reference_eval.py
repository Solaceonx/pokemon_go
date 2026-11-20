"""Score a standalone energy pilot without changing frozen labels or exports.

The context file supplies source-verified moves/identity, fast-only corridors,
initial-zero proof and named releases. Numeric truth/count targets are read only
after reconstruction. This is conditional timing/accounting evaluation, not a
claim that arbitrary VODs can identify their own moves or safe corridors.
"""
import argparse
import bisect
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path

from energy_rebuild import measured_impacts, rebuild


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_rows(path):
    with gzip.open(path, 'rt', encoding='utf8') as handle:
        return [json.loads(line) for line in handle if line.strip()]


def expand(rr):
    return {v for lo, hi in rr for v in range(lo, hi + 1)}


def baseline(rows, side, t):
    index = bisect.bisect_right([r['t'] for r in rows], t) - 1
    if index < 0 or t - rows[index]['t'] > .25:
        return set()
    state = rows[index]['game_state']['sides']['mine' if side == 'mine' else 'opponent']
    if state.get('active_status') not in {'observed', 'retained'}:
        return set()
    field = state.get('pokemon', {}).get(state.get('active'), {}).get('energy', {})
    if (field.get('status') not in {'observed', 'estimated', 'retained', 'inferred', 'constrained'}
            or field.get('state_validity') in {'pending', 'pending_change', 'before_faint', 'unconfirmed', 'unconfirmed_at_exit'}
            or field.get('pending') or field.get('unconfirmed_at_exit')):
        return set()
    rr = field.get('integer_ranges')
    if rr:
        return expand(rr)
    value = field.get('value')
    if isinstance(value, int):
        return {value}
    if isinstance(value, list) and len(value) == 2:
        return set(range(value[0], value[1] + 1))
    return set()


def score_points(points):
    result = {}
    for side in ['mine', 'theirs', 'both']:
        selected = [p for p in points if side == 'both' or p['side'] == side]
        covered = [p for p in selected if p['useful']]
        exact_labels = [p for p in selected if p['truth'][0] == p['truth'][1]]
        result[side] = dict(total=len(selected), useful=len(covered),
            useful_coverage=len(covered) / len(selected) if selected else None,
            exact_numeric_truth=len(exact_labels),
            exact_predictions_correct=sum(p['exact_correct'] for p in selected),
            reference_interval_contained=sum(p['truth_contained'] for p in selected),
            candidate_set_overlaps_reference=sum(p['overlaps'] for p in selected),
            covered_sets_contain_reference=sum(p['truth_contained'] for p in covered),
            covered_sets_within_reference=sum(p['prediction_within_reference'] for p in covered),
            within_one_fast_guaranteed=sum(p['within_one_fast_guaranteed'] for p in selected),
            group_bootstrap_95=None,
            margin_reason='One nested development battle/source: insufficient independent groups for a meaningful bootstrap margin')
    return result


def point_score(side, t, candidates, target, gain):
    truth = set(range(target[0], target[1] + 1))
    # Coverage uses the existing reader's fixed width <=15 criterion. A huge
    # set containing everything cannot count as useful correct energy.
    useful = bool(candidates) and max(candidates) - min(candidates) <= 15
    return dict(side=side, t=t, predicted_ranges=_ranges(candidates), truth=target,
        useful=useful, exact_correct=len(truth) == len(candidates) == 1 and candidates == truth,
        truth_contained=bool(candidates) and truth <= candidates,
        prediction_within_reference=bool(candidates) and candidates <= truth,
        overlaps=bool(truth & candidates),
        within_one_fast_guaranteed=bool(candidates) and
            all(min(abs(v - actual) for actual in truth) <= gain for v in candidates))


def _ranges(values):
    from energy_rebuild import ranges
    return ranges(values)


def audit_original_truth(root):
    names = ['creator_ground_truth_v1.json', 'creator_fullstate_ground_truth_v1.json',
             'creator_fullstate_ground_truth_v2_corrected1.json',
             'creator_fullstate_ground_truth_v3_corrected2.json',
             'creator_fullstate_ground_truth_v4_corrected1.json']
    reports = []
    for name in names:
        path = root / 'data' / name
        data = json.loads(path.read_text(encoding='utf8'))
        anchors = [a for b in data['battles'] for a in b.get('state_anchors', [])]
        energy = []
        def walk(value, route=''):
            if isinstance(value, dict):
                for key, child in value.items():
                    if 'energy' in key.lower():
                        energy.append(route + key)
                    walk(child, route + key + '.')
            elif isinstance(value, list):
                for i, child in enumerate(value): walk(child, route + str(i) + '.')
        walk(data)
        reports.append(dict(file='data/' + name, sha256=sha(path), battles=len(data['battles']),
                            state_anchors=len(anchors), energy_label_keys=energy))
    return dict(files=reports, total_battles=30, total_state_anchors=322,
        numeric_energy_labels=0, numeric_energy_accuracy_before=None,
        numeric_energy_accuracy_after=None,
        reason='The unchanged frozen references have no numeric energy or measured fast-completion labels; charged legality is not numeric accuracy.')


def evaluate(root, context, labels_path):
    # Do not read numeric labels until after all detector/rebuilder outputs exist.
    raw_path = root / context['native_health']
    rows = read_rows(raw_path)
    proof = dict(basis='current_pixel_measurement', source_sha256=sha(raw_path))
    observations = []
    detectors = {}
    for side in ['mine', 'theirs']:
        identity = context['identities'][side]
        move = context['moves'][side]
        observations.append(dict(t=context['initial_zero_at'], kind='segment_start', side=side,
            identity=identity, initial_battle_start_visible=True, proof=proof))
        found = measured_impacts(rows, damaged_side='theirs' if side == 'mine' else 'mine',
            start=context['fast_only_interval'][0], end=context['fast_only_interval'][1], turns=move['turns'])
        detectors[side] = found
        missing = found['initial_unmeasured_completion_count_range']
        if missing[1]:
            observations.append(dict(t=found['initial_baseline']['t'], kind='gap', side=side,
                identity=identity, move_source_verified=True, may_contain_release=False,
                gain_per_completion=move['gain'], maximum_possible_completions=missing[1], proof=proof,
                uncertainty_reason='Left-censored baseline; optional completions, not invented measured attacks'))
        for impact in found['impacts']:
            observations.append(dict(t=impact['t'], kind='fast_complete', side=side, identity=identity,
                measured_completion=True, move_source_verified=True, gain=move['gain'], proof=proof))
    for charge in context['charged_releases']:
        observations.append(dict(t=charge['t'], kind='charged_release', side=charge['side'],
            identity=context['identities'][charge['side']], move_source_verified=True,
            cost=charge['cost'], proof=dict(basis='source_review', source_sha256=context['video_sha256'])))
    observations.sort(key=lambda e: (e['t'], e['side'], e['kind']))
    rebuilt = rebuild(observations)
    labels = json.loads(labels_path.read_text(encoding='utf8'))
    if sha(root / 'data/gamemaster.json') != labels['gamemaster_sha256']:
        raise ValueError('Pinned GameMaster changed')
    ledger = read_rows(root / context['baseline_continuity'])
    before, after = [], []
    for label in labels['windows']:
        side, t = label['side'], label['end_seconds']
        candidate_rows = [e for e in rebuilt['events'] if e['side'] == side and e['t'] <= t]
        candidate = expand(candidate_rows[-1]['after_ranges']) if candidate_rows else set()
        # Unobserved native gaps cannot support a narrow completion count.
        if any(a < t and b > context['fast_only_interval'][0] for a, b in detectors[side]['unobserved_gaps']):
            candidate = set(range(101))
        gain = context['moves'][side]['gain']
        before.append(point_score(side, t, baseline(ledger, side, t), label['energy_range'], gain))
        after.append(point_score(side, t, candidate, label['energy_range'], gain))
    readiness = root / 'runs/task46-readiness-development-v21j4.json'
    availability = json.loads(readiness.read_text(encoding='utf8'))['field_availability_weighted_by_seconds']
    return dict(schema='task46-standalone-energy-reference-pilot-v1', frozen_reader_modified=False,
        wider_replay_performed=False, promoted=False,
        original_frozen_reference_audit=audit_original_truth(root),
        original_30_battle_reader_availability=dict(
            mine=availability['mine.energy'], theirs=availability['opponent.energy'],
            report_sha256=sha(readiness), after='Unchanged: separate prototype has not been integrated or widely replayed'),
        supplemental=dict(record=labels['battle']['record'], channel=labels['battle']['channel'],
            labels_sha256=sha(labels_path), source_video_sha256=context['video_sha256'],
            scope='Conditional automated timing in a manually source-verified fast-only corridor, moves and initial zero; not whole-VOD state accuracy',
            manual_numeric_targets_used_as_inputs=False, source_groups=1, battles=1,
            before=score_points(before), after=score_points(after), before_points=before, after_points=after,
            detectors=detectors, accounting=rebuilt,
            source_assisted_inputs=['Move identities/gains verified from animation and pinned GameMaster',
                'Initial-zero countdown and uninterrupted active pair',
                'Fast-only interval excludes charged animation/impact and queued boundary outside corridor',
                'Named first release from separate source-only review; normal cost40'],
            limitations=['One development source, not independent human adjudication',
                'HP-drop threshold can miss small damage or fail under moving/occluded bars',
                'No arbitrary VOD moveset or phase attribution validation',
                'No exact energy claims from unknown queued completions or source gaps',
                'Interval containment is reported separately from useful coverage and exact accuracy']),
        reproducibility=dict(evaluator_sha256=sha(Path(__file__)),
            rebuilder_sha256=sha(Path(__file__).with_name('energy_rebuild.py')),
            context_sha256=hashlib.sha256(json.dumps(context, sort_keys=True).encode()).hexdigest(),
            native_measurements_sha256=sha(raw_path), baseline_continuity_sha256=sha(root / context['baseline_continuity'])))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path, required=True)
    ap.add_argument('--context', type=Path, required=True)
    ap.add_argument('--labels', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    result = evaluate(args.root, json.loads(args.context.read_text(encoding='utf8')), args.labels)
    args.out.write_text(json.dumps(result, indent=2) + '\n', encoding='utf8')
    print(json.dumps(result['supplemental']['after']))


if __name__ == '__main__': main()
