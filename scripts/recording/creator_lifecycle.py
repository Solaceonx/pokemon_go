"""Creator-only source lifecycle evidence, independent of replacement timing.

No reference labels, result screens or battle-specific corrections are inputs.
Outlined zero bars and charged impact pixels prove deaths; absent bars alone do
not. Raw observations are immutable. Typed evidence retains source frame times.
"""
import json
from pathlib import Path
from creator_impact import _rows, sample_impact, zero_transition, corroborated_empty_transition
from vod_media import write_json, sha256
from public_transitions import counter_changes


def active(timeline, side, clip_time):
    shown = [f for f in timeline['field'][side]
             if f.get('header_seen_clip_seconds', f['t']+timeline['clip_origin_seconds']) <= clip_time]
    return shown[-1]['name'] if shown else None


def jumping_bar(a, b):
    # The HP rectangle follows its Pokémon vertically during fast animations.
    return (len(a) == len(b) == 4 and abs(a[0]-b[0]) <= 6 and abs(a[2]-b[2]) <= 6
            and abs((a[3]-a[1])-(b[3]-b[1])) <= 6 and abs(a[1]-b[1]) <= 100)




def resolve_forms(game, timeline, gd):
    """Resolve a form only when named observed moves identify one legal form.

    This prevents a real release being silently replaced by model move slot 0.
    A name shared by indistinguishable forms stays unresolved.
    """
    team = json.loads((game/'team.json').read_text(encoding='utf-8'))
    resolved = []
    names = {p['speciesName']: sid for sid, p in gd.species.items()}
    for entry in team['pokemon']:
        name = entry['species']
        moves = {q['move'] for q in timeline['charged'] if q['side'] == 'mine' and q['move']
                 and active(timeline, 'mine', q['t']+timeline['clip_origin_seconds']) == name}
        legal = lambda sid: {gd.moves[m].name for m in gd.species[sid]['chargedMoves'] if m in gd.moves}
        if name not in names or not moves or moves <= legal(names[name]):
            continue
        candidates = [sid for sid, p in gd.species.items()
                      if p['speciesName'].split(' (')[0] == name.split(' (')[0] and moves <= legal(sid)]
        if len(candidates) != 1:
            continue
        actual = gd.species[candidates[0]]['speciesName']
        entry['species'] = actual
        resolved.append({'header_species': name, 'resolved_species': actual,
                         'observed_charged_moves': sorted(moves), 'method': 'unique_legal_form_for_observed_moves'})
    write_json(game/'team.json', team)
    return resolved




def measure_fighting_faints(folder, raw, timeline, rows):
    """Resolve low-bar gaps using native frames, not thresholded cached HP.

    A one-pixel surviving red strip refutes zero. Every accepted normal faint
    requires live pixels, continuous outlined zero, and fade. Mere disappearance
    and the next replacement are insufficient.
    """
    import av
    import cv2
    import numpy as np
    import health_reader
    cv2.setNumThreads(1)
    meta = json.loads((folder/'battle.json').read_text(encoding='utf-8'))
    profile = json.loads((raw/'profile.json').read_text(encoding='utf-8'))
    alignment = {round(r['clip_seconds'], 6): r for r in _rows(folder/'frame_alignment.jsonl.gz')}
    candidates = []
    for key, side in [('m', 'mine'), ('o', 'theirs')]:
        for a, b in zip(rows, rows[1:]):
            hp = a[key].get('hp')
            if hp is None or not 0 <= hp <= .12 or b[key].get('hp') not in (None, 0):
                continue
            if hp == 0 and b[key].get('hp') == 0:
                continue
            t = b['t']
            if any(abs(t-(q['t']+timeline['clip_origin_seconds'])) < 2.5 for q in timeline['charged']):
                continue
            if any(c['side'] == side and abs(c['t']-t) < 3 for c in candidates):
                continue
            candidates.append({'side': side, 't': t, 'species': active(timeline, side, a['t'])})
    proofs, deaths = [], []
    intervals = sorted(b['t']-a['t'] for a, b in zip(rows, rows[1:]) if b['t'] > a['t'])
    fps = 1/intervals[len(intervals)//2]
    for i, candidate in enumerate(candidates):
        t, side = candidate['t'], candidate['side']
        cache = raw/f'fighting-faint-{i:03d}.json'
        fingerprint = {'video': meta['video_sha256'], 'alignment': sha256(folder/'frame_alignment.jsonl.gz'),
                       'code': sha256(__file__), 'impact_code': sha256(Path(__file__).with_name('creator_impact.py')),
                       'health_reader': sha256(health_reader.__file__), 'candidate': candidate,
                       'width': profile['hp_width'], 'av_version': av.__version__, 'cv2_version': cv2.__version__}
        saved = json.loads(cache.read_text(encoding='utf-8')) if cache.exists() else {}
        samples = saved.get('samples') if saved.get('fingerprint') == fingerprint else None
        if samples is None:
            samples, last, calibrated_width = [], -1, None
            region = [5, 240, 225, 900] if side == 'mine' else [230, 240, 505, 850]
            with av.open(str(folder/meta['video_file'])) as media:
                stream = media.streams.video[0]
                stream.codec_context.thread_count = 1
                media.seek(int(max(0, t-2)/stream.time_base), stream=stream, backward=True)
                for frame in media.decode(stream):
                    if frame.time is None or frame.time < t-2 or frame.time-last < 1/15-.001:
                        continue
                    if frame.time > t+5:
                        break
                    last = frame.time
                    point = alignment.get(round(frame.time, 6))
                    if point is None:
                        raise ValueError('Fighting faint has no source frame alignment')
                    rgb = np.asarray(frame.to_image().resize((508, 1080)))
                    bar = measure_side(rgb, region, profile['hp_width'], calibrated_width)
                    if bar and bar['outline_method'] == 'edge_contour':
                        calibrated_width = bar['bounds'][2]-bar['bounds'][0]
                    replacement = next((f for f in timeline['field'][side]
                                        if f['name'] != candidate['species'] and
                                        t < f.get('header_seen_clip_seconds', f['t']+timeline['clip_origin_seconds'])
                                        <= frame.time+.5), None)
                    # A new, high-HP teammate is not a recovery of the dying
                    # target. The fresh header independently disambiguates it.
                    foreign = bool(replacement and bar and bar['live_fraction'] > .2)
                    samples.append({'t': frame.time, 'clip_pts': frame.pts, 'clip_time_base': str(frame.time_base),
                                    'source_pts': point['source_pts'], 'source_time_base': point['source_time_base'],
                                    'bar': None if foreign else bar, 'replacement_bar': foreign})
            write_json(cache, {'fingerprint': fingerprint, 'samples': samples})
        proof = zero_transition(samples, require_orange=False, minimum_positive_pixels=1,
                                geometry=jumping_bar, positive_gap=.5, zero_gap=.2, follow_motion=True)
        if not proof:
            key = 'm' if side == 'mine' else 'o'
            counts = counter_changes(rows, key, 'left', fps)
            confirmations = [b for a, b in zip(counts, counts[1:]) if b['value'] < a['value']]
            confirmations += [{'first': f['header_seen_clip_seconds']} for f in timeline['field'][side]
                              if f['name'] != candidate['species'] and
                              t < f.get('header_seen_clip_seconds', -1) <= t+5]
            proof = corroborated_empty_transition(samples, confirmations)
            if proof:
                proof['method'] = 'native_empty_bar_and_fade_with_counter_or_fresh_replacement_header'
        proofs.append({'candidate': candidate, 'accepted': proof is not None, 'measurement': proof})
        if proof:
            at = proof['first_zero']['t']
            if active(timeline, side, at) != candidate['species']:
                continue
            if any(d['side'] == side and abs(d['clip_seconds']-at) < 3 for d in deaths):
                continue
            deaths.append({'side': side, 'species': candidate['species'], 'clip_seconds': at,
                           'method': proof.get('method', 'native_fighting_live_to_zero_and_fade'),
                           'confirmed_clip_seconds': proof['confirmed_zero']['t'],
                           'timing_uncertainty_seconds': .1,
                           'first_zero': proof['first_zero'],
                           'confirmed_zero': proof['confirmed_zero']})
    return deaths, proofs


def measure_side(rgb, region, width, calibrated_width=None):
    """The same live/damage palette, without centered-camera constraints."""
    from creator_impact import measure_palette, measured_outline
    bar = measured_outline(rgb, region, width, calibrated_width)
    if not bar or not 10 <= bar['bounds'][3]-bar['bounds'][1] <= 19:
        return None
    return measure_palette(rgb, bar)


def apply_lifecycle(folder, raw, game, gd):
    timeline = json.loads((game/'timeline.json').read_text(encoding='utf-8'))
    rows = _rows(raw/'readings-refined.jsonl.gz')
    deaths, fighting_proofs = measure_fighting_faints(folder, raw, timeline, rows)
    impacts = []
    for i, q in enumerate(timeline['charged']):
        if not q['move']:
            continue
        proof = sample_impact(folder, raw, timeline, i, terminal_only=False)
        impacts.append(proof)
        if proof.get('accepted'):
            at = proof['measurement']['first_zero']['t']
            if not any(d['side'] == proof['side'] and abs(d['clip_seconds']-at) < 3 for d in deaths):
                deaths.append({'side': proof['side'], 'species': proof['species'], 'clip_seconds': at,
                               'method': proof['measurement'].get('method', 'centered_positive_to_zero_and_fade'),
                               'confirmed_clip_seconds': proof['measurement']['confirmed_zero']['t'],
                               'timing_uncertainty_seconds': .1})
    forms = resolve_forms(game, timeline, gd)
    looks = _rows(game/'observations.jsonl')
    quarantined = []
    for side, key, prefix in [('mine', 'm', 'my'), ('theirs', 'o', 'foe')]:
        counts = timeline['left'][side]
        for previous, change in zip(counts, counts[1:]):
            at = change[0] + timeline['clip_origin_seconds']
            name = active(timeline, side, at)
            # A party decrement cannot belong to an active that is still
            # visibly alive several seconds later without a change of stint.
            future = [r for r in rows if at+3 <= r['t'] <= at+6
                      and active(timeline, side, r['t']) == name
                      and (r[key].get('hp') or 0) > .12]
            replaced = any(at < f['t']+timeline['clip_origin_seconds'] <= at+6
                           for f in timeline['field'][side])
            stint = max((f['t']+timeline['clip_origin_seconds'] for f in timeline['field'][side]
                         if f['t']+timeline['clip_origin_seconds'] <= at), default=at)
            if change[1] < previous[1] and len(future) >= 3 and not replaced and at-stint > 3:
                quarantined.append({'side': side, 'clip_seconds': at, 'species': name,
                                    'reason': 'decrement contradicted by surviving unchanged active',
                                    'corroborating_live_frames': len(future)})
                for look in looks:
                    if look['t'] >= change[0]:
                        look.pop(prefix+'_left', None)
                break
    for look in looks:
        for f in forms:
            if look.get('my_species') == f['header_species']:
                look['my_species'] = f['resolved_species']
    for d in deaths:
        t = round(d['clip_seconds']-timeline['clip_origin_seconds'], 6)
        prefix = 'my' if d['side'] == 'mine' else 'foe'
        name = next((f['resolved_species'] for f in forms if f['header_species'] == d['species']), d['species']) if prefix == 'my' else d['species']
        # Standalone evidence look ensures the zero is attached to the dying
        # identity even when the replacement header is delayed or absent.
        looks.append({'t': t, prefix+'_species': name, prefix+'_hp': 0,
                      prefix+'_fainted': True, 'note': 'source measured zero; creator-lifecycle.json'})
    looks.sort(key=lambda r: r['t'])
    (game/'observations.jsonl').write_bytes(''.join(json.dumps(r)+'\n' for r in looks).encode('utf-8'))
    write_json(game/'creator-lifecycle.json', {'schema': 'creator-lifecycle-v1', 'faints': deaths,
               'charged_impact_probes': impacts, 'forms': forms, 'quarantined_counters': quarantined,
               'fighting_faint_probes': fighting_proofs,
               'result_based_faints': 0})
    return deaths
