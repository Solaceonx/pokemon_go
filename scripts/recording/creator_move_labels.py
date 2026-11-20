"""Recognize charge-button text lines inside previously measured circles.

The physical circle cache is reusable. Only exact game vocabulary with a
unique cost survives; arbitrary OCR and images are never serialized.
"""
import re


def parse_label(text, confidence, vocabulary):
    if confidence < .90:
        return None
    key=re.sub('[^A-Z]','',text.upper())
    for suffix in ('NOTVERYEFFECTIVE','SUPEREFFECTIVE','EFFECTIVE'):
        if key.endswith(suffix):
            key=key[:-len(suffix)]
            break
    return vocabulary.get(key)


def measure_labels(rgb, discs, engine, vocabulary):
    import cv2
    result=[]
    for disc in discs:
        cx,cy=disc['center'];radius=disc['radius']
        x0,x1=max(0,round(cx-105)),min(rgb.shape[1],round(cx+105))
        top=round(cy+radius+2)
        choices=[]
        for lo,hi in [(top,top+28),(top,top+46)]:
            crop=rgb[max(0,lo):min(rgb.shape[0],hi),x0:x1]
            if crop.shape[0]<12:
                continue
            crop=cv2.resize(crop,None,fx=3,fy=3)
            recognized,_=engine(cv2.cvtColor(crop,cv2.COLOR_RGB2BGR),use_det=False,use_cls=False)
            for text,confidence in recognized or []:
                value=parse_label(text,float(confidence),vocabulary)
                if value:
                    choices.append({**value,'confidence':round(float(confidence),4)})
        if len({c['name'] for c in choices})==1:
            best=max(choices,key=lambda c:c['confidence'])
            result.append(dict(id=disc['id'],**best,method='physical_disc_direct_line_recognition'))
    return result


def acquire_labels(folder,raw):
    import bisect
    import gzip
    import hashlib
    import json
    from pathlib import Path
    import av
    import cv2
    import numpy as np
    import local_ocr
    from rapidocr_onnxruntime import RapidOCR
    from creator_health import rows
    from native_controls import move_vocabulary
    from vod_media import sha256,write_json
    root=Path(__file__).resolve().parents[2]
    gm=root/'data/gamemaster.json'
    meta=json.loads((folder/'battle.json').read_text(encoding='utf8'))
    geometry=raw/'native-controls-6hz.jsonl.gz'
    fingerprint=dict(schema='direct-charge-labels-v1',sample_hz=1,
        video_sha256=meta['video_sha256'],geometry_sha256=sha256(geometry),
        code_sha256=hashlib.sha256(Path(__file__).read_bytes().replace(b'\r\n',b'\n')).hexdigest(),
        gamemaster_sha256=sha256(gm))
    target,receipt=raw/'native-direct-labels-1hz.jsonl.gz',raw/'native-direct-labels-acquisition.json'
    if target.exists() and receipt.exists():
        saved=json.loads(receipt.read_text(encoding='utf8'))
        if saved.get('fingerprint')==fingerprint and saved.get('data_sha256')==sha256(target):
            return target
    if sha256(folder/meta['video_file'])!=meta['video_sha256']:
        raise ValueError('Move label source hash differs')
    vocabulary=move_vocabulary(json.loads(gm.read_text(encoding='utf8')))
    samples=rows(geometry);times=[s['t'] for s in samples]
    engine=RapidOCR(intra_op_num_threads=1,inter_op_num_threads=1,use_cls=False)
    result=[];next_time=None
    with av.open(str(folder/meta['video_file'])) as c:
        stream=c.streams.video[0];stream.codec_context.thread_count=1
        for f in c.decode(stream):
            if f.time is None:
                continue
            if next_time is None:
                next_time=f.time
            if f.time+1e-6<next_time:
                continue
            while next_time<=f.time+1e-6:
                next_time+=1
            index=bisect.bisect_right(times,f.time+1e-6)-1
            if index<0 or abs(samples[index]['t']-f.time)>1e-5:
                continue
            sample=samples[index]
            if sample['controls']['status']!='observed':
                continue
            labels=measure_labels(np.asarray(f.to_image().resize((508,1080))),sample['controls']['discs'],engine,vocabulary)
            result.append(dict(t=f.time,source_pts=sample['source_pts'],source_time_base=sample['source_time_base'],labels=labels))
    temporary=target.with_name(target.name+'.incomplete')
    temporary.write_bytes(gzip.compress(''.join(json.dumps(r,separators=(',',':'))+'\n' for r in result).encode('utf8'),mtime=0));temporary.replace(target)
    write_json(receipt,dict(fingerprint=fingerprint,data_sha256=sha256(target),
        observed_labels=sum(len(r['labels']) for r in result),raw_logs_modified=False))
    return target
