"""Interpret measured creator pixels without substituting model guesses.

Each observation carries its source time. Unreadable values stay unknown;
counter contradictions and gaps remain explicit. This stage does not consume
reference labels or game outcomes to manufacture state.
"""
import itertools
import json
import math


def glyph_row(panel):
    """Find three party glyphs and two shield glyphs, with their group gap."""
    if panel['background_value_median'] < 180:
        return None
    glyphs = panel['glyphs']
    choices = []
    for row in itertools.combinations(glyphs[:18], 5):
        xs = [(g['bounds'][0]+g['bounds'][2])/2 for g in row]
        ys = [(g['bounds'][1]+g['bounds'][3])/2 for g in row]
        gaps = [b-a for a, b in zip(xs, xs[1:])]
        if min(gaps) < 16 or max(gaps) > 46 or max(ys)-min(ys) > 7:
            continue
        mine = sum(xs)/5 < 254
        party_gaps = gaps[:2] if mine else gaps[2:]
        shield_gap, group_gap = (gaps[3], gaps[2]) if mine else (gaps[0], gaps[1])
        mean = sum(party_gaps)/2
        uneven = abs(party_gaps[0]-party_gaps[1])/mean
        if uneven > .25 or not .6 <= shield_gap/mean <= 1.2 or not .8 <= group_gap/mean <= 1.8:
            continue
        score = uneven+.15*abs(shield_gap/mean-.86)+.1*abs(group_gap/mean-1.35)
        choices.append((score, -sum(ys)/5, row))
    if not choices:
        return None
    choices.sort(key=lambda x: x[:2])
    return list(choices[0][2])


def classify_headers(panels):
    choices = {'mine': [], 'theirs': []}
    for panel in panels:
        row = glyph_row(panel)
        if row is None:
            continue
        x = sum((g['bounds'][0]+g['bounds'][2])/2 for g in row)/5
        side = 'mine' if x < 254 else 'theirs'
        party, shields = (row[:3], row[3:]) if side == 'mine' else (row[2:], row[:2])
        def active(g, color):
            pixels = g[color+'_pixels']
            if color == 'purple' and g['dark_pixels'] >= g['area']*.45 and pixels < g['area']*.18:
                return False
            if pixels >= max(4, g['area']*.06):
                return True
            if pixels < max(2, g['area']*.03) and g['dark_pixels'] >= g['area']*.3:
                return False
            return None
        p = [active(g, 'red') for g in party]
        s = [active(g, 'purple') for g in shields]
        choices[side].append({'party': sum(p) if None not in p else None,
                              'shields': sum(s) if None not in s else None,
                              'panel_bounds': panel['bounds'],
                              'glyph_bounds': [g['bounds'] for g in row],
                              'geometry_source': panel.get('geometry_source', 'pale_component')})
    result = {}
    for side, found in choices.items():
        result[side] = {}
        for field in ['party', 'shields']:
            values = {r[field] for r in found if r[field] is not None}
            result[side][field] = {'value': next(iter(values)) if len(values) == 1 else None,
                                   'status': 'observed' if len(values) == 1 else 'contradictory' if values else 'unknown'}
        result[side]['panels'] = found
    return result


def stable_counter_runs(readings, side, field, required=3, max_gap=.25):
    """Keep first-visible and confirmation time; do not hide counter increases."""
    result, run, value = [], [], None
    for r in readings:
        current = r.get('headers',{}).get(side,{}).get(field,{}).get('value')
        if current is None:
            run, value = [], None
            continue
        if current != value or (run and r['t']-run[-1]['t'] > max_gap):
            run = []
        run.append(r); value = current
        if len(run) == required and (not result or value != result[-1]['value']):
            result.append({'first_visible_seconds': run[0]['t'], 'confirmed_seconds': r['t'],
                           'value': value, 'source_pts': run[0]['source_pts'],
                           'source_time_base': run[0]['source_time_base'],
                           'continuity': 'increase_requires_review' if result and value > result[-1]['value'] else 'consistent'})
        if len(run) >= required and result and result[-1]['value'] == value:
            result[-1]['last_visible_seconds'] = r['t']
            result[-1]['last_source_pts'] = r['source_pts']
    return result


def interpret_measurements(native):
    result = []
    for r in native:
        result.append({**r, 'headers': classify_headers(r['header_panels'])})
    counters = {side: {field: stable_counter_runs(result, side, field)
                       for field in ['party', 'shields']} for side in ['mine', 'theirs']}
    return result, counters


def match_header_counts(counters, side, field, at, *, confirmed_only=True):
    key = 'confirmed_seconds' if confirmed_only else 'first_visible_seconds'
    seen = [r for r in counters[side][field] if r[key] <= at]
    return seen[-1] if seen else None


def health_owners(row, timeline):
    """Associate a center camera bar only when its charged phase identifies it."""
    result = {side: row['health'][side]['bar'] if row['health'][side]['status'] == 'observed' else None
              for side in ['mine', 'theirs']}
    center = row['health']['center']
    if center['status'] != 'observed':
        return result
    origin, at = timeline['clip_origin_seconds'], row['t']
    charges = [q for q in timeline['charged'] if origin+q['t'] <= at]
    if not charges:
        return result
    q = charges[-1]
    if at<q.get('side_confirmed_clip_seconds',origin+q['t']):
        return result
    announcements = q.get('announcement_clip_seconds', [])
    # A positive centered bar after a confirmed replacement may be the new
    # entrant's camera, rather than the previous attack's victim. Header text
    # alone cannot identify that camera. Keep a lingering empty victim bar
    # attributable, but withhold positive bars until another camera cue.
    if announcements and center['bar'].get('fraction', 0) > .03:
        released = min(announcements)
        replacements = [f for fields in timeline.get('field', {}).values() for f in fields
                        if f.get('header_first_visible_clip_seconds', f.get('header_seen_clip_seconds', origin+f['t'])) > released+.75
                        and f.get('header_seen_clip_seconds', origin+f['t']) <= at]
        if replacements:
            return result
    owner = None
    if announcements and max(announcements)+4 < at:
        return result
    if not announcements and at > origin+q['t']+14:
        return result
    side_source = q.get('side_evidence', 'explicit_cue')
    if not announcements or at < min(announcements):
        if side_source in ['explicit_cue', 'minigame']:
            owner = q['side']
    elif at >= min(announcements)+1:
        owner = 'theirs' if q['side'] == 'mine' else 'mine'
    if owner and result[owner] is None:
        identity_time = min(at, min(announcements)+.75) if announcements else at
        fields = [f for f in timeline.get('field', {}).get(owner, [])
                  if f.get('header_first_visible_clip_seconds',f.get('header_seen_clip_seconds', origin+f['t'])) <= identity_time
                  and f.get('header_seen_clip_seconds',origin+f['t'])<=at]
        species = (q.get('actor') if owner == q['side'] and announcements and at >= min(announcements)
                   else fields[-1]['name'] if fields else None)
        result[owner] = {**center['bar'],
            'camera_owner_basis': 'charged_attacker' if owner == q['side'] else 'charged_target',
            'camera_species': species, 'camera_identity_cutoff_seconds': identity_time}
    return result


def reconcile_source_shields(looks, timeline, counters):
    """Associate measured shield decreases with an incoming charged window.

    BLOCKED alone is not shield use. It can also be Disguise. First-visible
    counter changes can be confirmed slightly after the release; the receipt
    records that knowledge delay instead of moving the attack to that frame.
    """
    origin = timeline['clip_origin_seconds']
    assignments, unresolved = [], []
    charges = timeline['charged']
    for defending, prefix in [('mine', 'my'), ('theirs', 'foe')]:
        runs = counters[defending]['shields']
        for position, (before, after) in enumerate(zip(runs, runs[1:])):
            if after['value'] >= before['value']:
                continue
            drop = before['value']-after['value']
            earliest = before.get('last_visible_seconds', before['confirmed_seconds'])
            if earliest > after['first_visible_seconds'] or any(
                    r.get('continuity') == 'increase_requires_review' for r in runs[:position+2]):
                unresolved.append({'side': defending, 'counter': after,
                    'reason': 'shield counter history is contradictory'})
                continue
            candidates = []
            for i, q in enumerate(charges):
                if q['side'] == defending:
                    continue
                start = origin+q['t']
                announcements = q.get('announcement_clip_seconds', [])
                end = (max(announcements)+8) if announcements else start+14
                next_start = origin+charges[i+1]['t'] if i+1 < len(charges) else end
                end = min(end, next_start+1)
                # A following opposing attack can hide the glyph readback.
                # Test the whole interval since the last witnessed old count,
                # rather than dating the spend at the later readable frame.
                if start <= after['first_visible_seconds'] and earliest <= end:
                    candidates.append((i, q))
            if drop != 1 or len(candidates) != 1:
                unresolved.append({'side': defending, 'counter': after,
                                   'reason': 'shield decrement cannot be uniquely attributed',
                                   'candidate_charges': [i for i, _ in candidates]})
                continue
            index, q = candidates[0]
            incoming = 'foe_charged' if defending == 'mine' else 'my_charged'
            start = q['t']
            next_cue = charges[index+1]['t'] if index+1 < len(charges) else timeline['end']+1
            targets = [r for r in looks if r.get(incoming) is not None and r.get(incoming) is not False
                       and start <= r['t'] <= next_cue+1]
            if len(targets) != 1:
                unresolved.append({'side': defending, 'counter': after,
                                   'reason': 'no unique tracked incoming release for source counter drop'})
                continue
            targets[0][prefix+'_shields'] = after['value']
            assignments.append({'side': defending, 'charge_index': index, 'tracker_seconds': targets[0]['t'],
                                'value': after['value'], 'counter': after,
                                'counter_change_interval_seconds': [earliest, after['first_visible_seconds']]})
        repeated = {a['charge_index'] for a in assignments if a['side'] == defending and
                    sum(b['side'] == defending and b['charge_index'] == a['charge_index'] for b in assignments) > 1}
        if repeated:
            for a in assignments:
                if a['side'] == defending and a['charge_index'] in repeated:
                    unresolved.append({'side': defending, 'counter': a['counter'],
                        'reason': 'multiple shield decrements cannot belong to one charged attack',
                        'candidate_charges': [a['charge_index']]})
            assignments = [a for a in assignments if a['side'] != defending or a['charge_index'] not in repeated]
        # Rebuild the counter from independent pixels and confirmed assignments,
        # never from cumulative BLOCKED messages.
        current = None
        for look in sorted(looks, key=lambda r: r['t']):
            t = origin+look['t']
            measured = match_header_counts(counters, defending, 'shields', t)
            observed = measured['value'] if measured else None
            assigned = [a['value'] for a in assignments if a['side'] == defending and a['tracker_seconds'] <= look['t']+1e-6]
            known = ([observed] if observed is not None else [])+assigned[-1:]
            if known:
                current = min(known)
            if current is None:
                look.pop(prefix+'_shields', None)
            else:
                look[prefix+'_shields'] = current
    return {'assignments': assignments, 'unresolved_decrements': unresolved,
            'blocked_messages_are_shield_evidence': False}


def shield_readbacks(native, timeline):
    """Actual before/after glyph witnesses; missing assignment is not 'no shield'."""
    result=[]
    origin=timeline['clip_origin_seconds']
    stable={side:stable_counter_runs(native,side,'shields') for side in ['mine','theirs']}
    for index,q in enumerate(timeline['charged']):
        announcements=q.get('announcement_clip_seconds',[])
        if not announcements or q['side'] not in ('mine','theirs'):
            continue
        defending='theirs' if q['side']=='mine' else 'mine'
        start=origin+q['t'];released=max(announcements)
        prior=[r for r in native if start-.75<=r['t']<=start+.05 and
               r['headers'][defending]['shields'].get('value') is not None]
        before=prior[-3:]
        if len(before)<3 or len({r['headers'][defending]['shields']['value'] for r in before})!=1:
            # Shields cannot regenerate during a battle. The last independently
            # confirmed count bounds the entire unreadable gap; an equal later
            # count proves no spend in that gap, even across several charges.
            # Any observed increase invalidates that continuity argument.
            prior_runs=[r for r in stable[defending] if r['confirmed_seconds']<=start]
            if not prior_runs or any(r['continuity']!='consistent' for r in prior_runs):
                result.append(dict(charge_index=index,status='unknown',reason='No stable pre-attack glyph reading'))
                continue
            previous=prior_runs[-1]
            prior_value=previous['value'];prior_confirmed=previous['confirmed_seconds']
            prior_basis='last_confirmed_irreversible_shield_counter'
        else:
            prior_value=before[-1]['headers'][defending]['shields']['value']
            prior_confirmed=before[-1]['t'];prior_basis='fresh_pre_attack_glyphs'
        if prior_value==0:
            result.append(dict(charge_index=index,status='confirmed_no_spend',shielded=False,
                confirmed_at_seconds=max(start,prior_confirmed),before_confirmed_seconds=prior_confirmed,
                before_basis=prior_basis,reason='Independently observed zero shields before attack'))
            continue
        next_incoming=next((origin+n['t'] for n in timeline['charged'][index+1:] if n['side']==q['side']),released+8)
        end=min(released+8,next_incoming-.1)
        run=[]
        for r in native:
            if not released+1<=r['t']<=end:
                continue
            value=r['headers'][defending]['shields'].get('value')
            if value is None:
                run=[];continue
            if run and (value!=run[-1]['headers'][defending]['shields']['value'] or r['t']-run[-1]['t']>.25):
                run=[]
            run.append(r)
            if len(run)<3:
                continue
            known=value==prior_value
            if any(r['continuity']!='consistent' and prior_confirmed<r['confirmed_seconds']<=run[-1]['t']
                   for r in stable[defending]):
                known=False
            result.append(dict(charge_index=index,status='confirmed_no_spend' if known else 'counter_changed',
                shielded=False if known else None,confirmed_at_seconds=r['t'],
                before=prior_value,after=value,
                before_confirmed_seconds=prior_confirmed,before_basis=prior_basis,
                after_source_pts=[x['source_pts'] for x in run[-3:]],
                after_source_time_base=r['source_time_base']))
            break
        else:
            result.append(dict(charge_index=index,status='unknown',reason='No stable post-attack glyph reading'))
    return result
