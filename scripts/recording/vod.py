"""Download a calibrated Twitch VOD once and cut it into reproducible battle folders.

    python scripts/recording/vod.py https://www.twitch.tv/videos/ID --layout LAYOUT --download

--reader-dir points at the earlier screen_reader branch; --sources-root and
--library can point at an existing local library. Media stays outside Git.
This command discovers and cuts footage. It does not claim complete state tracking.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import copy
import gzip
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
from vod_media import media_facts, normalize_source, sha256, write_json


def reader_location(explicit=None):
    options = [explicit, os.environ.get("READER_DIR"), ROOT / ".reader/branch/screen_reader",
               ROOT.parent / "pokemon-go-github/screen_reader", ROOT.parent / "pokemon-go-screen-reader"]
    for option in options:
        if option and (Path(option) / "segment_battles.py").is_file():
            return Path(option).resolve()
    raise ValueError("Set --reader-dir to the screen_reader folder from screen-reader-video-pipeline")


def bootstrap(reader):
    paths = [reader, reader / "tools/python-libs", ROOT.parent / "pokemon-go-screen-reader/tools/python-libs"]
    for path in reversed(paths):
        if path.is_dir():
            sys.path.insert(0, str(path))


def download(url, folder, downloader):
    """Use native HLS with bounded fragment concurrency; never save access-token URLs."""
    from import_source import canonical_source
    platform, identity, canonical = canonical_source(url)
    if platform != "twitch":
        raise ValueError("This intake command expects one Twitch VOD")
    folder.mkdir(parents=True, exist_ok=True)
    selector = "best[ext=mp4][height>=720][height<=1080]"
    common = [str(downloader), "--ignore-config", "--no-playlist", "--socket-timeout", "20",
              "--retries", "3", "--extractor-retries", "2", "-f", selector]
    found = subprocess.run(common + ["--skip-download", "--dump-single-json", canonical], capture_output=True,
                           text=True, encoding="utf-8", timeout=180)
    if found.returncode:
        raise RuntimeError(found.stderr.strip())
    info = json.loads(found.stdout)
    if info.get("is_live") or str(info.get("id")) not in {identity, "v" + identity}:
        raise ValueError("A completed, single VOD is required")
    subprocess.run(common + ["--abort-on-unavailable-fragments", "--fragment-retries", "5",
                             "--concurrent-fragments", "4", "--progress-delta", "5", "--newline",
                             "--fixup", "never", "--no-overwrites", "-o", str(folder / "video.%(ext)s"), canonical], check=True)
    video = folder / "video.mp4"
    if not video.is_file():
        raise ValueError("No completed video; partial download retained for resume")
    record = {"schema": "video-source-v1", "platform": platform, "source_id": identity, "url": canonical,
              "title": info.get("title"), "creator": info.get("uploader"), "duration_seconds": info.get("duration"),
              "format_id": info.get("format_id"), "upload_date": info.get("upload_date"),
              "media_file": f"twitch/{identity}/video.mp4", "media": media_facts(video),
              "downloader_version": subprocess.check_output([str(downloader), "--version"], text=True).strip()}
    if abs(record["media"]["duration_seconds"] - info["duration"]) > 1:
        raise ValueError("Downloaded duration does not match the VOD; intake is incomplete")
    record["download_integrity"] = {"all_fragments_required": True, "expected_duration_seconds": info["duration"]}
    write_json(folder / "source.json", record)
    return video


def compatible_export(previous, candidate, view, fingerprint):
    prior = previous.get("vod_intake_fingerprint", {})
    boundary = previous.get("boundary_candidate", {})
    return (previous.get("source_sha256") == fingerprint["source_sha256"]
            and previous.get("source_viewport") == view["viewport"]
            and previous.get("encoding_crf") == 23
            and prior.get("reader_sha256", {}).get("extract_battles.py") == fingerprint["reader_sha256"]["extract_battles.py"]
            and all(boundary.get(key) == candidate.get(key) for key in ["start", "end", "first_hud_seconds"]))


def export_one(video, candidate, view, library, fingerprint, creator, url, source_record):
    from extract_battles import encode_clip, validate_candidate
    validate_candidate(candidate)
    folder = library / candidate["id"]
    if not folder.resolve().is_relative_to(library.resolve()):
        raise ValueError("Output escaped battle library")
    record_path = folder / "battle.json"
    if record_path.exists():
        previous = json.loads(record_path.read_text(encoding="utf-8"))
        if not compatible_export(previous, candidate, view, fingerprint):
            raise ValueError("Existing clip has different inputs or boundaries; no overwrite")
        saved = folder / previous["video_file"]
        if not saved.is_file() or sha256(saved) != previous["video_sha256"]:
            raise ValueError("Existing clip changed or disappeared")
        if previous.get("vod_intake_fingerprint") != fingerprint or previous.get("boundary_candidate") != candidate:
            previous.setdefault("video_export_fingerprint", previous["vod_intake_fingerprint"])
            previous.update({"vod_intake_fingerprint": fingerprint, "boundary_candidate": candidate,
                             "name": candidate["name"], "match_id": candidate["match_id"],
                             "notes": candidate["notes"], "completeness": candidate["completeness"]})
            write_json(record_path, previous)
        return {"id": candidate["id"], "match_id": candidate["match_id"], "reused": True,
                "video_bytes": previous["video_bytes"], "duration_seconds": previous["duration_seconds"]}
    facts = encode_clip(video, candidate, view["viewport"], folder)
    empty = {key: [] for key in ["readings", "states", "observations", "events"]}
    empty["bookmarks"] = [{"t": max(0, candidate["first_hud_seconds"] - facts["source_start_seconds"]),
                           "name": "First visible battle header · action start unverified"}]
    with gzip.open(folder / "viewer-data.json.gz", "wt", encoding="utf-8") as stream:
        json.dump(empty, stream, separators=(",", ":"))
    write_json(folder / "team.json", {"pokemon": []})
    (folder / "observations.jsonl").write_text("", encoding="utf-8")
    (folder / "report.md").write_text("Twitch boundary candidate, sampled automatically. Game-state tracking has not run. "
                                     "Inspect the boundary review and incomplete flags before evaluation. Source PTS are retained.\n", encoding="utf-8")
    metadata = {"schema": "battle-library-v1", "id": candidate["id"], "name": candidate["name"],
                "creator": creator, "reference_id": candidate["source_id"], "source_url": url,
                "source_video": str(video.resolve()), "source_sha256": fingerprint["source_sha256"],
                "source_edited": True, "source_kind": "twitch_vod", "timing_validated": False,
                "boundary_review_required": True, "boundary_candidate": candidate,
                "boundary_detector": fingerprint["detector"], "completeness": candidate["completeness"],
                "analysis_status": "not_analyzed", "viewer_data_file": "viewer-data.json.gz",
                "vod_intake_fingerprint": fingerprint, "video_export_fingerprint": fingerprint,
                "match_id": candidate["match_id"], "view_id": view["id"],
                "incomplete_start": candidate["incomplete_start"], "incomplete_end": candidate["incomplete_end"],
                "eligible_for_complete_battle_evaluation": candidate["eligible_for_complete_battle_evaluation"],
                "original_container_timestamp_offset_seconds": source_record.get("timestamp_normalization", {}).get("container_timestamp_offset_seconds", 0),
                "encoding_crf": 23, "notes": candidate["notes"], **facts}
    metadata["saved_data_bytes"] = sum(p.stat().st_size for p in folder.iterdir() if p.is_file() and p.name != "video.mp4")
    write_json(record_path, metadata)
    return {"id": candidate["id"], "match_id": candidate["match_id"], "reused": False,
            "video_bytes": facts["video_bytes"], "duration_seconds": facts["duration_seconds"]}


def coalesce_paired_fragments(views):
    """Join header gaps only inside a complete, simultaneous peer interval."""
    views = copy.deepcopy(views)
    complete = {"result_visible", "broadcast_result_visible"}
    anchors = [(side, c) for side, candidates in views.items() for c in candidates
               if c["completeness"] in complete and c["eligible_for_complete_battle_evaluation"]
               and c["end"] - c["start"] >= 60]
    for side, anchor in anchors:
        for peer, candidates in list(views.items()):
            if peer == side:
                continue
            fragments = sorted([c for c in candidates if c["source_id"] == anchor["source_id"]
                and anchor["start"] - 2 <= c["start"] and c["end"] <= anchor["end"] + 2],
                key=lambda c: c["start"])
            if len(fragments) < 2 or abs(fragments[0]["start"] - anchor["start"]) > 2 or abs(fragments[-1]["end"] - anchor["end"]) > 2:
                continue
            if any(b["start"] - a["end"] > 2 for a, b in zip(fragments, fragments[1:])):
                continue
            if any(c["start_method"] not in ("entry_gap_or_edit", "sustained_party_reset")
                   or any(cue["kind"] == "countdown" for cue in c["cues"]) for c in fragments[1:]):
                continue
            if any(c["incomplete_start"] or c["incomplete_end"] for c in fragments):
                continue
            merged = copy.deepcopy(fragments[0])
            merged.update({"end": fragments[-1]["end"], "end_method": fragments[-1]["end_method"],
                "end_uncertainty_seconds": max(anchor["end_uncertainty_seconds"], fragments[-1]["end_uncertainty_seconds"]),
                "completeness": anchor["completeness"], "eligible_for_complete_battle_evaluation": True,
                "paired_fragment_join": {"anchor_id": anchor["id"], "anchor_view": side,
                    "anchor_start": anchor["start"], "anchor_end": anchor["end"],
                    "fragments": [{key:c[key] for key in ("id", "start", "end", "start_method", "completeness")} for c in fragments]}})
            merged["cues"] = [cue for c in fragments for cue in c["cues"]]
            merged["notes"].append("Adjacent camera fragments joined inside one complete peer battle; exact boundaries still require review.")
            removed = {c["id"] for c in fragments}
            views[peer] = sorted([c for c in candidates if c["id"] not in removed] + [merged], key=lambda c: c["start"])
    return views


def result_refinement_windows(views, duration):
    """Short result graphics can fall between the VOD's two-second keyframes."""
    windows = []
    for side, candidates in views.items():
        for candidate in candidates:
            if candidate["completeness"] != "result_unseen_or_edited" or not candidate["eligible_for_complete_battle_evaluation"] or candidate["end"] - candidate["start"] < 60:
                continue
            covered = any(peer["completeness"] in ("result_visible", "broadcast_result_visible")
                and abs(peer["start"] - candidate["start"]) <= 2
                and min(peer["end"],candidate["end"]) - max(peer["start"],candidate["start"]) >= .9 * (candidate["end"] - candidate["start"])
                for other, peers in views.items() if other != side for peer in peers)
            if not covered:
                windows.append([max(0,candidate["end"] - 12), min(duration,candidate["end"] + 2)])
    merged = []
    for start,end in sorted(windows):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(end,merged[-1][1])
        else:
            merged.append([start,end])
    return merged


def refine_result_markers(video, regions, windows, cache):
    """Read only proposed endings at quarter-second cadence, preserving PTS."""
    import av
    from local_ocr import LocalOCR
    from vod_broadcast import cue_matches
    regions = [r for r in regions if r["kind"] == "match_win"]
    if not regions or not windows:
        return []
    fingerprint = {"source_sha256":sha256(video), "regions":regions, "windows":windows,
                   "interval_seconds":.25, "code_sha256":sha256(HERE / "vod.py")}
    if cache.is_file():
        with gzip.open(cache,"rt",encoding="utf-8") as f:
            prior = json.load(f)
        if prior["fingerprint"] == fingerprint:
            return prior["markers"]
    ocr, markers = LocalOCR(), []
    with av.open(str(video)) as source:
        stream = source.streams.video[0]
        stream.codec_context.thread_count = 4
        for number,(start,end) in enumerate(windows,1):
            source.seek(int(start / stream.time_base),stream=stream,backward=True)
            last = -100
            for frame in source.decode(stream):
                if frame.pts is None:
                    continue
                t = float(frame.pts * frame.time_base)
                if t < start:
                    continue
                if t >= end:
                    break
                if t - last < .25 - 1e-6:
                    continue
                last = t
                rgb = frame.to_ndarray(format="rgb24")
                for region in regions:
                    x,y,w,h = region["rect"]
                    if min(x,y) < 0 or x+w > frame.width or y+h > frame.height:
                        raise ValueError("Broadcast result region is outside this recording")
                    text = " ".join(item["text"] for item in ocr.read(rgb[y:y+h,x:x+w]) if item["confidence"] >= .75)
                    if cue_matches(region,text):
                        markers.append({"t":round(t,6), "kind":region["kind"], "text":text,
                                        "sampling":"quarter_second_result_window"})
            print(json.dumps({"stage":"result_refine","windows_done":number,"windows_total":len(windows),"markers":len(markers)}),flush=True)
    cache.parent.mkdir(parents=True,exist_ok=True)
    temporary = cache.with_name(cache.name + ".incomplete")
    with gzip.open(temporary,"wt",encoding="utf-8") as f:
        json.dump({"fingerprint":fingerprint,"markers":markers},f,separators=(",",":"))
    temporary.replace(cache)
    return markers


def align_paired_coverage(groups):
    """Cover the shared beginning/end and explicitly attribute a peer result."""
    complete = {"result_visible", "broadcast_result_visible"}
    for group in groups:
        anchors = [c for c in group if c["completeness"] in complete]
        if len(group) < 2 or not anchors or any(c["incomplete_start"] or c["incomplete_end"] for c in group):
            continue
        start, end = min(c["start"] for c in group), max(c["end"] for c in group)
        overlap = min(c["end"] for c in group) - max(c["start"] for c in group)
        if overlap / (end - start) < .9 or max(c["start"] for c in group) - start > 2:
            continue
        evidence = [{key:c[key] for key in ("id", "view_id", "completeness", "end")} for c in anchors]
        for candidate in group:
            candidate["paired_boundary_evidence"] = {"result_views": evidence,
                "own_start": candidate["start"], "own_end": candidate["end"],
                "own_completeness": candidate["completeness"]}
            if candidate["end"] != end:
                candidate["end_method"] = "paired_result_coverage"
            candidate["start"], candidate["end"] = start, end
            if candidate["completeness"] not in complete:
                candidate["completeness"] = "paired_result_visible"
            candidate["notes"].append("Paired views share source coverage; result evidence is attributed to the camera that showed it.")


def select_battles(views, limit=None, complete_only=False, required_views=None):
    """Limit unique games, keeping both views together and selection chronological."""
    if limit is not None and limit <= 0:
        raise ValueError("Battle limit must be positive")
    groups = {}
    for candidates in views.values():
        for candidate in candidates:
            groups.setdefault(candidate["match_id"], []).append(candidate)
    ordered = sorted(groups.values(), key=lambda group: min(c["first_hud_seconds"] for c in group))
    selected = []
    for group in ordered:
        if complete_only and any(not c["eligible_for_complete_battle_evaluation"] or
                                 c["completeness"] not in ("result_visible", "broadcast_result_visible", "paired_result_visible") for c in group):
            continue
        if required_views and {c["view_id"] for c in group} != required_views:
            continue
        selected.append(group)
        if limit is not None and len(selected) >= limit:
            break
    return [c for group in selected for c in sorted(group, key=lambda c: c["view_id"])]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--layout", required=True)
    parser.add_argument("--reader-dir", type=Path)
    parser.add_argument("--sources-root", type=Path, default=ROOT / ".vod/sources")
    parser.add_argument("--library", type=Path, default=ROOT / ".vod/battles")
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--downloader", type=Path)
    parser.add_argument("--stage", choices=["detect", "extract"], default="extract")
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--scan-end", type=float, help="Stop boundary discovery at this source second; preserve the full original")
    parser.add_argument("--limit-battles", type=int, help="Export at most this many unique games, including all paired views")
    parser.add_argument("--complete-only", action="store_true", help="Require complete flags and a visible result on every view")
    parser.add_argument("--paired-only", action="store_true", help="Require every configured view for each selected battle")
    parser.add_argument("--rescan", action="store_true")
    parser.add_argument("--resegment", action="store_true", help="Rebuild candidates while reusing unchanged visual samples")
    args = parser.parse_args()
    if not 1 <= args.jobs <= 4:
        parser.error("Use one to four export jobs")
    if args.scan_end is not None and (not math.isfinite(args.scan_end) or args.scan_end <= 0):
        parser.error("Use a positive finite scan ending time")
    if args.limit_battles is not None and args.limit_battles <= 0:
        parser.error("Use a positive battle limit")
    reader = reader_location(args.reader_dir)
    bootstrap(reader)
    from import_source import canonical_source
    from vod_segments import VERSION, profiles_for, coarse_scan, refine_scan, annotate_segments, pair_perspectives, discover_segments
    from vod_broadcast import marker_scan, filter_broadcast
    platform, identity, canonical = canonical_source(args.url)
    if platform != "twitch":
        parser.error("Use a Twitch VOD link")
    configs = json.loads((ROOT / "data/vod_layouts.json").read_text(encoding="utf-8"))["layouts"]
    if args.layout not in configs:
        parser.error("Unknown calibrated layout")
    layout = configs[args.layout]
    if identity not in layout["source_ids"]:
        parser.error("This layout has not been calibrated for that VOD")
    folder = args.sources_root.resolve() / "twitch" / identity
    video = folder / "video.mp4"
    record_path = folder / "source.json"
    if not video.exists():
        if not args.download:
            parser.error("Completed source is missing; add --download")
        executable = args.downloader or reader / "tools/yt-dlp.exe"
        if not executable.is_file():
            parser.error("Set --downloader to yt-dlp")
        video = download(canonical, folder, executable)
    elif not record_path.exists():
        raise ValueError("Source metadata is missing: wait for intake to finish")
    started = time.monotonic()
    media = normalize_source(video, record_path)
    source_record = json.loads(record_path.read_text(encoding="utf-8"))
    run_folder = ROOT / ".vod/runs" / identity
    run_folder.mkdir(parents=True, exist_ok=True)
    profiles = profiles_for(layout, reader, ROOT / "data/gamemaster.json")
    scan = coarse_scan(video, profiles, run_folder / "coarse-scan.json.gz", rescan=args.rescan, scan_end=args.scan_end)
    fingerprint = {"detector": VERSION, "source_sha256": scan["fingerprint"]["source_sha256"],
                   "layout": layout, "code_sha256": {name: sha256(HERE / name) for name in ["vod.py", "vod_media.py", "vod_segments.py", "vod_broadcast.py"]},
                   "reader_sha256": {name: sha256(reader / name) for name in ["segment_battles.py", "extract_battles.py", "local_ocr.py"]}}
    if args.scan_end is not None:
        fingerprint["scan_end_seconds"] = scan["duration_seconds"]
    manifest_path = run_folder / "battle-candidates.json"
    previous = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    if previous and not args.rescan and not args.resegment:
        manifest = previous
        if manifest.get("fingerprint") != fingerprint:
            raise ValueError("Boundary code or inputs changed: use --resegment or --rescan")
        views = manifest["views"]
    else:
        views = {}
        old = previous.get("fingerprint", {})
        reuse_fine = (not args.rescan and old.get("detector") == VERSION
                      and old.get("source_sha256") == fingerprint["source_sha256"]
                      and old.get("code_sha256", {}).get("vod_segments.py") == fingerprint["code_sha256"]["vod_segments.py"]
                      and old.get("reader_sha256") == fingerprint["reader_sha256"]
                      and old.get("layout", {}).get("views") == layout["views"])
        rough_views = {name: discover_segments(rows, name, scan["duration_seconds"]) for name, rows in scan["views"].items()}
        shared_seeds = []
        for candidate in sorted([c for candidates in rough_views.values() for c in candidates], key=lambda c: c["first_hud_seconds"]):
            if not shared_seeds or candidate["first_hud_seconds"] - shared_seeds[-1]["first_hud_seconds"] > 8:
                shared_seeds.append(candidate)
        for name, profile in profiles.items():
            rows = scan["views"][name]
            rough = rough_views[name]
            print(json.dumps({"stage": "coarse_candidates", "view": name, "count": len(rough)}), flush=True)
            fine_cache = run_folder / f"{name}-boundary-samples.json.gz"
            if reuse_fine and fine_cache.is_file():
                with gzip.open(fine_cache, "rt", encoding="utf-8") as stream:
                    fine_rows = json.load(stream)
                refined = discover_segments(fine_rows, name, scan["duration_seconds"], .25)
            else:
                fine_rows, refined = refine_scan(video, profile, rows, shared_seeds, scan["duration_seconds"])
            views[name] = annotate_segments(refined, fine_rows, identity, name, scan["duration_seconds"])
            with gzip.open(fine_cache, "wt", encoding="utf-8") as stream:
                json.dump(fine_rows, stream, separators=(",", ":"))
        markers = marker_scan(video, layout["broadcast_regions"], run_folder / "broadcast-labels.json.gz", scan_end=args.scan_end) if layout.get("broadcast_regions") else []
        unfiltered = views
        views, excluded = filter_broadcast(unfiltered, markers)
        extra_markers = refine_result_markers(video, layout.get("broadcast_regions", []),
            result_refinement_windows(views, scan["duration_seconds"]), run_folder / "result-refinement.json.gz")
        if extra_markers:
            markers = sorted(markers + extra_markers, key=lambda m:m["t"])
            views, excluded = filter_broadcast(unfiltered, markers)
        views = coalesce_paired_fragments(views)
        groups = pair_perspectives(views, identity)
        align_paired_coverage(groups)
        for number, group in enumerate(groups, 1):
            for candidate in group:
                suffix = " · partial" if candidate["incomplete_start"] or candidate["incomplete_end"] else ""
                candidate["name"] = f"{layout.get('label_prefix', layout['channel'])} · Match {number:02d} · {candidate['view_id']}{suffix}"
                candidate["dataset_role"] = layout["dataset_role"]
        manifest = {"schema": "twitch-battle-candidates-v1", "source_id": identity, "url": canonical,
                    "fingerprint": fingerprint, "views": views, "unique_match_candidates": len(groups),
                    "excluded_candidates": excluded, "broadcast_markers": markers,
                    "all_boundaries_review_required": True, "full_game_state_verified": False}
        write_json(manifest_path, manifest)
    selected = select_battles(views, args.limit_battles, args.complete_only,
                              {view["id"] for view in layout["views"]} if args.paired_only else None)
    manifest["export_selection"] = {"limit_unique_battles": args.limit_battles,
        "complete_only": args.complete_only, "paired_only": args.paired_only,
        "unique_battles": len({c["match_id"] for c in selected}), "clip_ids": [c["id"] for c in selected]}
    write_json(manifest_path, manifest)
    exports = []
    if args.stage == "extract":
        args.library.mkdir(parents=True, exist_ok=True)
        view_lookup = {view["id"]: view for view in layout["views"]}
        tasks = [(candidate, view_lookup[candidate["view_id"]]) for candidate in selected]
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            futures = [pool.submit(export_one, video, candidate, view, args.library.resolve(), fingerprint,
                                   source_record.get("creator") or layout["channel"], canonical, source_record) for candidate, view in tasks]
            for future in as_completed(futures):
                result = future.result()
                exports.append(result)
                print(json.dumps({"stage": "export", "clip": result["id"], "completed": len(exports),
                                  "total": len(tasks), "video_bytes": result["video_bytes"]}), flush=True)
    summary = {"source_id": identity, "url": canonical, "title": source_record.get("title"),
               "source_video_seconds": media["duration_seconds"], "source_bytes": media["bytes"],
               "unique_match_candidates": manifest["unique_match_candidates"],
               "perspective_clip_candidates": sum(len(candidates) for candidates in views.values()),
               "excluded_replay_perspectives": len(manifest.get("excluded_candidates", [])),
               "incomplete_candidates": [c["id"] for candidates in views.values() for c in candidates if c["incomplete_start"] or c["incomplete_end"]],
               "exports": sorted(exports, key=lambda item: item["id"]),
               "clip_video_bytes": sum(e["video_bytes"] for e in exports), "wall_seconds": round(time.monotonic() - started, 3),
               "boundary_review_required": True, "tracking_run": False, "independent_accuracy_measured": False}
    summary["export_selection"] = manifest["export_selection"]
    write_json(run_folder / "run.json", summary)
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
