"""Source-calibrated intake with a mandatory manual continuous-battle review.

The screen reader and its parameters are unchanged. `prepare` creates pending
intervals, never an exportable manifest. `approve` requires source witnesses for
the layout, league, replay context, and each reviewed game's boundaries/grouping.
Completed normalized source media must already exist in the owned workspace.
"""
from __future__ import annotations
import argparse
import copy
import gzip
import math
from pathlib import Path
import shutil

import collection_ops as ops

CHANNELS={'homeslicehenry','itsaxn','reis2occasion'}
ALIASES={'homeslicehenry':'homeslicehenry','itsaxn':'itsaxn','reis2occasion':'reis2occasion','reis2theoccasion':'reis2occasion'}


def finite(value):
    return type(value) in (int,float) and math.isfinite(value)


def canonical_channel(value):
    key=''.join(c for c in str(value).lower() if c.isalnum())
    return ALIASES.get(key)


def witnesses(rows,root,duration):
    if not rows:raise ValueError('Missing source-frame witnesses')
    for row in rows:
        p=Path(row['file']).resolve()
        if not p.is_relative_to(root.resolve()) or ops.digest(p)!=row['sha256']:
            raise ValueError('Source witness is outside owned evidence or changed')
        if not finite(row.get('source_seconds')) or not 0<=row['source_seconds']<=duration:
            raise ValueError('Invalid source witness time')


def validate_layout(layout,source,owned_witnesses,profiles_root):
    if layout.get('schema')!='creator-source-calibration-v1' or layout.get('source_id')!=str(source['source_id']):
        raise ValueError('Calibration belongs to another source')
    if layout.get('source_sha256')!=source['media']['sha256']:
        raise ValueError('Calibration belongs to different source bytes')
    channel=canonical_channel(source.get('creator'))
    if channel not in CHANNELS or layout.get('channel')!=channel:
        raise ValueError('Calibration channel must match this actual source creator')
    if layout.get('broadcast_regions')!=[] or layout.get('source_kind')!='direct_creator_phone':
        raise ValueError('This path needs an explicit direct-phone calibration, not an invented label region')
    if layout.get('manual_context_review_required') is not True or not layout.get('reviewed_by'):
        raise ValueError('Missing mandatory manual replay/layout review declaration')
    media=source['media'];size=[media['width'],media['height']]
    if layout.get('frame_size')!=size:raise ValueError('Calibration frame dimensions differ')
    views=layout.get('views',[])
    if len(views)!=1 or views[0].get('id')!='pov':raise ValueError('Creator intake expects one physical phone view')
    view=views[0]
    if set(view)!={'id','base_profile','viewport'}:
        raise ValueError('Source calibration cannot override frozen reader parameters')
    profile=view['base_profile']
    if Path(profile).name!=profile or not profile.endswith('.json') or not (profiles_root/profile).is_file():
        raise ValueError('Unknown frozen base profile')
    rect=view['viewport']
    if not isinstance(rect,list) or len(rect)!=4 or any(type(v) is not int for v in rect):raise ValueError('Invalid physical crop')
    x,y,w,h=rect
    if min(x,y)<0 or min(w,h)<=0 or w%2 or h%2 or x+w>size[0] or y+h>size[1]:
        raise ValueError('Crop is outside the recording or cannot be encoded exactly')
    rows=layout.get('witnesses',[])
    witnesses(rows,owned_witnesses,media['duration_seconds'])
    if len({r['source_seconds'] for r in rows})<2:
        raise ValueError('Physical layout needs repeated source observations')
    return {'channel':channel,'dataset_role':'unassigned','source_ids':[str(source['source_id'])],
        'frame_size':size,'views':copy.deepcopy(views),'broadcast_regions':[],
        'label_prefix':channel+' · source-reviewed recording'}


def current_source(root,sid):
    if not sid.isdigit() or sid in ops.EXCLUDED:raise ValueError('Invalid or heldout source')
    source_dir=(root/'sources/twitch'/sid).resolve()
    if not source_dir.is_relative_to((root/'sources').resolve()):raise ValueError('Source escaped workspace')
    record=ops.load(source_dir/'source.json');video=source_dir/'video.mp4'
    if record.get('source_id')!=sid or record.get('platform')!='twitch':raise ValueError('Source identity differs')
    if 'mp4' not in record['media']['container'] and 'mov' not in record['media']['container']:
        raise ValueError('Normalize the preserved completed source before calibration')
    if abs(record['media']['container_start_seconds'])>.05:raise ValueError('A shared-origin source is required')
    if ops.digest(video)!=record['media']['sha256']:raise ValueError('Current source differs from its pinned metadata')
    return video,record


def detection_run(root,sid,explicit=None):
    run=Path(explicit).resolve() if explicit else (root/'runs'/sid/'calibrated-v1').resolve()
    if not run.is_relative_to((root/'runs'/sid).resolve()):raise ValueError('Detection version escaped its owned source run')
    return run


def preserve_json(path,value):
    if path.exists():
        if ops.load(path)!=value:raise ValueError('Preserve existing source evidence; choose a new detection-run version')
        return
    ops.write(path,value)


def prepare(worker,sid,layout_path,run_dir=None):
    vod=ops.frozen_modules()
    from vod_segments import VERSION,profiles_for,coarse_scan,discover_segments,annotate_segments
    root=ops.worker_root(worker).resolve();canonical=root/'runs'/sid;run=detection_run(root,sid,run_dir)
    if (canonical/'battle-candidates.json').exists():raise ValueError('An existing final manifest cannot be overwritten')
    video,record=current_source(root,sid)
    layout=validate_layout(ops.load(layout_path),record,root/'witnesses'/sid,ops.FROZEN/'screen_reader/profiles')
    profiles=profiles_for(layout,ops.FROZEN/'screen_reader',ops.FROZEN/'data/gamemaster.json')
    run.mkdir(parents=True,exist_ok=True)
    preserve_json(run/'source-calibration-input.json',ops.load(layout_path))
    # Reuse a byte-identical full coarse result only when its exact profile and
    # source fingerprint agree. The original cache remains unchanged.
    prior=canonical/'coarse-scan.json.gz';cache=run/'coarse-scan.json.gz'
    if not cache.exists() and prior.exists():
        with gzip.open(prior,'rt',encoding='utf-8') as stream:old=__import__('json').load(stream)
        if old['fingerprint'].get('source_sha256')==record['media']['sha256'] and old['fingerprint'].get('profiles')==profiles and abs(old['duration_seconds']-record['media']['duration_seconds'])<=.05:
            shutil.copy2(prior,cache)
            preserve_json(run/'coarse-reuse.json',{'original_file':str(prior),'original_sha256':ops.digest(prior),'copied_sha256':ops.digest(cache),'fingerprint_rewritten':False})
    scan=coarse_scan(video,profiles,cache)
    if abs(scan['duration_seconds']-record['media']['duration_seconds'])>.05 or scan['fingerprint'].get('scan_start_seconds',0)!=0 or scan.get('scan_start_seconds',0)!=0:
        raise ValueError('Whole source was not scanned')
    if scan['fingerprint']['source_sha256']!=record['media']['sha256'] or scan['fingerprint'].get('scan_end_seconds',scan['duration_seconds'])<record['media']['duration_seconds']-.05:
        raise ValueError('Coarse source fingerprint differs or covers only a prefix')
    if ops.digest(video)!=record['media']['sha256']:raise ValueError('Source changed during the frozen coarse scan')
    views={name:annotate_segments(discover_segments(rows,name,scan['duration_seconds'],min_duration=3),
        rows,sid,name,scan['duration_seconds'],min_duration=3) for name,rows in scan['views'].items()}
    fingerprint={'detector':VERSION,'source_sha256':scan['fingerprint']['source_sha256'],'layout':layout,
        'boundary_sampling':'keyframes','outer_driver_sha256':ops.digest(__file__),
        'source_calibration_sha256':ops.digest(run/'source-calibration-input.json'),
        'code_sha256':{n:ops.digest(ops.FROZEN/'scripts/recording'/n) for n in
            ['vod.py','vod_media.py','vod_segments.py','vod_broadcast.py','vod_layout.py','vod_fixture.py']},
        'reader_sha256':{n:ops.digest(ops.FROZEN/'screen_reader'/n) for n in
            ['segment_battles.py','extract_battles.py','local_ocr.py']}}
    pending={'schema':'source-calibrated-pending-intervals-v1','source_id':sid,'platform':'twitch','url':record['url'],
        'fingerprint':fingerprint,'views':views,'manual_source_context_review_required':True,
        'broadcast_label_scan_performed':False,'broadcast_label_evidence':'not_measured_no_identified_broadcaster_region',
        'full_game_state_verified':False,'reader_detection_completed':False,
        'scan_coverage':{'source_seconds':record['media']['duration_seconds'],'scanned_seconds':scan['duration_seconds'],
            'full_recording_scanned':True,'partial_battles_kept':True,'selection_limited':False,
            'boundary_sampling':'keyframes','battle_recall_independently_verified':False}}
    pending['raw_coarse_scan_file']=cache.resolve().relative_to(ops.BASE).as_posix()
    pending['raw_coarse_scan_sha256']=ops.digest(cache)
    preserve_json(run/'calibrated-candidates.pending.json',pending)
    ops.verify_freeze()
    return {'source_id':sid,'raw_intervals':sum(map(len,views.values())),'exportable':False,
        'next_step':'Review source context and group raw fragments into actual continuous battles.'}


def review_battles(pending,review,witness_root):
    sid=pending['source_id'];duration=pending['scan_coverage']['source_seconds']
    if review.get('source_id')!=sid or review.get('source_sha256')!=pending['fingerprint']['source_sha256']:
        raise ValueError('Manual review source identity differs')
    for key in ('whole_coarse_context_reviewed','replays_reviewed','layout_changes_reviewed'):
        if review.get(key) is not True:raise ValueError('Full source context review is still pending')
    if not review.get('reviewed_by'):raise ValueError('Source reviewer missing')
    raw={c['id']:c for rows in pending['views'].values() for c in rows}
    used=set();battles=[];previous_end=-1
    for number,row in enumerate(review.get('battles',[]),1):
        ids=row.get('raw_fragment_ids',[])
        if not ids or len(set(ids))!=len(ids) or any(i not in raw or i in used for i in ids):
            raise ValueError('Each raw fragment needs exactly one reviewed battle assignment')
        if row.get('replay_status')!='direct_phone' or row.get('layout_status')!='consistent':
            raise ValueError('Replay or layout uncertainty must remain pending')
        if row.get('all_internal_gaps_reviewed') is not True:
            raise ValueError('Internal charged-animation gaps have not been reviewed')
        if row.get('all_visible_boundaries_reviewed') is not True:
            raise ValueError('Visible GO/result boundaries have not all been reviewed')
        start,end=row.get('start'),row.get('end')
        if not finite(start) or not finite(end) or not 0<=start<end<=duration or start<previous_end:
            raise ValueError('Reviewed battles overlap or have invalid boundaries')
        parts=sorted((raw[i] for i in ids),key=lambda c:c['start'])
        if start>parts[0]['start'] or end<max(c['end'] for c in parts):
            raise ValueError('Continuous battle cut would lose a raw fragment or internal animation')
        gaps=[(a['end'],b['start']) for a,b in zip(parts,parts[1:]) if b['start']>a['end']]
        reviews=row.get('gap_reviews',[])
        if len(reviews)!=len(gaps):raise ValueError('Every positive internal source gap needs continuity evidence')
        for gap,proof in zip(gaps,reviews):
            if (proof.get('start'),proof.get('end'))!=gap or proof.get('continuous_same_battle') is not True:
                raise ValueError('Internal source gap continuity remains unresolved')
            witnesses(proof.get('witnesses',[]),witness_root,duration)
        witnesses(row.get('context_witnesses',[]),witness_root,duration)
        boundary=row.get('boundary_evidence',{})
        for edge,allowed in [('start',{'visible_go','clipped'}),('end',{'visible_result','clipped'})]:
            item=boundary.get(edge,{})
            if item.get('status') not in allowed:raise ValueError('Battle boundary status unresolved')
            if item['status']!='clipped':witnesses(item.get('witnesses',[]),witness_root,duration)
        starts=row.get('observed_go_seconds',[])
        results=row.get('observed_result_seconds',[])
        if any(not finite(t) or not start<=t<=end for t in starts+results) or len(starts)>1 or len(results)>1:
            raise ValueError('More than one actual game was merged into one battle')
        if boundary['start']['status']=='visible_go' and len(starts)!=1:raise ValueError('Missing measured GO boundary')
        if boundary['end']['status']=='visible_result' and len(results)!=1:raise ValueError('Missing measured result boundary')
        c=copy.deepcopy(parts[0]);c.update(id=f'tw-{sid}-reviewed-pov-{number:03d}',match_id=f'tw-{sid}-match-{number:03d}',
            start=start,end=end,view_id='pov',name=pending['fingerprint']['layout']['channel']+f' · Reviewed battle {number:03d}',
            incomplete_start=boundary['start']['status']=='clipped',incomplete_end=boundary['end']['status']=='clipped',
            raw_fragment_ids=ids,source_boundary_review='manual_source_frames',source_segment_kind='live_candidate',dataset_role='unassigned')
        c['start_method']='manual_go_or_clipped_boundary'
        c['end_method']='manual_result_or_clipped_boundary'
        c['completeness']='result_visible' if not c['incomplete_end'] else 'source_reviewed_partial'
        c['eligible_for_complete_battle_evaluation']=not(c['incomplete_start'] or c['incomplete_end'])
        c.setdefault('notes',[]).append('Source-reviewed continuous battle; original frozen fragments retained separately. Full state remains unverified.')
        used.update(ids);previous_end=end;battles.append(c)
    if used!=set(raw) or not battles:raise ValueError('Raw intervals remain unaccounted or no battles were reviewed')
    return battles


def approve(worker,sid,review_path,run_dir=None):
    ops.frozen_modules();root=ops.worker_root(worker).resolve();canonical=root/'runs'/sid;run=detection_run(root,sid,run_dir)
    if (canonical/'battle-candidates.json').exists():raise ValueError('Existing final manifest cannot be overwritten')
    video,record=current_source(root,sid)
    pending=ops.load(run/'calibrated-candidates.pending.json')
    if pending['fingerprint']['source_sha256']!=record['media']['sha256']:raise ValueError('Pending coarse provenance differs')
    if ops.digest(run/'coarse-scan.json.gz')!=pending['raw_coarse_scan_sha256']:
        raise ValueError('Original coarse evidence changed after preparation')
    if ops.digest(run/'source-calibration-input.json')!=pending['fingerprint']['source_calibration_sha256']:
        raise ValueError('Physical calibration changed after preparation')
    from collection_exclusion import candidate_manifest
    with gzip.open(run/'coarse-scan.json.gz','rt',encoding='utf-8') as stream:scan=__import__('json').load(stream)
    if candidate_manifest(scan,sid)['views']!=pending['views']:
        raise ValueError('Raw frozen intervals were edited instead of reviewed separately')
    review=ops.load(review_path);battles=review_battles(pending,review,root/'witnesses'/sid)
    calibration=ops.load(run/'source-calibration-input.json')
    validate_layout(calibration,record,root/'witnesses'/sid,ops.FROZEN/'screen_reader/profiles')
    preserve_json(run/'manual-source-context-review.json',review)
    manifest=copy.deepcopy(pending);manifest['schema']='source-calibrated-reviewed-battles-v1'
    manifest['views']={'pov':battles};manifest['manual_source_context_review_required']=False
    manifest['manual_source_context_review_completed']=True;manifest['reader_detection_completed']=True
    manifest['reader_detection_method']='frozen_coarse_plus_explicit_manual_context_and_battle_grouping'
    manifest['frozen_cli_run_completed']=False
    manifest['source_reviewed_intake_completed']=True
    manifest['unique_match_candidates']=len(battles);manifest['raw_fragment_count']=sum(map(len,pending['views'].values()))
    manifest['excluded_candidates']=[];manifest['broadcast_markers']=[]
    manifest['all_boundaries_review_required']=False
    manifest['export_selection']={'limit_unique_battles':None,'complete_only':False,'paired_only':False,
        'unique_battles':len(battles),'clip_ids':[b['id'] for b in battles]}
    manifest['fingerprint']['manual_context_review_sha256']=ops.digest(run/'manual-source-context-review.json')
    manifest['fingerprint']['approval_driver_sha256']=ops.digest(__file__)
    proof_paths=[run/'source-calibration-input.json',run/'manual-source-context-review.json',run/'calibrated-candidates.pending.json',run/'coarse-scan.json.gz']
    proof_paths += [Path(w['file']) for w in calibration['witnesses']]
    for b in review['battles']:
        proof_paths += [Path(w['file']) for w in b['context_witnesses']]
        for edge in ('start','end'):proof_paths += [Path(w['file']) for w in b['boundary_evidence'][edge].get('witnesses',[])]
        for gap in b.get('gap_reviews',[]):proof_paths += [Path(w['file']) for w in gap.get('witnesses',[])]
    manifest['source_calibration_proofs_sha256']={p.resolve().relative_to(ops.BASE).as_posix():ops.digest(p) for p in proof_paths}
    if ops.digest(video)!=record['media']['sha256']:raise ValueError('Source changed during review approval')
    ops.verify_freeze();ops.write(canonical/'battle-candidates.json',manifest)
    return {'source_id':sid,'raw_fragments':manifest['raw_fragment_count'],'reviewed_continuous_battles':len(battles),
        'broadcast_label_scan_performed':False,'full_game_state_verified':False}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage',choices=['prepare','approve'])
    p.add_argument('--work-root',type=Path,default=ops.BASE)
    p.add_argument('--worker',choices=['worker-a','worker-b'],required=True)
    p.add_argument('--source-id',required=True)
    p.add_argument('--detection-run-dir',type=Path,help='A new owned detection version; original coarse results are never rewritten')
    p.add_argument('--layout',type=Path)
    p.add_argument('--review',type=Path)
    args=p.parse_args();ops.BASE=args.work_root.resolve();ops.FROZEN=ops.BASE/'frozen-reader'
    ops.pin(0 if args.worker=='worker-a' else 1)
    if args.stage=='prepare' and args.layout is None:p.error('--layout is required')
    if args.stage=='approve' and args.review is None:p.error('--review is required')
    import json
    print(json.dumps(prepare(args.worker,args.source_id,args.layout,args.detection_run_dir) if args.stage=='prepare' else approve(args.worker,args.source_id,args.review,args.detection_run_dir),indent=2))


if __name__=='__main__':main()
