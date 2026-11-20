"""Experimental energy bounds: no detected damage never proves zero attacks.

Only optional completion bounds come from active fighting time. Current own
charge controls may constrain energy directly; HP impacts are not fast-count
observations. The frozen reader and earlier energy implementations are untouched.
"""
import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path

from energy_rebuild import ranges


def exposure(intervals, start, end):
    return sum(max(0., min(end, hi) - max(start, lo)) for lo, hi in intervals)


def optional_completions(values, seconds, *, gain, period, initial_pending=False):
    if seconds < 0 or gain <= 0 or period <= 0:
        raise ValueError('Invalid fighting time or move')
    maximum = math.ceil(seconds / period) + int(initial_pending) if seconds > 0 else 0
    return {min(100, value + gain * n) for value in values for n in range(maximum + 1)}


def corridor_gain(values, intervals, start, end, move, *, boundary_allowance=True):
    maximum = 0
    for lo, hi in intervals:
        seconds = max(0., min(end, hi) - max(start, lo))
        if seconds:
            maximum += math.ceil(seconds / (move['turns'] * .5)) + int(boundary_allowance)
    return {min(100, value + move['gain'] * n) for value in values for n in range(maximum + 1)}


def bound_at(context, side, t):
    """Legal candidates from visible initial zero and named release bank.

    A source-reviewed fighting corridor is an upper bound, never a measured
    attack count. Charged minigame/impact holds outside the corridor add no time.
    An extra initial pending completion is allowed conservatively. Bench/actor
    attribution is supplied by source context; unresolved entries are abstained.
    """
    move = context['moves'][side]
    intervals = context.get('fighting_intervals', [context['fast_only_interval']])
    values = {0} if context.get('initial_zero_verified') is True else set(range(101))
    previous = context['initial_zero_at']
    for release in sorted(context['charged_releases'], key=lambda x: x['t']):
        if release['side'] != side or release['t'] > t:
            continue
        values = corridor_gain(values, intervals, previous, release['t'], move)
        values = {value - release['cost'] for value in values if value >= release['cost']}
        previous = release['t']
    return corridor_gain(values, intervals, previous, t, move)


def button_values(disc, cost, tolerance=.08):
    measure = disc.get('measurement', {})
    if (disc.get('status') != 'observed' or not measure.get('present')
            or measure.get('rim', 0) < .75 or measure.get('lopsided', 1) >= .08):
        return None
    white = disc.get('white_rim_fraction')
    ready = True if disc.get('ready') is True else False if white is not None and white <= .05 else None
    # Decorated/ambiguous ready discs have an unvalidated liquid-height map.
    # Abstain instead of interpreting the icon as an energy surface.
    if ready is None:
        return None
    fill = measure.get('fill')
    if not isinstance(fill, (int, float)) or not 0 <= fill <= 1:
        return None
    candidates = set()
    for value in range(101):
        if ready != (value >= cost):
            continue
        levels = [min(1., value / cost)]
        if value >= cost:
            levels.append(min(1., (value - cost) / cost))
        if min(abs(fill - level) for level in levels) <= tolerance:
            candidates.add(value)
    return candidates


def control_anchor(rows, costs, context, t):
    eligible = [row for row in rows if 0 <= t - row['t'] <= .25]
    for row in reversed(eligible):
        index = rows.index(row)
        if index == 0:
            continue
        before = rows[index - 1]
        if not 0 < row['t'] - before['t'] <= .25:
            continue
        discs = row.get('controls', {}).get('discs', [])
        old = before.get('controls', {}).get('discs', [])
        if len(discs) != len(old) or len(discs) != 2:
            continue
        candidates = bound_at(context, 'mine', row['t'])
        for i, (disc, previous) in enumerate(zip(discs, old)):
            a, b = button_values(disc, costs[i]), button_values(previous, costs[i])
            if (a is None or b is None
                    or abs(disc['measurement']['fill'] - previous['measurement']['fill']) > .035):
                candidates = None
                break
            candidates &= a
        if candidates:
            return dict(t=row['t'], values=candidates,
                method='two_settled_current_controls_intersect_optional_integer_bank')
    return None


def estimate(context, side, t, controls=None):
    candidates = bound_at(context, side, t)
    anchor = None
    if side == 'mine' and controls is not None and context.get('charge_button_costs'):
        anchor = control_anchor(controls, context['charge_button_costs'], context, t)
        if anchor:
            move = context['moves'][side]
            intervals = context.get('fighting_intervals', [context['fast_only_interval']])
            candidates &= optional_completions(anchor['values'], exposure(intervals, anchor['t'], t),
                gain=move['gain'], period=move['turns'] * .5)
    return dict(integer_ranges=ranges(candidates),
        status='contradictory' if not candidates else 'constrained',
        exact=len(candidates) == 1,
        source='own_current_controls_and_optional_bank' if anchor else 'optional_bank_only',
        anchor_at=anchor['t'] if anchor else None,
        completion_count_measured=False, hp_drop_count_used=False,
        accuracy_verified=False)


def read_rows(path):
    with gzip.open(path, 'rt', encoding='utf8') as handle:
        return [json.loads(line) for line in handle if line.strip()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context', type=Path, required=True)
    parser.add_argument('--side', choices=['mine', 'theirs'], required=True)
    parser.add_argument('--at', type=float, required=True)
    parser.add_argument('--controls', type=Path)
    args = parser.parse_args()
    context = json.loads(args.context.read_text(encoding='utf8'))
    print(json.dumps(estimate(context, args.side, args.at,
        read_rows(args.controls) if args.controls else None)))


if __name__ == '__main__': main()
