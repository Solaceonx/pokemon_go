"""Read a terminal charged impact, including its centered target HP bar.

Live yellow/red HP and the delayed orange damage strip are distinct. A missing
bar alone never establishes zero. This adapter is limited to an observed last
party member, a named attack, and a continuous live-to-zero impact sequence.
"""
import gzip
import json
from pathlib import Path
import re

from vod_media import sha256, write_json


def same_bar(a, b):
    return len(a) == len(b) == 4 and all(abs(x-y) <= 6 for x, y in zip(a, b))


def measure_center(rgb, expected_width):
    import cv2
    import numpy as np
    from health_reader import read_health_bar
    bar = read_health_bar(rgb, [150, 200, 370, 900], expected_width)
    if not bar:
        return None
    x, y, right, bottom = bar['bounds']
    if abs((x+right)/2 - 254) > 28 or not 10 <= bottom-y <= 19:
        return None
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
        stop = len(live_columns)
        for i in range(len(live_columns)-1):
            if not live_columns[i] and not live_columns[i+1]:
                stop = i
                break
    if live_columns[stop+2:].sum() > 2:
        return None
    return {'bounds': bar['bounds'], 'width': len(live_columns), 'live_pixels': stop,
            'orange_pixels': int(orange_columns.sum()),
            'live_fraction': round(stop/len(live_columns), 5),
            'outline_method': bar['outline_method']}


def zero_transition(samples):
    """A stable positive bar must become outlined orange-only, then leave view.

    The orange-only measurement is not reused when live HP returns. Sparse
    observations, cuts to another rectangle and initially warm bars are rejected.
    """
    positives, zeros, anchor = [], [], None
    for i, sample in enumerate(samples):
        bar, t = sample.get('bar'), sample['t']
        if not bar:
            continue
        if bar['live_pixels'] > 2:
            if (not positives or t-positives[-1]['t'] > .12 or
                    not same_bar(bar['bounds'], positives[-1]['bar']['bounds'])):
                positives = []
            positives.append(sample)
            zeros, anchor = [], None
            continue
        if bar['live_pixels'] != 0 or bar['orange_pixels'] < 5:
            continue
        if anchor is None:
            if (len(positives) < 2 or t-positives[-1]['t'] > .25 or
                    not same_bar(bar['bounds'], positives[-1]['bar']['bounds'])):
                continue
            anchor = positives[-1]
        if (zeros and t-zeros[-1]['t'] > .12) or not same_bar(bar['bounds'], anchor['bar']['bounds']):
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


def sample_impact(folder, raw, timeline):
    import av
    import numpy as np
    import health_reader
    from public_transitions import counter_changes
    meta = json.loads((folder/'battle.json').read_text(encoding='utf-8'))
    trace = {'schema': 'terminal-impact-v1', 'accepted': False,
             'video_sha256': meta['video_sha256'], 'result_based_faints': 0,
             'code_sha256': sha256(__file__)}
    charges = timeline['charged']
    if not charges or not charges[-1]['move']:
        return {**trace, 'reason': 'No final named charged attack'}
    q = charges[-1]
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
    if not before or before[-1]['value'] != 1:
        return {**trace, 'reason': 'Victim not independently observed as last party member'}
    if any(c['value'] == 0 for c in changes if c['t'] > announced):
        return {**trace, 'reason': 'Terminal party decrease already observed'}
    profile = json.loads((raw/'profile.json').read_text(encoding='utf-8'))
    alignment = {round(r['clip_seconds'], 6): r for r in _rows(folder/'frame_alignment.jsonl.gz')}
    cache = raw/'center-impact.json'
    fingerprint = {'code': trace['code_sha256'], 'video': meta['video_sha256'],
                   'alignment': sha256(folder/'frame_alignment.jsonl.gz'),
                   'health_reader': sha256(health_reader.__file__), 'av_version': av.__version__,
                   'announcement_seconds': announced, 'width': profile['hp_width']}
    saved = json.loads(cache.read_text(encoding='utf-8')) if cache.exists() else {}
    samples = saved.get('samples') if saved.get('fingerprint') == fingerprint else None
    if samples is None:
        samples = []
        with av.open(str(folder/meta['video_file'])) as media:
            stream = media.streams.video[0]
            stream.codec_context.thread_count = 2
            media.seek(int(max(0, announced-.25)/stream.time_base), stream=stream, backward=True)
            for frame in media.decode(stream):
                if frame.time is None or frame.time < announced:
                    continue
                if frame.time > announced+5:
                    break
                point = alignment.get(round(frame.time, 6))
                if point is None:
                    raise ValueError('Centered impact frame has no source PTS alignment')
                samples.append({'t': frame.time, 'clip_pts': frame.pts,
                                'clip_time_base': str(frame.time_base),
                                'source_pts': point['source_pts'], 'source_time_base': point['source_time_base'],
                                'bar': measure_center(np.asarray(frame.to_image().resize((508, 1080))),
                                                      profile['hp_width'])})
        write_json(cache, {'fingerprint': fingerprint, 'samples': samples})
    proof = zero_transition(samples)
    trace.update(side=victim, species=targets[-1], move=q['move'], attack_side=q['side'],
                 announced_clip_seconds=announced, attack_start_clip_seconds=start,
                 sample_count=len(samples), target_counter_before=1)
    if not proof:
        return {**trace, 'reason': 'No continuous positive-to-zero live strip with disappearing tail'}
    # A camera return showing the same target alive contradicts the proposed KO.
    zero = proof['first_zero']['t']
    if any(zero+.5 <= r['t'] <= zero+3 and r[key].get('sp') == targets[-1] and
           r[key].get('hp') is not None and r[key]['hp'] > .03 for r in readings):
        return {**trace, 'reason': 'Subsequent same-target health contradicts terminal zero'}
    return {**trace, 'accepted': True, 'reason': 'Live strip drains to zero during named centered impact',
            'measurement': proof, 'live_hp_pixel_tolerance': 2,
            'faint_inference': 'sustained_zero_live_strip_and_bar_fade_without_surviving_target'}


def apply_impact(folder, raw, game):
    timeline = json.loads((game/'timeline.json').read_text(encoding='utf-8'))
    trace = sample_impact(folder, raw, timeline)
    write_json(game/'terminal-impact.json', trace)
    if not trace['accepted']:
        return trace
    origin = timeline['clip_origin_seconds']
    at = round(trace['measurement']['confirmed_zero']['t']-origin, 6)
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
