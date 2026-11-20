"""Observable creator events independent of default model builds and movesets.

Occurrence and confirmation are separate. A generic visible move name remains
generic, and a result never supplies additional knockouts. Failed/ambiguous
observations remain explicitly unconfirmed instead of choosing a model slot.
"""


def source_events(timeline, lifecycle, measurements):
    events=[]
    shield_assignments=measurements.get('shield_reconciliation',{}).get('assignments',[])
    for index,q in enumerate(timeline['charged']):
        announcements=q.get('announcement_clip_seconds',[])
        if not announcements or not q.get('move'):
            continue
        at=min(announcements)
        side=q['side']
        actor=q.get('actor')
        if actor is None and side in ('mine','theirs'):
            fields=[f for f in timeline['field'][side]
                    if f.get('header_seen_clip_seconds',f['t']+timeline['clip_origin_seconds'])<=at]
            actor=fields[-1]['name'] if fields else None
        defended='theirs' if side=='mine' else 'mine'
        assignments=[a for a in shield_assignments if a['charge_index']==index and a['side']==defended]
        readback=next((v for v in measurements.get('shield_readbacks',[]) if v['charge_index']==index),{})
        shielded=True if assignments else False if readback.get('status')=='confirmed_no_spend' else None
        event=dict(kind='charged',side=side,pokemon=actor,move=q['move'],t=at,
            confirmed_at_seconds=max(at,q.get('actor_confirmed_clip_seconds') or at,
                                     q.get('side_confirmed_clip_seconds') or at),shielded=shielded,
            shield_status='confirmed_spend' if assignments else readback.get('status','unknown'),
            shield_confirmed_at_seconds=(assignments[0]['counter']['confirmed_seconds'] if assignments else
                                         readback.get('confirmed_at_seconds') if shielded is False else None),
            identity_status='observed_actor' if q.get('actor') else 'past_header' if actor else 'unknown',
            method='visible_named_release',charge_index=index,
            source_observation_seconds=sorted(set(announcements)),model_build_used=False)
        if q.get('cue_conflict'):
            event['cue_conflict'] = q['cue_conflict']
        events.append(event)
        for a in assignments:
            counter=a['counter']
            events.append(dict(kind='shield',side=defended,t=counter['first_visible_seconds'],
                confirmed_at_seconds=counter['confirmed_seconds'],
                associated_attack_seconds=at,associated_attack=q['move'],
                counter_change_interval_seconds=a.get('counter_change_interval_seconds'),
                method='independent_visible_shield_decrement',charge_index=index,model_build_used=False))
    for death in lifecycle['faints']:
        support=death.get('independent_support',{})
        if support.get('status') not in (None,'confirmed'):
            continue
        events.append(dict(kind='faint',side=death['side'],pokemon=death['species'],
            t=death['clip_seconds'],confirmed_at_seconds=death.get('confirmed_clip_seconds',death['clip_seconds']),
            timing_uncertainty_seconds=death.get('timing_uncertainty_seconds'),
            timing_interval_seconds=death.get('timing_interval_seconds'),
            occurrence_time_basis=death.get('occurrence_time_basis','measured_zero_or_disappearance'),
            method=death['method'],independent_support=support,
            model_build_used=False,result_used=False))
    return sorted(events,key=lambda e:(e['t'],e['kind'],str(e.get('side'))))
