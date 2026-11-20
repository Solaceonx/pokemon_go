"""Reproduce the fixed three-channel energy pilot without changing its solver."""
import argparse
import itertools
import json
import math
from pathlib import Path

from energy_reference_eval import evaluate, score_points, sha


def interval_guarantees(report, moves):
    """A guarantee covers every possible target value, not its nearest point."""
    for stage in ['before', 'after']:
        for point in report['supplemental'][stage + '_points']:
            rr, target = point['predicted_ranges'], point['truth']
            gain = moves[point['side']]['gain']
            point['within_one_fast_guaranteed'] = bool(rr) and max(
                abs(rr[0][0] - target[1]), abs(rr[-1][1] - target[0])) <= gain
        report['supplemental'][stage] = score_points(report['supplemental'][stage + '_points'])


def cluster_margin(groups):
    """Exact empirical bootstrap over battle/source groups, not nested frames.

    Each pair is a numerator/denominator for one source. Undefined resamples
    remain counted separately; they are never treated as zero successes.
    """
    if len(groups) < 2:
        return dict(interval_95=None, reason='Insufficient independent source groups')
    scores, undefined = [], 0
    for indices in itertools.product(range(len(groups)), repeat=len(groups)):
        numerator = sum(groups[i][0] for i in indices)
        denominator = sum(groups[i][1] for i in indices)
        if denominator:
            scores.append(numerator / denominator)
        else:
            undefined += 1
    scores.sort()
    interval = None if not scores else [scores[max(0, math.ceil(.025 * len(scores)) - 1)],
                                        scores[max(0, math.ceil(.975 * len(scores)) - 1)]]
    return dict(interval_95=interval, source_groups=len(groups),
        enumerated_resamples=len(groups) ** len(groups), undefined_resamples=undefined,
        method='Exact enumeration of source-cluster resampling with replacement; empirical inverse-CDF percentiles',
        limitation='Tiny development sample; conditional on reviewed moves and corridors, not whole-VOD reliability')


def aggregate(reports, stage):
    points = [p for report in reports for p in report['supplemental'][stage + '_points']]
    result = score_points(points)
    for side, summary in result.items():
        source_summaries = [report['supplemental'][stage][side] for report in reports]
        summary.pop('group_bootstrap_95', None)
        summary.pop('margin_reason', None)
        summary['useful_coverage_source_bootstrap'] = cluster_margin(
            [(s['useful'], s['total']) for s in source_summaries])
        summary['exact_recovery_source_bootstrap'] = cluster_margin(
            [(s['exact_predictions_correct'], s['exact_numeric_truth']) for s in source_summaries])
        summary['conditional_exact_accuracy'] = dict(
            correct=sum(p['exact_correct'] for p in points if side == 'both' or p['side'] == side),
            covered_scalar_targets=sum(p['useful'] and p['truth'][0] == p['truth'][1]
                for p in points if side == 'both' or p['side'] == side),
            limitation='Coverage-conditioned small development count; intervals are not scalar exact truth')
    return result


def run(root, manifest):
    reports = []
    for item in manifest['sources']:
        context = json.loads((root / item['context']).read_text(encoding='utf8'))
        result = evaluate(root, context, root / item['labels'])
        interval_guarantees(result, context['moves'])
        # The v1 helper's prose was specific to AXN. Keep its frozen bytes and
        # replace only this description for the newly evaluated channels.
        result['supplemental']['source_assisted_inputs'] = [
            'Move identities/gains verified from animation and pinned GameMaster',
            'Initial-zero countdown and uninterrupted active pair',
            'Source-reviewed fast-only corridor; no numeric target counts supplied']
        if context['charged_releases']:
            result['supplemental']['source_assisted_inputs'].append(
                'Named source-verified charged release(s): ' + ', '.join(
                    q['move'] + ' cost' + str(q['cost']) for q in context['charged_releases']))
        reports.append(result)
    return dict(schema='task46-energy-three-channel-reference-v1',
        detector_and_solver_unchanged_after_axn=True, promoted=False, wider_replay=False,
        sources=len(reports), battles=len(reports),
        reference_scope='One short source-derived development battle per channel; AXN has eight nested points, Henry/Reis two each',
        original_frozen_numeric_accuracy=None,
        original_numeric_accuracy_reason='The original30 frozen clips contain no numeric energy targets; their labels are unchanged',
        before=aggregate(reports, 'before'), after=aggregate(reports, 'after'), channel_reports=reports,
        reproduction=dict(manifest=manifest, batch_sha256=sha(Path(__file__))))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding='utf8'))
    result = run(args.root, manifest)
    args.out.write_text(json.dumps(result, indent=2) + '\n', encoding='utf8')
    print(json.dumps(dict(before=result['before']['both'], after=result['after']['both'])))


if __name__ == '__main__': main()
