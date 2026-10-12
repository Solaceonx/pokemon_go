"""Promote validated dataset predictions into the playback library without decoding again."""
from __future__ import annotations
import argparse
from collections import Counter
import gzip
import json
from pathlib import Path

from button_reader import ROOT
from import_source import write_record
from segment_battles import file_sha256
from run_video_pipeline import archive_analysis,ensure_original_alignment


def validate_provenance(provenance, video, profile, root=ROOT):
    if provenance.get("video_sha256")!=file_sha256(video):
        raise ValueError("Prediction input video bytes differ from the saved battle")
    if provenance.get("profile_sha256")!=file_sha256(profile):
        raise ValueError("Prediction layout profile changed")
    hashes=provenance.get("reader_code_sha256")
    if not isinstance(hashes,dict) or not hashes:
        raise ValueError("Prediction package lacks reader fingerprints")
    for name,digest in hashes.items():
        path=Path(name)
        if not path.is_absolute():path=Path(root)/path
        if not path.is_file() or file_sha256(path)!=digest:
            raise ValueError(f"Reader input changed since prediction: {name}")
    for name,digest in provenance.get("template_sha256",{}).items():
        path=Path(name)
        if not path.is_absolute():path=Path(root)/path
        if not path.is_file() or file_sha256(path)!=digest:
            raise ValueError(f"Template image changed since prediction: {name}")
    return True


def promote_prediction(prediction, folder, profile, *, root=ROOT):
    from battle_reader import EventTracker
    from build_viewer import compact
    prediction,folder,profile=Path(prediction),Path(folder),Path(profile)
    with gzip.open(prediction,"rt",encoding="utf-8") as stream:data=json.load(stream)
    meta=json.loads((folder/"battle.json").read_text(encoding="utf-8"))
    video=folder/meta["video_file"]
    provenance=data.get("prediction_provenance",{})
    validate_provenance(provenance,video,profile,root)
    rows=data.get("readings",[])
    if not rows:
        raise ValueError("Prediction package has no frame readings")
    if provenance.get("coverage")=="full_clip" and len(rows)!=meta.get("frames"):
        raise ValueError("Full-clip prediction frame count differs from saved clip")
    if any("schema_version" not in row or "timestamp_seconds" not in row for row in rows):
        raise ValueError("Promotion needs raw frame predictions, not a compact viewer-only package")
    target=folder/"viewer-data.json.gz"
    with gzip.open(target,"rt",encoding="utf-8") as stream:previous=json.load(stream)
    input_hash=file_sha256(prediction)
    published=previous.get("prediction_provenance",{}).get("publication",{})
    if published.get("prediction_package_sha256")==input_hash:
        return {"id":meta["id"],"reused_publication":True,"decoded_frames":len(rows)}
    alignment_path=ensure_original_alignment(folder,meta)
    if alignment_path is None:
        raise ValueError("Original source PTS cannot be recovered for this clip")
    with gzip.open(alignment_path,"rt",encoding="utf-8") as stream:alignment=[json.loads(line) for line in stream if line.strip()]
    tracker=EventTracker();screen_events=[];display=[];phase_counts=Counter()
    raw_temp=folder/"screen_readings.incomplete.jsonl.gz"
    event_temp=folder/"screen_events.incomplete.jsonl.gz"
    last=-1
    with gzip.open(raw_temp,"wt",encoding="utf-8") as raw, gzip.open(event_temp,"wt",encoding="utf-8") as event_log:
        for ordinal,row in enumerate(rows):
            t=row["timestamp_seconds"]
            if t<=last:
                raise ValueError("Frame prediction times must strictly increase")
            last=t
            index=row.get("frame_index",ordinal)
            if not isinstance(index,int) or not 0<=index<len(alignment):
                raise ValueError("Prediction frame index lies outside the source alignment")
            source=alignment[index]
            if abs(source["clip_seconds"]-t)>1/meta["fps"]:
                raise ValueError("Prediction timestamp differs from source alignment")
            row["clip_pts"],row["clip_time_base"]=row.get("source_pts"),row.get("source_time_base")
            row["source_pts"],row["source_time_base"]=source["source_pts"],source["source_time_base"]
            row["source_timestamp_seconds"]=source["source_seconds"]
            row["coordinates_basis"]="battle_clip_frame"
            raw.write(json.dumps(row,separators=(",",":"),ensure_ascii=False)+"\n")
            frame=compact(row)
            if "phase_estimate" in row:frame["phase_estimate"]=row["phase_estimate"]
            display.append(frame)
            phase_counts[row["phase"].get("value") or "unknown"]+=1
            for event in tracker.update(row):
                event_log.write(json.dumps(event,separators=(",",":"),ensure_ascii=False)+"\n")
                screen_events.append({"t":event["observed_at_seconds"],"event":event})
    # Validate again immediately before replacing anything a viewer can read.
    validate_provenance(provenance,video,profile,root)
    layout=json.loads(profile.read_text(encoding="utf-8"))
    template_hashes={}
    for entry in layout.get("templates",[]):
        path=(profile.parent/entry["file"]).resolve()
        name=path.relative_to(Path(root).resolve()).as_posix() if path.is_relative_to(Path(root).resolve()) else str(path)
        template_hashes[name]=file_sha256(path)
    recorded_templates={**provenance.get("reader_code_sha256",{}),**provenance.get("template_sha256",{})}
    templates_verified=all(recorded_templates.get(name)==sha for name,sha in template_hashes.items())
    output={**previous,"readings":display,"states":previous.get("states",[]),
            "observations":previous.get("observations",[]),"events":previous.get("events",[]),
            "screen_events":screen_events,"prediction_provenance":{**provenance,"publication":{
                "prediction_package_sha256":input_hash,"original_source_pts_aligned":True,
                "frame_alignment_sha256":file_sha256(alignment_path),
                "template_sha256_at_publication":template_hashes,
                "templates_verified_against_generation":templates_verified}}}
    temporary=folder/"viewer-data.incomplete.json.gz"
    temporary.write_bytes(gzip.compress(json.dumps(output,separators=(",",":"),ensure_ascii=False).encode("utf-8"),compresslevel=6,mtime=0))
    archive=archive_analysis(folder)
    raw_temp.replace(folder/"screen_readings.jsonl.gz")
    event_temp.replace(folder/"screen_events.jsonl.gz")
    temporary.replace(target)
    meta["analysis_status"]="analyzed_with_unknowns" if provenance.get("coverage")=="full_clip" else "partial"
    meta["prior_analysis_archive"]=archive
    meta["analysis_archive_bytes"]=sum(p.stat().st_size for p in (folder/"analysis-archive").rglob("*") if p.is_file())
    meta["saved_data_bytes"]=sum(p.stat().st_size for p in folder.iterdir() if p.is_file() and p!=video)
    write_record(folder/"battle.json",meta)
    summary={"id":meta["id"],"decoded_frames":len(rows),"phase_counts":dict(phase_counts),
             "source_pts_corrected_from_clip_pts":True,"tracker_outputs_retained":True,
             "full_game_state_verified":False,"prior_analysis_archive":archive,
             "provenance":output["prediction_provenance"]}
    write_record(folder/"analysis-summary.json",summary)
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("predictions",type=Path)
    parser.add_argument("--battles",type=Path,default=ROOT/"battles")
    parser.add_argument("--only",action="append")
    parser.add_argument("--profile",type=Path,help="Explicit profile for one creator/layout")
    args=parser.parse_args()
    references=json.loads((ROOT/"reference_manifest.json").read_text(encoding="utf-8"))["references"]
    results=[]
    for prediction in sorted(args.predictions.glob("*/viewer-data.json.gz")):
        identity=prediction.parent.name
        if args.only and identity not in args.only:continue
        folder=args.battles/identity
        if not (folder/"battle.json").exists():continue
        meta=json.loads((folder/"battle.json").read_text(encoding="utf-8"))
        ref=next((entry for entry in references if entry["id"]==meta.get("reference_id")),None)
        profile=args.profile or (ROOT/ref["profile"] if ref else None)
        if profile is None:raise ValueError(f"No known profile for {identity}; supply --profile")
        results.append(promote_prediction(prediction,folder,profile))
    if not results:raise ValueError("No matching battle predictions selected")
    print(json.dumps(results,separators=(",",":")),flush=True)


if __name__=="__main__":main()
