"""Read whitelisted species and CP from physically located header panels.

This supplements an unavailable profile header; no roster or game outcome is
used to invent an identity. Unrestricted OCR is discarded before serialization.
"""
import re


def code_digest(*objects):
    import hashlib
    import inspect
    return hashlib.sha256('\n'.join(inspect.getsource(o) for o in objects).replace('\r\n','\n').encode('utf8')).hexdigest()


def compact(value):
    return re.sub('[^A-Z]', '', value.upper())


def header_identity(records, species_names):
    """Require a unique exact game-vocabulary name and a unique CP reading."""
    vocabulary = {compact(n): n for n in species_names}
    names, cps = set(), set()
    for record in records:
        if record.get('confidence', 0) < .90:
            continue
        text = record['text'].strip()
        for value in re.findall(r'CP\s*[:.]?\s*(\d{2,5})(?!\d)', text, re.I):
            if 10 <= int(value) <= 10000:
                cps.add(int(value))
        name = re.sub(r'CP\s*[:.]?\s*\d{2,5}(?!\d)', '', text, flags=re.I).strip()
        if compact(name) in vocabulary:
            names.add(vocabulary[compact(name)])
    if len(names) != 1 or len(cps) != 1:
        return None
    return dict(species=names.pop(), cp=cps.pop(), method='physical_header_exact_vocabulary')


def measure_identity(rgb, engine, species_names):
    import cv2
    import numpy as np
    from native_health import header_panels, glyph_features
    from creator_observations import classify_headers
    panels = header_panels(rgb)
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
        result[side] = {**identity, 'panel_bounds': bounds} if identity else None
    return result


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
                    and 0 < sample['t']-prior['t'] <= 15)
            run = {**value, 't': sample['t'], 'count': prior['count']+1 if same else 1,
                   'first_visible_seconds': prior['first_visible_seconds'] if same else sample['t']}
            self.runs[side] = run
            identity=(side,value['species'],value['cp'])
            corroboration=next((a for a in reversed(announcements)
                if a['species']==value['species'] and 0<=sample['t']-a['t']<=2),None)
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
    from native_health import header_panels,glyph_features
    from creator_observations import glyph_row,classify_headers
    cv2.setNumThreads(1)
    root = Path(__file__).resolve().parents[2]
    gm = root/'data/gamemaster.json'
    meta = json.loads((folder/'battle.json').read_text(encoding='utf8'))
    fingerprint = dict(schema='physical-header-identities-v1', sample_hz=3,
        video_sha256=meta['video_sha256'], alignment_sha256=sha256(folder/'frame_alignment.jsonl.gz'),
        code_sha256=code_digest(compact,header_identity,measure_identity,acquire_identities,code_digest),
        geometry_sha256=code_digest(header_panels,glyph_features),
        glyphs_sha256=code_digest(glyph_row,classify_headers),gamemaster_sha256=sha256(gm),
        av=av.__version__,cv2=cv2.__version__,numpy=np.__version__)
    target,receipt = raw/'native-identities-3hz.jsonl.gz',raw/'native-identities-3hz-acquisition.json'
    if target.exists() and receipt.exists():
        saved=json.loads(receipt.read_text(encoding='utf8'))
        if saved.get('fingerprint') == fingerprint and saved.get('data_sha256') == sha256(target):
            return target
    if sha256(folder/meta['video_file']) != meta['video_sha256']:
        raise ValueError('Identity acquisition video hash differs')
    names=sorted({p['speciesName'].split(' (')[0] for p in json.loads(gm.read_text(encoding='utf8'))['pokemon']})
    aligned={round(r['clip_seconds'],6):r for r in rows(folder/'frame_alignment.jsonl.gz')}
    engine=RapidOCR(intra_op_num_threads=1,inter_op_num_threads=1,use_cls=False)
    result=[];next_time=None
    with av.open(str(folder/meta['video_file'])) as media:
        stream=media.streams.video[0];stream.codec_context.thread_count=1
        for index,frame in enumerate(media.decode(stream)):
            if frame.time is None:
                continue
            if next_time is None:
                next_time=frame.time
            if frame.time+1e-6 < next_time:
                continue
            while next_time <= frame.time+1e-6:
                next_time+=1/3
            point=aligned[round(frame.time,6)]
            value=measure_identity(np.asarray(frame.to_image().resize((508,1080))),engine,names)
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
    names={compact(p['speciesName'].split(' (')[0]):p['speciesName'].split(' (')[0]
           for p in json.loads((Path(__file__).resolve().parents[2]/'data/gamemaster.json').read_text(encoding='utf8'))['pokemon']}
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
