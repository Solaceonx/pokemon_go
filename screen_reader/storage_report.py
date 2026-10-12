"""Measure existing media and lossless log compression without copying videos."""
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "tools/python-libs"))
import av


def measure():
    report = {"units": "decimal MB (1 MB = 1,000,000 bytes)", "sources": [], "reader_logs": []}
    refs = json.loads((ROOT / "reference_manifest.json").read_text())["references"]
    for ref, name in zip(refs, ["reis-battle-log", "henry-battle-log"]):
        if not (ROOT / ref["file"]).is_file():
            continue
        source = {"id": ref["id"], "creator": ref["creator"]}
        for kind, field in [("video", "file"), ("audio", "audio")]:
            path = ROOT / ref[field]
            if not path.is_file():
                source[kind + "_bytes"] = source[kind + "_seconds"] = source[kind + "_bytes_per_second"] = 0
                continue
            with av.open(str(path)) as media:
                duration = media.duration / av.time_base
            source[kind + "_bytes"] = path.stat().st_size
            source[kind + "_seconds"] = duration
            source[kind + "_bytes_per_second"] = path.stat().st_size / duration
        report["sources"].append(source)
        if not (ROOT / "output" / name / "manifest.json").is_file():
            continue
        manifest = json.loads((ROOT / "output" / name / "manifest.json").read_text())
        seconds = manifest["requested_duration_seconds"]
        raw_bytes = packed_bytes = 0
        for file in ["observations.jsonl", "events.jsonl"]:
            content = (ROOT / "output" / name / file).read_bytes()
            raw_bytes += len(content)
            packed_bytes += len(gzip.compress(content, compresslevel=6, mtime=0))
        report["reader_logs"].append({"id": ref["id"], "measured_seconds": seconds,
                                      "raw_bytes": raw_bytes, "gzip_bytes": packed_bytes,
                                      "raw_bytes_per_second": raw_bytes / seconds,
                                      "gzip_bytes_per_second": packed_bytes / seconds})
    example_path = ROOT.parent / "games/example/states.jsonl"
    example = example_path.read_bytes() if example_path.is_file() else b""
    count = len([line for line in example.splitlines() if line.strip()])
    report["tracker_state_bytes_per_look"] = len(example) / count if count else 0
    from project_paths import game_data_path
    report["shared_game_data_bytes"] = sum(p.stat().st_size for p in game_data_path().parent.iterdir() if p.is_file())
    report["existing_folder_bytes"] = {name: sum(p.stat().st_size for p in (ROOT / name).rglob("*") if p.is_file())
                                      for name in ["reference-videos", "battles", "output", "samples", "tools", "tracker_bundle"]}
    if (ROOT / "battles").exists():
        from battle_library import scan_library
        library = scan_library(ROOT / "battles")
        details = []
        for b in library:
            folder = ROOT / "battles" / b["id"]
            package = folder / "viewer-data.json.gz"
            details.append({"id": b["id"], "reference_id": b.get("reference_id"), "duration_seconds": b.get("duration_seconds"),
                "video_bytes": b["video_bytes"], "current_saved_data_bytes": b["saved_data_bytes"],
                "analysis_status": b["analysis_status"],
                "analysis_archive_bytes": sum(p.stat().st_size for p in (folder / "analysis-archive").rglob("*") if p.is_file()),
                "compressed_readings_bytes": (folder / "screen_readings.jsonl.gz").stat().st_size if (folder / "screen_readings.jsonl.gz").exists() else 0,
                "compressed_viewer_bytes": package.stat().st_size if package.exists() else 0})
        report["battle_library"] = {"count": len(library), "video_bytes": sum(b["video_bytes"] for b in library),
                                   "saved_data_bytes": sum(b["saved_data_bytes"] for b in library),
                                   "full_analysis_count": sum(b["analysis_status"] == "analyzed_with_unknowns" for b in library),
                                   "per_battle": details}
        full = [b for b in details if b["analysis_status"] == "analyzed_with_unknowns" and b["duration_seconds"]]
        lib = report["battle_library"]
        lib["analysis_archive_bytes"] = sum(b["analysis_archive_bytes"] for b in details)
        if full:
            seconds = sum(b["duration_seconds"] for b in full)
            lib["full_analysis_duration_seconds"] = seconds
            lib["average_video_bytes"] = sum(b["video_bytes"] for b in full)/len(full)
            lib["average_saved_data_bytes"] = sum(b["current_saved_data_bytes"] for b in full)/len(full)
            lib["current_three_minute_projection"] = {
                "video_including_muxed_audio_bytes": sum(b["video_bytes"] for b in full)/seconds*180,
                "saved_files_including_raw_display_alignment_refinements_bytes": sum(b["current_saved_data_bytes"] for b in full)/seconds*180,
                "excludes": ["original recording", "older analysis archives", "shared dependencies", "tracker simulations", "portable HTML display copy"],
                "basis": "Measured full active clips; bitrate and future fields can change"}
        report["retained_superseded_video_bytes"] = sum((p.parent / "video.mp4").stat().st_size
            for p in (ROOT / "battles").glob("*/battle.json")
            if json.loads(p.read_text(encoding="utf-8")).get("segment_status") == "combined_superseded")
    report["limitations"] = ["Media extrapolation uses downloaded creator videos, not original iPhone recording bitrates.",
                              "Historical raw/event projections below use two older 60-second samples; current complete-package projections are measured separately.",
                              "Tracker-state estimate assumes two complete state snapshots per second, including nonfighting time; actual export cadence may be lower.",
                              "Compression measurements are in memory. No original data is removed or duplicated into compressed archives."]
    out = ROOT / "output"
    out.mkdir(exist_ok=True)
    (out / "storage-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    mb = lambda b: f"{b / 1e6:.2f} MB"
    text = "# Measured storage budget\n\nDecimal MB (1 MB = 1,000,000 bytes).\n"
    lib = report.get("battle_library", {})
    if lib.get("current_three_minute_projection"):
        projection = lib["current_three_minute_projection"]
        text += f"\nMeasured average across {lib['full_analysis_count']} fully processed battles: **{mb(lib['average_video_bytes'])} of video including audio + {mb(lib['average_saved_data_bytes'])} of current saved files per battle**. Mean duration is {lib['full_analysis_duration_seconds']/lib['full_analysis_count']:.1f} seconds.\n"
        text += f"\nA three-minute battle at these measured rates: **{mb(projection['video_including_muxed_audio_bytes'])} video + {mb(projection['saved_files_including_raw_display_alignment_refinements_bytes'])} saved files**. Saved files include compressed raw/event logs, display data, original frame alignment, refinement patches and metadata. Originals, older analysis archives, shared tools, tracker simulations and the portable HTML are separate.\n"
    text += "\nHistorical component estimates from the original downloads and two older 60-second reader samples (not the current full-package total):\n\n| Recording | Video | Separate commentary track | Raw screen/event logs | Same logs, gzip | Tracker states at 2/sec, raw |\n|---|---:|---:|---:|---:|---:|\n"
    for source in report["sources"]:
        logs = next((item for item in report["reader_logs"] if item["id"] == source["id"]), None)
        if not logs: continue
        text += "| " + " | ".join([source["creator"], mb(source["video_bytes_per_second"]*180), mb(source["audio_bytes_per_second"]*180), mb(logs["raw_bytes_per_second"]*180), mb(logs["gzip_bytes_per_second"]*180), mb(report["tracker_state_bytes_per_look"]*360)]) + " |\n"
    text += "\nShared game data: " + mb(report["shared_game_data_bytes"]) + ", stored once per project. Python packages and calibration assets are shared, not a per-battle cost.\n\nExisting folders (includes old references, previews and development assets):\n\n"
    for name, size in report["existing_folder_bytes"].items():
        text += f"- {name}: {mb(size)}\n"
    if report.get("battle_library"):
        lib = report["battle_library"]
        text += f"\nActive library: {lib['count']} physical phone-view clips, {mb(lib['video_bytes'])} of video including commentary, and {mb(lib['saved_data_bytes'])} of current saved data/metadata. {lib['full_analysis_count']} clips have full-frame readings; unreadable game values remain unknown. Physical clips are additional storage while originals remain available.\n"
        text += f"\nSuperseded combined video retained separately: {mb(report['retained_superseded_video_bytes'])}. Earlier analysis archives total {mb(lib['analysis_archive_bytes'])}, separate from current saved files.\n\n| Battle | Seconds | Video + audio | Current saved files | Earlier analysis |\n|---|---:|---:|---:|---:|\n"
        for b in lib['per_battle']:
            duration = f"{b['duration_seconds']:.1f}" if b['duration_seconds'] is not None else "unknown"
            text += f"| {b['id']} | {duration} | {mb(b['video_bytes'])} | {mb(b['current_saved_data_bytes'])} | {mb(b['analysis_archive_bytes'])} |\n"
    text += "\nStorage approach:\n\n- Keep one original video and reference it by path plus source timestamps. Each battle folder has a cropped physical clip requested by the user, not another copy of the complete source.\n- Save future full-frame reader logs with --compress-logs; gzip is lossless and writes no plain duplicate. The exporter, comparator and viewer builder accept compressed logs.\n- Keep observations separate from inferred states. Preserve source alignment and timing uncertainty.\n- The HTML viewer embeds a compressed display copy of the readings; video is referenced locally. Regenerate the viewer when readings change.\n- Keep only selected QA images, not one screenshot per frame. Avoid saving one full HTML per battle; regenerate one viewer for the recordings under review.\n- Retain current originals. No cleanup/deletion was performed.\n\nLimitations:\n\n" + "\n".join("- " + note for note in report["limitations"]) + "\n"
    (out / "storage-report.md").write_text(text, encoding="utf-8")
    print(text.split("Existing folders")[0])


if __name__ == "__main__":
    measure()
