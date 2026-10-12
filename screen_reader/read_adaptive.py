"""Run the experimental adaptive reader into a separate, fingerprinted folder."""
import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
import time

from adaptive_reader import AdaptiveReader
from battle_reader import EventTracker
from battle_io import read_jsonl
from build_viewer import compact
from import_source import checksum, write_record
from run_video_pipeline import prediction_hashes
from button_reader import ROOT
import av


def read(video, profile, output, *, start=0, seconds=None):
    video, profile, output = map(lambda p: Path(p).resolve(), [video, profile, output])
    if start < 0 or (seconds is not None and seconds <= 0):
        raise ValueError("Invalid video time range")
    if output.is_relative_to((ROOT / "battles").resolve()):
        raise ValueError("Use a separate output folder to preserve the frozen battle library")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Output folder already has files; choose a new run folder")
    code_hashes, profile_hash = prediction_hashes(profile)
    code_hashes.update({name: checksum(ROOT / name) for name in ["adaptive_reader.py", "roi_ocr.py", "read_adaptive.py"]})
    video_hash = checksum(video)
    output.mkdir(parents=True, exist_ok=True)
    alignment_path = video.parent / "frame_alignment.jsonl.gz"
    alignment = list(read_jsonl(alignment_path)) if alignment_path.is_file() else None
    reader, events = AdaptiveReader(profile), EventTracker()
    rows, counts, progress = [], Counter(), time.monotonic()
    raw_temp = output / "observations.incomplete.jsonl.gz"
    event_temp = output / "events.incomplete.jsonl.gz"
    started = time.perf_counter()
    with av.open(str(video)) as media, gzip.open(raw_temp, "wt", encoding="utf-8", compresslevel=6) as raw, gzip.open(event_temp, "wt", encoding="utf-8", compresslevel=6) as log:
        media.streams.video[0].codec_context.thread_count = 2
        # Decode from the beginning to keep the frame ordinal consistent with
        # original-PTS sidecars, even when only a selected interval is analyzed.
        for index, frame in enumerate(media.decode(video=0)):
            if frame.time is None: raise ValueError("Decoded frame has no presentation timestamp")
            t = frame.time
            if t < start: continue
            if seconds is not None and t >= start+seconds: break
            reading = reader.detect(frame.to_image(), t, index)
            reading["input_pts"], reading["input_time_base"] = frame.pts, str(frame.time_base)
            reading["evidence_time_basis"] = "input_video_presentation_timestamp"
            if alignment is not None:
                source = alignment[index]
                if abs(source["clip_seconds"]-t) > .00001:
                    raise ValueError("Source alignment differs from input video time")
                reading.update(source_pts=source["source_pts"], source_time_base=source["source_time_base"],
                    source_timestamp_seconds=source["source_seconds"], coordinates_basis="battle_clip_frame")
            else:
                reading.update(source_pts=frame.pts, source_time_base=str(frame.time_base),
                    source_timestamp_seconds=t, coordinates_basis="input_video_frame")
            raw.write(json.dumps(reading, ensure_ascii=False, separators=(",", ":"))+"\n")
            for event in events.update(reading): log.write(json.dumps(event, ensure_ascii=False, separators=(",", ":"))+"\n")
            rows.append(compact(reading)); counts[reading["phase_estimate"].get("value") or "unknown"] += 1
            if time.monotonic()-progress > 20:
                print(json.dumps({"decoded_frames": len(rows), "input_seconds": t}), flush=True)
                progress = time.monotonic()
    if not rows: raise ValueError("Selected interval has no decoded frames")
    if checksum(video) != video_hash or checksum(profile) != profile_hash or any(checksum(ROOT / name) != value for name, value in code_hashes.items()):
        raise ValueError("Input or reader changed; unfinished run was not published")
    provenance = {"reader_variant": "experimental_adaptive_v4", "code_sha256": code_hashes,
        "video_sha256": video_hash, "profile_sha256": profile_hash,
        "source_alignment_sha256": checksum(alignment_path) if alignment is not None else None,
        "ocr_interval_seconds": .5, "every_decoded_frame": True,
        "requested_start_seconds": start, "requested_seconds": seconds,
        "full_input_video": start == 0 and seconds is None,
        "evidence_time_basis": "input_video_presentation_timestamp", "independent_accuracy_verified": False}
    package = {"readings": rows, "states": [], "observations": [], "events": [], "bookmarks": [],
               "prediction_provenance": provenance}
    temporary = output / "viewer-data.incomplete.json.gz"
    temporary.write_bytes(gzip.compress(json.dumps(package, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), compresslevel=6, mtime=0))
    raw_temp.replace(output / "observations.jsonl.gz")
    event_temp.replace(output / "events.jsonl.gz")
    temporary.replace(output / "viewer-data.json.gz")
    summary = {"frames": len(rows), "first_input_seconds": rows[0]["t"], "last_input_seconds": rows[-1]["t"],
               "processing_seconds": round(time.perf_counter()-started, 3),
               "contextual_phase_counts": dict(counts), "provenance": provenance}
    write_record(output / "manifest.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", type=float, default=0)
    parser.add_argument("--seconds", type=float)
    args = parser.parse_args()
    summary = read(args.video, args.profile, args.output, start=args.start, seconds=args.seconds)
    print(json.dumps({k: v for k, v in summary.items() if k != "provenance"}))
