"""Explicit outer exclusion of wholly non-open VODs; never a reader pass."""
from __future__ import annotations
import argparse
import ctypes
import gzip
import json
import math
from pathlib import Path
import re
import sys

import collection_ops as ops

LEGACY_A_WRAPPER_SHA256='188fee5b16b187a3b7fa2412e0f865c99851608498d1d23cd272e227b9b308b9'
NONOPEN_LEAGUES={'restricted_laic_cup','restricted_cup','great_league_remix','ultra_league','mega_ultra_league','master_league','mega_master_league','little_cup','other_non_open'}


def inactive(pid):
    if not isinstance(pid,int) or isinstance(pid,bool) or pid<=0:
        return False
    if sys.platform!='win32':
        import os
        try:os.kill(pid,0)
        except ProcessLookupError:return True
        except PermissionError:return False
        return False
    kernel=ctypes.windll.kernel32
    kernel.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong]
    kernel.OpenProcess.restype=ctypes.c_void_p
    kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    handle=kernel.OpenProcess(0x1000,False,pid)
    if not handle:
        return kernel.GetLastError()==87
    try:
        code=ctypes.c_ulong()
        kernel.GetExitCodeProcess.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)]
        return bool(kernel.GetExitCodeProcess(handle,ctypes.byref(code))) and code.value!=259
    finally:kernel.CloseHandle(handle)


def validate_stop(proof, *, worker, sid, run, frozen, is_inactive=None):
    if is_inactive is None:is_inactive=inactive
    if proof.get('source_id')!=sid or proof.get('worker')!=worker or not proof.get('processes'):
        raise ValueError('Missing exact-source process stop proof')
    if proof.get('post_stop_cim_verified') is not True or proof.get('remaining_owned_processes')!=[]:
        raise ValueError('Owned reader descendants have not been checked after stopping')
    expected_script=str((frozen/'scripts/recording/vod.py').resolve()).replace('\\','/').lower()
    expected_run=str(run.resolve()).replace('\\','/').lower()
    for row in proof['processes']:
        command=str(row.get('command_line','')).replace('\\','/').lower()
        identified=expected_script in command and expected_run in command and ('https://www.twitch.tv/videos/'+sid) in command
        if not identified and worker=='worker-a' and row.get('legacy_wrapper'):
            wrapper=Path(row['legacy_wrapper']).resolve()
            allowed=(ops.BASE/'helpers/worker_a_detect.py').resolve()
            relative=str(allowed.relative_to(ops.REPO)).replace('\\','/').lower() if allowed.is_relative_to(ops.REPO) else None
            identified=(wrapper==allowed and ops.digest(wrapper)==LEGACY_A_WRAPPER_SHA256 and
                (str(wrapper).replace('\\','/').lower() in command or relative is not None and relative in command) and bool(re.search(r'(?<![0-9])'+sid+r'(?![0-9])',command)) and
                Path(row.get('owned_run_dir','')).resolve()==run.resolve())
        if not row.get('verified_before_stop') or not row.get('stopped') or not identified:
            raise ValueError('Process proof does not identify this owned frozen scan')
        if not is_inactive(row.get('pid')):
            raise ValueError('Owned source scan is still active or cannot be checked')
    for parent in proof.get('orchestrators',[]):
        command=str(parent.get('command_line','')).replace('\\','/').lower()
        helpers=[ops.REPO/'scripts/recording/collection_ops.py',ops.BASE/'helpers/collection_ops.py']
        helper_names=[str(h.resolve()).replace('\\','/').lower() for h in helpers]
        helper_names += [str(h.resolve().relative_to(ops.REPO)).replace('\\','/').lower() for h in helpers if h.resolve().is_relative_to(ops.REPO)]
        if not any(h in command for h in helper_names) or not re.search(r'(?<![0-9])'+sid+r'(?![0-9])',command) or worker not in command:
            raise ValueError('Unrecognized owned scanner orchestrator')
        if not any(row.get('parent_pid')==parent.get('pid') for row in proof['processes']):
            raise ValueError('Orchestrator is not linked to the owned frozen reader')
        if not parent.get('verified_before_stop') or not parent.get('stopped') or not is_inactive(parent.get('pid')):
            raise ValueError('Owned scanner orchestrator is still active')


def checked_artifacts(proof, owned):
    artifacts=proof.get('artifacts') or proof.get('matrix_files')
    if not artifacts:
        raise ValueError('Missing decoder proof artifacts')
    for item in artifacts:
        path=Path(item['file']).resolve()
        if not path.is_relative_to(owned.resolve()) or ops.digest(path)!=item['sha256']:
            raise ValueError('Decoder proof escaped owned witnesses or changed')


def validate_nonopen(manifest,review,witness_root,duration):
    selected=ops.selected_manifest(manifest,review,witness_root)
    if selected['export_selection']['clip_ids'] or not selected['league_review_completed']:
        raise ValueError('Open or unresolved candidates cannot be excluded')
    if review.get('context_coverage_reviewed') is not True or review.get('league_change_review_complete') is not True:
        raise ValueError('Whole-source league context review unfinished')
    candidates={c['id']:c for rows in manifest['views'].values() for c in rows}
    for row in review['decisions']:
        if row['league'] not in NONOPEN_LEAGUES:
            raise ValueError('Unrecognized non-open league classification')
        c=candidates[row['candidate_id']]
        coverage=row.get('continuity_review',{})
        start,end=coverage.get('from_source_seconds'),coverage.get('to_source_seconds')
        if any(not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v) for v in (start,end)):
            raise ValueError('Missing finite league context interval')
        if not 0<=start<=c['start']<c['end']<=end<=duration+.05 or coverage.get('unresolved_transitions')!=0 or coverage.get('method')!='full_coarse_context_and_source_frames':
            raise ValueError('League context does not cover this candidate')
        for w in row['in_game_league_evidence']['witnesses']:
            t=w.get('source_seconds')
            if not isinstance(t,(int,float)) or isinstance(t,bool) or not math.isfinite(t) or not start<=t<=c['start']:
                raise ValueError('League witness outside causal reviewed context')
    return selected


def candidate_manifest(scan,sid):
    ops.frozen_modules()
    from vod_segments import discover_segments,annotate_segments
    views={}
    for name,rows in scan['views'].items():
        rough=discover_segments(rows,name,scan['duration_seconds'],min_duration=3)
        views[name]=annotate_segments(rough,rows,sid,name,scan['duration_seconds'],min_duration=3)
    return {'source_id':sid,'views':views}


def exclude(worker,sid,review_path,decoder_path,stop_path,*,retire=False):
    root=ops.worker_root(worker).resolve()
    run=root/'runs'/sid
    source_root=(root/'sources').resolve()
    video=(source_root/'twitch'/sid/'video.mp4').resolve()
    if sid in ops.EXCLUDED or not sid.isdigit() or not video.is_relative_to(source_root):
        raise ValueError('Unsafe or reserved source')
    freeze=ops.verify_freeze()
    source=ops.load(video.parent/'source.json')
    with gzip.open(run/'coarse-scan.json.gz','rt',encoding='utf-8') as stream:scan=json.load(stream)
    expected=source['media']['sha256']
    duration=source['media']['duration_seconds']
    if scan['fingerprint']['source_sha256']!=expected or abs(scan['duration_seconds']-duration)>.05:
        raise ValueError('Incomplete or mismatched coarse source coverage')
    if scan['fingerprint'].get('scan_end_seconds',duration)<duration-.05:
        raise ValueError('Capped scan cannot exclude a full source')
    if scan['fingerprint'].get('scan_start_seconds',0)!=0 or scan.get('scan_start_seconds',0)!=0:
        raise ValueError('A source suffix cannot establish whole-source coverage')
    review=ops.load(review_path)
    if review.get('source_sha256')!=expected:
        raise ValueError('League review belongs to different source bytes')
    manifest=validate_nonopen(candidate_manifest(scan,sid),review,root/'witnesses'/sid,duration)
    decoder=ops.load(decoder_path)
    resolved=(decoder.get('issue_resolved') is True and decoder.get('witness_decode_mode')=='persistent_for_pixel_copy') or (
        decoder.get('decoder_provenance_resolved') is True and decoder.get('actual_disagreement') is False and
        decoder.get('all_hashes_agree_per_requested_timestamp') is True and decoder.get('source_replacement_ruled_out') is True and
        decoder.get('native_matrix_samples',0)>=2)
    if decoder.get('source_id')!=sid or decoder.get('source_sha256')!=expected or not resolved:
        raise ValueError('Decoder proof is unresolved or belongs to another source')
    checked_artifacts(decoder,root/'witnesses'/sid)
    stop=ops.load(stop_path)
    validate_stop(stop,worker=worker,sid=sid,run=run,frozen=ops.FROZEN)
    if ops.digest(video)!=expected:
        raise ValueError('Source bytes changed')
    proof_files={str(p.resolve()):ops.digest(p) for p in map(Path,[review_path,decoder_path,stop_path,run/'coarse-scan.json.gz'])}
    receipt={'schema':'creator-vod-early-exclusion-v1','source_id':sid,'worker':worker,'done':True,
        'source_excluded':True,'reader_detection_completed':False,'full_game_state_verified':False,
        'reason':'all_coarse_candidates_source_reviewed_non_open','battles_saved':0,'cuts_saved':0,
        'league_mix':dict(__import__('collections').Counter(r['league'] for r in review['decisions'])),
        'upload_date':source.get('upload_date'),'in_game_date':None,'source_sha256':expected,
        'source_bytes':video.stat().st_size,'whole_coarse_source_covered':True,'source_seconds':duration,
        'candidate_ids':[c['id'] for rows in manifest['views'].values() for c in rows],
        'proof_files_sha256':proof_files,'frozen_files_checked':freeze['files_checked'],'source_retired':False,
        'completed_at':ops.now()}
    ops.write(root/'receipts'/(sid+'.json'),receipt)
    if retire:
        # Recheck immediately before the one exact-file unlink. No directories,
        # cuts, partial downloads, historical inputs or backup files are removed.
        for path,sha in proof_files.items():
            if ops.digest(path)!=sha:raise ValueError('Exclusion proof changed before retirement')
        validate_nonopen(manifest,ops.load(review_path),root/'witnesses'/sid,duration)
        checked_artifacts(ops.load(decoder_path),root/'witnesses'/sid)
        validate_stop(ops.load(stop_path),worker=worker,sid=sid,run=run,frozen=ops.FROZEN)
        ops.verify_freeze()
        if ops.digest(video)!=expected:raise ValueError('Source changed before retirement')
        retirement={'source_id':sid,'source_file':str(video),'source_sha256':expected,'source_bytes':video.stat().st_size,
            'reason':'no_eligible_battles_explicit_outer_exclusion','deleted':False,'proof_files_sha256':proof_files,
            'reader_detection_completed':False,'retired_at':ops.now()}
        target=root/'receipts'/(sid+'-source-retirement.json')
        ops.write(target,retirement)
        video.unlink()
        retirement['deleted']=True;ops.write(target,retirement)
        receipt['source_retired']=True;ops.write(root/'receipts'/(sid+'.json'),receipt)
    return receipt


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--work-root',type=Path,default=ops.BASE)
    p.add_argument('--worker',required=True,choices=['worker-a','worker-b'])
    p.add_argument('--source-id',required=True)
    p.add_argument('--review',type=Path,required=True)
    p.add_argument('--decoder-proof',type=Path,required=True)
    p.add_argument('--stopped-process-proof',type=Path,required=True)
    p.add_argument('--retire',action='store_true')
    args=p.parse_args()
    ops.BASE=args.work_root.resolve();ops.FROZEN=ops.BASE/'frozen-reader'
    ops.pin(0 if args.worker=='worker-a' else 1)
    print(json.dumps(exclude(args.worker,args.source_id,args.review,args.decoder_proof,args.stopped_process_proof,retire=args.retire),indent=2))


if __name__=='__main__':main()
