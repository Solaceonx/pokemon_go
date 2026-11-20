"""Read whitelisted species and CP from physically located header panels.

This supplements an unavailable profile header; no roster or game outcome is
used to invent an identity. Unrestricted OCR is discarded before serialization.
"""
import re
from visible_vocabulary import header_species_names, species_key


def code_digest(*objects):
    import hashlib
    import inspect
    return hashlib.sha256('\n'.join(inspect.getsource(o) for o in objects).replace('\r\n','\n').encode('utf8')).hexdigest()


def compact(value):
    return species_key(value)


def header_identity(records, species_names, *, allow_collapsed_double=False, allow_il_confusable=False):
    """Require unique name/CP; only split physical tokens may recover a double."""
    vocabulary = {compact(n): n for n in species_names}
    names, cps = set(), set()
    recovered, il_recovered = False, False
    for record in records:
        if record.get('confidence', 0) < .90:
            continue
        text = record['text'].strip()
        for value in re.findall(r'CP\s*[:.]?\s*(\d{2,5})(?!\d)', text, re.I):
            if 10 <= int(value) <= 10000:
                cps.add(int(value))
        name = re.sub(r'CP\s*[:.]?\s*\d{2,5}(?!\d)', '', text, flags=re.I).strip()
        key = compact(name)
        if key in vocabulary:
            names.add(vocabulary[key])
        elif allow_collapsed_double and len(key) >= 8:
            collapse = lambda text: re.sub(r'(.)\1+', r'\1', text)
            choices = [value for candidate, value in vocabulary.items()
                       if len(candidate) == len(key)+1 and collapse(candidate) == collapse(key)]
            if len(choices) == 1:
                names.add(choices[0])
                recovered = True
        elif allow_il_confusable and len(key) >= 8:
            choices = [value for candidate, value in vocabulary.items()
                       if len(candidate) == len(key) and
                       sum(a != b for a, b in zip(candidate, key)) == 1 and
                       all(a == b or {a, b} == {'I', 'L'} for a, b in zip(candidate, key))]
            if len(choices) == 1:
                names.add(choices[0])
                il_recovered = True
    if len(names) != 1 or len(cps) != 1:
        return None
    if il_recovered:
        return dict(species=names.pop(), cp=cps.pop(), method='physical_header_unique_il_candidate',
                    requires_entry_corroboration=True)
    return dict(species=names.pop(), cp=cps.pop(), method=(
        'physical_header_separate_tokens_unique_collapsed_double' if recovered else 'physical_header_exact_vocabulary'))


def split_header_reading(rgb, bounds, engine, species_names):
    """Read CP/name separately across one dominant measured blank text gap.

    Called only on already validated five-icon header geometry. Each token
    retains the original confidence floor. Only a unique single omitted
    doubled letter may supplement the exact vocabulary; arbitrary edits and
    a guessed roster are insufficient.
    """
    import cv2
    x, y, right, bottom = bounds
    crop = rgb[y:min(bottom, y+32), x:right]
    if crop.shape[0] < 28 or crop.shape[1] < 60:
        return None
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    _, ink = cv2.threshold(gray[5:28], 0, 255, cv2.THRESH_BINARY_INV+cv2.THRESH_OTSU)
    occupied = (ink > 0).sum(axis=0) >= 2
    gaps, start = [], None
    for i, value in enumerate(occupied):
        if not value and start is None:
            start = i
        elif value and start is not None:
            if start >= 15 and i <= len(occupied)-15:
                gaps.append((i-start, start, i))
            start = None
    ranked = sorted(gaps, reverse=True)
    if not ranked or ranked[0][0] < 12 or (len(ranked) > 1 and ranked[0][0] < ranked[1][0]*2):
        return None
    _, left, end = ranked[0]
    split = (left+end)//2
    if occupied[:split].sum() < 6 or occupied[split:].sum() < 6:
        return None
    records = []
    for a, b in [(0, split), (split, crop.shape[1])]:
        image = cv2.resize(crop[:, a:b], None, fx=3, fy=3)
        text, _ = engine(cv2.cvtColor(image, cv2.COLOR_RGB2BGR), use_det=False, use_cls=False)
        records.extend(dict(text=s, confidence=float(conf)) for s, conf in text or [])
    result = header_identity(records, species_names, allow_collapsed_double=True)
    if result and result['method'] == 'physical_header_exact_vocabulary':
        result['method'] = 'physical_header_separate_exact_tokens'
    return result


def measure_identity(rgb, engine, species_names, anchors=()):
    import cv2
    import numpy as np
    from native_health import header_panels, glyph_features
    from creator_observations import classify_headers
    panels = header_panels(rgb, anchors)
    # Clouds may connect one pale header to the background. Its visible mate
    # supplies only a search rectangle; fresh glyph geometry still has to pass.
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    for panel in list(panels):
        x0,y0,x1,y1 = panel['bounds']
        x0,x1 = 508-x1,508-x0
        roi = hsv[y0:y1,x0:x1]
        pale = (roi[:,:,1] < 105) & (roi[:,:,2] > 150)
        if not roi.size or float(pale.mean()) < .55:
            continue
        glyph_y = y0+round((y1-y0)*.5)
        panels.append(dict(bounds=[x0,y0,x1,y1],
            background_value_median=float(np.median(roi[:,:,2][pale])),
            geometry_source='opposite_panel_search_with_fresh_glyph_geometry',
            glyphs=glyph_features(hsv[glyph_y:y1-2,x0:x1],x0,glyph_y)))
    measured = classify_headers(panels)
    result = {}
    for side, value in measured.items():
        # Group spacing and panel geometry have already selected the header.
        boxes = {tuple(p['panel_bounds']) for p in value.get('panels', [])}
        if not boxes:
            result[side] = None
            continue
        # Overlapping physical/search rectangles describe the same panel.
        if max(b[1] for b in boxes)-min(b[1] for b in boxes) > 8:
            result[side] = None
            continue
        physical = [p['panel_bounds'] for p in value['panels']
                    if p.get('geometry_source') == 'pale_component']
        bounds = physical[0] if physical else list(min(boxes, key=lambda b:b[2]-b[0]))
        x0, y0, x1, y1 = bounds
        crop = rgb[y0:min(y1, y0+32), x0:x1]
        if crop.size == 0:
            result[side] = None
            continue
        enlarged = cv2.resize(crop, None, fx=3, fy=3)
        # The panel already locates one text line. Whole-image text detection
        # can fail on this short, low-contrast strip even when recognition works.
        text, _ = engine(cv2.cvtColor(enlarged, cv2.COLOR_RGB2BGR), use_det=False, use_cls=False)
        identity = header_identity([dict(text=s, confidence=float(conf)) for s, conf in text or []], species_names)
        if identity:
            result[side] = {**identity, 'panel_bounds': bounds}
            continue
        recovered = [dict(**value, panel_bounds=list(box)) for box in sorted(boxes)
                     if (value := split_header_reading(rgb, box, engine, species_names))]
        identities = {(v['species'], v['cp']) for v in recovered}
        result[side] = recovered[0] if len(identities) == 1 else None
        if result[side] is None:
            candidate = header_identity([dict(text=s, confidence=float(conf)) for s, conf in text or []],
                                        species_names, allow_il_confusable=True)
            if candidate:
                result[side] = {**candidate, 'panel_bounds': bounds}
    return result


def fresh_cp_anchors(context, at):
    """Use only already-observed CP text bounds, never a future header."""
    anchors = []
    if context is None:
        return anchors
    for side, key in [('mine', 'mine'), ('theirs', 'opponent')]:
        cp = context.get(key, {}).get('cp', {})
        bounds = cp.get('evidence', {}).get('bounds_normalized_frame')
        seen = cp.get('evidence', {}).get('observed_at_seconds')
        if (cp.get('status') == 'observed' and cp.get('value') is not None
                and bounds and seen is not None and 0 <= at-seen <= .9):
            anchors.append({'side': side, 'bounds': bounds})
    return anchors


class IdentityEvidence:
    """Two independent exact readings before a source identity is confirmed."""
    def __init__(self):
        self.runs = {}
        self.confirmed = set()

    def update(self, sample, announcements=()):
        result = {}
        for side in ('mine', 'theirs'):
            value = sample.get(side)
            if not value:
                # An unreadable animation is not a contradictory header. Keep
                # the pending exact pair, but publish nothing on this sample.
                continue
            prior = self.runs.get(side)
            same = (prior and prior['species'] == value['species'] and prior['cp'] == value['cp']
                    and bool(prior.get('requires_entry_corroboration')) == bool(value.get('requires_entry_corroboration'))
                    and 0 < sample['t']-prior['t'] <= 15)
            run = {**value, 't': sample['t'], 'count': prior['count']+1 if same else 1,
                   'first_visible_seconds': prior['first_visible_seconds'] if same else sample['t']}
            self.runs[side] = run
            identity=(side,value['species'],value['cp'])
            corroboration=next((a for a in reversed(announcements)
                if a['species']==value['species'] and 0<=sample['t']-a['t']<=2),None)
            # A unique I/l confusion remains a candidate until the source
            # independently names a return of this already verified CP pair.
            # Repetition alone cannot turn a systematic OCR typo into a fact.
            if value.get('requires_entry_corroboration') and not (
                    run['count'] >= 2 and corroboration and identity in self.confirmed):
                continue
            # An entry names the species, not its CP. It can corroborate a
            # return of an already verified identity; a first CP still needs
            # two readings. Otherwise one CP typo creates a fourth team member.
            if run['count'] >= 2 or (corroboration and identity in self.confirmed):
                self.confirmed.add(identity)
                result[side] = {**run, 'confirmed_seconds': sample['t'],
                                'source_pts': sample['source_pts'], 'source_time_base': sample['source_time_base']}
                if run['count']<2:
                    result[side].update(method='physical_header_and_matching_entry_announcement',
                        entry_announcement_seconds=corroboration['t'])
        return result


def acquire_identities(folder, raw):
    """Three source-aligned observations per second; preserve original logs."""
    import gzip
    import hashlib
    import json
    from pathlib import Path
    import av
    import cv2
    import numpy as np
    import local_ocr
    from rapidocr_onnxruntime import RapidOCR
    from vod_media import sha256, write_json
    from creator_health import rows
    from native_health import header_panels,header_row_panels,glyph_features
    from creator_observations import glyph_row,classify_headers
    cv2.setNumThreads(1)
    root = Path(__file__).resolve().parents[2]
    gm = root/'data/gamemaster.json'
    meta = json.loads((folder/'battle.json').read_text(encoding='utf8'))
    fingerprint = dict(schema='physical-header-identities-v1', sample_hz=3,
        video_sha256=meta['video_sha256'], alignment_sha256=sha256(folder/'frame_alignment.jsonl.gz'),
        code_sha256=code_digest(compact,header_identity,split_header_reading,measure_identity,fresh_cp_anchors,acquire_identities,code_digest),
        vocabulary_code_sha256=sha256(Path(__file__).with_name('visible_vocabulary.py')),
        context_sha256=sha256(raw/'screen.jsonl.gz'),
        geometry_sha256=code_digest(header_panels,header_row_panels,glyph_features),
        glyphs_sha256=code_digest(glyph_row,classify_headers),gamemaster_sha256=sha256(gm),
        av=av.__version__,cv2=cv2.__version__,numpy=np.__version__)
    target,receipt = raw/'native-identities-3hz.jsonl.gz',raw/'native-identities-3hz-acquisition.json'
    if target.exists() and receipt.exists():
        saved=json.loads(receipt.read_text(encoding='utf8'))
        if saved.get('fingerprint') == fingerprint and saved.get('data_sha256') == sha256(target):
            return target
    if sha256(folder/meta['video_file']) != meta['video_sha256']:
        raise ValueError('Identity acquisition video hash differs')
    names=header_species_names(json.loads(gm.read_text(encoding='utf8')))
    aligned={round(r['clip_seconds'],6):r for r in rows(folder/'frame_alignment.jsonl.gz')}
    engine=RapidOCR(intra_op_num_threads=1,inter_op_num_threads=1,use_cls=False)
    result=[];next_time=None
    contexts=iter(rows(raw/'screen.jsonl.gz'))
    wanted,context=next(contexts,None),None
    with av.open(str(folder/meta['video_file'])) as media:
        stream=media.streams.video[0];stream.codec_context.thread_count=1
        for index,frame in enumerate(media.decode(stream)):
            if frame.time is None:
                continue
            while wanted is not None and wanted['frame_index'] <= index:
                context,wanted=wanted,next(contexts,None)
            if next_time is None:
                next_time=frame.time
            if frame.time+1e-6 < next_time:
                continue
            while next_time <= frame.time+1e-6:
                next_time+=1/3
            point=aligned[round(frame.time,6)]
            rgb=np.asarray(frame.to_image().resize((508,1080)))
            value=measure_identity(rgb,engine,names)
            if any(v is None for v in value.values()):
                anchors=fresh_cp_anchors(context,frame.time)
                if anchors:
                    fallback=measure_identity(rgb,engine,names,anchors)
                    value={side:current or fallback[side] for side,current in value.items()}
            result.append(dict(t=frame.time,frame_index=index,source_pts=point['source_pts'],
                source_time_base=point['source_time_base'],**value))
    temporary=target.with_name(target.name+'.incomplete')
    temporary.write_bytes(gzip.compress(''.join(json.dumps(r,separators=(',',':'))+'\n' for r in result).encode('utf8'),mtime=0));temporary.replace(target)
    write_json(receipt,dict(fingerprint=fingerprint,data_sha256=sha256(target),samples=len(result),raw_logs_modified=False))
    return target


def entry_announcements(raw):
    """Only exact typed entry names; unrestricted OCR never leaves this helper."""
    import json
    from pathlib import Path
    from creator_health import rows
    names={compact(name):name for name in header_species_names(
        json.loads((Path(__file__).resolve().parents[2]/'data/gamemaster.json').read_text(encoding='utf8')))}
    return [dict(t=r['t'],species=names[key[2:]]) for r in rows(raw/'text.jsonl.gz') for _,text in r['text']
            if (key:=compact(text)).startswith('GO') and key[2:] in names]


def confirmed_identities(samples, announcements=()):
    ledger = IdentityEvidence()
    return [dict(t=s['t'], values=ledger.update(s,announcements)) for s in samples]


def enrich_readings(base_path, raw):
    """Supplement a derived slim input with independent physical-header facts."""
    import bisect
    import copy
    import gzip
    import json
    from creator_health import rows
    samples = confirmed_identities(rows(raw/'native-identities-3hz.jsonl.gz'),entry_announcements(raw))
    times = [s['t'] for s in samples]
    result = []
    for original in rows(base_path):
        row = copy.deepcopy(original)
        index = bisect.bisect_right(times, row['t']+1e-6)-1
        if index >= 0 and row['t']-times[index] <= .75:
            for side,key in [('mine','m'),('theirs','o')]:
                identity = samples[index]['values'].get(side)
                if identity:
                    row[key].update(sp=identity['species'],cp=identity['cp'],
                        identity_observed_at_seconds=identity['confirmed_seconds'],
                        identity_first_visible_seconds=identity['first_visible_seconds'],
                        identity_source_pts=identity['source_pts'],
                        identity_source_time_base=identity['source_time_base'])
        result.append(row)
    target=raw/'readings-physical-identities.jsonl.gz'
    target.write_bytes(gzip.compress(''.join(json.dumps(r,separators=(',',':'))+'\n' for r in result).encode('utf8'),mtime=0))
    return target


def enrich_frame(frame, identity):
    """Apply a confirmed source reading, retaining its real observation time."""
    for side,visible_side in [('mine','mine'),('theirs','opponent')]:
        value=identity.get(side)
        if value is None:
            continue
        evidence=dict(method=value['method'],observed_at_seconds=value['confirmed_seconds'],
            source_pts=value['source_pts'],source_time_base=value['source_time_base'],
            first_visible_seconds=value['first_visible_seconds'])
        frame.setdefault(visible_side,{})
        frame[visible_side]['species']=dict(value=value['species'],status='observed',evidence=evidence)
        frame[visible_side]['cp']=dict(value=value['cp'],status='observed',evidence=evidence)
