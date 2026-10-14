"""Separate edited broadcast excerpts when the two displayed player names change."""
from __future__ import annotations

import bisect
import copy
from difflib import SequenceMatcher
import gzip
import json
from pathlib import Path
import re

from vod_media import sha256


def same_players(a, b):
    normal = lambda text: ''.join(c for c in text.upper() if c.isalnum()).replace('0','O')
    return all(SequenceMatcher(None, normal(x), normal(y)).ratio() >= .85 for x, y in zip(a, b))


def fixture_parts(candidate, readings):
    readings = [r for r in readings if candidate['start'] <= r['t'] < candidate['end']
                and r['hud'] and all(c >= .8 for c in r['confidence']) and all(len(n) >= 3 for n in r['players'])]
    if not readings:
        return []
    segments = [{'start': candidate['start'], 'first_read': readings[0]['t'],
                 'last_read': readings[0]['t'], 'players': readings[0]['players']}]
    for i, row in enumerate(readings[1:], 1):
        current = segments[-1]
        if same_players(current['players'], row['players']):
            current['last_read'] = row['t']
            continue
        confirm = next((r for r in readings[i+1:] if r['t']-row['t'] <= 16 and same_players(r['players'], row['players'])), None)
        if confirm:
            current['end'] = min(row['t']-1.5, current['last_read']+2)
            segments.append({'start':max(candidate['start'],row['t']-1.5), 'first_read':row['t'],
                             'last_read':row['t'], 'players':row['players']})
    if len(segments) == 1:
        return []
    segments[-1]['end'] = min(candidate['end'], segments[-1]['last_read']+2)
    return [s for s in segments if s['end']-s['start'] >= 3]


def split_fixtures(video, views, scan, regions, cache):
    """Read only candidate footage; no game-state values or labels are inferred."""
    import av
    from local_ocr import LocalOCR
    from segment_battles import recognize
    cache = Path(cache)
    groups = {}
    for candidates in views.values():
        for c in candidates:
            groups.setdefault(c['match_id'],[]).append(c)
    intervals = sorted((min(c['start'] for c in g),max(c['end'] for c in g)) for g in groups.values())
    fingerprint = {'source_sha256':scan['fingerprint']['source_sha256'], 'regions':regions,
                   'intervals':intervals, 'code_sha256':sha256(__file__), 'sampling_seconds':4}
    prior = None
    if cache.is_file():
        with gzip.open(cache,'rt',encoding='utf-8') as f:
            prior = json.load(f)
    if prior and prior['fingerprint'] == fingerprint:
        readings = prior['readings']
    else:
        readings, ocr = [], LocalOCR()
        samples = next(iter(scan['views'].values()))
        times = [r['t'] for r in samples]
        with av.open(str(video)) as source:
            stream=source.streams.video[0]; stream.codec_context.skip_frame='NONKEY';stream.codec_context.thread_count=4
            for start,end in intervals:
                source.seek(int(start/stream.time_base),stream=stream,backward=True)
                last=-100
                for frame in source.decode(stream):
                    if frame.pts is None:
                        continue
                    t=float(frame.pts*frame.time_base)
                    if t<start:
                        continue
                    if t>=end:
                        break
                    if t-last<4:
                        continue
                    last=t
                    k=bisect.bisect_left(times,t)
                    k=min(k,len(times)-1)
                    if k>0 and abs(times[k-1]-t)<abs(times[k]-t):
                        k-=1
                    rgb=frame.to_ndarray(format='rgb24')
                    hud = any(rows[k]['hud'] for rows in scan['views'].values())
                    evidence_kind='cp_header' if hud else 'native_statusbar_clock'
                    if not hud:
                        # Edited excerpts can use another phone aspect ratio,
                        # hiding CP from the calibrated strip. The native clock
                        # remains visible through charge animations, unlike ads.
                        for profile in scan['fingerprint']['profiles'].values():
                            import cv2
                            x,y,w,h=profile['viewport']
                            phone=cv2.resize(rgb[y:y+h,x:x+w],(508,1080))
                            text,confidence=recognize(ocr,phone[:65,30:165])
                            match=re.search(r'(\d{1,2}):(\d{2})',text)
                            if match and confidence>=.7 and int(match[1])<=23 and int(match[2])<=59:
                                hud=True
                                break
                    if not hud:
                        continue
                    values=[]
                    for x,y,w,h in regions:
                        values.append(recognize(ocr,rgb[y:y+h,x:x+w]))
                    readings.append({'t':t, 'hud':True, 'players':[v[0] for v in values],
                                     'confidence':[v[1] for v in values], 'presence_evidence':evidence_kind})
        cache.parent.mkdir(parents=True,exist_ok=True)
        with gzip.open(cache,'wt',encoding='utf-8') as f:
            json.dump({'fingerprint':fingerprint,'readings':readings},f,separators=(',',':'))
    output={side:[] for side in views};changed=[]
    for group in groups.values():
        envelope={'start':min(c['start'] for c in group),'end':max(c['end'] for c in group)}
        parts=fixture_parts(envelope,readings)
        if not parts:
            for c in group:
                output[c['view_id']].append(copy.deepcopy(c))
            continue
        changed.append({'original_match_id':group[0]['match_id'],'parts':parts,
                        'classification':'edited_fixture_sequence; complete new games not established'})
        for c in group:
            for number,part in enumerate(parts,1):
                start,end=max(c['start'],part['start']),min(c['end'],part['end'])
                if end-start<3:
                    continue
                fragment=copy.deepcopy(c)
                fragment.update({'start':start,'end':end,'first_hud_seconds':max(start,part['first_read']),
                    'id':c['id']+f'-fragment-{number:02d}','match_id':c['match_id']+f'-fragment-{number:02d}',
                    'incomplete_start':True,'incomplete_end':True,'eligible_for_complete_battle_evaluation':False,
                    'completeness':'edited_battle_fragment','source_segment_kind':'edited_fixture_sequence',
                    'start_method':'edited_fixture_change','end_method':'last_fixture_gameplay_read',
                    'fixture_evidence':part,'name':c['name']+f' · excerpt {number}',
                    'notes':c['notes']+['Displayed player pair changed within this interval; excerpts are kept separately as partial footage.']})
                output[c['view_id']].append(fragment)
    return output, {'reading_fingerprint':fingerprint,'reading_file_sha256':sha256(cache),
                    'changed_intervals':changed,'independent_battle_identity_verified':False}
