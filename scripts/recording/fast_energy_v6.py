"""Diagnostic counted-VFX energy; never promoted as calibrated game state.

Gesture counts are measured pixels, but missing gestures and the VFX-to-energy
phase are not resolved. The point diagnostic is deliberately separate from
conservative candidates and is ineligible for full-state analysis.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path

from energy_bounds_v4 import read_rows
from energy_bounds_v5 import estimate
from energy_bounds_eval_v4 import compare
from energy_reference_eval import expand
from fast_vfx_v6 import gestures


def counted_hypothesis(context, side, t, events, *, initial_sequence_assumed_complete):
    if context.get('initial_zero_verified') is not True:
        return dict(value=None, status='unresolved', usable_for_fullstate=False,
            reason='Initial energy is not source-verified; do not assume zero')
    measured = [e for e in events if e['side'] == side and e['t'] <= t]
    if not initial_sequence_assumed_complete or not measured:
        return dict(value=None, status='unresolved', usable_for_fullstate=False,
            reason='No attributed gestures or initial observation prefix is incomplete; do not fabricate zero')
    bank, gain = 0, context['moves'][side]['gain']
    steps = [(e['t'], 'fast', gain) for e in measured]
    steps += [(e['t'], 'spend', e['cost']) for e in context['charged_releases']
              if e['side'] == side and e['t'] <= t]
    for at, kind, amount in sorted(steps):
        if kind == 'fast':
            bank = min(100, bank + amount)
        elif bank >= amount:
            bank -= amount
        else:
            return dict(value=None, status='contradictory', usable_for_fullstate=False,
                reason='Measured gesture bank cannot afford the named release; missing observations remain unresolved')
    return dict(value=bank, status='uncalibrated_diagnostic', usable_for_fullstate=False,
        attributed_gestures=len(measured), energy_credit_phase_verified=False,
        assumes_no_missing_initial_gestures=True,
        assumes_one_grouped_gesture_per_fast=True,
        completion_time_rule='VisiblegestureonsetusedONLYfordiagnostic;notverifiedenergycredit',
        absence_of_gestures_never_becomes_exact_zero=True)


def evaluate(root, inputs, model_path, feature_manifest):
    model = json.loads(model_path.read_text(encoding='utf8'))
    measured_rows = {}
    for record, item in feature_manifest['records'].items():
        rows = []
        for name in item['features']:
            rows += read_rows(root / name)
        rows.sort(key=lambda r: r['t'])
        measured_rows[record] = rows
    records = []
    for item in inputs['sources']:
        labels = json.loads((root / item['labels']).read_text(encoding='utf8'))
        record = labels['battle']['record']
        context, controls = None, None
        if not item.get('unscorable'):
            context = json.loads((root / item['base_context']).read_text(encoding='utf8'))
            context['initial_zero_verified'] = item.get('initial_zero_verified') is True
            context['charge_button_costs'] = item['charge_button_costs']
            controls = read_rows(root / item['controls'])
        points = []
        for label in labels['windows']:
            side, t, target = label['side'], label['end_seconds'], label['energy_range']
            safe = estimate(context, side, t, controls) if context else dict(integer_ranges=[], status='unknown')
            causal_events = []
            for m in model['models']:
                if m['record'] == record:
                    causal_events += gestures([row for row in measured_rows.get(record, []) if row['t'] <= t], m)['events']
            h = counted_hypothesis(context, side, t, causal_events,
                initial_sequence_assumed_complete=feature_manifest['records'].get(record, {}).get('initial_sequence_assumed_complete', False)) if context else dict(value=None, usable_for_fullstate=False, status='unknown')
            points.append(dict(side=side, t=t, truth=target, conservative=safe,
                conservative_comparison=compare(expand(safe['integer_ranges']), target),
                vfx_point_diagnostic=h,
                diagnostic_comparison=compare({h['value']} if h['value'] is not None else set(), target)))
        records.append(dict(record=record, points=points))
    all_points = [p for r in records for p in r['points']]
    provided = [p for p in all_points if p['vfx_point_diagnostic']['value'] is not None]
    return dict(schema='v6-measured-vfx-energy-diagnostic-v1', scope=inputs['target_set'],
        attempted_points=len(all_points), labelled=sum(p['truth'] is not None for p in all_points),
        conservative_useful=sum(p['conservative_comparison']['useful'] for p in all_points),
        vfx_accepted_fullstate_points=0,
        diagnostic_point_provided=len(provided),
        diagnostic_scalar_exact_matches=sum(p['diagnostic_comparison']['exact_scalar_recovered'] is True for p in all_points),
        diagnostic_source_bound_compatible=sum(p['diagnostic_comparison']['prediction_within_reference'] is True for p in provided),
        diagnostic_source_bound_denominator=len(provided), records=records,
        warnings=['Point diagnostics are NOT calibrated usable energy or full-state certification',
            'Broad source intervals can hide a missed8energyPeck; compatibility is not exact accuracy',
            'NoHPdeltaattackcounts, noelapsed-timeinventedmoves, nozeroopponentenergyfromabsentVFX',
            'Knownmoves/camera/initialzero/releasecosts are source-assisted',
            'FrozenV1–V5 reader/data/artifacts unchanged; no82replay or integration'],
        promoted=False, energy_credit_calibrated=False,
        reproduction=dict(inputs=inputs, features=feature_manifest,
            model_sha256=hashlib.sha256(model_path.read_bytes()).hexdigest(),
            estimator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--features', type=Path, required=True)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = evaluate(args.root, json.loads(args.inputs.read_text(encoding='utf8')),
        args.model, json.loads(args.features.read_text(encoding='utf8')))
    args.out.write_text(json.dumps(result, indent=2)+'\n', encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k not in {'records','reproduction','warnings'}}))


if __name__ == '__main__': main()
