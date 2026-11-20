"""Transport observed own energy as expanding candidates, never a stale point."""
import math

from energy_bounds_v4 import button_values, corridor_gain
from energy_rebuild import ranges


def bank_from(values, context, side, start, end, *, boundary_allowance):
    move = context['moves'][side]
    intervals = context.get('fighting_intervals', [context['fast_only_interval']])
    previous = start
    for release in sorted(context['charged_releases'], key=lambda q: q['t']):
        if release['side'] != side or not start < release['t'] <= end:
            continue
        values = corridor_gain(values, intervals, previous, release['t'], move,
                               boundary_allowance=boundary_allowance)
        values = {v - release['cost'] for v in values if v >= release['cost']}
        # A pending completion can credit after the spend. In particular,
        # cap100 before a spend must not erase the possible post-spend gain.
        values |= {min(100, v + move['gain']) for v in values}
        previous = release['t']
    return corridor_gain(values, intervals, previous, end, move,
                         boundary_allowance=boundary_allowance)


def bound_at(context, side, t):
    initial = {0} if context.get('initial_zero_verified') is True else set(range(101))
    return bank_from(initial, context, side, context['initial_zero_at'], t,
                     boundary_allowance=True)


def estimate(context, side, t, controls=None, *, lookback_seconds=1.):
    candidates = bound_at(context, side, t)
    anchor_at = None
    if side == 'mine' and controls is not None and context.get('charge_button_costs'):
        for index in range(len(controls) - 1, 0, -1):
            row, previous = controls[index], controls[index - 1]
            if not 0 <= t - row['t'] <= lookback_seconds:
                continue
            if not 0 < row['t'] - previous['t'] <= .25:
                continue
            discs = row.get('controls', {}).get('discs', [])
            old = previous.get('controls', {}).get('discs', [])
            if len(discs) != len(old) or len(discs) != 2:
                continue
            anchored = bound_at(context, side, row['t'])
            for i, (disc, before) in enumerate(zip(discs, old)):
                a = button_values(disc, context['charge_button_costs'][i])
                b = button_values(before, context['charge_button_costs'][i])
                if (a is None or b is None or
                        abs(disc['measurement']['fill'] - before['measurement']['fill']) > .035):
                    anchored = None
                    break
                anchored &= a
            if anchored:
                transported = bank_from(anchored, context, side, row['t'], t,
                                        boundary_allowance=False)
                if candidates & transported:
                    candidates &= transported
                    anchor_at = row['t']
                    break
    return dict(integer_ranges=ranges(candidates), exact=len(candidates) == 1,
        status='contradictory' if not candidates else 'constrained',
        source='control_anchor_with_expanding_bank' if anchor_at is not None else 'optional_bank_only',
        anchor_at=anchor_at, anchor_age_seconds=t-anchor_at if anchor_at is not None else None,
        completion_count_measured=False, hp_drop_count_used=False,
        transported_energy_is_current_exact_observation=False,
        post_release_queued_credit_allowed=True, accuracy_verified=False)
