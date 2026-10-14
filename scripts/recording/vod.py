"""Download a YouTube video or Twitch VOD once and extract its visible battles.

    python scripts/recording/vod.py https://www.twitch.tv/videos/ID --download

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
    folder.mkdir(parents=True, exist_ok=True)
    selector = ("best[ext=mp4][height>=720][height<=1080]" if platform == "twitch" else
                "best[ext=mp4][height>=720][height<=1080]/bestvideo[ext=mp4][height>=720][height<=1080]")
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
              "media_file": f"{platform}/{identity}/video.mp4", "media": media_facts(video),
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


def export_one(video, candidate, view, library, fingerprint, creator, url, source_record, *, preserve_existing=False):
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
        if not preserve_existing and (previous.get("vod_intake_fingerprint") != fingerprint or previous.get("boundary_candidate") != candidate):
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
                "source_edited": True, "source_kind": "twitch_vod" if source_record.get("platform", "twitch") == "twitch" else "youtube_video", "timing_validated": False,
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


def coalesce_paired_fragments(views, *, allow_unverified=False):
    """Join header gaps only inside a complete, simultaneous peer interval."""
    views = copy.deepcopy(views)
    complete = {"result_visible", "broadcast_result_visible"}
    anchors = [(side, c) for side, candidates in views.items() for c in candidates
               if (allow_unverified or c["completeness"] in complete and c["eligible_for_complete_battle_evaluation"])
               and c["end"] - c["start"] >= 60 and (not allow_unverified or c["end"] - c["start"] <= 420)]
    for side, anchor in anchors:
        for peer, candidates in list(views.items()):
            if peer == side:
                continue
            fragments = sorted([c for c in candidates if c["source_id"] == anchor["source_id"]
                and anchor["start"] - 2 <= c["start"] and c["end"] <= anchor["end"] + (12 if allow_unverified else 2)],
                key=lambda c: c["start"])
            if len(fragments) < 2 or abs(fragments[0]["start"] - anchor["start"]) > 2 or abs(fragments[-1]["end"] - anchor["end"]) > (12 if allow_unverified else 2):
                continue
            if any(b["start"] - a["end"] > (30 if allow_unverified else 2) for a, b in zip(fragments, fragments[1:])):
                continue
            if any(c["start_method"] not in (("entry_gap_or_edit", "sustained_party_reset", "first_hud_context") if allow_unverified else ("entry_gap_or_edit", "sustained_party_reset"))
                   or any(cue["kind"] == "countdown" for cue in c["cues"]) for c in fragments[1:]):
                continue
            if any(c["incomplete_start"] or c["incomplete_end"] for c in fragments):
                continue
            merged = copy.deepcopy(fragments[0])
            merged.update({"end": fragments[-1]["end"], "end_method": fragments[-1]["end_method"],
                "end_uncertainty_seconds": max(anchor["end_uncertainty_seconds"], fragments[-1]["end_uncertainty_seconds"]),
                "completeness": anchor["completeness"], "eligible_for_complete_battle_evaluation": anchor["completeness"] in complete,
                "paired_fragment_join": {"anchor_id": anchor["id"], "anchor_view": side,
                    "anchor_start": anchor["start"], "anchor_end": anchor["end"],
                    "fragments": [{key:c[key] for key in ("id", "start", "end", "start_method", "completeness")} for c in fragments]}})
            merged["cues"] = [cue for c in fragments for cue in c["cues"]]
            merged["notes"].append("Adjacent camera fragments joined inside one peer interval; exact boundaries and completeness still require review.")
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


def align_paired_coverage(groups, *, allow_unverified=False):
    """Cover the shared beginning/end and explicitly attribute a peer result."""
    complete = {"result_visible", "broadcast_result_visible"}
    for group in groups:
        anchors = [c for c in group if c["completeness"] in complete]
        if len(group) < 2 or (not anchors and not allow_unverified) or any(c["incomplete_start"] or c["incomplete_end"] for c in group):
            continue
        start, end = min(c["start"] for c in group), max(c["end"] for c in group)
        overlap = min(c["end"] for c in group) - max(c["start"] for c in group)
        if (allow_unverified and end - start > 420) or overlap / (end - start) < (.65 if allow_unverified else .9) or (not allow_unverified and max(c["start"] for c in group) - start > 2):
            continue
        evidence = [{key:c[key] for key in ("id", "view_id", "completeness", "end")} for c in anchors]
        for candidate in group:
            candidate["paired_boundary_evidence"] = {"result_views": evidence,
                "own_start": candidate["start"], "own_end": candidate["end"],
                "own_completeness": candidate["completeness"]}
            if candidate["end"] != end:
                candidate["end_method"] = "paired_result_coverage"
            candidate["start"], candidate["end"] = start, end
            if anchors and candidate["completeness"] not in complete:
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


def reuse_existing_candidates(views, library, fingerprint, platform, identity):
    """Keep already saved cuts and their analysis; new full scans get distinct IDs."""
    previous = []
    library = Path(library).resolve()
    for path in library.glob('*/battle.json'):
        if not path.resolve().is_relative_to(library):
            continue
        meta = json.loads(path.read_text(encoding='utf-8'))
        if meta.get('segment_status') != 'combined_superseded' and meta.get('reference_id') == identity and meta.get('source_sha256') == fingerprint['source_sha256']:
            previous.append(meta)
    layouts = {v['id']: v for v in fingerprint['layout']['views']}
    result = copy.deepcopy(views)
    prefix = 'tw' if platform == 'twitch' else 'yt'
    def reusable(meta, candidate, side):
        boundary = meta.get('boundary_candidate')
        if meta.get('view_id') != side or not boundary:
            return False
        if compatible_export(meta, candidate, layouts[side], fingerprint):
            return True
        # Full intake accepts a few seconds of missing edge footage. Prefer the
        # already reviewed/encoded version of the same long game over a duplicate.
        reviewed_end = boundary.get('completeness') in ('result_visible','broadcast_result_visible','paired_result_visible') and not (
            meta.get('incomplete_start') or meta.get('incomplete_end'))
        end_tolerance = max(12, .35 * (boundary['end'] - boundary['start'])) if reviewed_end else 3
        close = candidate['end'] - candidate['start'] >= 30 and all(
            abs(boundary.get(k, -100) - candidate[k]) <= 3 for k in ['start', 'first_hud_seconds']) and abs(boundary['end'] - candidate['end']) <= end_tolerance
        at_previous_edges = {**candidate, **{k: boundary[k] for k in ['start', 'end', 'first_hud_seconds']}}
        return close and compatible_export(meta, at_previous_edges, layouts[side], fingerprint)
    for side, candidates in result.items():
        for number, candidate in enumerate(candidates):
            found = next((meta for meta in previous if reusable(meta, candidate, side)), None)
            if found:
                candidates[number] = copy.deepcopy(found['boundary_candidate'])
            else:
                candidate['id'] = f'{prefix}-{identity}-full-{side}-{number+1:03d}'
                if (library/candidate['id']/'battle.json').exists():
                    import hashlib
                    revision = json.dumps({**{k:candidate[k] for k in ['start','end','first_hud_seconds']},
                        'source_sha256':fingerprint['source_sha256'],'viewport':layouts[side]['viewport'],
                        'extractor_sha256':fingerprint['reader_sha256']['extract_battles.py']},sort_keys=True).encode()
                    candidate['id'] += '-r'+hashlib.sha256(revision).hexdigest()[:8]
                candidate['match_id'] = candidate['match_id'].replace(f'tw-{identity}-', f'{prefix}-{identity}-full-', 1)
    # Keep a new camera of an existing battle in that battle's original group.
    for side, candidates in views.items():
        for index, original in enumerate(candidates):
            old = [result[peer][j]['match_id'] for peer, peers in views.items() for j, c in enumerate(peers)
                   if c['match_id'] == original['match_id'] and '-full-' not in result[peer][j]['id']]
            if old:
                result[side][index]['match_id'] = old[0]
    return result


def retire_previous_full_cuts(library, identity, selected):
    """Hide superseded derived cuts after replacement clips are safely exported."""
    library=Path(library).resolve(); selected=set(selected); retired=[]
    if not selected:
        return retired
    for path in library.glob('*/battle.json'):
        if not path.resolve().is_relative_to(library) or '-full-' not in path.parent.name or path.parent.name in selected:
            continue
        meta=json.loads(path.read_text(encoding='utf-8'))
        if meta.get('reference_id') != identity or meta.get('segment_status') == 'combined_superseded':
            continue
        if meta.get('boundary_candidate',{}).get('dataset_role') == 'reserved_state_evaluation':
            continue
        meta['segment_status']='combined_superseded'
        meta['superseded_by_full_source_selection']=sorted(selected)
        meta.setdefault('notes',[]).append('Revised cuts supersede this derived video; its media and saved analysis are retained.')
        write_json(path,meta); retired.append(path.parent.name)
    return retired


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--layout", default="auto", help="Auto-detect phone views, or use a named screen layout")
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
    parser.add_argument("--run-dir", type=Path, help="Folder for this scan's receipts and boundary samples")
    parser.add_argument('--precise-boundaries', action='store_true', help='Refine candidate edges to quarter-second samples; default full intake accepts approximate edges')
    parser.add_argument('--reuse-broadcast-labels', action='store_true', help='Resegment using a completed source-matched broadcast-label receipt; do not extend its result-label windows')
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
    from vod_layout import resolve_layout
    platform, identity, canonical = canonical_source(args.url)
    configs = json.loads((ROOT / "data/vod_layouts.json").read_text(encoding="utf-8"))["layouts"]
    sample_mode = any([args.scan_end is not None, args.limit_battles is not None, args.complete_only, args.paired_only])
    run_folder = args.run_dir or ROOT / '.vod/runs' / (identity if sample_mode else f'{platform}-{identity}-full')
    run_folder.mkdir(parents=True, exist_ok=True)
    folder = args.sources_root.resolve() / platform / identity
    video = folder / "video.mp4"
    record_path = folder / "source.json"
    # Reuse the project's previously downloaded YouTube references in place.
    if not video.exists() and platform == 'youtube' and (reader / 'reference_manifest.json').is_file():
        refs = json.loads((reader / 'reference_manifest.json').read_text(encoding='utf-8'))['references']
        ref = next((r for r in refs if r['id'] == identity and (reader / r['file']).is_file()), None)
        if ref:
            video = reader / ref['file']
            if not record_path.exists():
                write_json(record_path, {'schema': 'video-source-v1', 'platform': platform,
                    'source_id': identity, 'url': canonical, 'creator': ref['creator'],
                    'media_file': ref['file'], 'media': media_facts(video)})
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
    layout = resolve_layout(args.layout, configs, identity, media, reader, video,
                            run_folder / 'detected-layout.json', source_record.get('creator'))
    if not sample_mode:
        layout['dataset_role'] = 'unassigned'
        layout['label_prefix'] = layout['channel'] + ' · full recording'
    min_duration = 15 if sample_mode else 3
    precise = sample_mode or args.precise_boundaries
    profiles = profiles_for(layout, reader, ROOT / "data/gamemaster.json")
    scan = coarse_scan(video, profiles, run_folder / "coarse-scan.json.gz", rescan=args.rescan, scan_end=args.scan_end)
    fingerprint = {"detector": VERSION, "source_sha256": scan["fingerprint"]["source_sha256"],
                   "layout": layout, "code_sha256": {name: sha256(HERE / name) for name in ["vod.py", "vod_media.py", "vod_segments.py", "vod_broadcast.py", "vod_layout.py", "vod_fixture.py"]},
                   "reader_sha256": {name: sha256(reader / name) for name in ["segment_battles.py", "extract_battles.py", "local_ocr.py"]}}
    fingerprint['boundary_sampling'] = 'quarter_second_edges' if precise else 'keyframes'
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
                      and old.get('boundary_sampling') == 'quarter_second_edges'
                      and old.get("source_sha256") == fingerprint["source_sha256"]
                      and old.get("code_sha256", {}).get("vod_segments.py") == fingerprint["code_sha256"]["vod_segments.py"]
                      and old.get("reader_sha256") == fingerprint["reader_sha256"]
                      and old.get("layout", {}).get("views") == layout["views"])
        rough_views = {name: discover_segments(rows, name, scan["duration_seconds"], min_duration=min_duration) for name, rows in scan["views"].items()}
        shared_seeds = []
        for candidate in sorted([c for candidates in rough_views.values() for c in candidates], key=lambda c: c["first_hud_seconds"]):
            if not shared_seeds or candidate["first_hud_seconds"] - shared_seeds[-1]["first_hud_seconds"] > 8:
                shared_seeds.append(candidate)
        for name, profile in profiles.items():
            rows = scan["views"][name]
            rough = rough_views[name]
            print(json.dumps({"stage": "coarse_candidates", "view": name, "count": len(rough)}), flush=True)
            fine_cache = run_folder / f"{name}-boundary-samples.json.gz"
            if not precise:
                fine_rows, refined = rows, rough
            elif reuse_fine and fine_cache.is_file():
                with gzip.open(fine_cache, "rt", encoding="utf-8") as stream:
                    fine_rows = json.load(stream)
                refined = discover_segments(fine_rows, name, scan["duration_seconds"], .25, min_duration=min_duration)
            else:
                fine_rows, refined = refine_scan(video, profile, rows, shared_seeds, scan["duration_seconds"], min_duration=min_duration)
            views[name] = annotate_segments(refined, fine_rows, identity, name, scan["duration_seconds"], min_duration=min_duration)
            with gzip.open(fine_cache, "wt", encoding="utf-8") as stream:
                json.dump(fine_rows, stream, separators=(",", ":"))
        # Result graphics only affect a proposed edge. Replay labels are still
        # checked throughout the recording, including outside candidate windows.
        match_windows = None if precise else [[max(0, c['end'] - 20), min(scan['duration_seconds'], c['end'] + 16)]
            for candidates in views.values() for c in candidates]
        label_cache = run_folder / 'broadcast-labels.json.gz'
        label_receipt = None
        if args.reuse_broadcast_labels and layout.get('broadcast_regions'):
            with gzip.open(label_cache, 'rt', encoding='utf-8') as stream:
                saved_labels = json.load(stream)
            label_fingerprint = saved_labels['fingerprint']
            if label_fingerprint['source_sha256'] != fingerprint['source_sha256'] or label_fingerprint['regions'] != layout['broadcast_regions']:
                raise ValueError('Saved broadcast labels belong to a different source or screen arrangement')
            if label_fingerprint.get('scan_end_seconds', media['duration_seconds']) < scan['duration_seconds']:
                raise ValueError('Saved replay-label coverage is shorter than this scan')
            markers = saved_labels['markers']
            label_receipt = {'file_sha256':sha256(label_cache), 'reading_fingerprint':label_fingerprint,
                             'result_label_windows_extended':False}
        else:
            markers = marker_scan(video, layout["broadcast_regions"], label_cache,
                scan_end=args.scan_end, match_windows=match_windows) if layout.get("broadcast_regions") else []
        unfiltered = views
        views, excluded = filter_broadcast(unfiltered, markers)
        extra_markers = refine_result_markers(video, layout.get("broadcast_regions", []),
            result_refinement_windows(views, scan["duration_seconds"]), run_folder / "result-refinement.json.gz") if precise else []
        if extra_markers:
            markers = sorted(markers + extra_markers, key=lambda m:m["t"])
            views, excluded = filter_broadcast(unfiltered, markers)
        views = coalesce_paired_fragments(views, allow_unverified=not sample_mode)
        groups = pair_perspectives(views, identity, allow_partial=not sample_mode)
        align_paired_coverage(groups, allow_unverified=not sample_mode)
        for number, group in enumerate(groups, 1):
            for candidate in group:
                suffix = " · partial" if candidate["incomplete_start"] or candidate["incomplete_end"] else ""
                candidate["name"] = f"{layout.get('label_prefix', layout['channel'])} · Match {number:02d} · {candidate['view_id']}{suffix}"
                candidate["dataset_role"] = layout["dataset_role"]
        fixture_receipt = None
        if not sample_mode and layout.get('fixture_regions'):
            from vod_fixture import split_fixtures
            views, fixture_receipt = split_fixtures(video, views, scan, layout['fixture_regions'],
                                                    run_folder/'fixture-readings.json.gz')
        if not sample_mode:
            views = reuse_existing_candidates(views, args.library, fingerprint, platform, identity)
        manifest = {"schema": "twitch-battle-candidates-v1" if sample_mode else "vod-battle-candidates-v2", "source_id": identity, "platform": platform, "url": canonical,
                    "fingerprint": fingerprint, "views": views,
                    "unique_match_candidates":len({c['match_id'] for v in views.values() for c in v}),
                    "non_montage_game_interval_candidates":len(groups)-len(fixture_receipt['changed_intervals'] if fixture_receipt else []),
                    "edited_excerpt_candidates":sum(len(c['parts']) for c in fixture_receipt['changed_intervals']) if fixture_receipt else 0,
                    "excluded_candidates": excluded, "broadcast_markers": markers,
                    "reused_broadcast_label_receipt":label_receipt,
                    "fixture_review":fixture_receipt,
                    "all_boundaries_review_required": True, "full_game_state_verified": False}
        write_json(manifest_path, manifest)
    selected = select_battles(views, args.limit_battles, args.complete_only,
                              {view["id"] for view in layout["views"]} if args.paired_only else None)
    manifest["export_selection"] = {"limit_unique_battles": args.limit_battles,
        "complete_only": args.complete_only, "paired_only": args.paired_only,
        "unique_battles": len({c["match_id"] for c in selected}), "clip_ids": [c["id"] for c in selected]}
    manifest['scan_coverage'] = {'source_seconds': media['duration_seconds'],
        'scanned_seconds': scan['duration_seconds'],
        'full_recording_scanned': scan['duration_seconds'] >= media['duration_seconds'] - .05,
        'selection_limited': args.limit_battles is not None or args.complete_only or args.paired_only,
        'partial_battles_kept': not args.complete_only,
        'boundary_sampling': fingerprint['boundary_sampling'],
        'battle_recall_independently_verified': False}
    write_json(manifest_path, manifest)
    exports = []
    retired=[]
    if args.stage == "extract":
        args.library.mkdir(parents=True, exist_ok=True)
        view_lookup = {view["id"]: view for view in layout["views"]}
        tasks = [(candidate, view_lookup[candidate["view_id"]]) for candidate in selected]
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            futures = [pool.submit(export_one, video, candidate, view, args.library.resolve(), fingerprint,
                                   source_record.get("creator") or layout["channel"], canonical, source_record,
                                   preserve_existing=not sample_mode) for candidate, view in tasks]
            for future in as_completed(futures):
                result = future.result()
                exports.append(result)
                print(json.dumps({"stage": "export", "clip": result["id"], "completed": len(exports),
                                  "total": len(tasks), "video_bytes": result["video_bytes"]}), flush=True)
        if not sample_mode:
            retired=retire_previous_full_cuts(args.library,identity,[c['id'] for c in selected])
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
    summary['scan_coverage'] = manifest['scan_coverage']
    summary['extraction_succeeded'] = bool(selected) and args.stage == 'extract' and len(exports) == len(selected)
    summary['game_state_tracking_required_for_extraction'] = False
    summary['superseded_full_cuts_retained']=retired
    summary['non_montage_game_interval_candidates']=manifest.get('non_montage_game_interval_candidates',manifest['unique_match_candidates'])
    summary['edited_excerpt_candidates']=manifest.get('edited_excerpt_candidates',0)
    write_json(run_folder / "run.json", summary)
    print(json.dumps(summary), flush=True)
    if not selected:
        raise ValueError('No battle clips were found. Check layout-review.json and the scan coverage; this is not a successful extraction.')


if __name__ == "__main__":
    main()
