"""Refine saved visual cues without redoing OCR or replacing raw observations.

The prior display package is archived. Sparse changes and their input fingerprints
remain separate from the frozen reader's complete raw log. Video is never copied.
"""
import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
import shutil

from adaptive_reader import AdaptiveReader, GradeSceneTracker
from battle_reader import EventTracker
from battle_io import read_jsonl
from battle_library import scan_library
from build_viewer import compact
from health_tracker import HealthTracker
from import_source import checksum, write_record
from button_reader import ROOT, np
import av


class SavedHeaderMarkers(AdaptiveReader):
    def __init__(self, profile):
        # Only pixel marker measurement is used here; no OCR models or templates
        # are loaded. Headers and their original observation times come from logs.
        self.profile = json.loads(Path(profile).read_text(encoding="utf-8"))
        self.headers = {}
        self.detect_time = self.last_ocr_time = None

    def _header(self, side, text_fresh):
        return self.headers[side]


def display_patch(before, after):
    patch = {k: v for k, v in after.items() if k not in {"mine", "opponent"} and before.get(k) != v}
    for side in ["mine", "opponent"]:
        changed = {k: v for k, v in after[side].items() if before[side].get(k) != v}
        if changed: patch[side] = changed
    return patch


def merge_patch(reading, patch):
    result = dict(reading)
    for key, value in patch.items():
        result[key] = {**reading[key], **value} if key in {"mine", "opponent"} else value
    return result


def refine(folder, profile):
    folder, profile = Path(folder), Path(profile)
    meta = json.loads((folder / "battle.json").read_text(encoding="utf-8"))
    if meta.get("analysis_status") != "analyzed_with_unknowns":
        raise ValueError("Finish the full raw reader run before refining this battle")
    package = folder / "viewer-data.json.gz"
    raw_path, video = folder / "screen_readings.jsonl.gz", folder / meta["video_file"]
    with gzip.open(package, "rt", encoding="utf-8") as stream: previous = json.load(stream)
    code = {name: checksum(ROOT / name) for name in ["adaptive_reader.py", "refine_saved_readings.py",
        "scene_tracker.py", "health_tracker.py", "battle_reader.py", "button_reader.py",
        "local_ocr.py", "roi_ocr.py", "build_viewer.py", "battle_io.py", "import_source.py", "requirements.txt"]}
    inputs = {"raw_log_sha256": checksum(raw_path), "video_sha256": checksum(video),
              "profile_sha256": checksum(profile), "refinement_code_sha256": code}
    if all(previous.get("refinement_provenance", {}).get(k) == v for k, v in inputs.items()):
        return {"id": meta["id"], "reused_refinement": True}
    raw_rows = list(read_jsonl(raw_path))
    if len(raw_rows) != meta["frames"]: raise ValueError("Full raw frame count differs from clip metadata")
    if previous.get("prediction_provenance", {}).get("profile_sha256") != inputs["profile_sha256"]:
        raise ValueError("Refinement layout differs from the layout used to read the headers")
    if previous.get("prediction_provenance", {}).get("video_sha256") != inputs["video_sha256"]:
        raise ValueError("Video changed since raw analysis")
    markers, scenes, health, events = SavedHeaderMarkers(profile), GradeSceneTracker(), HealthTracker(), EventTracker()
    rows, changes, event_rows, grade_frames = [], [], [], 0
    before_scenes, after_scenes = Counter(), Counter()
    changed_counts = Counter()
    with av.open(str(video)) as media:
        media.streams.video[0].codec_context.thread_count = 2
        for index, frame in enumerate(media.decode(video=0)):
            reading = raw_rows[index]
            if reading.get("coordinates_basis") != "battle_clip_frame":
                raise ValueError("This pass requires normalized physical-clip readings")
            if frame.time is None or abs(frame.time-reading["timestamp_seconds"]) > .00001:
                raise ValueError("Video frame differs from raw observation timestamp")
            before = compact(reading)
            rgb = np.asarray(frame.to_image().resize((508, 1080)))
            markers.detect_time = reading["timestamp_seconds"]
            markers.last_ocr_time = reading.get("text_observation", {}).get("observed_at_seconds")
            markers.headers = {s: {k: reading[s][k] for k in ["species", "cp"]} for s in ["mine", "opponent"]}
            for side in ["mine", "opponent"]:
                party, shields = markers._markers(rgb, side)
                for key, field in [("pokemon_left", party), ("shields_left", shields)]:
                    if field.get("value") != reading[side][key].get("value"):
                        changed_counts[side+"."+key] += 1
                    reading[side][key] = field
            scenes.update(reading); health.update(reading)
            after = compact(reading)
            if "phase_before_refinement" in reading:
                after["phase_before_refinement"] = reading["phase_before_refinement"]
                grade_frames += 1
            patch = display_patch(before, after)
            if patch: changes.append({"t": after["t"], "patch": patch})
            rows.append(after)
            before_scenes[before.get("phase_estimate", before["phase"]).get("value") or "unknown"] += 1
            after_scenes[after["phase_estimate"].get("value") or "unknown"] += 1
            event_rows.extend({"t": e["observed_at_seconds"], "event": e} for e in events.update(reading))
    if len(rows) != len(raw_rows): raise ValueError("Decoded video and raw log frame counts differ")
    if inputs["raw_log_sha256"] != checksum(raw_path) or inputs["video_sha256"] != checksum(video) or inputs["profile_sha256"] != checksum(profile) or any(checksum(ROOT / k) != v for k, v in code.items()):
        raise ValueError("Refinement inputs changed; output was not published")
    baseline = folder / "analysis-archive" / checksum(package)[:16]
    baseline.mkdir(parents=True, exist_ok=True)
    for path in [package, folder / "battle.json"]:
        target = baseline / path.name
        if not target.exists(): shutil.copyfile(path, target)
    patch_temp = folder / "screen_refinements.incomplete.jsonl.gz"
    with gzip.open(patch_temp, "wt", encoding="utf-8", compresslevel=6) as stream:
        for change in changes: stream.write(json.dumps(change, ensure_ascii=False, separators=(",", ":"))+"\n")
    provenance = {**inputs, "method": "saved_grade_cues_and_current_frame_header_anchored_markers",
        "prior_display_archive": str(baseline.relative_to(folder)),
        "refinement_log_file": "screen_refinements.jsonl.gz", "refinement_log_sha256": checksum(patch_temp),
        "original_raw_observations_unchanged": True, "maximum_hp_supplied": False,
        "independent_accuracy_verified": False, "evidence_time_basis": "clip_presentation_timestamp"}
    current = {**previous, "readings": rows, "screen_events": event_rows, "refinement_provenance": provenance}
    temporary = folder / "viewer-data.incomplete.json.gz"
    temporary.write_bytes(gzip.compress(json.dumps(current, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), compresslevel=6, mtime=0))
    patch_temp.replace(folder / "screen_refinements.jsonl.gz")
    temporary.replace(package)
    summary = {"id": meta["id"], "frames": len(rows), "grade_cue_frames": grade_frames,
               "count_value_changes": dict(changed_counts), "before_contextual_phase_counts": dict(before_scenes),
               "after_contextual_phase_counts": dict(after_scenes), "provenance": provenance}
    write_record(folder / "refinement-summary.json", summary)
    meta["refinement_version"] = "saved_visual_v4"
    write_record(folder / "battle.json", meta)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", action="append", help="Restrict to a battle ID; may repeat")
    args = parser.parse_args()
    results = []
    for meta in scan_library(ROOT / "battles"):
        if args.only and meta["id"] not in args.only: continue
        references = json.loads((ROOT / "reference_manifest.json").read_text(encoding="utf-8"))["references"]
        reference = next((r for r in references if r["id"] == meta.get("reference_id")), None)
        if reference is None:
            raise ValueError("Use the interactive importer with an explicit calibrated profile for an unfamiliar source")
        profile = ROOT / reference["profile"]
        result = refine(ROOT / "battles" / meta["id"], profile)
        results.append(result)
        print(json.dumps({k: v for k, v in result.items() if k not in {"provenance", "before_contextual_phase_counts", "after_contextual_phase_counts"}}), flush=True)
    write_record(ROOT / "output/refinement-library-summary.json", {"battles": results})
