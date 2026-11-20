"""Outer collection operations; imports frozen producers, never modifies them."""
import argparse
import collections
import ctypes
import datetime
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BASE = REPO / '.vod/task46-collection-20261120'
FROZEN = BASE / 'frozen-reader'
EXCLUDED = {'2906166125', '2883201730', '2914289331'}

def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(4194304), b''):
            h.update(chunk)
    return h.hexdigest()

def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.incomplete')
    tmp.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    tmp.replace(path)

def pin(cpu):
    if sys.platform == 'win32':
        kernel=ctypes.windll.kernel32
        kernel.GetCurrentProcess.restype=ctypes.c_void_p
        kernel.SetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.c_size_t]
        if not kernel.SetProcessAffinityMask(kernel.GetCurrentProcess(), 1 << cpu):
            raise OSError('Unable to enforce one-CPU affinity')

def frozen_modules():
    verify_freeze()
    sys.path.insert(0, str(FROZEN/'scripts/recording'))
    import vod
    vod.bootstrap(FROZEN/'screen_reader')
    return vod

def verify_freeze():
    import importlib.util
    spec=importlib.util.spec_from_file_location('outer_reader_freeze',REPO/'scripts/recording/reader_freeze.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result=module.verify(FROZEN,load(BASE/'reader-freeze.json'))
    if not result['unchanged']:
        raise ValueError('Frozen reader changed: '+str(result['failures']))
    return result

def claim(worker):
    folder = BASE/'claims'
    folder.mkdir(exist_ok=True)
    for row in load(BASE/'queue.json')['sources']:
        sid = row['source_id']
        if row['status'] != 'queued' or sid in EXCLUDED:
            continue
        try:
            with (folder/(sid+'.json')).open('x', encoding='utf-8') as f:
                json.dump({'worker':worker,'source_id':sid,'claimed_at':now()}, f)
        except FileExistsError:
            continue
        return row
    return None

def worker_root(worker):
    if worker not in {'worker-a', 'worker-b'}:
        raise ValueError('Unknown worker')
    return FROZEN/'.vod/collection'/worker

def detect(worker, sid):
    if sid in EXCLUDED:
        raise ValueError('Reserved heldout source')
    root = worker_root(worker)
    # Reserve room for the source and its temporary normalized copy. Stop
    # intake well before the retained-cut storage floor is reached.
    entry=next((r for r in load(BASE/'queue.json')['sources'] if r['source_id']==sid),None)
    if entry is None:
        raise ValueError('Source must be present in the reviewed queue')
    reserve=25_000_000_000 + int((entry.get('duration_seconds') or 21600)*3_000_000)
    if shutil.disk_usage(root if root.exists() else BASE).free < reserve:
        raise ValueError('Insufficient free space for source normalization and retained-cut floor')
    args = [sys.executable, str(FROZEN/'scripts/recording/vod.py'),
        'https://www.twitch.tv/videos/'+sid, '--download', '--stage', 'detect', '--jobs', '1',
        '--reader-dir', str(FROZEN/'screen_reader'), '--downloader', str(FROZEN/'screen_reader/tools/yt-dlp.exe'),
        '--sources-root', str(root/'sources'), '--run-dir', str(root/'runs'/sid), '--library', str(root/'cuts')]
    subprocess.run(args, check=True)
    verify_freeze()

def witnesses(video, times, output):
    import av
    import cv2
    import numpy as np
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    records, thumbs = [], []
    with av.open(str(video)) as source:
        stream = source.streams.video[0]
        stream.codec_context.thread_count = 1
        for requested in times:
            source.seek(int(requested / stream.time_base), stream=stream, backward=True)
            frame = next((f for f in source.decode(stream) if f.time is not None and f.time >= requested), None)
            if frame is None:
                continue
            rgb = frame.to_ndarray(format='bgr24')
            path = output/('frame-%09.3f.jpg'%frame.time)
            cv2.imwrite(str(path), rgb, [cv2.IMWRITE_JPEG_QUALITY,92])
            records.append({'file':str(path),'sha256':digest(path),'requested_seconds':requested,'source_seconds':frame.time})
            thumb = cv2.resize(rgb, (480,270))
            cv2.putText(thumb, '%.3f s'%frame.time, (8,24), cv2.FONT_HERSHEY_SIMPLEX,.7,(0,0,255),2)
            thumbs.append(thumb)
    for i in range(0,len(thumbs),12):
        batch=thumbs[i:i+12]
        batch += [np.zeros_like(batch[0])]*(12-len(batch))
        sheet=np.vstack([np.hstack(batch[j:j+3]) for j in range(0,12,3)])
        cv2.imwrite(str(output/('sheet-%03d.jpg'%(i//12))),sheet)
    write(output/'witnesses.json',{'source_video_sha256':digest(video),'frames':records})
    return records

def selected_manifest(manifest, review, witness_root=None):
    """Only human-reviewed selected/active Open GL, never titles or CP alone."""
    if review.get('source_id') != manifest['source_id']:
        raise ValueError('Review source mismatch')
    candidates={c['id']:c for rows in manifest['views'].values() for c in rows}
    decisions={r['candidate_id']:r for r in review['decisions']}
    if len(decisions)!=len(review['decisions']):
        raise ValueError('Duplicate league decisions')
    if set(candidates) != set(decisions):
        raise ValueError('Every detected candidate must have a league decision')
    chosen=[]
    for cid, row in decisions.items():
        if row['league'] in {'unknown','unverified'}:
            continue
        proof=row['in_game_league_evidence']
        if proof.get('context') not in {'selected_league','active_league'} or not proof.get('reviewed_by'):
            raise ValueError('A league classification needs selected/active in-game proof')
        for w in proof['witnesses']:
            if witness_root is None or not Path(w['file']).resolve().is_relative_to(Path(witness_root).resolve()):
                raise ValueError('League witness outside owned witness folder')
            if digest(w['file']) != w['sha256']:
                raise ValueError('League witness changed')
        if not proof['witnesses']:
            raise ValueError('No source witness')
        if row['league']=='open_great_league':
            chosen.append(cid)
    manifest=json.loads(json.dumps(manifest))
    manifest['export_selection']={'limit_unique_battles':None,'complete_only':False,'paired_only':False,
        'unique_battles':len({candidates[c]['match_id'] for c in chosen}),'clip_ids':chosen,
        'league_filter':'verified_open_great_league','review_sha256':hashlib.sha256(json.dumps(review,sort_keys=True).encode()).hexdigest()}
    manifest['league_review_completed']=bool(decisions) and all(r['league'] not in {'unknown','unverified'} for r in decisions.values())
    return manifest

def retained_after_retirement(root,sid,manifest):
    receipt_path=root/'receipts'/(sid+'-source-retirement.json')
    if not receipt_path.exists():return False
    receipt=load(receipt_path)
    if not receipt.get('deleted'):return False
    run=root/'runs'/sid
    if digest(run/'battle-candidates.json')!=receipt['manifest_sha256'] or digest(run/'league-review.json')!=receipt['league_review_sha256']:
        raise ValueError('Retirement provenance changed')
    if receipt.get('media_validation_sha256') and digest(run/'media-validation.json')!=receipt['media_validation_sha256']:
        raise ValueError('Retirement cut verification changed')
    expected=set(manifest['export_selection']['clip_ids'])
    if {c['id'] for c in receipt['cuts']}!=expected:
        raise ValueError('Retirement cut selection changed')
    for cut in receipt['cuts']:
        folder=root/'cuts'/cut['id']
        meta=load(folder/'battle.json')
        video=(folder/meta['video_file']).resolve()
        if not video.is_relative_to(folder.resolve()) or digest(video)!=cut['video_sha256'] or digest(folder/'frame_alignment.jsonl.gz')!=cut['alignment_sha256']:
            raise ValueError('Retained cut or alignment changed')
    return True

def verify_source_input(video,manifest,record,review):
    """Require the bytes, scan, source record and league witnesses to agree."""
    expected=manifest.get('fingerprint',{}).get('source_sha256')
    if not expected or record.get('media',{}).get('sha256')!=expected or review.get('source_sha256')!=expected:
        raise ValueError('Source record, coarse scan and league review have different byte provenance')
    if digest(video)!=expected:
        raise ValueError('Current full source bytes differ from the reviewed coarse scan')
    return expected

def finish(worker, sid, review_path, export_only=False):
    vod=frozen_modules()
    from vod_verify import verify
    from vod_track import read_clip, track_clip
    import game_record
    root=worker_root(worker)
    run=root/'runs'/sid
    review=load(review_path)
    manifest=selected_manifest(load(run/'battle-candidates.json'),review,root/'witnesses'/sid)
    selected=set(manifest['export_selection']['clip_ids'])
    retirement=root/'receipts'/(sid+'-source-retirement.json')
    source=root/'sources/twitch'/sid
    record=load(source/'source.json')
    if retirement.exists() and load(retirement).get('deleted'):
        # Validate existing proof before writing anything: a changed review
        # must not destroy the only retained provenance of a retired source.
        retained_after_retirement(root,sid,load(run/'battle-candidates.json'))
        if review!=load(run/'league-review.json') or manifest!=load(run/'battle-candidates.json'):
            raise ValueError('Cannot replace league evidence after source retirement')
    else:
        verify_source_input(source/'video.mp4',manifest,record,review)
        if not (run/'battle-candidates-unfiltered.json').exists():
            write(run/'battle-candidates-unfiltered.json',load(run/'battle-candidates.json'))
        write(run/'league-review.json',review)
        write(run/'battle-candidates.json',manifest)
    source_retired=retained_after_retirement(root,sid,manifest)
    if not selected:
        resolved=bool(review['decisions']) and all(r['league'] not in {'unknown','unverified'} for r in review['decisions'])
        scanned=manifest.get('scan_coverage',{}).get('full_recording_scanned') is True
        write(root/'receipts'/(sid+'.json'),{'source_id':sid,'status':'no_verified_open_candidates','done':resolved and scanned,
             'battles_saved':0,'cuts_saved':0,'source_retired':source_retired,
             'upload_date':record.get('upload_date'),'in_game_date':None,
             'league_mix':dict(collections.Counter(r['league'] for r in review['decisions']))})
        verify_freeze()
        return
    layout=manifest['fingerprint']['layout']
    views={r['id']:r for r in layout['views']}
    cuts=root/'cuts'
    if not source_retired:
        for view_id,rows in manifest['views'].items():
            for candidate in rows:
                if candidate['id'] in selected:
                    vod.export_one(source/'video.mp4',candidate,views[view_id],cuts,
                        manifest['fingerprint'],record.get('creator') or layout['channel'],manifest['url'],record,preserve_existing=True)
        write(run/'battle-candidates.json',manifest)
        validation=verify(sid,cuts,run)
        if not validation['media_checks_passed']:
            raise ValueError('Full-frame clip alignment validation failed')
        verify_source_input(source/'video.mp4',manifest,record,review)
    verify_freeze()
    if export_only:
        write(root/'receipts'/(sid+'-cuts.json'),{'source_id':sid,'cuts_verified':True,'cuts_saved':len(selected),
            'done':False,'tracking_pending':True,'validation_sha256':digest(run/'media-validation.json')})
        return
    results=[]
    for cid in sorted(selected):
        folder=cuts/cid
        read_clip(folder,FROZEN/'screen_reader')
        result=track_clip(folder,FROZEN/'screen_reader',creator_root=root/'records'/layout['channel'])
        exported=FROZEN/result['creator_game_folder']
        game_record.write(exported)
        if not (exported/'game.json').is_file() or not (exported/'game.txt').is_file():
            raise ValueError('Missing typed render')
        results.append(result)
        write(root/'receipts'/(sid+'-tracking.json'),{'source_id':sid,'completed':results,'finished':len(results)==len(selected)})
    verify_freeze()
    write(root/'receipts'/(sid+'.json'),{'source_id':sid,'status':'tracked_with_unknowns','done':True,
        'battles_saved':len({c['match_id'] for rows in manifest['views'].values() for c in rows if c['id'] in selected}),
        'cuts_saved':len(selected),'league_mix':dict(collections.Counter(r['league'] for r in review['decisions'])),
        'upload_date':record.get('upload_date'),'in_game_date':None,'source_retired':source_retired,'records':results})

def retire(worker,sid):
    """Delete exactly one completed full source after positively verified cuts."""
    root=worker_root(worker).resolve()
    source_root=(root/'sources').resolve()
    video=(source_root/'twitch'/sid/'video.mp4').resolve()
    if not video.is_relative_to(source_root) or video.name!='video.mp4' or sid in EXCLUDED:
        raise ValueError('Source deletion target outside intended collection source folder')
    run=root/'runs'/sid
    manifest=load(run/'battle-candidates.json')
    selected=set(manifest['export_selection']['clip_ids'])
    if selected:
        validation=load(run/'media-validation.json')
        if not validation['media_checks_passed'] or selected!={c['id'] for c in validation['checked_clips']}:
            raise ValueError('Source retirement requires every retained cut verified')
    if not manifest['scan_coverage']['full_recording_scanned']:
        raise ValueError('Source scan incomplete')
    if manifest['export_selection'].get('league_filter')!='verified_open_great_league':
        raise ValueError('League review unfinished')
    if manifest.get('league_review_completed') is not True:
        raise ValueError('Source contains unresolved league candidates; retain it')
    reviewed=selected_manifest(manifest,load(run/'league-review.json'),root/'witnesses'/sid)
    if reviewed['export_selection']!=manifest['export_selection']:
        raise ValueError('League review changed after cut selection')
    verify_freeze()
    source_record=load(video.parent/'source.json')
    if digest(video)!=manifest['fingerprint']['source_sha256']:
        raise ValueError('Source bytes changed')
    cuts=[]
    for cid in sorted(selected):
        folder=root/'cuts'/cid
        meta=load(folder/'battle.json')
        path=(folder/meta['video_file']).resolve()
        if not path.is_relative_to(folder.resolve()) or digest(path)!=meta['video_sha256']:
            raise ValueError('Retained cut missing or changed')
        cuts.append({'id':cid,'video_sha256':meta['video_sha256'],'alignment_sha256':digest(folder/'frame_alignment.jsonl.gz')})
    receipt={'source_id':sid,'source_file':str(video),'source_sha256':digest(video),'source_bytes':video.stat().st_size,
        'source_upload_date':source_record.get('upload_date'),'cuts':cuts,
        'media_validation_sha256':digest(run/'media-validation.json') if selected else None,
        'league_review_sha256':digest(run/'league-review.json'),
        'reason':'all_accepted_cuts_verified' if selected else 'no_eligible_battles',
        'manifest_sha256':digest(run/'battle-candidates.json'),'retired_at':now(),'deleted':False}
    target=root/'receipts'/(sid+'-source-retirement.json')
    write(target,receipt)
    video.unlink()
    receipt['deleted']=True
    write(target,receipt)
    completed=root/'receipts'/(sid+'.json')
    if completed.exists():
        status=load(completed)
        status['source_retired']=True
        write(completed,status)
    return receipt

def main():
    global BASE, FROZEN
    p=argparse.ArgumentParser()
    p.add_argument('action',choices=['claim','detect','witnesses','export_verify','finish','retire'])
    p.add_argument('--work-root', type=Path, default=BASE)
    p.add_argument('--worker',default='worker-b',choices=['worker-a','worker-b'])
    p.add_argument('--source-id')
    p.add_argument('--review')
    p.add_argument('--times',nargs='*',type=float)
    a=p.parse_args()
    BASE=a.work_root.resolve()
    FROZEN=BASE/'frozen-reader'
    pin(0 if a.worker=='worker-a' else 1)
    if a.action=='claim':print(json.dumps(claim(a.worker)))
    elif a.action=='detect':detect(a.worker,a.source_id)
    elif a.action=='finish':finish(a.worker,a.source_id,a.review)
    elif a.action=='export_verify':finish(a.worker,a.source_id,a.review,export_only=True)
    elif a.action=='retire':print(json.dumps(retire(a.worker,a.source_id)))
    else:
        frozen_modules()
        root=worker_root(a.worker)
        witnesses(root/'sources/twitch'/a.source_id/'video.mp4',a.times,root/'witnesses'/a.source_id)

if __name__=='__main__':main()
