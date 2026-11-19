"""Recover additional source-timed faints from the complete native HP stream."""
import json
from creator_health import rows
from creator_observations import interpret_measurements, health_owners, match_header_counts
from vod_media import write_json, sha256


def native_faints(native, timeline, counters):
    origin = timeline['clip_origin_seconds']
    bars = [(r, health_owners(r, timeline)) for r in native]
    candidates = []
    for side in ['mine', 'theirs']:
        fields = timeline['field'][side]
        previous = None
        for index, (row, owners) in enumerate(bars):
            bar = owners[side]
            if not bar:
                continue
            if bar['live_pixels']:
                previous = (row, bar)
                continue
            if not previous or not 0 < row['t']-previous[0]['t'] <= .5:
                continue
            shown = [f for f in fields if f.get('header_seen_clip_seconds', origin+f['t']) <= previous[0]['t']]
            if not shown:
                continue
            victim = bar.get('camera_species') or shown[-1]['name']
            # A later observed return disproves the proposed death.
            if any(f['name'] == victim and f.get('header_seen_clip_seconds', origin+f['t']) > row['t']+1
                   for f in fields[len(shown):]):
                continue
            zeros, missing, refuted = [], [], False
            for after, values in bars[index:index+24]:
                delta = after['t']-row['t']
                if delta > 1.75:
                    break
                current = values[side]
                if current and current['live_pixels'] > 2:
                    refuted = True
                    break
                if current and current['live_pixels'] == 0 and delta <= .3:
                    if max(abs(a-b) for a, b in zip(bar['bounds'], current['bounds'])) <= 8:
                        zeros.append(after)
                if current is None and delta >= .25:
                    missing.append(after)
                if len(zeros) >= 3 and len(missing) >= 3 and missing[-1]['t']-missing[0]['t'] >= .16:
                    break
            if refuted or len(zeros) < 3 or len(missing) < 3 or missing[-1]['t']-missing[0]['t'] < .16:
                continue
            proof, confirm = None, max(zeros[2]['t'], missing[-1]['t'])
            runs = counters[side]['party']
            drops = [b for a, b in zip(runs, runs[1:]) if a['value']-b['value'] == 1
                     and -.25 <= b['first_visible_seconds']-row['t'] <= 8]
            replacement = next((f for f in fields if f['name'] != victim and
                row['t'] < f.get('header_seen_clip_seconds', origin+f['t']) <= row['t']+5), None)
            # A one-HP red strip can fall below the palette threshold before
            # the camera moves. A later named release proves it was alive.
            later_releases = [q for q in timeline['charged'] if q['side'] == side
                and q.get('announcement_clip_seconds') and
                row['t'] < min(q['announcement_clip_seconds']) <= row['t']+15
                and (not replacement or min(q['announcement_clip_seconds']) < replacement['header_seen_clip_seconds'])]
            if later_releases:
                continue
            count = match_header_counts(counters, side, 'party', row['t'])
            if len(drops) == 1:
                proof = {'method': 'independent_party_decrement', 'counter': drops[0]}
                confirm = max(confirm, drops[0]['confirmed_seconds'])
            elif replacement:
                proof = {'method': 'fresh_replacement_header', 'species': replacement['name'],
                         'observed_at_seconds': replacement['header_seen_clip_seconds']}
                confirm = max(confirm, replacement['header_seen_clip_seconds'])
            elif count and count['value'] == 1:
                proof = {'method': 'independently_observed_last_party_member', 'counter': count}
            if proof is None:
                continue
            if any(c['side'] == side and c['species'] == victim for c in candidates):
                continue
            candidates.append({'side': side, 'species': victim, 'clip_seconds': row['t'],
                'confirmed_clip_seconds': confirm, 'timing_uncertainty_seconds': 1/12,
                'method': 'native_stream_positive_zero_fade_and_independent_confirmation',
                'previous_positive': {'t': previous[0]['t'], 'bar': previous[1]},
                'first_zero': {'t': row['t'], 'bar': bar, 'source_pts': row['source_pts'],
                               'source_time_base': row['source_time_base']},
                'independent_confirmation': proof, 'zero_frames': len(zeros), 'missing_frames': len(missing)})
    return sorted(candidates, key=lambda c: c['clip_seconds'])


def disappearance_faints(native, timeline):
    """Date disappearance when a tiny bar cannot resolve zero versus one HP.

    Independent party/life support is still required. Camera changes during
    a charged animation are excluded; an unchanged party count refutes a swap.
    """
    from creator_faint_support import faint_support
    origin = timeline['clip_origin_seconds']
    assigned = [(r,health_owners(r,timeline)) for r in native]
    result=[]
    for side in ['mine','theirs']:
        recent=[]
        for index,(row,owners) in enumerate(assigned):
            bar=owners[side]
            if bar:
                if recent and row['t']-recent[-1][0]['t'] > .25:
                    recent=[]
                recent.append((row,bar));recent=recent[-4:]
                continue
            previous=recent;recent=[]
            if len(previous)<2 or row['t']-previous[-1][0]['t'] > .2:
                continue
            # The remaining strip can be lost behind a hit before an empty
            # rectangle is readable. A low strip is only a candidate; the
            # independent counter/life check below decides whether it is a KO.
            fractions=[b['live_pixels']/b.get('interior_width_pixels',b['bounds'][2]-b['bounds'][0])
                       for _,b in previous[-2:]]
            if fractions[-1]>.1 or fractions[0]>.2 or fractions[-1]>fractions[0]+.015:
                continue
            after=assigned[index:index+7]
            if len(after)<3 or any(v[side] is not None for _,v in after):
                continue
            at=row['t']
            charges=[q for q in timeline['charged'] if origin+q['t']<=at and q.get('announcement_clip_seconds')]
            if charges:
                q=charges[-1];first,last=min(q['announcement_clip_seconds']),max(q['announcement_clip_seconds'])
                if at<first+1 or (q['side']==side and at<=last+3):
                    continue
            shown=[f for f in timeline['field'][side]
                   if f.get('header_seen_clip_seconds',origin+f['t'])<=previous[0][0]['t']]
            if not shown:
                continue
            victim = previous[0][1].get('camera_species') or shown[-1]['name']
            stint = next((f for f in reversed(shown) if f['name'] == victim), None)
            if not stint or previous[0][0]['t']-stint.get('header_seen_clip_seconds',origin+stint['t']) < .5:
                continue
            death=dict(side=side,species=victim,clip_seconds=at,
                confirmed_clip_seconds=after[2][0]['t'],timing_uncertainty_seconds=1/12,
                method='tiny_bar_to_measured_disappearance_with_independent_party_support',
                last_tiny_bar=dict(t=previous[-1][0]['t'],bar=previous[-1][1]),
                disappearance_source_pts=row['source_pts'],disappearance_source_time_base=row['source_time_base'])
            support=faint_support(death,timeline,native)
            if support['status']!='confirmed':
                continue
            # Without an actual counter drop, restrict the last-member case
            # to a much smaller strip. These are disappearance times with a
            # bounded last-visible interval, never a fabricated pixel zero.
            if support['reason'] != 'independent_party_decrement' and any(
                    b['live_pixels']/b.get('interior_width_pixels',b['bounds'][2]-b['bounds'][0]) > .05
                    for _,b in previous[-2:]):
                continue
            death['timing_interval_seconds']=[previous[-1][0]['t'],at]
            death['independent_support']=support
            death['confirmed_clip_seconds']=max(death['confirmed_clip_seconds'],support['confirmed_seconds'])
            if not any(d['side']==side and d['species']==death['species'] for d in result):
                result.append(death)
    return result


def counter_zero_faints(native, timeline, counters):
    """An independently counted death can corroborate a brief empty bar.

    No positive predecessor is required when the camera hid the damage. An
    empty-looking one-HP survivor is still refuted by its return/release or an
    unchanged counter. Confirmation is later than the observed zero samples.
    """
    from creator_faint_support import faint_support
    origin=timeline['clip_origin_seconds']; runs={s:[] for s in ['mine','theirs']}; result=[]
    for row in native:
        owners=health_owners(row,timeline)
        for side in runs:
            bar=owners[side]
            shown=[f for f in timeline['field'][side] if f.get('header_seen_clip_seconds',origin+f['t'])<=row['t']]
            victim=(bar or {}).get('camera_species') or (shown[-1]['name'] if shown else None)
            run=runs[side]
            if not bar or bar['live_pixels'] or not victim:
                runs[side]=[];continue
            moving_sidebars=(bar.get('camera_owner_basis') is None and owners['theirs' if side=='mine' else 'mine'] is not None)
            if run and (row['t']-run[-1][0]['t']>.2 or run[-1][2]!=victim or
                        (max(abs(a-b) for a,b in zip(run[-1][1]['bounds'],bar['bounds']))>8 and not moving_sidebars)):
                run=[];runs[side]=run
            run.append((row,bar,victim))
            if len(run)!=3:
                continue
            first,first_bar,_=run[0]
            anchored=next((q for q in reversed(timeline['charged']) if q['side']!=side and
                q.get('announcement_clip_seconds') and min(q['announcement_clip_seconds'])+1<=first['t']<=max(q['announcement_clip_seconds'])+4),None)
            target=anchored is not None and first_bar.get('camera_owner_basis')=='charged_target'
            drops=[b for a,b in zip(counters[side]['party'],counters[side]['party'][1:])
                   if a['value']-b['value']==1 and -.5<=b['first_visible_seconds']-first['t']<=(8 if target else 2)]
            if len(drops)!=1:
                continue
            death=dict(side=side,species=victim,clip_seconds=first['t'],
                confirmed_clip_seconds=row['t'],timing_uncertainty_seconds=1/12,
                method='three_empty_bar_samples_and_independent_party_decrement',
                first_zero=dict(t=first['t'],bar=first_bar,source_pts=first['source_pts'],
                    source_time_base=first['source_time_base']),zero_frames=3)
            if target:
                death['charged_target_anchor']=dict(cue_seconds=origin+anchored['t'],release_seconds=min(anchored['announcement_clip_seconds']))
            support=faint_support(death,timeline,native)
            if support['status']!='confirmed' or support['reason']!='independent_party_decrement':
                continue
            death['independent_support']=support
            death['confirmed_clip_seconds']=max(row['t'],support['confirmed_seconds'])
            if not any(d['side']==side and d['species']==victim for d in result):
                result.append(death)
    return result


def caught_entry_faints(native,timeline,counters):
    """Attribute a counted death in a short A->B->A stint to B.

    The outgoing A demonstrably returns alive. B was independently identified
    by its header and matching entry announcement in the assembler. Date the
    observed party decrement, retaining a wider timing interval: no HP zero
    was resolved in this case. This is retrospective confirmation, not a
    decision-time assertion that was available before A returned.
    """
    origin=timeline['clip_origin_seconds'];result=[]
    for side in ['mine','theirs']:
        fields=timeline['field'][side]
        for previous,entry,after in zip(fields,fields[1:],fields[2:]):
            at=entry.get('header_seen_clip_seconds',origin+entry['t'])
            returned=after.get('header_seen_clip_seconds',origin+after['t'])
            if previous['name']!=after['name'] or entry['name']==previous['name'] or not 0<returned-at<=6:
                continue
            if not any(f['name']==entry['name'] for f in fields if f.get('header_seen_clip_seconds',origin+f['t'])<at):
                continue
            if any(f['name']==entry['name'] for f in fields if f.get('header_seen_clip_seconds',origin+f['t'])>returned):
                continue
            runs=counters[side]['party']
            drops=[b for a,b in zip(runs,runs[1:]) if a['value']-b['value']==1
                   and at-.5<=b['first_visible_seconds']<=returned]
            if len(drops)!=1:
                continue
            drop=drops[0]
            if any(q['side']==side and q.get('actor')==entry['name'] and
                   q.get('announcement_clip_seconds') and min(q['announcement_clip_seconds'])>drop['first_visible_seconds']+2
                   for q in timeline['charged']):
                continue
            result.append(dict(side=side,species=entry['name'],clip_seconds=drop['first_visible_seconds'],
                confirmed_clip_seconds=max(returned,drop['confirmed_seconds']),
                timing_interval_seconds=[min(at-.5,drop['first_visible_seconds']),drop['first_visible_seconds']],
                timing_uncertainty_seconds=max(.5,at-drop['first_visible_seconds']),
                method='party_zero_for_short_identified_entry_with_outgoing_survivor_return',
                independent_support=dict(status='confirmed',reason='independent_party_decrement_and_outgoing_returns_alive',
                    first_visible_seconds=drop['first_visible_seconds'],confirmed_seconds=max(returned,drop['confirmed_seconds'])),
                entry=entry,outgoing_survivor_return=after,counter=drop))
    return result


def queued_charge_faints(native,timeline,counters):
    """A counted death around a queued release has a bounded, unresolved time.

    A palette-empty bar at the cue cannot distinguish zero from one HP. The
    later decrement confirms the victim, while the entire empty-to-decrement
    interval remains explicit. This does not declare it dead before its move.
    """
    origin=timeline['clip_origin_seconds'];result=[]
    assigned=[(r,health_owners(r,timeline)) for r in native]
    for index,q in enumerate(timeline['charged']):
        if q.get('side_evidence')!='explicit_cue' or not q.get('actor') or not q.get('announcement_clip_seconds'):
            continue
        side=q['side'];cue=origin+q['t'];released=max(q['announcement_clip_seconds'])
        fields=[f for f in timeline['field'][side] if f.get('header_seen_clip_seconds',origin+f['t'])<=cue]
        if not fields or fields[-1]['name']!=q['actor']:continue
        drops=[b for a,b in zip(counters[side]['party'],counters[side]['party'][1:])
               if a['value']-b['value']==1 and released<=b['first_visible_seconds']<=released+3]
        if len(drops)!=1:continue
        drop=drops[0];run=[]
        for row,owners in assigned:
            if not cue-1<=row['t']<=cue+2:continue
            bar=owners[side]
            if not bar or bar['live_pixels']!=0:
                run=[];continue
            if run and row['t']-run[-1][0]['t']>.2:run=[]
            run.append((row,bar))
            if len(run)<3:continue
            first,zero=run[0]
            if any(values[side] and values[side]['live_pixels']>2 for after,values in assigned
                   if row['t']<after['t']<drop['first_visible_seconds']):break
            end=drop['first_visible_seconds'];at=first['t']
            result.append(dict(side=side,species=q['actor'],clip_seconds=at,
                confirmed_clip_seconds=drop['confirmed_seconds'],
                timing_interval_seconds=[at,end],timing_uncertainty_seconds=end-at,
                occurrence_time_basis='earliest_empty_bar_bound_not_exact_faint_time',
                method='counted_death_during_observed_queued_charge',
                first_zero=dict(t=at,bar=zero,source_pts=first['source_pts'],source_time_base=first['source_time_base']),
                queued_charge=dict(charge_index=index,cue_seconds=cue,release_seconds=released),
                independent_counter=drop,zero_frames=3))
            break
    return result


def apply_native_faints(game, raw):
    from creator_faint_support import faint_support
    path = raw/'native-health-12hz.jsonl.gz'
    native, counters = interpret_measurements(rows(path))
    timeline = json.loads((game/'timeline.json').read_text(encoding='utf-8'))
    evidence_path = game/'creator-lifecycle.json'
    evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
    candidates = (counter_zero_faints(native,timeline,counters)+native_faints(native, timeline, counters)
                  +disappearance_faints(native,timeline)+caught_entry_faints(native,timeline,counters)
                  +queued_charge_faints(native,timeline,counters))
    added, retained, quarantined = [], [], []
    original = evidence['faints']
    for death in original:
        support = faint_support(death, timeline, native)
        if support['status'] != 'confirmed':
            quarantined.append({**death, 'independent_support': support})
            continue
        death['independent_support'] = support
        death['confirmed_clip_seconds'] = max(death.get('confirmed_clip_seconds', death['clip_seconds']), support['confirmed_seconds'])
        retained.append(death)
    evidence['faints'] = retained
    for death in candidates:
        support = faint_support(death, timeline, native)
        if support['status'] != 'confirmed':
            quarantined.append({**death, 'independent_support': support})
            continue
        existing=next((d for d in evidence['faints'] if d['side']==death['side'] and d.get('species')==death['species']),None)
        if existing:
            if death['method']!='three_empty_bar_samples_and_independent_party_decrement' or not .15<existing['clip_seconds']-death['clip_seconds']<6:
                continue
            # A later body/replacement fade must not override an earlier
            # independently corroborated zero. Keep the superseded receipt.
            death['supersedes_later_faint']=existing
            evidence['faints'].remove(existing)
            if existing in retained:
                retained.remove(existing)
        death['independent_support'] = support
        death['confirmed_clip_seconds'] = max(death['confirmed_clip_seconds'], support['confirmed_seconds'])
        evidence['faints'].append(death)
        added.append(death)
    if added or quarantined:
        from vod_track import plain_rows
        looks = plain_rows(game/'observations.jsonl')
        removed = [d for d in original if d not in retained]
        for look in looks:
            for d in removed:
                if abs(look['t']-(d['clip_seconds']-timeline['clip_origin_seconds'])) < .15:
                    prefix = 'my' if d['side'] == 'mine' else 'foe'
                    if look.get(prefix+'_fainted'):
                        look.pop(prefix+'_fainted', None)
                        look.pop(prefix+'_hp', None)
        for d in added:
            from creator_faint_support import death_state_seconds
            prefix = 'my' if d['side'] == 'mine' else 'foe'
            name = d['species']
            if prefix == 'my':
                name = next((f['resolved_species'] for f in evidence['forms'] if f['header_species'] == name), name)
            looks.append({'t': round(death_state_seconds(d)-timeline['clip_origin_seconds'], 6),
                prefix+'_species': name, prefix+'_hp': 0, prefix+'_fainted': True,
                'note': 'native source stream zero/fade with independent confirmation'})
        looks.sort(key=lambda r: r['t'])
        (game/'observations.jsonl').write_bytes(''.join(json.dumps(r)+'\n' for r in looks).encode('utf-8'))
    evidence['native_stream_faint_audit'] = {'measurement_sha256': sha256(path),
        'code_sha256': sha256(__file__), 'candidates': candidates, 'added': len(added),
        'quarantined': quarantined, 'result_based_faints': 0}
    write_json(evidence_path, evidence)
    return added
