"""Read charged impacts, including the centered target HP bar.

Live yellow/red HP and the delayed orange damage strip are distinct. A missing
bar alone never establishes zero. A camera cut to zero needs a complete
physical outline and independent target/counter evidence, followed by fade.
"""
import gzip
import json
from pathlib import Path
import re

from vod_media import sha256, write_json


def same_bar(a, b):
    return len(a) == len(b) == 4 and all(abs(x-y) <= 6 for x, y in zip(a, b))


def measure_center(rgb, expected_width, calibrated_width=None):
    import cv2
    import numpy as np
    bar = measured_outline(rgb, [150, 200, 370, 900], expected_width, calibrated_width)
    if not bar:
        return None
    x, y, right, bottom = bar['bounds']
    if abs((x+right)/2 - 254) > 28 or not 10 <= bottom-y <= 19:
        return None
    return measure_palette(rgb, bar)


def measured_outline(rgb, region, expected_width, calibrated_width=None):
    """Prefer a complete measured rectangle over a right-anchored width guess.

    Broadcast scaling changes true width. A guessed left edge can crop away
    the last live pixels and manufacture a zero, even with a perfect palette.
    """
    from health_reader import read_health_bar
    import cv2
    import numpy as np
    widths = list(dict.fromkeys([expected_width, expected_width+10, expected_width-10] +
                               ([calibrated_width] if calibrated_width else [])))
    candidates = [b for width in widths
                  if (b := read_health_bar(rgb, region, width))]
    edges = [b for b in candidates if b['outline_method'] == 'edge_contour']
    if edges:
        return min(edges, key=lambda b: abs((b['bounds'][2]-b['bounds'][0])-expected_width))
    if calibrated_width:
        matched = [b for b in candidates if abs(b['bounds'][2]-b['bounds'][0]-calibrated_width) <= 1]
        if matched:
            return matched[0]
    for bar in candidates:
        x, y, right, bottom = bar['bounds']
        hsv = cv2.cvtColor(rgb[max(0, y-1):bottom+1, max(0, x-1):right+1], cv2.COLOR_RGB2HSV)
        pale = ((hsv[:, :, 1] < 100) & (hsv[:, :, 2] > 150)) | (
            (hsv[:, :, 0] >= 15) & (hsv[:, :, 0] <= 40) & (hsv[:, :, 2] > 160))
        # Both physical side rails must exist at the inferred positions. A
        # right-anchored rail through a live red strip fails the left-rail test.
        if pale[3:-3, :3].mean(axis=0).max() >= .65 and pale[3:-3, -3:].mean(axis=0).max() >= .65:
            return bar
    # Unvalidated fixed-width rails must not establish a faint.
    return None


def measure_palette(rgb, bar):
    import cv2
    import numpy as np
    x, y, right, bottom = bar['bounds']
    hsv = cv2.cvtColor(rgb[y+3:bottom-3, x+3:right-3], cv2.COLOR_RGB2HSV)
    vivid = (hsv[:, :, 1] > 90) & (hsv[:, :, 2] > 150)
    live = vivid & (((hsv[:, :, 0] >= 65) & (hsv[:, :, 0] <= 105)) |
                    ((hsv[:, :, 0] >= 26) & (hsv[:, :, 0] <= 40)) |
                    (hsv[:, :, 0] <= 9) | (hsv[:, :, 0] >= 170))
    pending = vivid & (hsv[:, :, 0] >= 14) & (hsv[:, :, 0] <= 24)
    live_columns, orange_columns = live.mean(axis=0) >= .5, pending.mean(axis=0) >= .5
    # Live HP must begin at the left end; particles farther right are not HP.
    stop = 0
    if live_columns[:3].any():
        leading = int(np.flatnonzero(live_columns)[0])
        stop = len(live_columns)
        for i in range(leading, len(live_columns)-1):
            if not live_columns[i] and not live_columns[i+1]:
                stop = i
                break
    elif live_columns.any():
        return None  # an offset live sliver cannot be called an empty bar
    if live_columns[stop+2:].sum() > 2:
        return None
    return {'bounds': bar['bounds'], 'width': len(live_columns), 'live_pixels': stop,
            'orange_pixels': int(orange_columns.sum()),
            'live_fraction': round(stop/len(live_columns), 5),
            'outline_method': bar['outline_method']}


def zero_transition(samples, *, require_orange=True, minimum_positive_pixels=3,
                    geometry=same_bar, positive_gap=.12, zero_gap=.12, follow_motion=False):
    """A stable positive bar must become outlined orange-only, then leave view.

    The orange-only measurement is not reused when live HP returns. Sparse
    observations, cuts to another rectangle and initially warm bars are rejected.
    """
    positives, zeros, anchor = [], [], None
    for i, sample in enumerate(samples):
        bar, t = sample.get('bar'), sample['t']
        if not bar:
            continue
        if bar['live_pixels'] >= minimum_positive_pixels:
            if (not positives or t-positives[-1]['t'] > positive_gap or
                    not geometry(bar['bounds'], positives[-1]['bar']['bounds'])):
                positives = []
            positives.append(sample)
            zeros, anchor = [], None
            continue
        if bar['live_pixels'] != 0 or (require_orange and bar['orange_pixels'] < 5):
            continue
        if anchor is None:
            if (len(positives) < 2 or t-positives[-1]['t'] > .25 or
                    not geometry(bar['bounds'], positives[-1]['bar']['bounds'])):
                continue
            anchor = positives[-1]
        reference = zeros[-1] if follow_motion and zeros else anchor
        if (zeros and t-zeros[-1]['t'] > zero_gap) or not geometry(bar['bounds'], reference['bar']['bounds']):
            zeros, anchor = [], None
            continue
        zeros.append(sample)
        if len(zeros) < 3 or t-zeros[0]['t'] < .10:
            continue
        tail = samples[i+1:]
        # Allow a shrinking/fading bar, but never a surviving live strip, a new
        # geometry masquerading as the old bar, or a clip ending at the impact.
        if not tail or tail[-1]['t'] < t+1.5:
            continue
        near = [s for s in tail if s['t'] <= t+2]
        if any(s.get('bar') and s['bar']['live_pixels'] > 0 for s in near):
            continue
        missing = [s for s in near if s['t'] >= t+.5 and s.get('bar') is None]
        if len(missing) < 3 or missing[-1]['t']-missing[0]['t'] < .2:
            continue
        return {'positive': anchor, 'first_zero': zeros[0], 'confirmed_zero': sample,
                'zero_samples': len(zeros), 'missing_tail_samples': len(missing)}
    return None


def _rows(path):
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rt', encoding='utf-8') as stream:
        return [json.loads(line) for line in stream if line.strip()]


def corroborated_empty_transition(samples, decreases):
    """A camera can cut directly to an already empty target bar.

    Require multiple real outlined empty measurements followed by fade AND an
    independently stable party decrement local to that impact. The decrement
    confirms death; the first outlined zero dates it. No result screen input.
    """
    for i, sample in enumerate(samples):
        bar, t = sample.get('bar'), sample['t']
        if not bar or bar['live_pixels'] != 0:
            continue
        same = [s for s in samples[i+1:] if 0 < s['t']-t <= .25 and s.get('bar')
                and s['bar']['live_pixels'] == 0 and abs(s['bar']['width']-bar['width']) <= 6]
        if not same or not any(t-1 <= c['first'] <= t+3 for c in decreases):
            continue
        tail = [s for s in samples[i+1:] if t+.5 <= s['t'] <= t+1.5]
        if len(tail) < 3 or any(s.get('bar') and s['bar']['live_pixels'] > 0 for s in tail):
            continue
        if sum(s.get('bar') is None for s in tail) < 3:
            continue
        return {'first_zero': sample, 'confirmed_zero': same[0],
                'method': 'outlined_empty_target_and_independent_party_decrement',
                'zero_samples': len(same)+1}
    return None


def complete_empty_target(samples, after):
    """An independently known last target can already be empty at camera cut.

    Only complete physical outlines qualify, after the release announcement.
    Multiple zero frames and subsequent fade are required. No width-guessed
    rail or result screen can supply the missing zero observation.
    """
    for i, sample in enumerate(samples):
        bar, t = sample.get('bar'), sample['t']
        if t < after or not bar or bar['outline_method'] != 'edge_contour' or bar['live_pixels']:
            continue
        zeros = [s for s in samples[i+1:] if 0 < s['t']-t <= .3 and s.get('bar')
                 and s['bar']['outline_method'] == 'edge_contour' and s['bar']['live_pixels'] == 0
                 and same_bar(bar['bounds'], s['bar']['bounds'])]
        if len(zeros) < 2 or zeros[-1]['t']-t < .1:
            continue
        tail = [s for s in samples[i+1:] if t+.5 <= s['t'] <= t+2]
        if not tail or tail[-1]['t'] < t+1.5 or any(s.get('bar') and s['bar']['live_pixels'] > 0 for s in tail):
            continue
        missing = [s for s in tail if s.get('bar') is None]
        if len(missing) >= 3 and missing[-1]['t']-missing[0]['t'] >= .2:
            return {'first_zero': sample, 'confirmed_zero': zeros[1],
                    'method': 'complete_empty_centered_target_and_fade_after_named_attack'}
    return None


def sample_impact(folder, raw, timeline, charge_index=-1, terminal_only=True):
    import av
    import numpy as np
    import health_reader
    from public_transitions import counter_changes
    meta = json.loads((folder/'battle.json').read_text(encoding='utf-8'))
    trace = {'schema': 'terminal-impact-v1', 'accepted': False,
             'video_sha256': meta['video_sha256'], 'result_based_faints': 0,
             'code_sha256': sha256(__file__)}
    charges = timeline['charged']
    if not charges or not charges[charge_index]['move']:
        return {**trace, 'reason': 'No final named charged attack'}
    q = charges[charge_index]
    origin = timeline['clip_origin_seconds']
    start = origin + q['t']
    victim = 'theirs' if q['side'] == 'mine' else 'mine'
    caster = [f['name'] for f in timeline['field'][q['side']] if origin+f['t'] <= start+.5]
    targets = [f['name'] for f in timeline['field'][victim] if origin+f['t'] <= start+.5]
    if not caster or not targets:
        return {**trace, 'reason': 'Active identities unavailable'}
    canon = lambda text: re.sub('[^a-z]', '', text.lower())
    texts = _rows(raw/'text.jsonl.gz')
    hits = [r['t'] for r in texts if start <= r['t'] <= start+20 and
            all(s in canon(' '.join(part for _, part in r['text'])) for s in
                ['used', canon(caster[-1]), canon(q['move'])])]
    if not hits:
        return {**trace, 'reason': 'No matching named attack announcement'}
    announced = min(hits)
    readings = _rows(raw/'readings-refined.jsonl.gz')
    intervals = sorted(b['t']-a['t'] for a, b in zip(readings, readings[1:]) if b['t'] > a['t'])
    if not intervals:
        return {**trace, 'reason': 'No continuous party-counter evidence'}
    key = 'o' if victim == 'theirs' else 'm'
    changes = counter_changes(readings, key, 'left', 1/intervals[len(intervals)//2])
    before = [c for c in changes if c['t'] <= announced]
    if terminal_only and (not before or before[-1]['value'] != 1):
        return {**trace, 'reason': 'Victim not independently observed as last party member'}
    if terminal_only and any(c['value'] == 0 for c in changes if c['t'] > announced):
        return {**trace, 'reason': 'Terminal party decrease already observed'}
    profile = json.loads((raw/'profile.json').read_text(encoding='utf-8'))
    alignment = {round(r['clip_seconds'], 6): r for r in _rows(folder/'frame_alignment.jsonl.gz')}
    cache = raw/('center-impact.json' if terminal_only else f'center-impact-{charge_index:03d}.json')
    fingerprint = {'code': trace['code_sha256'], 'video': meta['video_sha256'],
                   'alignment': sha256(folder/'frame_alignment.jsonl.gz'),
                   'health_reader': sha256(health_reader.__file__), 'av_version': av.__version__,
                   'announcement_seconds': announced, 'width': profile['hp_width']}
    saved = json.loads(cache.read_text(encoding='utf-8')) if cache.exists() else {}
    samples = saved.get('samples') if saved.get('fingerprint') == fingerprint else None
    if samples is None:
        samples = []
        last_sample = -1.0
        calibrated_width = None
        with av.open(str(folder/meta['video_file'])) as media:
            stream = media.streams.video[0]
            stream.codec_context.thread_count = 2
            media.seek(int(max(0, announced-.25)/stream.time_base), stream=stream, backward=True)
            for frame in media.decode(stream):
                if frame.time is None or frame.time < announced:
                    continue
                if frame.time > announced+5:
                    break
                if not terminal_only and frame.time-last_sample < 1/15-.001:
                    continue
                last_sample = frame.time
                point = alignment.get(round(frame.time, 6))
                if point is None:
                    raise ValueError('Centered impact frame has no source PTS alignment')
                bar = measure_center(np.asarray(frame.to_image().resize((508, 1080))),
                                     profile['hp_width'], calibrated_width)
                if bar and bar['outline_method'] == 'edge_contour':
                    calibrated_width = bar['bounds'][2]-bar['bounds'][0]
                samples.append({'t': frame.time, 'clip_pts': frame.pts,
                                'clip_time_base': str(frame.time_base),
                                'source_pts': point['source_pts'], 'source_time_base': point['source_time_base'],
                                'bar': bar})
        write_json(cache, {'fingerprint': fingerprint, 'samples': samples})
    proof = zero_transition(samples)
    if not proof and before and before[-1]['value'] == 1:
        proof = complete_empty_target(samples, announced+1)
    if not proof and not terminal_only:
        local = [b for a, b in zip(changes, changes[1:])
                 if b['value'] < a['value'] and start <= b['first'] <= announced+5]
        proof = corroborated_empty_transition(samples, local)
    trace.update(side=victim, species=targets[-1], move=q['move'], attack_side=q['side'],
                 announced_clip_seconds=announced, attack_start_clip_seconds=start,
                 sample_count=len(samples), target_counter_before=before[-1]['value'] if before else None)
    if not proof:
        return {**trace, 'reason': 'No continuous positive-to-zero live strip with disappearing tail'}
    # A camera return showing the same target alive contradicts the proposed KO.
    zero = proof['first_zero']['t']
    if any(zero+.5 <= r['t'] <= zero+3 and r[key].get('sp') == targets[-1] and
           r[key].get('hp') is not None and r[key]['hp'] > .03 for r in readings):
        return {**trace, 'reason': 'Subsequent same-target health contradicts terminal zero'}
    return {**trace, 'accepted': True, 'reason': proof.get('method', 'Live strip drains to zero during named centered impact'),
            'measurement': proof, 'live_hp_pixel_tolerance': 2,
            'faint_inference': proof.get('method', 'sustained_zero_live_strip_and_bar_fade_without_surviving_target')}


def apply_impact(folder, raw, game):
    timeline = json.loads((game/'timeline.json').read_text(encoding='utf-8'))
    trace = sample_impact(folder, raw, timeline)
    write_json(game/'terminal-impact.json', trace)
    if not trace['accepted']:
        return trace
    origin = timeline['clip_origin_seconds']
    at = round(trace['measurement']['first_zero']['t']-origin, 6)
    looks = _rows(game/'observations.jsonl')
    attack_field = 'my_charged' if trace['attack_side'] == 'mine' else 'foe_charged'
    attacks = [r for r in looks if r.get(attack_field) and
               r['t'] >= trace['attack_start_clip_seconds']-origin-.5]
    if len(attacks) != 1:
        trace.update(accepted=False, reason='Final charge cannot be uniquely linked to tracker look')
        write_json(game/'terminal-impact.json', trace)
        return trace
    attack = attacks[0]
    looks.remove(attack)
    # The prior fallback placed an unresolved final charge at the result screen.
    # Its source-measured impact supplies its actual resolution time instead.
    attack['t'] = at
    prefix = 'foe' if trace['side'] == 'theirs' else 'my'
    attack.update({prefix+'_hp': 0.0, prefix+'_left': 0,
                   'note': 'source-measured centered terminal impact; no result-derived damage'})
    previous = max((r['t'] for r in looks if r['t'] < at), default=at)
    attack['paused'] = round(max(0, at-previous-10), 6)
    looks.append(attack)
    for r in looks:
        if r['t'] >= at and prefix+'_left' in r:
            r[prefix+'_left'] = 0
    (game/'observations.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in sorted(looks, key=lambda x:x['t'])),
                                           encoding='utf-8')
    trace['tracker_seconds'] = at
    write_json(game/'terminal-impact.json', trace)
    return trace


def record_faint(game, trace):
    """Attach the measured terminal faint when no replacement header follows."""
    if not trace.get('accepted'):
        return
    path = game/'events.jsonl'
    events = _rows(path)
    kind = 'foe_faint' if trace['side'] == 'theirs' else 'my_faint'
    at = trace['tracker_seconds']
    if any(e['event'] == kind and abs(e['t']-at) < 3 for e in events):
        return
    events.append({'t': at, 'event': kind, 'next': None, 'species': trace['species'],
                   'known_from': 'centered_impact_pixels', 'evidence_file': 'terminal-impact.json'})
    path.write_text(''.join(json.dumps(e)+'\n' for e in sorted(events, key=lambda x:x['t'])), encoding='utf-8')
    track = json.loads((game/'track.json').read_text(encoding='utf-8'))
    track.setdefault('events', {})[kind] = track.get('events', {}).get(kind, 0)+1
    write_json(game/'track.json', track)
