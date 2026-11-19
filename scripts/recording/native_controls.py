"""Source-measured charge discs and exact local OCR of their move labels.

The cache contains recognized game vocabulary and numeric pixel features only.
Unmatched OCR and images stay out of the exported data. No moveset is supplied.
"""
import gzip
import hashlib
import json
import re
from pathlib import Path
from vod_media import sha256, write_json


def charge_discs(rgb):
    import cv2
    import numpy as np
    from buttons import one
    gray = cv2.cvtColor(rgb[875:1055], cv2.COLOR_RGB2GRAY)
    circles = cv2.HoughCircles(gray, cv2.HOUGH_GRADIENT, dp=1, minDist=35,
                              param1=90, param2=24, minRadius=28, maxRadius=56)
    if circles is None:
        return {'status': 'unknown', 'discs': []}
    found = [(float(x), float(y)+875, float(r)) for x, y, r in circles[0]
             if y+875+1.25*r < rgb.shape[0]]
    left = [c for c in found if 105 <= c[0] <= 205 and 905 <= c[1] <= 1015]
    right = [c for c in found if 303 <= c[0] <= 403 and 905 <= c[1] <= 1015]
    pairs = [(a, b) for a in left for b in right if abs(a[1]-b[1]) <= 12
             and abs(a[0]+b[0]-508) <= 32 and 145 <= b[0]-a[0] <= 255]
    if len(pairs) != 1:
        return {'status': 'ambiguous' if pairs else 'unknown', 'discs': []}
    discs = []
    for index, (cx, cy, radius) in enumerate(pairs[0]):
        d = one(rgb, cx, cy, radius)
        angles = np.linspace(0, 2*np.pi, 72, endpoint=False)
        xs = np.rint(cx+radius*np.cos(angles)).astype(int)
        ys = np.rint(cy+radius*np.sin(angles)).astype(int)
        rim = rgb[ys, xs].astype(int)
        white = float(((rim.min(1) > 190) & (rim.max(1)-rim.min(1) < 65)).mean())
        reliable = d['rim'] >= .6 and d['lopsided'] < .15
        discs.append({'id': f'charge_{index}', 'center': [round(cx, 2), round(cy, 2)],
            'radius': round(radius, 2), 'geometry': 'paired_physical_circles',
            'measurement': d, 'status': 'observed' if reliable else 'unknown',
            'fill_interval': [round(max(0, d['fill']-.08), 3), round(min(1, d['fill']+.08), 3)] if reliable else None,
            'ready': True if white >= .7 else None, 'white_rim_fraction': round(white, 3)})
    return {'status': 'observed', 'discs': discs}


def move_vocabulary(gamemaster):
    table = {}
    for m in gamemaster['moves']:
        if m['energy'] <= 0:
            continue
        name = re.sub(r'\s*\([^)]*\)', '', m['name'])
        key = re.sub('[^A-Z]', '', name.upper())
        table.setdefault(key, []).append({'name': name, 'cost': m['energy']})
    return {k: values[0] for k, values in table.items()
            if len({v['cost'] for v in values}) == 1}


def acquire_controls(folder, raw):
    import av
    import cv2
    import numpy as np
    import local_ocr  # Configure the existing project-local OCR runtime.
    from rapidocr_onnxruntime import RapidOCR
    from creator_health import rows
    cv2.setNumThreads(1)
    root = Path(__file__).resolve().parents[2]
    gm = root/'data/gamemaster.json'
    meta = json.loads((folder/'battle.json').read_text(encoding='utf-8'))
    fingerprint = {'schema': 'native-charge-controls-v1', 'sample_hz': 6, 'label_hz': 1,
        'video_sha256': meta['video_sha256'], 'context_sha256': sha256(raw/'screen-refined.jsonl.gz'),
        'code_sha256': sha256(__file__), 'disc_code_sha256': sha256(root/'scripts/recording/buttons.py'),
        'gamemaster_sha256': sha256(gm), 'av': av.__version__, 'cv2': cv2.__version__}
    target, receipt = raw/'native-controls-6hz.jsonl.gz', raw/'native-controls-acquisition.json'
    if target.exists() and receipt.exists():
        saved = json.loads(receipt.read_text(encoding='utf-8'))
        if saved.get('fingerprint') == fingerprint and saved.get('data_sha256') == sha256(target):
            return target
    vocabulary = move_vocabulary(json.loads(gm.read_text(encoding='utf-8')))
    engine = RapidOCR(intra_op_num_threads=1, inter_op_num_threads=1, use_cls=False)
    context = rows(raw/'screen-refined.jsonl.gz'); cursor = -1
    alignment = {round(r['clip_seconds'], 6): r for r in rows(folder/'frame_alignment.jsonl.gz')}
    result, next_time, next_label = [], None, 0
    label_runs, physical_pair = {}, None
    with av.open(str(folder/meta['video_file'])) as media:
        stream = media.streams.video[0]; stream.codec_context.thread_count = 1
        for frame in media.decode(stream):
            if frame.time is None:
                continue
            if next_time is None:
                next_time = frame.time
            if frame.time+1e-6 < next_time:
                continue
            while next_time <= frame.time+1e-6:
                next_time += 1/6
            while cursor+1 < len(context) and context[cursor+1]['timestamp_seconds'] <= frame.time+1e-6:
                cursor += 1
            rgb = np.asarray(frame.to_image().resize((508, 1080)))
            measured = charge_discs(rgb)
            if measured['status'] == 'observed':
                physical_pair = (frame.time, measured['discs'])
            elif physical_pair and frame.time-physical_pair[0] <= .5:
                from buttons import one
                fallback = []
                for saved in physical_pair[1]:
                    cx, cy = saved['center']
                    d = one(rgb, cx, cy, saved['radius'])
                    if d['rim'] < .75 or d['lopsided'] >= .08:
                        break
                    fallback.append({**saved, 'measurement': d, 'status': 'observed',
                        'geometry': 'recent_physical_circle_with_fresh_edge_test',
                        'geometry_observed_at_seconds': physical_pair[0],
                        'fill_interval': [round(max(0, d['fill']-.08), 3), round(min(1, d['fill']+.08), 3)],
                        'ready': True if d['ready'] else None})
                if len(fallback) == 2:
                    measured = {'status': 'observed', 'discs': fallback}
            typed = []
            owner = context[cursor]['mine'] if cursor >= 0 else {}
            species = owner.get('species', {}); cp = owner.get('cp', {}).get('value')
            seen = species.get('evidence', {}).get('observed_at_seconds')
            identity = (species.get('value'), cp) if seen is not None and 0 <= frame.time-seen <= .75 else None
            if measured['status'] == 'observed' and frame.time >= next_label:
                next_label = frame.time+1
                for d in measured['discs']:
                    previous_label = label_runs.get((identity, d['id'])) if identity else None
                    if previous_label and previous_label['count'] >= 2 and frame.time-previous_label['last'] < 10:
                        continue
                    cx, cy = d['center']; r = d['radius']
                    x, y = max(0, round(cx-105)), min(1080, round(cy+r+2))
                    crop = rgb[y:min(1080, y+56), x:min(508, round(cx+105))]
                    if min(crop.shape[:2]) < 8:
                        continue
                    recognized, _ = engine(cv2.cvtColor(crop, cv2.COLOR_RGB2BGR))
                    for polygon, text, confidence in recognized or []:
                        key = re.sub('[^A-Z]', '', text.upper())
                        if confidence >= .9 and key in vocabulary:
                            typed.append({'id': d['id'], **vocabulary[key],
                                'observed_at_seconds': frame.time, 'confidence': round(float(confidence), 4),
                                'method': 'exact_visible_move_label'})
                            if identity:
                                same = (previous_label and previous_label['key'] == key
                                        and frame.time-previous_label['last'] <= 3)
                                label_runs[(identity, d['id'])] = {'key': key, 'last': frame.time,
                                    'count': previous_label['count']+1 if same else 1}
            point = alignment[round(frame.time, 6)]
            result.append({'t': frame.time, 'source_pts': point['source_pts'],
                'source_time_base': point['source_time_base'], 'controls': measured, 'labels': typed,
                'context_frame_index': context[cursor]['frame_index'] if cursor >= 0 else None})
    temporary = target.with_name(target.name+'.incomplete')
    temporary.write_bytes(gzip.compress(''.join(json.dumps(r, separators=(',', ':'))+'\n'
        for r in result).encode('utf-8'), mtime=0)); temporary.replace(target)
    write_json(receipt, {'fingerprint': fingerprint, 'data_sha256': sha256(target),
        'sampled_frames': len(result), 'typed_labels': sum(len(r['labels']) for r in result),
        'raw_logs_modified': False, 'accuracy_verified': False})
    return target
