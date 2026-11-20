"""Standalone integer-energy accounting; does not modify the frozen reader.

Inputs are explicit source evidence, not assumed ranked moves or fitted clocks.
The fast-only HP-impact detector is experimental and requires a source-reviewed
uninterrupted matchup and identified move. It is not a general animation reader.
"""
from __future__ import annotations

import argparse
from collections import defaultdict, deque
import hashlib
import json
import math
from pathlib import Path
import statistics


def ranges(values):
    result = []
    for value in sorted(values):
        if result and value == result[-1][1] + 1:
            result[-1][1] = value
        else:
            result.append([value, value])
    return result


def integer(value, minimum=0, maximum=100):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError('Expected a legal integer energy/count')
    return value


def source_proof(event):
    proof = event.get('proof', {})
    if proof.get('basis') not in {'source_review', 'current_pixel_measurement'}:
        raise ValueError('Source proof required; fitted/assumed events are rejected')
    digest = proof.get('source_sha256', '')
    if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('Source SHA256 required')


def rebuild(events):
    """Causal candidates per side/identity, preserving noncontiguous sets.

    There are no automatic gains from elapsed time. Callers must insert explicit
    gap events for missing fighting; an animation hold changes nothing. Switches
    only change the active identity. A charge filters affordability then spends
    its cost, so a release never implies an empty meter. Contradictions remain
    empty until an explicitly documented new-segment event, never silently reset.
    """
    states = {}
    active = {}
    output = []
    last = (-math.inf, -1)
    for index, event in enumerate(events):
        t = event.get('t')
        if isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t):
            raise ValueError('Finite event time required')
        order = (t, event.get('sequence', index))
        if order <= last:
            raise ValueError('Explicit increasing time/sequence order required')
        last = order
        side, actor = event.get('side'), event.get('identity')
        if side not in {'mine', 'theirs'} or not isinstance(actor, str) or not actor:
            raise ValueError('Source side and stable identity required')
        source_proof(event)
        key = (side, actor)
        before = states.get(key, set(range(101)))
        after = set(before)
        kind = event['kind']
        if kind == 'switch':
            active[side] = actor
        elif kind == 'segment_start':
            if not event.get('initial_battle_start_visible'):
                raise ValueError('Clipped entries do not prove zero energy')
            if key in states:
                raise ValueError('Cannot restart an existing identity to clear a contradiction')
            after = {0}
            active[side] = actor
        elif kind == 'anchor':
            measured = {integer(v) for v in event['candidates']}
            after &= measured
        elif kind == 'fast_complete':
            if not event.get('move_source_verified') or not event.get('measured_completion'):
                raise ValueError('Both source-verified move and measured completion required')
            gain = integer(event['gain'], 1)
            lo, hi = [integer(v, 0, 1000) for v in event.get('count_range', [1, 1])]
            if lo > hi:
                raise ValueError('Reversed completion count')
            after = {min(100, value + gain * n) for value in before for n in range(lo, hi + 1)}
        elif kind == 'charged_release':
            if not event.get('move_source_verified') or event.get('meter', 'normal') != 'normal':
                raise ValueError('Named release and verified normal-energy cost required')
            cost = integer(event['cost'], 1)
            after = {value - cost for value in before if value >= cost}
        elif kind == 'gap':
            # Unknown intervening releases can spend any amount; do not preserve
            # an old lower bound across a truly censored interval.
            if event.get('may_contain_release', True):
                after = set(range(101)) if before else set()
            elif 'gain_per_completion' in event:
                if not event.get('move_source_verified'):
                    raise ValueError('Known fast gain required for an unmeasured gap')
                gain = integer(event['gain_per_completion'], 1)
                count = integer(event['maximum_possible_completions'], 0, 1000)
                after = {min(100, v + gain * n) for v in before for n in range(count + 1)}
            else:
                gain = integer(event.get('maximum_possible_gain', 100))
                after = {min(100, v + g) for v in before for g in range(gain + 1)}
        elif kind == 'animation_hold':
            pass
        else:
            raise ValueError('Unknown evidence event kind')
        states[key] = after
        output.append({'t': t, 'sequence': order[1], 'side': side, 'identity': actor,
                       'kind': kind, 'before_ranges': ranges(before),
                       'after_ranges': ranges(after), 'exact': len(after) == 1,
                       'status': 'contradictory' if not after else 'constrained',
                       'causal': True, 'accuracy_verified': False})
    return {'schema': 'standalone-energy-rebuild-v1', 'events': output,
            'active': active,
            'final': [{'side': side, 'identity': actor, 'integer_ranges': ranges(values)}
                      for (side, actor), values in states.items()],
            'continuous_state_certified': False}


def measured_impacts(rows, *, damaged_side, start, end, turns):
    """Measure current-pixel HP-drop times in an attested fast-only interval.

    A five-sample median rejects rail jitter. Each accepted lower plateau is a
    possible completed damaging fast move by the opposite side; timing is the
    measurement time, not a generated periodic schedule. No missing attack is
    inserted. This prototype cannot resolve invisible/minimal damage, buffs,
    healing, zero damage, simultaneous non-fast effects or attribution changes.
    """
    period = integer(turns, 1, 10) * .5
    window = deque(maxlen=5)
    baseline = None
    impacts = []
    last_valid = None
    gaps = []
    initial_unmeasured_completions = [0, 0]
    initial_baseline = None
    for row in rows:
        t = row['t']
        if not start <= t <= end:
            continue
        health = row.get('health', {}).get(damaged_side, {})
        bar = health.get('bar') or {}
        value = bar.get('fraction')
        # Wide/weak geometry is excluded rather than treated as a real drop.
        if (health.get('status') != 'observed' or bar.get('outline_method') != 'closed_physical_contour'
                or not isinstance(value, (int, float)) or not 0 <= value <= 1):
            continue
        if last_valid is not None and t - last_valid > .5:
            gaps.append([last_valid, t])
            window.clear()
        last_valid = t
        window.append((t, value))
        if len(window) < 5 or window[-1][0] - window[0][0] > .5:
            continue
        value = statistics.median(v for _, v in window)
        if baseline is None:
            baseline = value
            initial_baseline = {'t': t, 'fraction': value,
                                'window': [window[0][0], t]}
            if value < .99:
                # The first readable plateau is already damaged: an attack may
                # have completed before this detector acquired a baseline.
                # Bound missing completions by duration plus one in-flight
                # move, never insert the source-labelled missing count.
                initial_unmeasured_completions = [0, math.ceil((t - start) / period) + 1]
        elif value < baseline - .025 and (not impacts or t - impacts[-1]['t'] >= period * .6):
            impacts.append({'t': t, 'previous_fraction': baseline,
                            'fraction': value, 'measurement_window': [window[0][0], t]})
            baseline = value
    return {'impacts': impacts, 'unobserved_gaps': gaps,
            'initial_baseline': initial_baseline,
            'initial_unmeasured_completion_count_range': initial_unmeasured_completions,
            'method': 'five_current_pixel_samples_new_lower_plateau',
            'damaged_side': damaged_side, 'threshold_fraction': .025,
            'automated': True, 'manual_target_counts_used': False,
            'accuracy_verified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('evidence', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    raw = args.evidence.read_bytes()
    result = rebuild(json.loads(raw)['events'])
    result['input_sha256'] = hashlib.sha256(raw).hexdigest()
    result['code_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    args.out.write_text(json.dumps(result, indent=2) + '\n', encoding='utf8')


if __name__ == '__main__':
    main()
