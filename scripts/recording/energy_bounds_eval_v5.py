"""Separate candidate containment, exact recovery and availability for v5."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path

from energy_bounds_v5 import estimate
from energy_bounds_v4 import read_rows
from energy_reference_batch import cluster_margin
from energy_reference_eval import expand, sha


def compare(candidates, target):
    if target is None:
        return dict(scorable=False, scalar=None, useful=False, scalar_truth_contained=None,
            exact_scalar_recovered=None, interval_fully_contained=None, overlap=None,
            prediction_within_reference=None, disjoint_narrow=False)
    truth = set(range(target[0], target[1] + 1))
    scalar = len(truth) == 1
    useful = bool(candidates) and max(candidates) - min(candidates) <= 15
    return dict(scorable=True, scalar=scalar, useful=useful,
        scalar_truth_contained=scalar and truth <= candidates,
        exact_scalar_recovered=scalar and len(candidates) == 1 and truth == candidates,
        interval_fully_contained=not scalar and truth <= candidates,
        overlap=bool(candidates & truth),
        prediction_within_reference=bool(candidates) and candidates <= truth,
        disjoint_narrow=useful and not bool(candidates & truth))


def summary(records, variant):
    result = {}
    for side in ['mine', 'theirs', 'both']:
        points = [p for r in records for p in r[variant] if side == 'both' or p['side'] == side]
        groups = defaultdict(lambda: [0, 0])
        for record in records:
            for point in record[variant]:
                if side == 'both' or point['side'] == side:
                    groups[record['source_vod']][0] += point['useful']
                    groups[record['source_vod']][1] += 1
        result[side] = dict(attempted=len(points), labelled=sum(p['scorable'] for p in points),
            unscorable=sum(not p['scorable'] for p in points),
            useful=sum(p['useful'] for p in points),
            useful_fraction=sum(p['useful'] for p in points) / len(points) if points else None,
            scalar_targets=sum(p['scalar'] is True for p in points),
            scalar_truth_contained=sum(p['scalar_truth_contained'] is True for p in points),
            exact_scalar_recovered=sum(p['exact_scalar_recovered'] is True for p in points),
            interval_targets=sum(p['scalar'] is False for p in points),
            interval_fully_contained=sum(p['interval_fully_contained'] is True for p in points),
            candidate_set_overlaps_reference=sum(p['overlap'] is True for p in points),
            prediction_entirely_within_reference=sum(p['prediction_within_reference'] is True for p in points),
            false_confident_disjoint_narrow=sum(p['disjoint_narrow'] for p in points),
            coverage_source_bootstrap=cluster_margin(list(groups.values())))
    return result


def evaluate(root, manifest):
    original = json.loads((root / 'data/creator_ground_truth_v1.json').read_text())
    sources = {b['record']: b['source']['source_url'] for b in original['battles']}
    records = []
    for item in manifest['sources']:
        labelpath = root / item['labels']
        labels = json.loads(labelpath.read_text(encoding='utf8'))
        controls, context = None, None
        if not item.get('unscorable'):
            context = json.loads((root / item['base_context']).read_text(encoding='utf8'))
            context['initial_zero_verified'] = item.get('initial_zero_verified') is True
            context['charge_button_costs'] = item['charge_button_costs']
            controls = read_rows(root / item['controls'])
        record = dict(channel=labels['battle']['channel'], record=labels['battle']['record'],
            source_vod=sources[labels['battle']['record']], labels_sha256=sha(labelpath),
            bounds_only=[], controls_and_bounds=[])
        for target in labels['windows']:
            side, t = target['side'], target['end_seconds']
            for variant, rows in [('bounds_only', None), ('controls_and_bounds', controls)]:
                predicted = estimate(context, side, t, rows) if context else dict(
                    integer_ranges=[], status='unknown', source='unscorable_entry', exact=False)
                point = dict(side=side, t=t, truth=target['energy_range'], prediction=predicted,
                    **compare(expand(predicted['integer_ranges']), target['energy_range']))
                record[variant].append(point)
        records.append(record)
    return dict(schema='energy-v5-transported-controls-development-v1', promoted=False, wider_replay=False,
        evaluation_scope=manifest.get('target_set'),
        frozen_reader_modified=False, original_v1_v2_v3_artifacts_modified=False,
        no_hp_delta_counting=True, control_input_source='Existing frozen reader numerical pixel measurements, independent from HP; moves/corridors source-verified',
        bounds_only=summary(records, 'bounds_only'), controls_and_bounds=summary(records, 'controls_and_bounds'),
        records=records,
        distinctions=['Scalar contained in a candidate set is valid uncertainty, distinct from exact recovery',
            'Interval fully contained, overlap, and predicted set inside annotation are distinct metrics',
            'Optional fast completions are only legal upper bounds, never reported as measured attacks',
            'Narrow disjoint sets identify false confidence; broad valid uncertainty is not a wrong exact prediction',
            'These are source-derived windows from permitted development VODs, not independent whole-VOD validation'],
        reproduction=dict(manifest=manifest, evaluator_sha256=sha(Path(__file__)),
            bounds_sha256=sha(Path(__file__).with_name('energy_bounds_v5.py'))))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = evaluate(args.root, json.loads(args.manifest.read_text(encoding='utf8')))
    args.out.write_text(json.dumps(result, indent=2) + '\n', encoding='utf8')
    print(json.dumps(dict(bounds_only=result['bounds_only']['both'], controls_and_bounds=result['controls_and_bounds']['both'])))


if __name__ == '__main__': main()
