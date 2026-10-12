"""Add derived health to existing battle packages; retain original screen logs."""
import argparse
import gzip
import json
import hashlib
from collections import Counter
from pathlib import Path
from battle_io import read_jsonl
from health_tracker import HealthTracker


def run(root, maximum_hp=None):
    summary = {}
    for folder in sorted(root.iterdir()):
        metadata = folder / "battle.json"
        if metadata.is_file() and json.loads(metadata.read_text(encoding="utf-8")).get("segment_status") == "combined_superseded":
            continue
        raw = folder / "screen_readings.jsonl.gz"
        package = folder / "viewer-data.json.gz"
        if not raw.exists() or not package.exists():
            continue
        tracker = HealthTracker(maximum_hp)
        estimates = {}
        counts = {side: Counter() for side in ("mine", "opponent")}
        for row in read_jsonl(raw):
            clip_time = row["timestamp_seconds"]
            # New clip readers timestamp cached headers in clip time too. Older
            # organized logs retain source-time header evidence. Keep each set
            # consistent instead of making every later battle's identity stale.
            if row.get("coordinates_basis") != "battle_clip_frame":
                row["timestamp_seconds"] = row.get("source_timestamp_seconds", clip_time)
            tracker.update(row)
            for side in counts:
                estimate = row[side]["health_estimate"]
                if "settled_since_seconds" in estimate:
                    estimate["settled_since_seconds"] -= row["timestamp_seconds"]-clip_time
            estimates[clip_time] = {side: row[side]["health_estimate"] for side in counts}
            for side in counts:
                counts[side][row[side]["health_estimate"]["status"]] += 1
        with gzip.open(package, "rt", encoding="utf-8") as stream:
            data = json.load(stream)
        for row in data["readings"]:
            for side, estimate in estimates.get(row["t"], {}).items():
                row[side]["health_estimate"] = estimate
        data["bookmarks"] = [b for b in data.get("bookmarks", []) if not b["name"].startswith("Health:")]
        last = -100
        for row in data["readings"]:
            estimate = row["mine"].get("health_estimate", {})
            if estimate["status"] == "estimated" and row["t"]-last >= 8:
                low, high = estimate["fraction_range"]
                data["bookmarks"].append({"t": row["t"], "name": f"Health: {low:.0%}–{high:.0%}"})
                last = row["t"]
        data["bookmarks"].sort(key=lambda b: b["t"])
        data["health_estimation_provenance"] = {
            "reader_sha256": hashlib.sha256(Path(__file__).with_name("health_tracker.py").read_bytes()).hexdigest(),
            "postprocessor_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "raw_readings_sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
            "supplied_maximum_hp": maximum_hp or {},
            "time_basis": "matches_header_evidence_then_returns_clip_time",
            "meaning": "Derived health; source observations retained unchanged"}
        temporary = package.with_name("viewer-data.incomplete.json.gz")
        with gzip.open(temporary, "wt", encoding="utf-8", compresslevel=6) as stream:
            json.dump(data, stream, separators=(",", ":"))
        from run_video_pipeline import archive_analysis
        archive_analysis(folder)
        temporary.replace(package)
        summary[folder.name] = {side: dict(counts[side]) for side in counts}
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--battles", type=Path, default=Path(__file__).parent / "battles")
    parser.add_argument("--maximum-hp", type=Path, help="JSON identity-to-known-maximum-HP map")
    args = parser.parse_args()
    maximum = json.loads(args.maximum_hp.read_text(encoding="utf-8")) if args.maximum_hp else None
    summary = run(args.battles, maximum)
    output = Path(__file__).parent / "output/health-estimation-summary.json"
    output.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary))
