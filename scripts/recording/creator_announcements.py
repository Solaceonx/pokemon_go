"""Reread missing release banners locally, preserving typed source witnesses.

Only exact species/move vocabulary and source coordinates are serialized.
The original OCR files are immutable; supplemental text is a derived input.
"""
import re
from visible_vocabulary import species_key, move_key


def compact(text):
    return move_key(text)


def parse_banner(records,legal_pairs):
    names={species_key(name):name for name,_ in legal_pairs}
    moves={compact(move):move for _,move in legal_pairs}
    ordered=sorted((r for r in records if r['confidence']>=.90),key=lambda r:(r['bounds'][1],r['bounds'][0]))
    found=[]
    for index,item in enumerate(ordered):
        text=compact(item['text'])
        if 'USED' not in text:continue
        actor,tail=text.split('USED',1)
        if actor not in names:continue
        options=[tail]
        for after in ordered[index+1:index+3]:
            if after['bounds'][1]-item['bounds'][3]>100:break
            options.append(options[-1]+compact(after['text']))
        for move_text in options:
            if move_text not in moves:continue
            pair=(names[actor],moves[move_text])
            if pair in legal_pairs:
                found.append(dict(pokemon=pair[0],move=pair[1],method='exact_native_release_banner'))
    unique={(v['pokemon'],v['move']) for v in found}
    return found[0] if len(unique)==1 else None


def acquire_releases(folder,raw,timeline):
    import gzip,json,hashlib
    from pathlib import Path
    import av,cv2,numpy as np
    import local_ocr
    from rapidocr_onnxruntime import RapidOCR
    from creator_health import rows
    from vod_media import sha256,write_json
    from assemble import LEGAL_RELEASE_PAIRS
    windows=[[timeline['clip_origin_seconds']+q['t']+4,timeline['clip_origin_seconds']+q['t']+14]
             for q in timeline['charged'] if not q.get('announcement_clip_seconds') or not q.get('actor')]
    if not windows:return raw/'text.jsonl.gz'
    root=Path(__file__).resolve().parents[2];meta=json.loads((folder/'battle.json').read_text(encoding='utf8'))
    target,receipt=raw/'native-release-banners-2hz.jsonl.gz',raw/'native-release-banners-acquisition.json'
    fingerprint=dict(schema='missing-native-release-banners-v1',sample_hz=2,windows=windows,
        video_sha256=meta['video_sha256'],alignment_sha256=sha256(folder/'frame_alignment.jsonl.gz'),
        kernel_sha256=hashlib.sha256(Path(__file__).read_bytes().replace(b'\r\n',b'\n')).hexdigest(),
        vocabulary_sha256=sha256(Path(__file__).with_name('visible_vocabulary.py')),
        gamemaster_sha256=sha256(root/'data/gamemaster.json'),av=av.__version__,cv2=cv2.__version__)
    saved=json.loads(receipt.read_text(encoding='utf8')) if receipt.exists() else {}
    if saved.get('fingerprint')!=fingerprint or not target.exists() or saved.get('data_sha256')!=sha256(target):
        if sha256(folder/meta['video_file'])!=meta['video_sha256']:raise ValueError('Release banner source hash differs')
        aligned={round(r['clip_seconds'],6):r for r in rows(folder/'frame_alignment.jsonl.gz')}
        engine=RapidOCR(intra_op_num_threads=1,inter_op_num_threads=1,use_cls=False);found={};samples=0
        with av.open(str(folder/meta['video_file'])) as media:
            stream=media.streams.video[0];stream.codec_context.thread_count=1
            for start,end in windows:
                media.seek(int(max(0,start)/stream.time_base),stream=stream,backward=True);next_time=max(0,start)
                for frame in media.decode(stream):
                    if frame.time is None or frame.time+1e-6<next_time:continue
                    if frame.time>end:break
                    while next_time<=frame.time+1e-6:next_time+=.5
                    if round(frame.time,6) in found:continue
                    rgb=np.asarray(frame.to_image().resize((508,1080)))[180:420]
                    enlarged=cv2.resize(rgb,None,fx=2,fy=2)
                    read,_=engine(cv2.cvtColor(enlarged,cv2.COLOR_RGB2BGR))
                    records=[dict(text=text,confidence=float(conf),bounds=[min(p[0] for p in points),min(p[1] for p in points),max(p[0] for p in points),max(p[1] for p in points)]) for points,text,conf in read or []]
                    label=parse_banner(records,LEGAL_RELEASE_PAIRS);samples+=1
                    if label:
                        point=aligned[round(frame.time,6)]
                        found[round(frame.time,6)]=dict(t=frame.time,source_pts=point['source_pts'],source_time_base=point['source_time_base'],**label)
        data=[found[k] for k in sorted(found)]
        target.write_bytes(gzip.compress(''.join(json.dumps(r,separators=(',',':'))+'\n' for r in data).encode('utf8'),mtime=0))
        write_json(receipt,dict(fingerprint=fingerprint,data_sha256=sha256(target),frames_read=samples,typed_witnesses=len(data),raw_logs_modified=False))
    texts=rows(raw/'text.jsonl.gz');by_time={round(r['t'],6):r for r in texts}
    for release in rows(target):
        key=round(release['t'],6);record=by_time.setdefault(key,dict(t=release['t'],text=[]))
        record['text'].append(('middle',release['pokemon']+' used '+release['move']))
    derived=raw/'text-native-release-derived.jsonl.gz'
    derived.write_bytes(gzip.compress(''.join(json.dumps(by_time[k],separators=(',',':'))+'\n' for k in sorted(by_time)).encode('utf8'),mtime=0))
    return derived
