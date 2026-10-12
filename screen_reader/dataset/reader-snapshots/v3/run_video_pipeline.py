"""Import, discover, extract, and read battles with one resumable local command.

Example: python run_video_pipeline.py https://youtu.be/qSaL7jM9NbA --stage track
Known references reuse their originals and layout profiles. Other recordings need
an explicit calibrated profile; this pipeline never assumes a creator's layout.
"""
from __future__ import annotations
import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
import sys
import time
import shutil

from button_reader import ROOT
from import_source import import_source, write_record
from segment_battles import scan_video, propose_segments, file_sha256, VERSION
from extract_battles import export_candidates


def archive_analysis(folder):
    """Retain prior saved analysis once per content version; never copy media."""
    folder=Path(folder)
    names=[name for name in ["viewer-data.json.gz","screen_readings.jsonl.gz","screen_events.jsonl.gz",
                             "analysis-summary.json","battle.json"] if (folder/name).is_file()]
    if not names:
        return None
    version=file_sha256(folder/names[0])[:16]
    archive=folder/"analysis-archive"/version
    archive.mkdir(parents=True,exist_ok=True)
    for name in names:
        target=archive/name
        if not target.exists():
            shutil.copyfile(folder/name,target)
        elif file_sha256(target)!=file_sha256(folder/name):
            # A package may be unchanged while raw logs differ. Preserve both
            # versions without overwriting an archive.
            target=archive/(file_sha256(folder/name)[:12]+"-"+name)
            if not target.exists():shutil.copyfile(folder/name,target)
    return str(archive.relative_to(folder))


def ensure_original_alignment(folder,meta):
    """Recover source PTS for old clips that predate alignment sidecars."""
    import av
    path=Path(folder)/"frame_alignment.jsonl.gz"
    if path.exists():
        return path
    source=Path(meta.get("source_video", ""))
    if not source.is_absolute():source=ROOT/source
    if not source.is_file() or not meta.get("frames"):
        return None
    start,end=meta["source_start_seconds"],meta["source_end_seconds"]
    rows=[]
    with av.open(str(source)) as container:
        container.streams.video[0].codec_context.thread_count=2
        container.seek(int(max(0,start-2)*av.time_base))
        rate=meta["fps"]
        for frame in container.decode(video=0):
            if frame.pts is None:continue
            timestamp=float(frame.pts*frame.time_base)
            if timestamp<start-1e-7:continue
            if timestamp>=end:break
            rows.append({"clip_frame_index":len(rows),"clip_seconds":round((timestamp-start)*rate)/rate,
                         "source_seconds":timestamp,"source_pts":frame.pts,"source_time_base":str(frame.time_base)})
    if len(rows)!=meta["frames"]:
        raise ValueError("Legacy clip frame count differs from its recorded original source interval")
    temporary=path.with_name("frame_alignment.incomplete.jsonl.gz")
    with gzip.open(temporary,"wt",encoding="utf-8") as stream:
        for row in rows:stream.write(json.dumps(row,separators=(",",":"))+"\n")
    temporary.replace(path)
    return path


def prediction_hashes(profile):
    paths=[ROOT/name for name in ["battle_reader.py","button_reader.py","health_reader.py",
                                  "health_tracker.py","local_ocr.py","build_viewer.py",
                                  "run_video_pipeline.py","requirements.txt","scene_tracker.py",
                                  "tracker_bundle/data/gamemaster.json"]]
    layout=json.loads(Path(profile).read_text(encoding="utf-8"))
    paths.extend((Path(profile).parent/entry["file"]).resolve() for entry in layout.get("templates",[]))
    return {path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path):file_sha256(path)
            for path in paths if path.exists()},file_sha256(profile)


def predict_clip(folder, profile, *, seconds=None, ocr_interval=.5):
    """Publish causal frame readings and explicit unknowns, never default stats."""
    from battle_reader import BattleReader,EventTracker
    from build_viewer import compact
    from local_ocr import LocalOCR
    import av
    folder,profile=Path(folder),Path(profile)
    meta=json.loads((folder/"battle.json").read_text(encoding="utf-8"))
    video=folder/meta["video_file"]
    code_hashes,profile_hash=prediction_hashes(profile)
    video_hash=file_sha256(video)
    original_source=Path(meta.get("source_video", ""))
    if not original_source.is_absolute():original_source=ROOT/original_source
    original_sha=file_sha256(original_source) if original_source.is_file() else meta.get("source_sha256")
    provenance={"reader_code_sha256":code_hashes,"profile_sha256":profile_hash,
                "video_sha256":video_hash,"source_video_sha256":original_sha,
                "source_start_seconds":meta["source_start_seconds"],"ocr_interval_seconds":ocr_interval,
                "requested_seconds":seconds,"every_decoded_frame":True,
                "time_basis":"clip_presentation_timestamp_with_original_source_pts_alignment",
                "maximum_hp_supplied":False,"battle_action_start_verified":False,
                "python_version":sys.version.split()[0],"pyav_version":av.__version__,
                "coverage":"partial" if seconds is not None else "full_clip"}
    target=folder/"viewer-data.json.gz"
    if target.exists():
        with gzip.open(target,"rt",encoding="utf-8") as stream:
            previous=json.load(stream)
        if previous.get("prediction_provenance")==provenance:
            return {"id":meta["id"],"reused_predictions":True}
        bookmarks=previous.get("bookmarks",[])
    else:
        previous={}
        bookmarks=[]
    reader,events=BattleReader(profile,LocalOCR(),ocr_interval),EventTracker()
    rows=[];event_rows=[];phase_counts=Counter();field_counts=Counter();progress=time.monotonic()
    alignment_path=ensure_original_alignment(folder,meta) or folder/"frame_alignment.jsonl.gz"
    alignment=None
    if alignment_path.exists():
        with gzip.open(alignment_path,"rt",encoding="utf-8") as stream:
            alignment=[json.loads(line) for line in stream if line.strip()]
    raw_temp=folder/"screen_readings.incomplete.jsonl.gz"
    event_temp=folder/"screen_events.incomplete.jsonl.gz"
    with av.open(str(video)) as container, gzip.open(raw_temp,"wt",encoding="utf-8") as raw, gzip.open(event_temp,"wt",encoding="utf-8") as event_log:
        container.streams.video[0].codec_context.thread_count=2
        for index,frame in enumerate(container.decode(video=0)):
            if frame.pts is None:
                continue
            t=float(frame.pts*frame.time_base)
            if seconds is not None and t>=seconds:
                break
            reading=reader.detect(frame.to_image(),t,index,[0,0,frame.width,frame.height])
            reading["coordinates_basis"]="battle_clip_frame"
            reading["clip_pts"],reading["clip_time_base"]=frame.pts,str(frame.time_base)
            source=alignment[index] if alignment is not None else None
            if source is not None:
                if abs(source["clip_seconds"]-t)>1/float(container.streams.video[0].average_rate):
                    raise ValueError("Frame-to-source alignment differs from clip PTS")
                reading["source_pts"],reading["source_time_base"]=source["source_pts"],source["source_time_base"]
                reading["source_timestamp_seconds"]=source["source_seconds"]
            else:
                reading["source_timestamp_seconds"]=t+meta["source_start_seconds"]
                reading["source_timestamp_precision"]="clip_offset_only_original_pts_unavailable"
            raw.write(json.dumps(reading,separators=(",",":"),ensure_ascii=False)+"\n")
            display=compact(reading)
            if "phase_estimate" in reading:
                display["phase_estimate"]=reading["phase_estimate"]
            rows.append(display)
            phase_counts[reading["phase"]["value"] or "unknown"]+=1
            for side in ["mine","opponent"]:
                for field in ["species","cp","health_bar","shields_left","pokemon_left","energy"]:
                    field_counts[f"{side}.{field}.{reading[side][field]['status']}"]+=1
            for event in events.update(reading):
                event_log.write(json.dumps(event,separators=(",",":"),ensure_ascii=False)+"\n")
                event_rows.append({"t":event["observed_at_seconds"],"event":event})
            if time.monotonic()-progress>20:
                print(json.dumps({"battle":meta["id"],"clip_seconds":round(t,2),"decoded_frames":len(rows)}),flush=True)
                progress=time.monotonic()
    if not rows:
        raise ValueError("No prediction frames decoded")
    if prediction_hashes(profile)!=(code_hashes,profile_hash) or file_sha256(video)!=video_hash:
        raise ValueError("Reader, profile, or clip changed during analysis; unfinished predictions were not published")
    data={**previous,"readings":rows,"states":previous.get("states",[]),
          "observations":previous.get("observations",[]),"events":previous.get("events",[]),
          "screen_events":event_rows,"bookmarks":bookmarks,"prediction_provenance":provenance}
    temporary=folder/"viewer-data.incomplete.json.gz"
    temporary.write_bytes(gzip.compress(json.dumps(data,separators=(",",":"),ensure_ascii=False).encode("utf-8"),compresslevel=6,mtime=0))
    archive=archive_analysis(folder)
    temporary.replace(target)
    raw_temp.replace(folder/"screen_readings.jsonl.gz")
    event_temp.replace(folder/"screen_events.jsonl.gz")
    summary={"id":meta["id"],"decoded_frames":len(rows),"phase_counts":dict(phase_counts),
             "field_status_counts":dict(field_counts),"full_game_state_verified":False,"provenance":provenance}
    write_record(folder/"analysis-summary.json",summary)
    meta["analysis_status"]="partial" if seconds is not None else "analyzed_with_unknowns"
    meta["prior_analysis_archive"]=archive
    meta["analysis_archive_bytes"]=sum(p.stat().st_size for p in (folder/"analysis-archive").rglob("*") if p.is_file()) if (folder/"analysis-archive").exists() else 0
    meta["saved_data_bytes"]=sum(p.stat().st_size for p in folder.iterdir() if p.is_file() and p!=video)
    write_record(folder/"battle.json",meta)
    return summary


def run_pipeline(url, *, profile=None, library=None, stage="track", download=False, only=None,
                 interval=.5, predict_seconds=None, rescan=False, root=ROOT):
    root=Path(root)
    imported=import_source(url,download=download,root=root)
    if not imported.get("media_file"):
        raise ValueError("Source metadata inspected but no video downloaded; add --download to process it")
    sid=imported["source_id"]
    references=json.loads((root/"reference_manifest.json").read_text(encoding="utf-8"))["references"] if (root/"reference_manifest.json").exists() else []
    reference=next((r for r in references if r["id"]==sid),None)
    if profile is None and reference:
        profile=root/reference["profile"]
    if profile is None:
        raise ValueError("A new recording requires --profile with its calibrated gameplay viewport and UI layout")
    profile=Path(profile).resolve();layout=json.loads(profile.read_text(encoding="utf-8"))
    video=(root/imported["media_file"]).resolve()
    job_folder=root/"sources"/imported["platform"]/sid
    cache=job_folder/"segmentation-samples.json.gz"
    if cache.exists() and not rescan:
        with gzip.open(cache,"rt",encoding="utf-8") as stream:
            facts=json.load(stream)
        if facts.get("detector")!=VERSION or facts["source_sha256"]!=file_sha256(video) or facts["profile"]!=layout or facts["sample_interval_seconds"]!=interval:
            raise ValueError("Cached scan differs from the input/profile/interval; use --rescan")
    else:
        facts=scan_video(video,layout,interval=interval,output=cache)
    manifest={"schema":"battle-boundary-candidates-v1","detector":VERSION,
              "detector_sha256":file_sha256(ROOT/"segment_battles.py"),"source_id":sid,
              "source_video":str(video),"source_sha256":facts["source_sha256"],
              "sample_interval_seconds":interval,"segments":propose_segments(facts,sid),"review_required":True}
    write_record(job_folder/"battle-candidates.json",manifest)
    job={"schema":"video-pipeline-run-v1","source_id":sid,"source_sha256":facts["source_sha256"],
         "stage":stage,"profile_sha256":file_sha256(profile),"candidate_count":len(manifest["segments"]),
         "candidates_file":str(job_folder/"battle-candidates.json"),
         "evaluation_role":"unassigned_not_independently_tested","boundaries_review_required":True,
         "full_game_state_verified":False}
    if stage in {"extract","track"}:
        library=Path(library or root/"battles")
        audio=(root/reference["audio"]) if reference and reference.get("audio") else None
        job["exports"]=export_candidates(manifest,library,viewport=layout["viewport"],video=video,audio=audio,
                                         creator=imported.get("creator") or "Local recording",url=imported["url"],only=only)
        if stage=="track":
            job["predictions"]=[predict_clip(library/exported["id"],profile,seconds=predict_seconds) for exported in job["exports"]]
    write_record(job_folder/"pipeline-run.json",job)
    return job


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--download",action="store_true")
    parser.add_argument("--profile",type=Path)
    parser.add_argument("--library",type=Path)
    parser.add_argument("--stage",choices=["detect","extract","track"],default="track")
    parser.add_argument("--only",action="append",help="Candidate id to export/track; may be repeated")
    parser.add_argument("--interval",type=float,default=.5)
    parser.add_argument("--predict-seconds",type=float,help="Explicitly partial per-battle smoke check")
    parser.add_argument("--rescan",action="store_true")
    args=parser.parse_args()
    if args.interval<=0 or (args.predict_seconds is not None and args.predict_seconds<=0):
        parser.error("Intervals must be positive")
    result=run_pipeline(args.url,profile=args.profile,library=args.library,stage=args.stage,download=args.download,
                        only=args.only,interval=args.interval,predict_seconds=args.predict_seconds,rescan=args.rescan)
    print(json.dumps(result,separators=(",",":")),flush=True)


if __name__=="__main__":
    main()
