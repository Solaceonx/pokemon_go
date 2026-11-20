"""Fixed-solver six-reference evaluation, retaining unscorable attempts."""
import argparse
from collections import defaultdict
import json
from pathlib import Path

from energy_reference_batch import cluster_margin, interval_guarantees
from energy_reference_eval import evaluate, sha


def grouped_counts(reports, stage, side, numerator, denominator):
    groups = defaultdict(lambda: [0, 0])
    for report in reports:
        for point in report[stage + '_points']:
            if side == 'both' or point['side'] == side:
                groups[report['source_vod']][0] += bool(numerator(point))
                groups[report['source_vod']][1] += bool(denominator(point))
    return list(groups.values())


def summarize(reports, stage):
    result = {}
    for side in ['mine', 'theirs', 'both']:
        points = [p for report in reports for p in report[stage + '_points']
                  if side == 'both' or p['side'] == side]
        labelled = [p for p in points if p.get('truth') is not None]
        useful = [p for p in labelled if p['useful']]
        scalar = [p for p in labelled if p['truth'][0] == p['truth'][1]]
        false_confident = [p for p in useful if not p['overlaps']]
        result[side] = dict(attempted_windows=len(points), evaluable_numeric_windows=len(labelled),
            unscorable_windows=len(points) - len(labelled), useful_predictions=len(useful),
            useful_coverage_all_attempts=len(useful) / len(points) if points else None,
            useful_coverage_evaluable=len(useful) / len(labelled) if labelled else None,
            scalar_numeric_targets=len(scalar), exact_scalar_recovered=sum(p['exact_correct'] for p in scalar),
            covered_scalar_targets=sum(p['useful'] for p in scalar),
            covered_scalar_exact_correct=sum(p['exact_correct'] for p in scalar if p['useful']),
            covered_predictions_within_source_bounds=sum(p['prediction_within_reference'] for p in useful),
            covered_source_bound_denominator=len(useful), false_confident_predictions=false_confident,
            coverage_source_bootstrap=cluster_margin(grouped_counts(reports, stage, side,
                lambda p: p['useful'], lambda p: True)),
            exact_recovery_source_bootstrap=cluster_margin(grouped_counts(reports, stage, side,
                lambda p: bool(p.get('exact_correct')),
                lambda p: p.get('truth') is not None and p['truth'][0] == p['truth'][1])))
    return result


def run(root, manifest):
    original = json.loads((root / 'data/creator_ground_truth_v1.json').read_text(encoding='utf8'))
    sources = {b['record']: b['source']['source_url'] for b in original['battles']}
    reports = []
    for item in manifest['sources']:
        labels_path = root / item['labels']
        if item.get('unscorable'):
            labels = json.loads(labels_path.read_text(encoding='utf8'))
            windows = [dict(side=w['side'], t=w['end_seconds'], truth=None, predicted_ranges=[],
                useful=False, exact_correct=None, prediction_within_reference=None, overlaps=None,
                reason=w['reason']) for w in labels['windows']]
            record = labels['battle']['record']
            report = dict(channel=labels['battle']['channel'], record=record,
                labels_sha256=sha(labels_path), before_points=windows, after_points=windows,
                detector_run=False, reason='Initial balance unresolved; no assumed incoming zero')
        else:
            context = json.loads((root / item['context']).read_text(encoding='utf8'))
            evaluated = evaluate(root, context, labels_path)
            interval_guarantees(evaluated, context['moves'])
            report = evaluated['supplemental']
            record = report['record']
            report['source_assisted_inputs'] = ['Source-verified moves/initial zero and fast-only corridor; no numeric target counts supplied']
            if context['charged_releases']:
                report['source_assisted_inputs'].append('Source-verified named release/cost anchors; no meter reset')
            report['input_provenance'] = evaluated['reproducibility']
        if record not in sources:
            raise ValueError('Only the original frozen six reference records are permitted')
        report['source_vod'] = sources[record]
        reports.append(report)
    return dict(schema='task46-energy-six-original-reference-v1',
        reader_frozen=True, solver_and_timing_thresholds_unchanged_after_axn=True,
        promoted=False, wider_replay=False, original_frozen_numeric_accuracy=None,
        original_numeric_accuracy_reason='Original event/state references have no numeric energy targets; separate source-derived supplemental labels are development evidence',
        reference_records=len(reports), source_vod_groups=len({r['source_vod'] for r in reports}),
        source_group_rule='Exact original reference.source.source_url; coalesce all clips sharing the same VOD',
        before=summarize(reports, 'before'), after=summarize(reports, 'after'), records=reports,
        interpretation=['Coverage includes all requested attempts, including explicitly unscorable windows',
            'Exact numeric accuracy applies only to scalar source-derived truth, not interval compatibility',
            'Source-bound compatibility of interval labels does not prove their exact hidden value',
            'Native physical-bar gaps and missed small impacts cause abstentions and false confident zeros',
            'Small assistant-reviewed development windows, not independently human adjudicated whole-VOD accuracy'],
        reproduction=dict(manifest=manifest, wrapper_sha256=sha(Path(__file__))))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = run(args.root, json.loads(args.manifest.read_text(encoding='utf8')))
    args.out.write_text(json.dumps(result, indent=2) + '\n', encoding='utf8')
    print(json.dumps(dict(before=result['before']['both'], after=result['after']['both'])))


if __name__ == '__main__': main()
