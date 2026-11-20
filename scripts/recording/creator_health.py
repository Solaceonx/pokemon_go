"""Version-pinned, source-aligned health/header measurements for creator clips."""
import gzip
import hashlib
import inspect
import io
import json
from pathlib import Path

from native_health import acquisition_digest, measure_frame, measure_with_recent_geometry, header_panels, scene_features
from vod_media import sha256, write_json


def rows(path):
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        return [json.loads(line) for line in stream if line.strip()]


def acquire(folder, raw, sample_hz=12):
    """Measure at native-aligned high cadence, retaining immutable OCR context.

    Twelve samples/second resolve half-second fast moves. New sample PTS come
    from the full saved frame alignment; OCR context is only from past frames.
    """
    import av
    import cv2
    import numpy as np
    import PIL
    cv2.setNumThreads(1)
    meta = json.loads((folder/'battle.json').read_text(encoding='utf-8'))
    profile = json.loads((raw/'profile.json').read_text(encoding='utf-8'))
    fingerprint = {'schema': 'native-health-acquisition-v2', 'video_sha256': meta['video_sha256'],
                   'context_sha256': sha256(raw/'screen.jsonl.gz'),
                   'alignment_sha256': sha256(folder/'frame_alignment.jsonl.gz'),
                   'measurement_code_sha256': acquisition_digest(), 'sample_hz': sample_hz,
                   'sampler_code_sha256': hashlib.sha256(inspect.getsource(acquire).replace('\r\n', '\n').encode()).hexdigest(),
                   'expected_width': profile['hp_width'], 'normalization': [508, 1080],
                   'av': av.__version__, 'cv2': cv2.__version__, 'numpy': np.__version__, 'PIL': PIL.__version__}
    target, receipt = raw/f'native-health-{sample_hz}hz.jsonl.gz', raw/f'native-health-{sample_hz}hz-acquisition.json'
    if target.exists() and receipt.exists():
        saved = json.loads(receipt.read_text(encoding='utf-8'))
        if saved.get('fingerprint') == fingerprint and saved.get('data_sha256') == sha256(target):
            return target
    source = iter(rows(raw/'screen.jsonl.gz'))
    wanted, context = next(source, None), None
    aligned = {round(r['clip_seconds'], 6): r for r in rows(folder/'frame_alignment.jsonl.gz')}
    temporary = target.with_name(target.name+'.incomplete')
    count, next_time = 0, None
    recent_geometry = []
    with temporary.open('wb') as binary, gzip.GzipFile(filename='', fileobj=binary, mode='wb', mtime=0) as packed, io.TextIOWrapper(packed, encoding='utf-8', newline='\n') as output, av.open(str(folder/meta['video_file'])) as media:
        stream = media.streams.video[0]
        stream.codec_context.thread_count = 1
        for index, frame in enumerate(media.decode(stream)):
            if frame.time is None:
                continue
            while wanted is not None and wanted['frame_index'] <= index:
                context, wanted = wanted, next(source, None)
            if next_time is None:
                next_time = frame.time
            if frame.time+1e-6 < next_time:
                continue
            while next_time <= frame.time+1e-6:
                next_time += 1/sample_hz
            point = aligned.get(round(frame.time, 6))
            if point is None or point.get('clip_pts', frame.pts) != frame.pts:
                raise ValueError('High-cadence health sample lacks original frame alignment')
            rgb = np.asarray(frame.to_image().resize((508, 1080)))
            anchors = []
            if context is not None:
                for side, key in [('mine', 'mine'), ('theirs', 'opponent')]:
                    cp = context[key]['cp']
                    bounds = cp.get('evidence', {}).get('bounds_normalized_frame')
                    seen = cp.get('evidence', {}).get('observed_at_seconds')
                    if cp.get('value') is not None and bounds and seen is not None and 0 <= frame.time-seen <= .9:
                        anchors.append({'side': side, 'bounds': bounds})
            recent_geometry = [r for r in recent_geometry if 0 < frame.time-r['t'] <= .25]
            health = measure_with_recent_geometry(rgb, profile['hp_width'], recent_geometry, frame.time)
            measurement = {'t': frame.time, 'frame_index': index,
                'context_frame_index': context['frame_index'] if context else None,
                'clip_pts': frame.pts, 'clip_time_base': str(frame.time_base),
                'source_pts': point['source_pts'], 'source_time_base': point['source_time_base'],
                'health': health, 'header_panels': header_panels(rgb, anchors),
                'scene': scene_features(rgb)}
            recent_geometry.append(dict(t=frame.time, health=health))
            output.write(json.dumps(measurement, separators=(',', ':'))+'\n')
            count += 1
    if wanted is not None:
        raise ValueError('Video ended before the cached context ordinals')
    temporary.replace(target)
    write_json(receipt, {'fingerprint': fingerprint, 'data_sha256': sha256(target),
                         'sampled_frames': count, 'raw_logs_modified': False})
    return target


def derive(folder, raw, base_path, phase_timeline):
    """Produce a new slim input; originals remain unchanged and hash-pinned."""
    import copy
    from creator_observations import interpret_measurements, health_owners, shield_readbacks
    path = acquire(folder, raw)
    native, counters = interpret_measurements(rows(path))
    old = rows(base_path)
    index = -1
    result, coverage = [], {s: 0 for s in ['mine', 'theirs']}
    for measurement in native:
        while index+1 < len(old) and old[index+1]['t'] <= measurement['t']+1e-6:
            index += 1
        if index < 0:
            continue
        row = copy.deepcopy(old[index])
        context_time = row['t']
        fresh = abs(context_time-measurement['t']) <= 1e-5
        # Keep the assembler's original OCR cadence. Repeating an old label at
        # 12 Hz would incorrectly count it as multiple independent witnesses.
        # The separate native stream retains all high-cadence HP evidence.
        if not fresh:
            continue
        row.update(t=measurement['t'], source_context_seconds=context_time)
        if not fresh:
            row.update(phase=None, result=None, cm=[])
        row['buttons_observed_at_seconds'] = context_time
        measured = health_owners(measurement, phase_timeline)
        for side, key in [('mine', 'm'), ('theirs', 'o')]:
            value = row[key]
            if not fresh:
                value.update(sp=None, cp=None)
            bar = measured[side]
            attributable = bar and (not bar.get('camera_species') or bar['camera_species'] == value.get('sp'))
            value['live_hp_fraction'] = (bar['fraction'] if attributable and bar['fraction'] > 0 else None)
            value['measured_live_hp_fraction'] = bar['fraction'] if bar else None
            value['hp_fraction_interval'] = bar['fraction_interval'] if bar else None
            value['hp'] = value['live_hp_fraction']
            value['w'] = bar['interior_width_pixels'] if bar else None
            if bar:
                colors = bar['live_color_pixels']
                color = max(colors, key=colors.get)
                value['seg'] = [[color, bar['live_pixels']]]
                value['damage_trail_pixels'] = bar['damage_pixels']
                coverage[side] += 1
            else:
                value['seg'] = None
            value['left'] = measurement['headers'][side]['party']['value']
            value['sh'] = measurement['headers'][side]['shields']['value']
        result.append(row)
    target = raw/'readings-live-health.jsonl.gz'
    target.write_bytes(gzip.compress(''.join(json.dumps(r, separators=(',', ':'))+'\n' for r in result).encode('utf-8'), mtime=0))
    audit = {'schema': 'creator-live-health-input-v1', 'native_measurements_sha256': sha256(path),
             'base_readings_sha256': sha256(base_path), 'derived_sha256': sha256(target),
             'measurement_acquisition': json.loads(path.with_name('native-health-12hz-acquisition.json').read_text(encoding='utf-8')),
             'sampled_frames': len(result), 'health_measurements': coverage, 'counters': counters,
             'zero_hp_is_not_independent_faint_evidence': True, 'raw_logs_modified': False}
    audit['shield_readbacks'] = shield_readbacks(native,phase_timeline)
    controls = raw/'native-controls-acquisition.json'
    if controls.exists():
        audit['charge_controls_acquisition'] = json.loads(controls.read_text(encoding='utf-8'))
    identities = raw/'native-identities-3hz-acquisition.json'
    if identities.exists():
        audit['identity_acquisition'] = json.loads(identities.read_text(encoding='utf-8'))
    labels = raw/'native-direct-labels-acquisition.json'
    if labels.exists():
        audit['move_label_acquisition'] = json.loads(labels.read_text(encoding='utf-8'))
    return target, audit
