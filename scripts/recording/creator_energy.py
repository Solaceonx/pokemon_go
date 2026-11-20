"""Integer energy constraints; never substitute an assumed fast move or IVs."""
import math


def button_candidates(fill, cost, *, ready=None, uncertainty=.06):
    """All legal energy integers consistent with a measured button fill.

    A ready button can show its first complete helping or its second fill.
    Near-full fills therefore supply a lower bound, not exact energy.
    Geometry/animation error is an explicit fraction of one helping.
    """
    if not isinstance(cost, (int, float)) or cost <= 0 or not 0 <= fill <= 1:
        raise ValueError('Expected a legal positive cost and a fill fraction')
    result = set()
    for energy in range(101):
        if ready is True and energy < cost:
            continue
        if ready is False and energy >= cost:
            continue
        levels = [min(1., energy/cost)]
        if energy >= cost:
            levels.append(min(1., (energy-cost)/cost))
        if min(abs(shown-fill) for shown in levels) <= uncertainty:
            result.add(energy)
    return result


def intersect_buttons(buttons, uncertainty=.06):
    """Return a union of integer ranges, keeping contradictions explicit."""
    candidates = set(range(101))
    used = 0
    for b in buttons:
        if not b.get('observed') or b.get('cost') is None:
            continue
        candidates &= button_candidates(b['fill'], b['cost'], ready=b.get('ready'), uncertainty=uncertainty)
        used += 1
    ranges = []
    for value in sorted(candidates):
        if ranges and value == ranges[-1][1]+1:
            ranges[-1][1] = value
        else:
            ranges.append([value, value])
    return {'status': 'constrained' if used and candidates else 'contradictory' if used else 'unknown',
            'integer_ranges': ranges, 'independent_buttons': used,
            'fill_uncertainty': uncertainty, 'exact': used > 0 and len(candidates) == 1}


def legal_transition(ranges, *, elapsed_seconds, fast_options, charged_cost=None,
                     confirmed_fast_count=0):
    """Conservative causal bounds when move timing is not fully observed.

    No attack is forced merely because time passed. The upper bound allows a
    pending fast move to complete immediately. Charged animations must be
    removed from elapsed attacking time by the caller; switch cooldown uses
    wall time separately.
    """
    if elapsed_seconds < 0 or confirmed_fast_count < 0:
        raise ValueError('Negative elapsed time or attack count')
    if not ranges:
        return []
    if not fast_options:
        return [[0, 100]]
    gain_hi = max((math.ceil(elapsed_seconds/(o['turns']*.5))+1)*o['energy'] for o in fast_options)
    gain_lo = min(o['energy'] for o in fast_options)*confirmed_fast_count
    cost = charged_cost or 0
    low = max(0, min(r[0] for r in ranges)+gain_lo-cost)
    high = min(100, max(r[1] for r in ranges)+gain_hi-cost)
    return [[low, high]] if low <= high else []
