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
        source = {"id": ref["id"], "creator": ref["creator"]}
        for kind, field in [("video", "file"), ("audio", "audio")]:
            path = ROOT / ref[field]
            with av.open(str(path)) as media:
                duration = media.duration / av.time_base
            source[kind + "_bytes"] = path.stat().st_size
            source[kind + "_seconds"] = duration
            source[kind + "_bytes_per_second"] = path.stat().st_size / duration
        report["sources"].append(source)
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
    example = (ROOT / "tracker_bundle/games/example/states.jsonl").read_bytes()
    count = len([line for line in example.splitlines() if line.strip()])
    report["tracker_state_bytes_per_look"] = len(example) / count
    report["shared_game_data_bytes"] = sum(p.stat().st_size for p in (ROOT / "tracker_bundle/data").iterdir() if p.is_file())
    report["existing_folder_bytes"] = {name: sum(p.stat().st_size for p in (ROOT / name).rglob("*") if p.is_file())
                                      for name in ["reference-videos", "battles", "output", "samples", "tools", "tracker_bundle"]}
    if (ROOT / "battles").exists():
        from battle_library import scan_library
        library = scan_library(ROOT / "battles")
        details = []
        for b in library:
            folder = ROOT / "battles" / b["id"]
            details.append({"id": b["id"], "duration_seconds": b["duration_seconds"],
                "video_bytes": b["video_bytes"], "current_saved_data_bytes": b["saved_data_bytes"],
                "analysis_status": b["analysis_status"],
                "analysis_archive_bytes": sum(p.stat().st_size for p in (folder / "analysis-archive").rglob("*") if p.is_file()),
                "compressed_readings_bytes": (folder / "screen_readings.jsonl.gz").stat().st_size if (folder / "screen_readings.jsonl.gz").exists() else 0,
                "compressed_viewer_bytes": (folder / "viewer-data.json.gz").stat().st_size})
        report["battle_library"] = {"count": len(library), "video_bytes": sum(b["video_bytes"] for b in library),
                                   "saved_data_bytes": sum(b["saved_data_bytes"] for b in library),
                                   "full_analysis_count": sum(b["analysis_status"] == "analyzed_with_unknowns" for b in library),
                                   "per_battle": details}
        report["retained_superseded_video_bytes"] = sum((p.parent / "video.mp4").stat().st_size
            for p in (ROOT / "battles").glob("*/battle.json")
            if json.loads(p.read_text(encoding="utf-8")).get("segment_status") == "combined_superseded")
    report["limitations"] = ["Media extrapolation uses downloaded creator videos, not original iPhone recording bitrates.",
                              "Log compression ratio comes from current clips; richer observations can compress differently.",
                              "Tracker-state estimate assumes two complete state snapshots per second, including nonfighting time; actual export cadence may be lower.",
                              "Compression measurements are in memory. No original data is removed or duplicated into compressed archives."]
    out = ROOT / "output"
    (out / "storage-report.json").write_text(json.dumps(report, indent=2) + "\n")
    mb = lambda b: f"{b / 1e6:.2f} MB"
    text = "# Measured storage budget\n\nDecimal MB. Three-minute battle estimate using the existing creator recordings:\n\n| Recording | Video | Optional commentary | Raw screen/event logs | Same logs, gzip | Tracker states at 2/sec, raw |\n|---|---:|---:|---:|---:|---:|\n"
    for source, logs in zip(report["sources"], report["reader_logs"]):
        text += "| " + " | ".join([source["creator"], mb(source["video_bytes_per_second"]*180), mb(source["audio_bytes_per_second"]*180), mb(logs["raw_bytes_per_second"]*180), mb(logs["gzip_bytes_per_second"]*180), mb(report["tracker_state_bytes_per_look"]*360)]) + " |\n"
    text += "\nShared game data: " + mb(report["shared_game_data_bytes"]) + ", stored once per project. Python packages and calibration assets are shared, not a per-battle cost.\n\nExisting folders (includes old references, previews and development assets):\n\n"
    for name, size in report["existing_folder_bytes"].items():
        text += f"- {name}: {mb(size)}\n"
    if report.get("battle_library"):
        lib = report["battle_library"]
        text += f"\nActive library: {lib['count']} physical phone-view clips, {mb(lib['video_bytes'])} of video including commentary, and {mb(lib['saved_data_bytes'])} of current saved data/metadata. {lib['full_analysis_count']} clips have full-frame readings; unreadable game values remain unknown. Physical clips are additional storage while originals remain available.\n"
        text += f"\nSuperseded combined video retained separately: {mb(report['retained_superseded_video_bytes'])}. Earlier analysis archives are measured separately below.\n\n| Battle | Seconds | Video + audio | Current saved files | Earlier analysis |\n|---|---:|---:|---:|---:|\n"
        for b in lib['per_battle']:
            text += f"| {b['id']} | {b['duration_seconds']:.1f} | {mb(b['video_bytes'])} | {mb(b['current_saved_data_bytes'])} | {mb(b['analysis_archive_bytes'])} |\n"
    text += "\nStorage approach:\n\n- Keep one original video and reference it by path plus source timestamps. Each battle folder has a cropped physical clip requested by the user, not another copy of the complete source.\n- Save future full-frame reader logs with --compress-logs; gzip is lossless and writes no plain duplicate. The exporter, comparator and viewer builder accept compressed logs.\n- Keep observations separate from inferred states. Preserve source alignment and timing uncertainty.\n- The HTML viewer embeds a compressed display copy of the readings; video is referenced locally. Regenerate the viewer when readings change.\n- Keep only selected QA images, not one screenshot per frame. Avoid saving one full HTML per battle; regenerate one viewer for the recordings under review.\n- Retain current originals. No cleanup/deletion was performed.\n\nLimitations:\n\n" + "\n".join("- " + note for note in report["limitations"]) + "\n"
    (out / "storage-report.md").write_text(text, encoding="utf-8")
    print(text.split("Existing folders")[0])


if __name__ == "__main__":
    measure()
