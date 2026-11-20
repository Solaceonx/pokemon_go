"""Attribute explicit form captions to independently observed source identities.

No initial form is supplied by a model build or a species header. A Disguise
caption establishes only the busted form, after repeated literal readings and
an unchanged, previously confirmed Mimikyu/CP target.
"""
import bisect
import copy
import math
import re


def busted_caption(text):
    return re.sub('[^a-z]', '', text.lower()) in (
        'mimikyusdisguiseisbusted', 'mimikyudisguiseisbusted')


def past_identity(identities, side, at):
    index = bisect.bisect_right([r['t'] for r in identities], at)-1
    while index >= 0 and at-identities[index]['t'] <= .75:
        value = identities[index]['values'].get(side)
        if value:
            break
        index -= 1
    else:
        return None
    if (not value or not isinstance(value.get('confirmed_seconds'), (int, float))
            or value['confirmed_seconds'] > identities[index]['t']
            or not 0 <= at-value['confirmed_seconds'] <= .75
            or not isinstance(value.get('cp'), int) or isinstance(value['cp'], bool) or value['cp'] <= 0):
        return None
    return value


def bracketed_target(identities, side, cue, caption):
    """Confirm a hidden camera target only once its physical header returns."""
    before = [r for r in identities if r['t'] <= cue and r.get('values', {}).get(side)]
    after = [r for r in identities if caption < r['t'] <= caption+4 and r.get('values', {}).get(side)]
    if not before or not after or not 0 <= cue-before[-1]['t'] <= 2:
        return None
    a, b = before[-1], after[0]
    values = [r['values'][side] for r in (a, b)]
    for row, value in zip((a, b), values):
        confirmed = value.get('confirmed_seconds')
        if (not isinstance(confirmed, (int, float)) or isinstance(confirmed, bool)
                or not math.isfinite(confirmed) or not 0 <= row['t']-confirmed <= .75
                or value.get('species') != 'Mimikyu' or not isinstance(value.get('cp'), int)
                or isinstance(value['cp'], bool) or value['cp'] <= 0):
            return None
    if values[0]['cp'] != values[1]['cp']:
        return None
    if not 0 <= cue-values[0]['confirmed_seconds'] <= 2 or values[1]['confirmed_seconds'] <= caption:
        return None
    return values[0], values[1]


def collect(text_rows, timeline, source_events, identities, raw_identities):
    releases = [(i, q, min(q['announcement_clip_seconds']))
                for i, q in enumerate(timeline.get('charged', [])) if q.get('announcement_clip_seconds')]
    candidates, events, pending = [], [], {}
    for record in text_rows:
        if not any(busted_caption(text) for _, text in record.get('text', [])):
            continue
        at = record['t']
        available = record.get('recognition_available_at_seconds', at)
        if (not isinstance(available, (int, float)) or isinstance(available, bool)
                or not math.isfinite(available) or available < at):
            continue
        row = dict(kind='form_caption', observed_at_seconds=at, form='mimikyu_busted',
                   recognition_available_at_seconds=available,
                   status='unattributed', reason='No unique causal named-release target')
        eligible = [(i, q, t) for i, q, t in releases if 0 <= at-t <= 8]
        latest = max((t for _, _, t in eligible), default=None)
        choices = [(i, q, t) for i, q, t in eligible if t == latest]
        if len(choices) != 1:
            candidates.append(row)
            continue
        index, charge, release = choices[0]
        source = [e for e in source_events if e.get('kind') == 'charged' and e.get('charge_index') == index
                  and isinstance(e.get('confirmed_at_seconds'), (int, float)) and e['confirmed_at_seconds'] <= available]
        side_at = charge.get('side_confirmed_clip_seconds')
        if (charge.get('side') not in ('mine', 'theirs') or len(source) != 1
                or side_at is None or side_at > available or source[0].get('side') != charge['side']):
            candidates.append(row)
            continue
        side = 'theirs' if charge['side'] == 'mine' else 'mine'
        anchor = release
        recovery = None
        target = past_identity(identities, side, anchor)
        # The charge camera may hide both headers at release. Retain a fresh
        # pre-cue target only if nothing subsequently contradicts that identity.
        if target is None and side_at <= release:
            anchor = side_at
            target = past_identity(identities, side, anchor)
        if target is None and isinstance(charge.get('t'), (int, float)) and not charge.get('cue_conflict'):
            cue = timeline.get('clip_origin_seconds', 0)+charge['t']
            bracket = bracketed_target(identities, side, cue, at)
            if bracket:
                target, recovery = bracket
                anchor = cue
        if not target or target['species'] != 'Mimikyu':
            row['reason'] = 'No fresh independently confirmed Mimikyu/CP at release or cue'
            candidates.append(row)
            continue
        identity = ('Mimikyu', target['cp'])
        proof_start = target['confirmed_seconds']
        proof_end = max(at, recovery['confirmed_seconds']) if recovery else at
        changed = any((value['species'], value['cp']) != identity
                      for sample in raw_identities if proof_start < sample['t'] <= proof_end
                      for value in [sample.get(side)] if value)
        entered = any(proof_start < f.get('header_seen_clip_seconds', float('inf')) <= proof_end
                      for f in timeline.get('field', {}).get(side, []))
        if changed or entered:
            row['reason'] = 'A different physical identity or entry intervenes before the caption'
            candidates.append(row)
            continue
        shield_at = source[0].get('shield_confirmed_at_seconds')
        if source[0].get('shielded') is True and isinstance(shield_at, (int, float)) and shield_at <= proof_end:
            row.update(status='contradictory', reason='Confirmed Protect Shield conflicts with a Disguise change')
            candidates.append(row)
            continue
        row.update(status='candidate', side=side, pokemon='Mimikyu', cp=target['cp'],
                   identity=f"Mimikyu:{target['cp']}", charge_index=index,
                   target_proof_anchor_seconds=anchor,
                   target_header_seen_seconds=target['confirmed_seconds'],
                   target_source_pts=target.get('source_pts'), target_source_time_base=target.get('source_time_base'),
                   reason='Literal caption with unchanged independently confirmed charged-release target')
        if recovery:
            row.update(target_recovery_seconds=recovery['confirmed_seconds'],
                target_recovery_source_pts=recovery.get('source_pts'),
                target_recovery_time_base=recovery.get('source_time_base'),
                target_recovery_identity=f"Mimikyu:{recovery['cp']}",
                reason='Caption attribution waits for the same physical Mimikyu/CP header to return')
        candidates.append(row)
        key = (side, index, row['identity'])
        previous = pending.get(key)
        if not previous or not 0 < at-previous['observed_at_seconds'] <= 1.5:
            pending[key] = row
            continue
        if any(e['side'] == side and e['charge_index'] == index for e in events):
            continue
        confirmed = max(at, available, previous['recognition_available_at_seconds'],
                        previous.get('target_recovery_seconds', at), row.get('target_recovery_seconds', at))
        if source[0].get('shielded') is True and isinstance(shield_at, (int, float)) and shield_at <= confirmed:
            row.update(status='contradictory', reason='Protect Shield conflict is known by deferred form confirmation')
            continue
        event = dict(kind='form', status='confirmed', side=side, pokemon='Mimikyu', cp=target['cp'],
            identity=row['identity'], form='mimikyu_busted', t=previous['observed_at_seconds'],
            confirmed_at_seconds=confirmed, source_observation_seconds=[previous['observed_at_seconds'], at],
            source_availability_seconds=[previous['recognition_available_at_seconds'], available],
            charge_index=index, target_header_seen_seconds=target['confirmed_seconds'],
            target_proof_anchor_seconds=anchor,
            target_source_pts=target.get('source_pts'), target_source_time_base=target.get('source_time_base'),
            method='repeated_literal_disguise_caption_with_independent_causal_target', model_build_used=False)
        recovered = [r for r in (previous, row) if r.get('target_recovery_seconds') is not None]
        if recovered:
            proof = max(recovered, key=lambda r:r['target_recovery_seconds'])
            event.update(method='repeated_literal_disguise_caption_with_bracketed_causal_target',
                target_recovery_seconds=proof['target_recovery_seconds'],
                target_recovery_source_pts=proof['target_recovery_source_pts'],
                target_recovery_time_base=proof['target_recovery_time_base'],
                target_recovery_identity=proof['target_recovery_identity'])
        events.append(event)
    return dict(schema='creator-source-forms-v1', events=events, candidates=candidates,
                initial_forms_assumed=False, model_build_used=False, accuracy_verified=False)


def derive(raw, timeline, source_events):
    """Typed evidence only; neither unrestricted OCR nor images are serialized."""
    import hashlib
    from pathlib import Path
    from creator_health import rows
    from creator_identity import confirmed_identities, entry_announcements
    identity_path = raw/'native-identities-3hz.jsonl.gz'
    samples = rows(identity_path) if identity_path.exists() else []
    identities = confirmed_identities(samples, entry_announcements(raw)) if samples else []
    from creator_form_captions import acquire, caption_rows
    text_rows = rows(raw/'text.jsonl.gz')
    witnesses = acquire(raw, timeline, source_events, identities, text_rows)
    alignment = {round(r['clip_seconds'],6):r for r in rows(raw.parent/'frame_alignment.jsonl.gz')}
    result = collect(caption_rows(text_rows, witnesses, alignment=alignment), timeline, source_events, identities, samples)
    result['provenance'] = dict(code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        input_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in
                      (raw/'text.jsonl.gz', identity_path, raw/'native-form-captions-6hz.jsonl.gz',
                       raw/'native-form-captions-acquisition.json') if p.exists()})
    result['provenance']['caption_code_sha256'] = hashlib.sha256(
        Path(__file__).with_name('creator_form_captions.py').read_bytes()).hexdigest()
    import json
    result['provenance'].update(
        timeline_sha256=hashlib.sha256(json.dumps(timeline,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
        release_evidence_sha256=hashlib.sha256(json.dumps(source_events,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
        identity_code_sha256=hashlib.sha256(Path(__file__).with_name('creator_identity.py').read_bytes()).hexdigest(),
        gamemaster_sha256=hashlib.sha256((Path(__file__).resolve().parents[2]/'data/gamemaster.json').read_bytes()).hexdigest())
    return result


class FormEvidence:
    """Reveal confirmed source facts only after their confirmation timestamp."""
    def __init__(self, events=()):
        self.pending = []
        self.events = []
        self.cursor = 0
        for event in events:
            observed, confirmed = event.get('t'), event.get('confirmed_at_seconds')
            cp = event.get('cp')
            samples = event.get('source_observation_seconds')
            valid_time = all(isinstance(t, (int, float)) and not isinstance(t, bool) and math.isfinite(t)
                             for t in (observed, confirmed))
            valid_samples = (isinstance(samples,list) and len(samples)>=2
                and all(isinstance(t,(int,float)) and not isinstance(t,bool) and math.isfinite(t) for t in samples)
                and all(a<b for a,b in zip(samples,samples[1:]))
                and valid_time and samples[0]==observed and samples[-1]<=confirmed)
            method = event.get('method')
            availability = event.get('source_availability_seconds')
            valid_availability = availability is None or (valid_samples and isinstance(availability,list)
                and len(availability)==len(samples)
                and all(isinstance(t,(int,float)) and not isinstance(t,bool) and math.isfinite(t)
                        and sample<=t<=confirmed for sample,t in zip(samples,availability)))
            valid_method = method == 'repeated_literal_disguise_caption_with_independent_causal_target'
            if method == 'repeated_literal_disguise_caption_with_bracketed_causal_target':
                before, after = event.get('target_header_seen_seconds'), event.get('target_recovery_seconds')
                valid_method = (valid_time and all(isinstance(t,(int,float)) and not isinstance(t,bool)
                    and math.isfinite(t) for t in (before,after)) and 0 <= before <= observed < after <= confirmed
                    and event.get('target_recovery_identity') == event.get('identity'))
            if (event.get('kind') == 'form' and event.get('status') == 'confirmed'
                    and event.get('side') in ('mine', 'theirs') and event.get('pokemon') == 'Mimikyu'
                    and event.get('form') == 'mimikyu_busted' and isinstance(cp, int) and not isinstance(cp, bool)
                    and cp > 0 and event.get('identity') == f'Mimikyu:{cp}'
                    and valid_time and valid_samples and valid_availability and 0 <= observed <= confirmed
                    and valid_method):
                self.events.append(copy.deepcopy(event))
        self.events.sort(key=lambda e: e['confirmed_at_seconds'])

    def advance(self, at, sides):
        while self.cursor < len(self.events) and self.events[self.cursor]['confirmed_at_seconds'] <= at:
            self.pending.append(self.events[self.cursor])
            self.cursor += 1
        changed, pending = [], []
        for event in self.pending:
            side = 'mine' if event['side'] == 'mine' else 'opponent'
            mon = sides[side]['pokemon'].get(event['identity'])
            if mon is None:
                pending.append(event)
                continue
            if mon['species'].get('value') != 'Mimikyu' or mon['cp'].get('value') != event['cp']:
                continue
            # Busted Disguise persists when this same Pokemon goes to the bench.
            # Do not replace an earlier confirmed proof with a later duplicate.
            if mon['form'].get('value') == 'mimikyu_busted':
                continue
            mon['form'] = dict(value='mimikyu_busted', status='observed', observed_at_seconds=event['t'],
                confirmed_at_seconds=max(event['confirmed_at_seconds'], at),
                source_observation_seconds=event['source_observation_seconds'], method=event['method'],
                identity=event['identity'], model_build_used=False)
            if 'source_availability_seconds' in event:
                mon['form']['source_availability_seconds'] = event['source_availability_seconds']
            changed.append((side, event['identity']))
        self.pending = pending
        return changed
