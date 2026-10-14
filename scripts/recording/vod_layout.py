"""Find the phone views in a new recording, independently of battle state tracking."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from vod_media import sha256, write_json


def overlap(a, b):
    x, y, w, h = a
    xx, yy, ww, hh = b
    area = max(0, min(x + w, xx + ww) - max(x, xx)) * max(0, min(y + h, yy + hh) - max(y, yy))
    return area / max(1, min(w * h, ww * hh))


def even_crop(rect, width, height):
    """H.264 needs even dimensions; expand by one pixel where the frame allows."""
    x, y, w, h = rect
    if w % 2:
        w += 1 if x + w < width else -1
    if h % 2:
        h += 1 if y + h < height else -1
    return [x, y, w, h]


def candidate_rectangles(rgb, configs):
    """Existing screen arrangements plus strong vertical screen boundaries."""
    import numpy as np
    height, width = rgb.shape[:2]
    rectangles = []
    if .35 <= width / height <= .65:
        rectangles.append([0, 0, width, height])
    for layout in configs.values():
        source_w, source_h = layout.get('frame_size', [1920, 1080])
        for view in layout['views']:
            x, y, w, h = view['viewport']
            rectangles.append([round(x * width / source_w), round(y * height / source_h),
                               round(w * width / source_w), round(h * height / source_h)])
    # A phone edge is vertical for most of its height. Use a robust row average
    # so a small webcam or the text in a header cannot supply the whole edge.
    contrast = np.abs(np.diff(rgb.astype('float32'), axis=1)).mean(axis=2)
    strength = np.quantile(contrast, .65, axis=0)
    peaks = []
    for x in np.argsort(strength)[::-1]:
        if strength[x] < 5 or len(peaks) >= 12:
            break
        if all(abs(int(x) - prior) > max(3, width // 150) for prior in peaks):
            peaks.append(int(x) + 1)
    pairs = sorted(((strength[max(0, x - 1)] + strength[max(0, xx - 1)], x, xx)
        for x in peaks for xx in peaks if max(120, .12 * height) <= xx - x <= .62 * height), reverse=True)[:8]
    for _, x, xx in pairs:
        w = xx - x
        row_strength = np.quantile(np.abs(np.diff(rgb[:, x:xx].astype('float32'), axis=0)).mean(axis=2), .4, axis=1)
        row_peaks = []
        for y in np.argsort(row_strength)[::-1]:
            if row_strength[y] < 5 or len(row_peaks) >= 8:
                break
            if all(abs(int(y) + 1 - prior) > max(3, height // 150) for prior in row_peaks):
                row_peaks.append(int(y) + 1)
        bounds = sorted(((row_strength[y-1] + row_strength[yy-1], y, yy)
            for y in row_peaks for yy in row_peaks if 1.55 * w <= yy - y <= 2.65 * w), reverse=True)[:2]
        rectangles.extend([x, y, w, yy-y] for _, y, yy in bounds)
        for ratio in [508 / 1080, 448 / 976]:
            h = min(height, round(w / ratio))
            for y in sorted({0, round((height - h) / 2)}):
                rectangles.append([x, y, w, h])
    unique = []
    for rect in rectangles:
        rect = even_crop(rect, width, height)
        x, y, w, h = rect
        if min(x, y) >= 0 and w >= 120 and h >= 250 and x + w <= width and y + h <= height and rect not in unique:
            unique.append(rect)
    return unique


def infer_layout(video, media, reader, configs, identity, channel, cache):
    """Require repeated reads of both CP headers before accepting a crop."""
    import av
    import cv2
    from local_ocr import LocalOCR
    from segment_battles import sample_features
    fingerprint = {'source_sha256': media['sha256'], 'version': 'phone-layout-probe-v1',
                   'code_sha256': sha256(__file__),
                   'profile_sha256': {name: sha256(Path(reader) / 'profiles' / name)
                       for name in ['reis-great.json', 'henry-great.json']},
                   'templates': {k: v['views'] for k, v in configs.items()}}
    cache = Path(cache)
    if cache.is_file():
        saved = json.loads(cache.read_text(encoding='utf-8'))
        if saved.get('fingerprint') == fingerprint:
            return saved['layout']
    profiles = {name: json.loads((Path(reader) / 'profiles' / name).read_text(encoding='utf-8'))
                for name in ['reis-great.json', 'henry-great.json']}
    duration = media['duration_seconds']
    times = sorted({round(t, 3) for t in [5, 30, 60, 120, 180, 300,
        duration * .1, duration * .25, duration * .5, duration * .75, duration * .9] if 0 <= t < duration})
    scores, probes = {}, []
    ocr = LocalOCR()
    with av.open(str(video)) as source:
        stream = source.streams.video[0]
        stream.codec_context.thread_count = 4
        for at in times:
            source.seek(int(at / stream.time_base), stream=stream, backward=True)
            frame = next((f for f in source.decode(stream) if f.pts is not None and float(f.pts * f.time_base) >= at), None)
            if frame is None:
                continue
            rgb = frame.to_ndarray(format='rgb24')
            rectangles = candidate_rectangles(rgb, configs)
            probes.append({'t': float(frame.pts * frame.time_base), 'rectangles': len(rectangles)})
            for rect in rectangles:
                x, y, w, h = rect
                crop = cv2.resize(rgb[y:y+h, x:x+w], (508, 1080))
                for name, profile in profiles.items():
                    result = sample_features(crop, profile, ocr)
                    if result['hud']:
                        scores.setdefault((tuple(rect), name), []).append({'t': probes[-1]['t'],
                            'cp': result['cp'], 'party': result['party']})
    # Wide crops can still read the CP numbers while moving every party marker
    # away from its expected position. Prefer agreement on both HUD features.
    ranked = sorted(scores, key=lambda key: (sum(1 + 3 * (sum(r['party'] or []) >= 2) for r in scores[key]),
                    len(scores[key]), -key[0][2] * key[0][3]), reverse=True)
    accepted = []
    for rect, name in ranked:
        evidence = scores[(rect, name)]
        if len(evidence) < 2 or any(overlap(rect, v['viewport']) > .5 for v in accepted):
            continue
        accepted.append({'viewport': list(rect), 'base_profile': name, 'header_evidence': evidence})
    accepted.sort(key=lambda v: v['viewport'][0])
    if not accepted:
        write_json(cache.with_name('layout-review.json'), {'fingerprint': fingerprint, 'probes': probes,
            'accepted_views': 0, 'reason': 'No phone crop produced both CP headers at two separate probe times.'})
        raise ValueError('Could not locate the game screens reliably. No empty battle collection was marked successful. '
                         'See layout-review.json; a crop profile is needed for this recording.')
    for number, view in enumerate(accepted):
        view['id'] = 'pov' if len(accepted) == 1 else ['left', 'right'][number] if len(accepted) == 2 else f'view{number+1}'
    layout = {'channel': channel or 'Video', 'dataset_role': 'unassigned', 'source_ids': [identity],
        'frame_size': [media['width'], media['height']], 'views': accepted,
        'layout_method': 'repeated_cp_header_probe', 'layout_changes_verified': False,
        'notes': ['Phone crops selected from repeated visible headers; battle state and changing layouts are unverified.']}
    # Reuse the broadcast labels only when the whole detected arrangement
    # matches that template. Otherwise look for an explicit standalone REPLAY.
    for template in configs.values():
        scaled = scale_layout(template, media)
        if len(accepted) == len(scaled['views']) and scaled.get('broadcast_regions') and all(
                any(overlap(v['viewport'], known['viewport']) > .98
                    and abs(v['viewport'][2] - known['viewport'][2]) <= .03 * known['viewport'][2]
                    for known in scaled['views']) for v in accepted):
            layout['broadcast_regions'] = scaled['broadcast_regions']
            if scaled.get('fixture_regions'):
                layout['fixture_regions'] = scaled['fixture_regions']
            break
    layout.setdefault('broadcast_regions', [{'rect': [0, 0, media['width'], media['height']],
        'kind': 'replay', 'cue': 'REPLAY', 'exact_record': True}])
    write_json(cache, {'fingerprint': fingerprint, 'probes': probes, 'layout': layout})
    return layout


def scale_layout(layout, media):
    layout = copy.deepcopy(layout)
    width, height = layout.get('frame_size', [1920, 1080])
    if [width, height] != [media['width'], media['height']]:
        def scale(rect):
            x, y, w, h = rect
            return [round(x * media['width'] / width), round(y * media['height'] / height),
                    round(w * media['width'] / width), round(h * media['height'] / height)]
        for view in layout['views']:
            view['viewport'] = even_crop(scale(view['viewport']), media['width'], media['height'])
        for region in layout.get('broadcast_regions', []):
            region['rect'] = scale(region['rect'])
        if layout.get('fixture_regions'):
            layout['fixture_regions'] = [scale(rect) for rect in layout['fixture_regions']]
        layout['frame_size'] = [media['width'], media['height']]
    return layout


def resolve_layout(name, configs, identity, media, reader, video, cache, channel=None):
    if name and name != 'auto':
        if name not in configs:
            raise ValueError('Unknown screen layout')
        return scale_layout(configs[name], media)
    known = next((layout for layout in configs.values() if identity in layout['source_ids']), None)
    if known:
        return scale_layout(known, media)
    references = Path(reader) / 'reference_manifest.json'
    if references.is_file():
        ref = next((r for r in json.loads(references.read_text())['references'] if r['id'] == identity), None)
        if ref:
            return scale_layout({'channel': ref['creator'], 'dataset_role': 'unassigned', 'source_ids': [identity],
                    'views': [{'id': 'pov', 'viewport': ref['viewport'], 'base_profile': Path(ref['profile']).name}],
                    'layout_method': 'existing_source_calibration'}, media)
    return infer_layout(video, media, reader, configs, identity, channel, cache)
