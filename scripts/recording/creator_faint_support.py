"""Check pixel-zero candidates against independent party and life evidence.

An empty-looking bar and a replacement do not distinguish a faint from a
voluntary switch at one HP. This offline check preserves confirmation time and
quarantines contradictions instead of making a replacement a second victim.
"""


def death_state_seconds(death):
    """A bounded death must not remove a queued attacker at its lower bound."""
    if death.get('occurrence_time_basis')=='earliest_empty_bar_bound_not_exact_faint_time':
        return death['timing_interval_seconds'][1]
    return death['clip_seconds']


def faint_support(death, timeline, native):
    side, name, at = death['side'], death['species'], death['clip_seconds']
    origin = timeline['clip_origin_seconds']
    fields = timeline['field'][side]
    queued=None
    if death.get('method')=='counted_death_during_observed_queued_charge':
        proof=death.get('queued_charge',{});index=proof.get('charge_index',-1)
        charges=timeline.get('charged',[])
        if isinstance(index,int) and 0<=index<len(charges):
            q=charges[index]
            if (q['side']==side and q.get('actor')==name and q.get('side_evidence')=='explicit_cue'
                and q.get('announcement_clip_seconds') and origin+q['t']-1<=at<=origin+q['t']+2
                and proof.get('release_seconds')==max(q['announcement_clip_seconds'])):
                queued=q
    known=[f for f in fields if f.get('header_seen_clip_seconds',origin+f['t'])<=death.get('confirmed_clip_seconds',at)]
    if (known and known[-1]['name']!=name and
        known[-1].get('header_first_visible_clip_seconds',known[-1].get('header_seen_clip_seconds',origin+known[-1]['t']))<=at-2):
        return dict(status='contradicted',reason='different_active_physically_identified_before_proposed_faint',
                    confirmed_seconds=known[-1].get('header_seen_clip_seconds',origin+known[-1]['t']))
    later = [f for f in fields if f.get('header_seen_clip_seconds', origin+f['t']) > at+1e-6]
    replacement = next((f for f in later if f['name'] != name), None)
    returned = next((f for f in later if f['name'] == name and replacement and
                     f.get('header_seen_clip_seconds', origin+f['t']) >
                     replacement.get('header_seen_clip_seconds', origin+replacement['t'])), None)
    if returned:
        witness = returned
        return dict(status='contradicted', reason='same_species_returns_alive_after_proposed_faint',
                    confirmed_seconds=witness.get('header_seen_clip_seconds', origin+witness['t']))
    end = replacement.get('header_seen_clip_seconds', origin+replacement['t']) if replacement else float('inf')
    release = next((q for q in timeline.get('charged', []) if q['side'] == side and
                    q.get('actor', q.get('pokemon')) == name and
                    q.get('announcement_clip_seconds') and at+2 < min(q['announcement_clip_seconds']) < end
                    and q is not queued), None)
    if release:
        return dict(status='contradicted', reason='later_named_release_before_replacement',
                    confirmed_seconds=min(release['announcement_clip_seconds']))
    before = [r for r in native if at-2 <= r['t'] <= at-.15 and
              r['headers'][side]['party'].get('value') is not None]
    if not before and death.get('charged_target_anchor'):
        cue=death['charged_target_anchor']['cue_seconds']
        before=[r for r in native if cue-1<=r['t']<=cue+.05 and
                r['headers'][side]['party'].get('value') is not None]
    if not before:
        bars=[death.get(key,{}).get('bar',{}) for key in ['previous_positive','first_zero','last_tiny_bar']]
        target=any(b.get('camera_owner_basis')=='charged_target' and b.get('camera_species')==name for b in bars)
        charge=next((q for q in reversed(timeline.get('charged',[])) if q['side']!=side and q.get('announcement_clip_seconds')
                     and min(q['announcement_clip_seconds'])+1<=at<=max(q['announcement_clip_seconds'])+4),None)
        if target and charge:
            # Headers can remain hidden across back-to-back charged cameras.
            # A coherent last pre-cue count plus the measured target zero and
            # a unique later decrement still supports this death. No count is
            # manufactured at the impact or replacement timestamp.
            cue=origin+charge['t']
            historical=[r for r in native if r['t']<=cue+.05 and r['headers'][side]['party'].get('value') is not None][-3:]
            if len(historical)==3 and historical[-1]['t']-historical[0]['t']<=.5 and len({r['headers'][side]['party']['value'] for r in historical})==1:
                before=historical
    if not before:
        return dict(status='unconfirmed', reason='no_independent_party_count_before_zero')
    previous = max(r['headers'][side]['party']['value'] for r in before)
    deadline=max(queued['announcement_clip_seconds'])+3 if queued else at+8
    after = [r for r in native if at+.1 <= r['t'] <= deadline and
             r['headers'][side]['party'].get('value') is not None]
    run = []
    for r in after:
        value = r['headers'][side]['party']['value']
        if value == previous-1:
            if run and r['t']-run[-1]['t'] > .25:
                run = []
            run.append(r)
            if len(run) >= 3:
                return dict(status='confirmed', reason='independent_party_decrement',
                            first_visible_seconds=run[0]['t'], confirmed_seconds=r['t'])
        else:
            run = []
    if previous == 1:
        return dict(status='confirmed', reason='known_last_party_member_and_measured_zero_fade',
                    confirmed_seconds=death.get('confirmed_clip_seconds', at))
    if len(after) >= 3 and all(r['headers'][side]['party']['value'] == previous for r in after):
        return dict(status='contradicted', reason='party_remains_unchanged_after_zero_and_replacement',
                    confirmed_seconds=after[-1]['t'])
    return dict(status='unconfirmed', reason='no_unique_party_decrement_or_last_member_confirmation')
