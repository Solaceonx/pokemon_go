"""Turn automatically proposed source intervals into playable battle folders.

Sources are reused in place. Only cropped per-battle media and compact metadata
are written, with source PTS retained in a compressed frame-alignment file.
Candidates stay visibly unreviewed and receive no invented state observations.
"""
from __future__ import annotations
import argparse
from fractions import Fraction
import gzip
import json
import re
from pathlib import Path

from button_reader import ROOT
from segment_battles import file_sha256
import av


def matching_existing_clip(library, candidate, source_id, source_sha=None):
    """Reuse an organized source interval instead of encoding near-identical media."""
    matches=[]
    library=Path(library).resolve()
    for path in Path(library).glob("*/battle.json"):
        try:
            if not path.resolve().is_relative_to(library):continue
            meta=json.loads(path.read_text(encoding="utf-8"))
            if meta.get("segment_status")=="combined_superseded" or meta.get("reference_id")!=source_id:
                continue
            if source_sha and meta.get("source_sha256") and meta["source_sha256"]!=source_sha:continue
            start,end=meta.get("source_start_seconds"),meta.get("source_end_seconds")
            video=(path.parent/meta.get("video_file","video.mp4")).resolve()
            if start is None or end is None or not video.is_relative_to(path.parent.resolve()) or not video.is_file():
                continue
            intersection=max(0,min(end,candidate["end"])-max(start,candidate["start"]))
            union=max(end,candidate["end"])-min(start,candidate["start"])
            iou=intersection/union if union else 0
            if iou>=.80 and start<=candidate["first_hud_seconds"]<end:
                matches.append((iou,path,meta))
        except (ValueError,TypeError,OSError):
            continue
    return max(matches,key=lambda item:item[0],default=None)


def validate_candidate(candidate, duration=None):
    identity=candidate.get("id", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]+",identity):
        raise ValueError("Unsafe candidate id")
    start,end=float(candidate["start"]),float(candidate["end"])
    if not 0 <= start < end or (duration is not None and end > duration+.05):
        raise ValueError("Candidate interval lies outside the source")
    return start,end


def encode_clip(video_path, candidate, viewport, folder, audio_path=None):
    """Decode using original PTS, retain audio when present, and crop one clip."""
    start,end=validate_candidate(candidate)
    source=Path(video_path)
    folder=Path(folder)
    folder.mkdir(parents=True,exist_ok=True)
    temporary=folder/"video.incomplete.mp4"
    target=folder/"video.mp4"
    if target.exists():
        raise FileExistsError(f"Refusing to overwrite existing clip: {target}")
    with av.open(str(source)) as video:
        stream=video.streams.video[0]
        stream.codec_context.thread_count=4
        rate=stream.average_rate or Fraction(30,1)
        duration=float(video.duration/av.time_base) if video.duration else None
        validate_candidate(candidate,duration)
        x,y,width,height=map(int,viewport)
        if min(width,height) <= 0 or min(x,y) < 0 or x+width > stream.width or y+height > stream.height:
            raise ValueError("Viewport lies outside the source")
        if width%2 or height%2:
            raise ValueError("H264 crop dimensions must be even")
        video.seek(int(max(0,start-2)*av.time_base))
        decoded=video.decode(stream)
        first=next((frame for frame in decoded if frame.pts is not None and float(frame.pts*frame.time_base)>=start-1e-7),None)
        if first is None or float(first.pts*first.time_base)>=end:
            raise ValueError("Candidate contains no video frames")
        origin=float(first.pts*first.time_base)
        audio_container=av.open(str(audio_path or source))
        try:
            audio_stream=audio_container.streams.audio[0] if audio_container.streams.audio else None
            if audio_path and audio_stream is None:
                raise ValueError("Specified audio source has no audio stream")
            if audio_stream:
                audio_container.seek(int(origin*av.time_base))
            with av.open(str(temporary),"w",options={"movflags":"+faststart"}) as out, gzip.open(folder/"frame_alignment.jsonl.gz","wt",encoding="utf-8") as alignment:
                vs=out.add_stream("libx264",rate=rate)
                vs.width,vs.height,vs.pix_fmt=width,height,"yuv420p"
                vs.options={"crf":"23","preset":"veryfast"}
                vs.codec_context.thread_count=2
                audio_out=out.add_stream_from_template(audio_stream) if audio_stream else None
                def audio_packets():
                    if audio_stream is None:
                        return
                    for packet in audio_container.demux(audio_stream):
                        if packet.pts is None or packet.dts is None:
                            continue
                        timestamp=float(packet.pts*packet.time_base)
                        if timestamp < origin:
                            continue
                        if timestamp >= end:
                            break
                        offset=round(origin/float(packet.time_base))
                        packet.pts-=offset;packet.dts-=offset
                        packet.stream=audio_out
                        yield packet
                audio=iter(audio_packets())
                pending=next(audio,None)
                def mux(packet):
                    nonlocal pending
                    timestamp=float(packet.dts*packet.time_base)
                    while pending is not None and float(pending.dts*pending.time_base)<=timestamp:
                        out.mux(pending);pending=next(audio,None)
                    out.mux(packet)
                frame_count=0;last_pts=None
                def frames():
                    yield first
                    yield from decoded
                for frame in frames():
                    if frame.pts is None:
                        continue
                    timestamp=float(frame.pts*frame.time_base)
                    if timestamp >= end:
                        break
                    rgb=frame.to_ndarray(format="rgb24")[y:y+height,x:x+width]
                    crop=av.VideoFrame.from_ndarray(rgb,format="rgb24")
                    crop.pts=round((timestamp-origin)*rate)
                    crop.time_base=1/rate
                    if last_pts is not None and crop.pts<=last_pts:
                        raise ValueError("Input timestamps collide at the nominal frame rate; VFR input requires separate handling")
                    last_pts=crop.pts
                    for packet in vs.encode(crop):
                        mux(packet)
                    alignment.write(json.dumps({"clip_frame_index":frame_count,
                                                "clip_seconds":float(crop.pts*crop.time_base),
                                                "source_seconds":timestamp,"source_pts":frame.pts,
                                                "source_time_base":str(frame.time_base)},separators=(",",":"))+"\n")
                    frame_count+=1
                for packet in vs.encode():
                    mux(packet)
                while pending is not None:
                    out.mux(pending);pending=next(audio,None)
        finally:
            audio_container.close()
    temporary.replace(target)
    with av.open(str(target)) as saved:
        actual_duration=saved.duration/av.time_base
        actual_audio=bool(saved.streams.audio)
        if saved.streams.video[0].width!=width or saved.streams.video[0].height!=height:
            raise ValueError("Saved crop dimensions differ")
    return {"duration_seconds":actual_duration,"fps":float(rate),"frames":frame_count,
            "source_start_seconds":origin,"source_end_seconds":end,"audio_in_video":actual_audio,
            "viewport":[0,0,width,height],"source_viewport":list(viewport),"video_file":"video.mp4",
            "video_bytes":target.stat().st_size,"video_sha256":file_sha256(target)}


def export_candidates(manifest, library, *, viewport, video=None, audio=None, creator="Local recording", url=None, only=None):
    library=Path(library).resolve()
    source=Path(video or manifest["source_video"]).resolve()
    if file_sha256(source)!=manifest["source_sha256"]:
        raise ValueError("Source video differs from segmentation input")
    if only and set(only)-{candidate["id"] for candidate in manifest["segments"]}:
        raise ValueError("Requested candidate id was not found")
    results=[]
    for candidate in manifest["segments"]:
        if only and candidate["id"] not in only:
            continue
        validate_candidate(candidate)
        matched=matching_existing_clip(library,candidate,manifest["source_id"],manifest["source_sha256"])
        if matched and matched[1].parent.name!=candidate["id"]:
            iou,record,previous=matched
            source_record={"candidate":candidate,"detector":manifest["detector"],
                           "detector_sha256":manifest.get("detector_sha256"),
                           "source_sha256":manifest["source_sha256"],
                           "interval_iou_with_saved_clip":iou,
                           "saved_clip_boundaries_unchanged":True}
            evidence_path=record.parent/"boundary-candidates.json"
            if evidence_path.exists():
                evidence=json.loads(evidence_path.read_text(encoding="utf-8"))
            else:
                evidence={"schema":"retained-battle-boundary-evidence-v1","records":[]}
            if source_record not in evidence["records"]:
                evidence["records"].append(source_record)
                evidence_path.write_text(json.dumps(evidence,indent=2)+"\n",encoding="utf-8")
            results.append({"id":record.parent.name,"candidate_id":candidate["id"],
                            "reused":True,"reused_organized_clip":True,"interval_iou":iou})
            continue
        folder=library/candidate["id"]
        if not folder.resolve().is_relative_to(library):
            raise ValueError("Candidate output escaped the library")
        record=folder/"battle.json"
        if record.exists():
            previous=json.loads(record.read_text(encoding="utf-8"))
            if previous.get("source_sha256")!=manifest["source_sha256"] or previous.get("boundary_candidate")!=candidate:
                raise ValueError("Existing output has different input or boundaries")
            if not (folder/previous["video_file"]).is_file():
                raise ValueError("Existing clip metadata has missing video")
            if previous.get("video_sha256") and file_sha256(folder/previous["video_file"])!=previous["video_sha256"]:
                raise ValueError("Existing exported clip bytes changed")
            results.append({"id":candidate["id"],"reused":True});continue
        facts=encode_clip(source,candidate,viewport,folder,audio_path=audio)
        empty={key:[] for key in ["readings","states","observations","events"]}
        empty["bookmarks"]=[{"t":max(0,candidate["first_hud_seconds"]-facts["source_start_seconds"]),"name":"First visible battle HUD (action start unverified)"}]
        with gzip.open(folder/"viewer-data.json.gz","wt",encoding="utf-8") as stream:
            json.dump(empty,stream,separators=(",",":"))
        (folder/"team.json").write_text('{"pokemon":[]}\n',encoding="utf-8")
        (folder/"observations.jsonl").write_text("",encoding="utf-8")
        (folder/"report.md").write_text("Automatically proposed battle clip. Boundaries, exact action start, internal edits and game states remain unreviewed. Original source PTS are retained in frame_alignment.jsonl.gz.\n",encoding="utf-8")
        metadata={"schema":"battle-library-v1","id":candidate["id"],"name":candidate["name"]+" · unreviewed",
                  "creator":creator,"reference_id":manifest["source_id"],"source_url":url,
                  "source_video":str(source),"source_sha256":manifest["source_sha256"],
                  "boundary_candidate":candidate,"boundary_detector":manifest["detector"],
                  "source_edited":True,"timing_validated":False,"boundary_review_required":True,
                  "completeness":candidate["completeness"],"analysis_status":"not_analyzed",
                  "viewer_data_file":"viewer-data.json.gz","encoding_crf":23,**facts,
                  "notes":candidate["notes"]}
        metadata["saved_data_bytes"]=sum(p.stat().st_size for p in folder.iterdir() if p.is_file() and p.name!="video.mp4")
        record.write_text(json.dumps(metadata,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
        results.append({"id":candidate["id"],"reused":False,"video_bytes":facts["video_bytes"],"duration_seconds":facts["duration_seconds"]})
    return results


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidates",type=Path)
    parser.add_argument("--library",type=Path,required=True)
    parser.add_argument("--viewport",type=int,nargs=4,required=True,metavar=("X","Y","WIDTH","HEIGHT"))
    parser.add_argument("--video",type=Path)
    parser.add_argument("--audio",type=Path)
    parser.add_argument("--creator",default="Local recording")
    parser.add_argument("--url")
    parser.add_argument("--only",action="append",help="Export just this candidate id; may be repeated")
    args=parser.parse_args()
    manifest=json.loads(args.candidates.read_text(encoding="utf-8"))
    results=export_candidates(manifest,args.library,viewport=args.viewport,video=args.video,audio=args.audio,
                              creator=args.creator,url=args.url,only=args.only)
    print(json.dumps(results),flush=True)


if __name__=="__main__":
    main()
