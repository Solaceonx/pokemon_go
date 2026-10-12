"""Deterministic source-group dataset manifest and independent viewer evaluation.

No media copying; videos are identified by SHA256. Existing outputs are predictions,
never labels. Test sources were already exposed during prototype calibration.
"""
import argparse
import bisect
import gzip
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
POLICY = {"qSaL7jM9NbA": "train", "8O7kDtNZs6Y": "test"}
PHASE_ALIASES = {
    "opponent_charge_imminent": "opponent_charged_warning",
    "my_charged_minigame": "my_charged_minigame",
    "choose_next_after_my_faint": "choose_next",
}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(root=ROOT):
    clips = []
    for meta_path in sorted((root / "battles").glob("*/battle.json")):
        meta = read_json(meta_path)
        if meta.get("segment_status") == "combined_superseded":
            continue
        source = meta["reference_id"]
        if source not in POLICY:
            raise ValueError(f"New source {source}: assign a partition explicitly before building")
        video = meta_path.parent / meta["video_file"]
        clips.append({
            "battle_id": meta["id"], "partition": POLICY[source], "source_id": source,
            "source_url": meta["source_url"], "creator": meta["creator"],
            "video": video.relative_to(root).as_posix(), "video_sha256": digest(video),
            "video_bytes": video.stat().st_size, "fps": meta["fps"],
            "clip_duration_seconds": meta["duration_seconds"],
            "source_start_seconds": meta["source_start_seconds"],
            "source_end_seconds": meta["source_end_seconds"],
            "completeness": meta["completeness"], "source_edited": meta["source_edited"],
            "previously_exposed_to_development": True,
        })
    return {"schema": "battle-dataset-v1", "split_unit": "original_source_video",
            "policy": POLICY, "seed": None,
            "test_role": "frozen_regression_previously_exposed_not_unbiased_final_test",
            "clips": clips,
            "label_inventory": {
                "user_frame_phase_labels": "fixtures/reis-phase-labels-01.jsonl",
                "user_sequence_labels": "fixtures/reis-clip-labels-01.jsonl",
                "assistant_transition_reviews": "fixtures/reis-transition-review-01.jsonl",
                "independent_test_labels": "none_yet",
                "reader_logs_tracker_states_health_estimates": "predictions_not_ground_truth"}}


def validate_manifest(manifest, root=ROOT, check_hashes=True):
    groups, seen, spans, fingerprints = {}, set(), {}, {}
    for clip in manifest["clips"]:
        battle = clip["battle_id"]
        if battle in seen:
            raise ValueError(f"Duplicate battle {battle}")
        seen.add(battle)
        source, part = clip["source_id"], clip["partition"]
        if part not in {"train", "test"}:
            raise ValueError(f"Invalid partition {part}")
        if source in groups and groups[source] != part:
            raise ValueError(f"Source leakage: {source}")
        groups[source] = part
        sha = clip["video_sha256"]
        if sha in fingerprints and fingerprints[sha] != part:
            raise ValueError("Identical video content crosses partitions")
        fingerprints[sha] = part
        begin, end = clip["source_start_seconds"], clip["source_end_seconds"]
        if begin < 0 or end <= begin:
            raise ValueError(f"Invalid source interval: {battle}")
        for previous_begin, previous_end in spans.setdefault(source, []):
            if max(begin, previous_begin) < min(end, previous_end):
                raise ValueError(f"Overlapping source clips: {battle}")
        spans[source].append((begin, end))
        if check_hashes:
            path = (root / clip["video"]).resolve()
            if not path.is_relative_to(root.resolve()):
                raise ValueError("Video path escapes dataset root")
            if path.stat().st_size != clip["video_bytes"] or digest(path) != sha:
                raise ValueError(f"Video changed: {battle}")
    return {p: sum(c["partition"] == p for c in manifest["clips"]) for p in ("train", "test")}


def annotation_tasks(manifest, every_seconds=5):
    if every_seconds <= 0:
        raise ValueError("Sampling interval must be positive")
    tasks = []
    for clip in manifest["clips"]:
        index = 0
        while index * every_seconds < clip["clip_duration_seconds"]:
            t = index * every_seconds
            tasks.append({"battle_id": clip["battle_id"], "partition": clip["partition"],
                          "clip_seconds": t, "source_seconds": round(t + clip["source_start_seconds"], 6),
                          "review_status": "unreviewed", "provenance": None,
                          "expected": {}, "notes": "Label from video with predictions hidden. Blank is not truth."})
            index += 1
    return tasks


def normalize_label(label, clips):
    # Existing user phase fixtures use original-source time and coarse vocabulary.
    if "source_id" in label and "timestamp_seconds" in label:
        if label.get("label_source") != "user":
            return None
        matches = [c for c in clips if c["source_id"] == label["source_id"] and
                   c["source_start_seconds"] <= label["timestamp_seconds"] < c["source_end_seconds"]]
        if len(matches) != 1:
            raise ValueError("A source label must match exactly one clip")
        clip = matches[0]
        phase = label["phase"]
        return {"battle_id": clip["battle_id"],
                "clip_seconds": label["timestamp_seconds"] - clip["source_start_seconds"],
                "phase": PHASE_ALIASES.get(phase, phase), "provenance": "human_review",
                "original_human_phase": phase}
    if label.get("provenance") != "human_review" or label.get("review_status") == "unreviewed":
        return None
    return label


def present(field):
    if not isinstance(field, dict):
        return field
    if field.get("status") in {"unknown", "stale"}:
        return None
    return field.get("value")


def score_labels(manifest, labels, packages, partition="test", phase_source="observed"):
    if phase_source not in {"observed", "estimate"}:
        raise ValueError("Phase source must be observed or estimate")
    clips = {c["battle_id"]: c for c in manifest["clips"]}
    details, unreadable_fields, prediction_exposed_labels = [], 0, 0
    for original in labels:
        label = normalize_label(original, list(clips.values()))
        if label is None:
            continue
        if label["battle_id"] not in clips:
            raise ValueError(f"Unknown labelled battle {label['battle_id']}")
        clip = clips[label["battle_id"]]
        if clip["partition"] != partition:
            continue
        if label.get("reviewed_without_predictions") is False:
            prediction_exposed_labels += 1
            continue
        t = label["clip_seconds"]
        if not 0 <= t < clip["clip_duration_seconds"]:
            raise ValueError("Label time outside clip")
        readings = packages.get(clip["battle_id"], {}).get("readings", [])
        times = [r["t"] for r in readings]
        if times != sorted(times):
            raise ValueError("Viewer predictions must be time sorted")
        i = bisect.bisect_right(times, t + 1e-9) - 1
        row = readings[i] if i >= 0 and t - times[i] <= 1 / clip["fps"] + 0.01 else None
        expected = label.get("expected", label)
        fields = []
        if "phase" in expected:
            phase = (row or {}).get("phase_estimate" if phase_source == "estimate" else "phase", {})
            predicted = phase.get("value") if phase_source == "estimate" and phase.get("status") in {"observed", "inferred"} else present(phase)
            fields.append(("phase", expected["phase"], predicted, None))
        for side in ("mine", "opponent"):
            side_expected = expected.get(side, {})
            actual = (row or {}).get(side, {})
            for field in ("species", "cp", "shields_left", "pokemon_left"):
                if field in side_expected:
                    fields.append((f"{side}.{field}", side_expected[field], present(actual.get(field)), None))
            if "health_fraction_range" in side_expected:
                interval = side_expected["health_fraction_range"]
                if interval is not None and not (isinstance(interval, list) and len(interval) == 2 and
                        all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in interval) and
                        0 <= interval[0] <= interval[1] <= 1):
                    raise ValueError("Human health range must be [low, high] within 0..1")
                h = actual.get("health_estimate", {})
                predicted = h.get("fraction") if h.get("status") == "estimated" else None
                fields.append((f"{side}.health_fraction_range", interval, predicted, h.get("fraction_range")))
        for field, truth, predicted, interval in fields:
            # Human uncertainty is unscorable; never reward matching uncertainty.
            if truth is None or (field == "phase" and truth == "unknown"):
                unreadable_fields += 1
                continue
            if field.endswith("health_fraction_range"):
                covered = predicted is not None
                correct = covered and truth[0] <= predicted <= truth[1]
            else:
                covered, correct = predicted is not None, predicted == truth
            details.append({"battle_id": clip["battle_id"], "clip_seconds": t, "field": field,
                            "expected": truth, "prediction": predicted, "prediction_range": interval,
                            "covered": covered, "correct": bool(correct),
                            "prediction_clip_seconds": row["t"] if row else None})
    n, covered, correct = len(details), sum(d["covered"] for d in details), sum(d["correct"] for d in details)
    return {"schema": "battle-evaluation-v1", "partition": partition, "phase_source": phase_source,
            "status": "evaluated" if n else "awaiting_independent_human_labels",
            "test_role": manifest["test_role"], "labelled_field_count": n,
            "covered_field_count": covered, "correct_field_count": correct,
            "coverage_fraction": covered / n if n else None,
            "accuracy_among_covered": correct / covered if covered else None,
            "correct_fraction_all_labels": correct / n if n else None,
            "unscorable_human_field_count": unreadable_fields,
            "prediction_exposed_label_count": prediction_exposed_labels,
            "unknown_truth_policy": "Unreadable human fields and unknown human phase are excluded and reported separately",
            "health_metric": "Point estimate lies within human interval; estimator interval shown but does not enlarge acceptance",
            "details": details}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["build", "verify", "tasks", "predict", "evaluate"])
    parser.add_argument("--manifest", type=Path, default=ROOT / "dataset/manifest.json")
    parser.add_argument("--labels", type=Path, default=ROOT / "fixtures/reis-phase-labels-01.jsonl")
    parser.add_argument("--partition", choices=["train", "test"], default="test")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--every-seconds", type=float, default=5)
    parser.add_argument("--predictions", type=Path, help="Fresh prediction folder; omit to score existing battle viewer packages")
    parser.add_argument("--only", help="Limit fresh prediction to one battle ID")
    parser.add_argument("--seconds", type=float, help="Explicitly partial fresh prediction for smoke checks")
    parser.add_argument("--phase-source", choices=["observed", "estimate"], default="observed")
    args = parser.parse_args()
    if args.command == "build":
        manifest = build_manifest()
        validate_manifest(manifest)
        write_json(args.manifest, manifest)
        print(json.dumps({"manifest": str(args.manifest), "clips": len(manifest["clips"])}))
        return
    manifest = read_json(args.manifest)
    if args.command == "verify":
        print(json.dumps(validate_manifest(manifest)))
    elif args.command == "predict":
        if args.seconds is not None and args.seconds <= 0:
            parser.error("--seconds must be positive")
        run_predictions(manifest, args.partition, args.output or ROOT / "dataset/predictions", args.only, args.seconds)
    elif args.command == "tasks":
        output = args.output or ROOT / "dataset/annotation-tasks.jsonl"
        output.parent.mkdir(parents=True, exist_ok=True)
        tasks = annotation_tasks(manifest, args.every_seconds)
        output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in tasks), encoding="utf-8")
        print(json.dumps({"tasks": len(tasks), "output": str(output)}))
    else:
        labels = [json.loads(line) for line in args.labels.read_text(encoding="utf-8").splitlines() if line.strip()]
        packages, package_hashes, generation_provenance = {}, {}, {}
        for clip in manifest["clips"]:
            path = (args.predictions or ROOT / "battles") / clip["battle_id"] / "viewer-data.json.gz"
            if path.exists() and clip["partition"] == args.partition:
                packages[clip["battle_id"]] = json.loads(gzip.decompress(path.read_bytes()))
                package_hashes[str(path.resolve())] = digest(path)
                generation_provenance[clip["battle_id"]] = packages[clip["battle_id"]].get("prediction_provenance")
        result = score_labels(manifest, labels, packages, args.partition, args.phase_source)
        # Snapshot inputs at evaluation time so later changes can be distinguished.
        code_paths = [ROOT / name for name in (
            "dataset_tools.py", "battle_reader.py", "button_reader.py", "health_reader.py",
            "health_tracker.py", "estimate_health.py", "local_ocr.py", "requirements.txt",
            "build_viewer.py", "viewer_template.html", "viewer_values.js")]
        code_paths.extend(sorted((ROOT / "profiles").glob("*.json")))
        result["reproduction_inputs"] = {
            "manifest_sha256": digest(args.manifest), "labels_sha256": digest(args.labels),
            "python_version": sys.version.split()[0], "viewer_packages_sha256": package_hashes,
            "reader_viewer_profile_sha256": {p.relative_to(ROOT).as_posix(): digest(p)
                                            for p in code_paths if p.exists()},
            "prediction_origin": "fresh_prediction_folder" if args.predictions else "saved_viewer_packages",
            "prediction_generation_provenance": generation_provenance,
        }
        output = args.output or ROOT / f"dataset/{args.partition}-evaluation.json"
        write_json(output, result)
        print(json.dumps({k: v for k, v in result.items() if k not in {"details", "reproduction_inputs"}}))


def run_predictions(manifest, partition, output, only=None, seconds=None):
    """Run current frozen reader on clip frames into a separate reproducible folder.

    No tracker states, default HP/moves, copied media or invented ground truth.
    """
    from battle_reader import BattleReader
    from local_ocr import LocalOCR
    import av
    import time
    selected = [c for c in manifest["clips"] if c["partition"] == partition and
                (only is None or c["battle_id"] == only)]
    if not selected:
        raise ValueError("No battles selected in requested partition")
    for clip in selected:
        profile = ROOT / "profiles" / ("reis-great.json" if clip["source_id"] == "qSaL7jM9NbA" else "henry-great.json")
        reader, rows = BattleReader(profile, LocalOCR(), 0.5), []
        generation_profile_hash = digest(profile)
        generation_hashes = {name: digest(ROOT / name) for name in
                            ("battle_reader.py", "button_reader.py", "health_reader.py",
                             "health_tracker.py", "scene_tracker.py", "local_ocr.py", "dataset_tools.py", "requirements.txt",
                             "tracker_bundle/data/gamemaster.json")}
        progress = time.monotonic()
        video = ROOT / clip["video"]
        if digest(video) != clip["video_sha256"]:
            raise ValueError("Video differs from frozen manifest")
        with av.open(str(video)) as container:
            container.streams.video[0].codec_context.thread_count = 2
            for index, frame in enumerate(container.decode(video=0)):
                if frame.time is None:
                    continue
                if seconds is not None and frame.time >= seconds:
                    break
                r = reader.detect(frame.to_image(), frame.time, index, [0, 0, frame.width, frame.height])
                r["source_pts"] = frame.pts
                r["source_time_base"] = str(frame.time_base)
                r["coordinates_basis"] = "battle_clip_frame"
                r["t"] = r["timestamp_seconds"]
                rows.append(r)
                if time.monotonic() - progress > 20:
                    print(json.dumps({"battle": clip["battle_id"], "processed_frames": len(rows),
                                      "clip_seconds": frame.time}), flush=True)
                    progress = time.monotonic()
        folder = output / clip["battle_id"]
        folder.mkdir(parents=True, exist_ok=True)
        if generation_profile_hash != digest(profile) or any(
                digest(ROOT / name) != sha for name, sha in generation_hashes.items()):
            raise ValueError("Reader/profile changed while generating predictions; output not published")
        data = {"readings": rows, "states": [], "observations": [], "events": [], "bookmarks": [],
                "prediction_provenance": {"video_sha256": clip["video_sha256"],
                    "profile_sha256": generation_profile_hash, "ocr_interval_seconds": 0.5,
                    "time_basis": "physical_clip_presentation_timestamp",
                    "source_start_seconds": clip["source_start_seconds"],
                    "requested_seconds": seconds, "coverage": "partial" if seconds is not None else "full_clip",
                    "reader_code_sha256": generation_hashes,
                    "python_version": sys.version.split()[0], "pyav_version": av.__version__,
                    "every_decoded_frame": True, "maximum_hp_supplied": False}}
        target = folder / "viewer-data.json.gz"
        temporary = target.with_name("viewer-data.incomplete.json.gz")
        temporary.write_bytes(gzip.compress(json.dumps(data, separators=(",", ":")).encode("utf-8"),
                                            compresslevel=6, mtime=0))
        temporary.replace(target)
        print(json.dumps({"battle": clip["battle_id"], "frames": len(rows), "output": str(target)}), flush=True)


if __name__ == "__main__":
    main()
