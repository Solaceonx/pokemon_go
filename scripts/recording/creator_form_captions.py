"""Read only literal ability captions; keep recognition time separate from frame time.

The extra frames are selected by already observed releases or captions. This is
an offline replay of a short frame buffer, so a lookback reading is never made
available before the observation that requested it. No free-form OCR is saved.
"""
import math

CAPTION = "Mimikyu's disguise is busted!"


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def parse_caption(records):
    from creator_forms import busted_caption
    ordered = sorted((r for r in records if finite(r.get('confidence')) and r['confidence'] >= .90),
                     key=lambda r: (r['bounds'][1], r['bounds'][0]))
    matches = []
    for index, item in enumerate(ordered):
        pieces = [[item]]
        if index+1 < len(ordered):
            other = ordered[index+1]
            a, b = item['bounds'], other['bounds']
            overlap = min(a[2], b[2])-max(a[0], b[0])
            if 0 <= b[1]-a[3] <= 45 and overlap >= .25*min(a[2]-a[0], b[2]-b[0]):
                pieces.append([item, other])
        for group in pieces:
            if busted_caption(' '.join(r['text'] for r in group)):
                matches.append(dict(caption_id='mimikyu_disguise_busted',
                    confidence=min(r['confidence'] for r in group),
                    bounds=[min(r['bounds'][0] for r in group), min(r['bounds'][1] for r in group),
                            max(r['bounds'][2] for r in group), max(r['bounds'][3] for r in group)]))
    return max(matches, key=lambda r:r['confidence']) if matches else None


def frame_time(at, alignment):
    """Resolve a rounded OCR timestamp only to its matching physical frame."""
    point = alignment.get(round(at, 6)) if alignment else None
    return point['clip_seconds'] if point else at


def caption_rows(text_rows, witnesses=(), *, alignment=None):
    """A source frame counts once, even when two sampling paths found it."""
    from creator_forms import busted_caption
    found = {}
    for row in text_rows:
        if finite(row.get('t')) and any(busted_caption(text) for _, text in row.get('text', [])):
            key = round(row['t'], 6)
            at = frame_time(row['t'], alignment) if alignment is not None else key
            found[key] = dict(t=at, text=[['caption', CAPTION]], recognition_available_at_seconds=at)
    for row in witnesses:
        at, available = row.get('t'), row.get('recognition_available_at_seconds')
        if (row.get('caption_id') != 'mimikyu_disguise_busted'
                or not finite(row.get('confidence')) or row['confidence'] < .90
                or not finite(at) or not finite(available) or at < 0 or available < at
                or not isinstance(row.get('source_pts'), int) or isinstance(row['source_pts'], bool)):
            continue
        from fractions import Fraction
        try:
            if Fraction(row['source_time_base']) <= 0:
                continue
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            continue
        key = round(at, 6)
        if alignment is not None:
            point = alignment.get(key)
            if (not point or point['source_pts'] != row['source_pts']
                    or point['source_time_base'] != row['source_time_base']):
                continue
        at = frame_time(at, alignment) if alignment is not None else key
        available = frame_time(available, alignment) if alignment is not None else available
        candidate = dict(t=at, text=[['caption', CAPTION]],
                         recognition_available_at_seconds=max(at, available))
        if key not in found or candidate['recognition_available_at_seconds'] < found[key]['recognition_available_at_seconds']:
            found[key] = candidate
    return [found[key] for key in sorted(found)]


def acquisition_windows(text_rows, timeline, source_events, identities):
    """Schedule only after a literal caption or independently named release."""
    from creator_forms import busted_caption
    windows = []
    for row in text_rows:
        if finite(row.get('t')) and any(busted_caption(text) for _, text in row.get('text', [])):
            windows.append(dict(start=max(0, row['t']-.5), end=row['t']+.5, available=row['t']))
    for index, charge in enumerate(timeline.get('charged', [])):
        releases = charge.get('announcement_clip_seconds') or []
        side = charge.get('side')
        if not releases or side not in ('mine', 'theirs'):
            continue
        release = min(releases)
        cue = timeline.get('clip_origin_seconds', 0)+charge['t'] if 't' in charge else release
        target = 'theirs' if side == 'mine' else 'mine'
        before = [r for r in identities if 0 <= cue-r['t'] <= 2 and r.get('values', {}).get(target)]
        if not before or before[-1]['values'][target]['species'] != 'Mimikyu':
            continue
        proofs = [e for e in source_events if e.get('kind') == 'charged' and e.get('charge_index') == index
                  and e.get('side') == side and finite(e.get('confirmed_at_seconds'))]
        if len(proofs) != 1:
            continue
        windows.append(dict(start=release, end=release+8,
                            available=max(release, proofs[0]['confirmed_at_seconds'])))
    return sorted(windows, key=lambda w:(w['start'], w['end'], w['available']))


def preserve_cache_file(path):
    """Use short content-addressed names, including on Windows without long paths."""
    import hashlib, json
    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    history = path.parent/'fh'; history.mkdir(exist_ok=True)
    backup = history/(digest+'.bin')
    if backup.exists():
        if backup.read_bytes() != payload:
            raise ValueError('Preserved caption cache differs from its content hash')
    else:
        temporary = history/(digest+'.tmp')
        temporary.write_bytes(payload); temporary.replace(backup)
    manifest = history/'manifest.json'
    entries = json.loads(manifest.read_text(encoding='utf8')) if manifest.exists() else []
    entry = dict(original_name=path.name, sha256=digest, blob=backup.name)
    if entry not in entries:
        entries.append(entry)
        temporary = history/'manifest.tmp'
        temporary.write_text(json.dumps(entries,indent=2)+'\n',encoding='utf8')
        temporary.replace(manifest)
    return backup


def acquire(raw, timeline, source_events, identities, text_rows):
    import gzip, hashlib, json
    from pathlib import Path
    windows = acquisition_windows(text_rows, timeline, source_events, identities)
    if not windows:
        return []
    import av, cv2, numpy as np
    import local_ocr
    from rapidocr_onnxruntime import RapidOCR
    from creator_health import rows
    from vod_media import sha256, write_json
    folder = raw.parent
    meta = json.loads((folder/'battle.json').read_text(encoding='utf8'))
    aligned = {round(r['clip_seconds'],6):r for r in rows(folder/'frame_alignment.jsonl.gz')}
    for window in windows:
        window['available'] = frame_time(window['available'], aligned)
    target = raw/'native-form-captions-6hz.jsonl.gz'
    receipt = raw/'native-form-captions-acquisition.json'
    digest = lambda value:hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    fingerprint = dict(schema='native-literal-form-captions-v1', sample_hz=6, windows=windows,
        video_sha256=meta['video_sha256'], alignment_sha256=sha256(folder/'frame_alignment.jsonl.gz'),
        code_sha256=sha256(Path(__file__)), forms_code_sha256=sha256(Path(__file__).with_name('creator_forms.py')),
        text_sha256=sha256(raw/'text.jsonl.gz'), identities_sha256=digest(identities),
        timeline_sha256=digest(timeline), releases_sha256=digest(source_events),
        av=av.__version__, cv2=cv2.__version__)
    saved = json.loads(receipt.read_text(encoding='utf8')) if receipt.exists() else {}
    if saved.get('fingerprint') == fingerprint and target.exists() and saved.get('data_sha256') == sha256(target):
        return rows(target)
    if sha256(folder/meta['video_file']) != meta['video_sha256']:
        raise ValueError('Form caption source hash differs')
    # Preserve rejected/old derived bytes; originals and unrestricted OCR stay untouched.
    for path in (target, receipt):
        if path.exists():
            preserve_cache_file(path)
    engine = RapidOCR(intra_op_num_threads=1, inter_op_num_threads=1, use_cls=False)
    found, seen, samples = {}, set(), 0
    with av.open(str(folder/meta['video_file'])) as media:
        stream = media.streams.video[0]; stream.codec_context.thread_count = 1
        for window in windows:
            media.seek(int(window['start']/stream.time_base),stream=stream,backward=True)
            next_time = window['start']
            for frame in media.decode(stream):
                if frame.time is None or frame.time+1e-6 < next_time:
                    continue
                if frame.time > window['end']:
                    break
                while next_time <= frame.time+1e-6:
                    next_time += 1/6
                key = round(frame.time, 6)
                available = max(frame.time, window['available'])
                if key in seen:
                    if key in found:
                        found[key]['recognition_available_at_seconds'] = min(available, found[key]['recognition_available_at_seconds'])
                    continue
                seen.add(key)
                rgb = np.asarray(frame.to_image().resize((508,1080)))[180:650]
                enlarged = cv2.resize(rgb,None,fx=2,fy=2)
                readings, _ = engine(cv2.cvtColor(enlarged,cv2.COLOR_RGB2BGR))
                records = [dict(text=text,confidence=float(conf),bounds=[min(p[0] for p in points)/2,
                    min(p[1] for p in points)/2+180,max(p[0] for p in points)/2,max(p[1] for p in points)/2+180])
                    for points,text,conf in readings or []]
                label = parse_caption(records); samples += 1
                if label:
                    point = aligned[key]
                    found[key] = dict(t=frame.time,source_pts=point['source_pts'],
                        source_time_base=point['source_time_base'],recognition_available_at_seconds=available,**label)
    data = [found[key] for key in sorted(found)]
    temporary = target.with_name(target.name+'.incomplete')
    temporary.write_bytes(gzip.compress(''.join(json.dumps(r,separators=(',',':'))+'\n' for r in data).encode(),mtime=0))
    temporary.replace(target)
    write_json(receipt,dict(fingerprint=fingerprint,data_sha256=sha256(target),frames_read=samples,
                           typed_witnesses=len(data),raw_logs_modified=False))
    return data
