"""Independent fast-gain intervals from integer own controls and known spends."""
import argparse
import hashlib
import json
from pathlib import Path

from energy_bounds_v4 import button_values, exposure
from energy_bounds_v4 import read_rows
from energy_bounds_v5 import bound_at


def gain_count(before, after, cost, gain, *, possible_cap=False):
    amount = after - before + cost
    if amount < 0 or amount % gain:
        return dict(status='contradictory', count=None)
    return dict(status='lower_bound_only' if possible_cap else 'measured_aggregate_gain',
                count=None if possible_cap else amount // gain, minimum_count=amount // gain)


def increments(context, controls):
    if context.get('initial_zero_verified') is not True:
        return dict(events=[], gaps=[dict(reason='Initial energy unresolved')])
    intervals = context.get('fighting_intervals', [context['fast_only_interval']])
    previous = dict(energy=0, first=context['initial_zero_at'], last=context['initial_zero_at'],
                    source='visible_initial_zero')
    events, gaps, anchors = [], [], []
    gain = context['moves']['mine']['gain']
    for index in range(1, len(controls)):
        row, before = controls[index], controls[index-1]
        if row['t'] < context['initial_zero_at'] or not 0 < row['t']-before['t'] <= .25:
            continue
        if not any(lo <= before['t'] <= row['t'] <= hi for lo, hi in intervals):
            continue
        discs, old = row.get('controls', {}).get('discs', []), before.get('controls', {}).get('discs', [])
        if len(discs) != len(old) or len(discs) != 2:
            continue
        candidates = bound_at(context, 'mine', row['t'])
        for i, (disc, prior) in enumerate(zip(discs, old)):
            current, past = button_values(disc, context['charge_button_costs'][i]), button_values(prior, context['charge_button_costs'][i])
            if current is None or past is None or abs(disc['measurement']['fill']-prior['measurement']['fill']) > .035:
                candidates = set(); break
            candidates &= current
        if len(candidates) != 1:
            continue
        energy = next(iter(candidates))
        anchors.append(dict(t=row['t'], energy=energy))
        if previous is not None and energy == previous['energy']:
            previous['last'] = row['t']; continue
        if previous is not None:
            releases = [q for q in context['charged_releases'] if q['side']=='mine' and previous['last'] < q['t'] <= row['t']]
            cost = sum(q['cost'] for q in releases)
            checkpoints = [previous['last'], row['t']] + [q['t']-1e-6 for q in releases]
            cap = any(max(bound_at(context, 'mine', t), default=100) >= 100 for t in checkpoints)
            measured = gain_count(previous['energy'], energy, cost, gain, possible_cap=cap)
            if measured['status'] == 'contradictory':
                gaps.append(dict(window=[previous['last'], row['t']], reason='Control/cost gain inconsistent'))
            elif measured['minimum_count']:
                window = [previous['last'], row['t']]
                events.append(dict(side='mine', kind='control_energy_gain', window=window,
                    before=previous['energy'], after=energy, known_spend=cost, gain_per_fast=gain,
                    fighting_seconds=exposure(intervals, *window),
                    individual_completion_timestamps_known=False, hp_used=False, **measured))
        previous = dict(energy=energy, first=row['t'], last=row['t'], source='settled_integer_controls')
    return dict(events=events, gaps=gaps, anchors=anchors,
        interpretation='Positive integer gains plus named spends measure aggregate completions; no individual times inserted in gaps',
        exact_game_credit_phase_verified=False, accuracy_verified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    inputs = json.loads(args.inputs.read_text(encoding='utf8'))
    records = []
    for item in inputs['sources']:
        labels = json.loads((args.root/item['labels']).read_text(encoding='utf8'))
        if item.get('unscorable'):
            records.append(dict(record=labels['battle']['record'], unscorable=True))
            continue
        context = json.loads((args.root/item['base_context']).read_text(encoding='utf8'))
        context['initial_zero_verified'] = item.get('initial_zero_verified') is True
        context['charge_button_costs'] = item['charge_button_costs']
        control_path = args.root/item['controls']
        records.append(dict(record=labels['battle']['record'],
            controls_sha256=hashlib.sha256(control_path.read_bytes()).hexdigest(),
            measurement=increments(context, read_rows(control_path))))
    result = dict(schema='own-control-positive-fast-gain-v6', scope=inputs['target_set'],
        manual_target_counts_used=False, records=records,
        code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    args.out.write_text(json.dumps(result, indent=2)+'\n', encoding='utf8')
    print(json.dumps(dict(records=len(records), positive_intervals=sum(
        len(r.get('measurement', {}).get('events', [])) for r in records))))


if __name__ == '__main__': main()
