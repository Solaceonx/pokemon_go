"""Validate saved frame coverage, source alignment and causal timestamps.

These are pipeline integrity checks, not recognition accuracy. No logs are edited.
"""
import argparse
from collections import Counter
from fractions import Fraction
import gzip
import hashlib
import json
from pathlib import Path

from battle_io import read_jsonl
from battle_library import scan_library
from button_reader import ROOT
from build_viewer import compact
from refine_saved_readings import merge_patch


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024*1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_battle(folder, meta, *, check_media=True):
    problems = []
    video = folder / meta["video_file"]
    package = folder / meta["viewer_data_file"]
    with gzip.open(package, "rt", encoding="utf-8") as stream:
        data = json.load(stream)
    display = data["readings"]
    raw = list(read_jsonl(folder / "screen_readings.jsonl.gz"))
    alignment = list(read_jsonl(folder / "frame_alignment.jsonl.gz"))
    provenance = data.get("prediction_provenance", {})
    refinement = data.get("refinement_provenance", {})
    patches = {}
    if refinement:
        if sha(folder / "screen_readings.jsonl.gz") != refinement.get("raw_log_sha256"):
            problems.append("Refinement input raw checksum differs")
        patch_path = folder / refinement["refinement_log_file"]
        if sha(patch_path) != refinement.get("refinement_log_sha256"):
            problems.append("Refinement patch checksum differs")
        for row in read_jsonl(patch_path):
            if row["t"] in patches: problems.append("Duplicate refinement timestamp")
            patches[row["t"]] = row["patch"]
        if set(patches)-{r["timestamp_seconds"] for r in raw}:
            problems.append("Refinement contains timestamps outside the raw frames")
    expected = meta["frames"]
    if meta.get("analysis_status") != "analyzed_with_unknowns" or provenance.get("coverage") != "full_clip":
        problems.append("Full-clip analysis has not been published")
    if not len(display) == len(raw) == len(alignment) == expected:
        problems.append("Display, raw, alignment and decoded frame counts differ")
    if check_media:
        import av
        with av.open(str(video)) as container:
            frames = sum(1 for _ in container.decode(video=0))
        if frames != expected:
            problems.append("Actual video frame count differs from metadata")
        if sha(video) != provenance.get("video_sha256"):
            problems.append("Video checksum differs from analysis input")
    last = None
    cues, contexts = Counter(), Counter()
    health = {side: Counter() for side in ["mine", "opponent"]}
    for ordinal, (r, view, source) in enumerate(zip(raw, display, alignment)):
        t = r["timestamp_seconds"]
        if last is not None and not 0 < t-last <= 1/meta["fps"]+.00001:
            problems.append(f"Frame {ordinal}: nonmonotonic or missing clip timestamp")
        last = t
        if r.get("frame_index") != ordinal or source.get("clip_frame_index") != ordinal:
            problems.append(f"Frame {ordinal}: frame ordinal differs")
        if abs(view["t"]-t) > .000001 or abs(source["clip_seconds"]-t) > .000001:
            problems.append(f"Frame {ordinal}: display/source alignment differs")
        if (r.get("source_pts"), r.get("source_time_base")) != (source["source_pts"], source["source_time_base"]):
            problems.append(f"Frame {ordinal}: original PTS differs")
        pts_seconds = float(source["source_pts"]*Fraction(source["source_time_base"]))
        if abs(pts_seconds-source["source_seconds"]) > .000001:
            problems.append(f"Frame {ordinal}: original PTS conversion differs")
        if abs(r.get("source_timestamp_seconds", -1)-pts_seconds) > .000001:
            problems.append(f"Frame {ordinal}: original timestamp differs")
        cues[r["phase"].get("value") or "unknown"] += 1
        contexts[view.get("phase_estimate", view.get("phase", {})).get("value") or "unknown"] += 1
        expected_view = merge_patch(compact(r), patches.get(t, {}))
        for field in ["phase", "phase_estimate", "buttons", "mine", "opponent"]:
            if view.get(field) != expected_view.get(field):
                problems.append(f"Frame {ordinal}: display {field} differs from raw plus recorded refinement")
        support = view.get("phase_estimate", {}).get("evidence", {}).get("last_support_seconds")
        if support is not None and support > t+.000001:
            problems.append(f"Frame {ordinal}: future derived scene support")
        for side in health:
            for field in ["species", "cp"]:
                seen = r[side].get(field, {}).get("evidence", {}).get("observed_at_seconds")
                if seen is not None and seen > t+.000001:
                    problems.append(f"Frame {ordinal}: future {side} {field} OCR evidence")
            estimate = view[side].get("health_estimate", {})
            health[side][estimate.get("status", "not_estimated")] += 1
    return {"id": meta["id"], "passed": not problems, "frames": len(raw),
            "expected_frames": expected, "duration_seconds": meta["duration_seconds"],
            "raw_phase_counts": dict(cues), "contextual_phase_counts": dict(contexts),
            "health_status_counts": {s: dict(c) for s, c in health.items()},
            "scene_classified_fraction": (len(raw)-contexts["unknown"])/len(raw) if raw else None,
            "input_code_sha256": provenance.get("reader_code_sha256", {}),
            "separate_visual_refinement": bool(refinement),
            "viewer_package_sha256": sha(package), "raw_log_sha256": sha(folder / "screen_readings.jsonl.gz"),
            "problems": problems[:25], "problem_count": len(problems)}


def validate(root=ROOT, *, check_media=True):
    battles = []
    for meta in scan_library(root / "battles"):
        folder = root / "battles" / meta["id"]
        try:
            result = validate_battle(folder, meta, check_media=check_media)
        except (OSError, KeyError, ValueError) as error:
            result = {"id": meta["id"], "passed": False, "problems": [str(error)]}
        battles.append(result)
    return {"role": "pipeline_integrity_and_coverage_not_recognition_accuracy",
            "passed": bool(battles) and all(b["passed"] for b in battles),
            "battles": battles, "count": len(battles),
            "total_decoded_frames": sum(b.get("frames", 0) for b in battles),
            "media_independently_decoded": check_media}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-media-decode", action="store_true")
    args = parser.parse_args()
    result = validate(check_media=not args.skip_media_decode)
    (ROOT / "output/full-library-validation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "battles"}))
    if not result["passed"]: raise SystemExit(1)
