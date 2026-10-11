"""Coarse keyframe discovery, then finer boundary sampling for long Twitch VODs."""
from __future__ import annotations

import bisect
import copy
import gzip
import json
from pathlib import Path
import re
import time

from vod_media import sha256, write_json

VERSION = "vod-keyframe-refine-v2"


def discover_segments(rows, source_id, duration, interval=.5):
    """Add lobby gaps and sustained party resets when shield colours are unreadable."""
    from segment_battles import propose_segments
    initial = propose_segments({"samples": rows, "duration_seconds": duration,
                                "sample_interval_seconds": interval}, source_id)
    starts = list(initial)
    last_hud, minimum_party, low_run = None, 6, 0
    result_since_hud = False
    for index, row in enumerate(rows):
        if row.get("result"):
            result_since_hud = True
        if not row["hud"]:
            continue
        total = sum(row["party"]) if row.get("party") else None
        gap = row["t"] - last_hud if last_hud is not None else 0
        nearby = [r for r in rows[index + 1:index + 4] if r["hud"]]
        reset = total == 6 and minimum_party <= 4 and any(r.get("party") == [3, 3] for r in nearby)
        kind = "hud_after_visible_result" if result_since_hud else "hud_after_lobby_gap" if gap > 25 else "sustained_party_reset" if reset else None
        if kind:
            starts.append({"start": max(0, row["t"] - 1.5), "first_hud_seconds": row["t"],
                           "cues": [{"t": row["t"], "kind": kind, "sample_index": index}],
                           "start_method": kind, "sampling_resolution_seconds": interval,
                           "start_uncertainty_seconds": max(interval, 1.5), "confidence": "medium"})
            minimum_party, low_run = 6, 0
        result_since_hud = False
        low_run = low_run + 1 if total is not None and total < minimum_party else 0
        if low_run >= 2:
            minimum_party = total
        last_hud = row["t"]
    grouped = []
    for start in sorted(starts, key=lambda c: c["first_hud_seconds"]):
        if grouped and start["first_hud_seconds"] - grouped[-1]["first_hud_seconds"] <= 8:
            preferred = grouped[-1]
            if any(cue["kind"] == "countdown" for cue in start["cues"]):
                start["cues"].extend(cue for cue in preferred["cues"] if cue not in start["cues"])
                grouped[-1] = start
            else:
                preferred["cues"].extend(cue for cue in start["cues"] if cue not in preferred["cues"])
            continue
        grouped.append(copy.deepcopy(start))
    output = []
    for index, start in enumerate(grouped):
        ceiling = grouped[index + 1]["start"] if index + 1 < len(grouped) else duration
        start["start"] = max(0, min(start["start"], start["first_hud_seconds"]))
        inside = [r for r in rows if start["first_hud_seconds"] <= r["t"] < ceiling]
        active = [r for r in inside if r["hud"]]
        results = [r for r in inside if r.get("result")]
        if not active:
            continue
        end = min(ceiling, results[0]["t"] + 2) if results else min(ceiling, active[-1]["t"] + 12)
        if end - start["start"] < 15:
            continue
        output.append({**start, "id": f"{source_id}-candidate-{len(output) + 1:03d}",
                       "source_id": source_id, "end": end,
                       "end_method": "visible_result" if results else "last_hud_plus_resolution_tail",
                       "end_uncertainty_seconds": max(interval, 2 if results else 12),
                       "completeness": "result_visible" if results else "result_unseen_or_edited",
                       "notes": ["Boundary candidate from sampled video; exact action start and completeness require review."]})
    return output


def profiles_for(layout, reader_dir, gamemaster):
    gm = json.loads(Path(gamemaster).read_text(encoding="utf-8"))
    lexicon = sorted({p["speciesName"].split(" (")[0] for p in gm["pokemon"]})
    profiles = {}
    for view in layout["views"]:
        path = Path(reader_dir) / "profiles" / view["base_profile"]
        profile = json.loads(path.read_text(encoding="utf-8"))
        profile.update(view.get("overrides", {}))
        profile["viewport"] = view["viewport"]
        profile["id"] = view["id"]
        profile["known_moves"], profile["team_moves"] = [], {}
        profile["species_lexicon"] = lexicon
        profile.pop("video_id", None)
        profiles[view["id"]] = profile
    return profiles


def sample_frame(frame, profile, ocr, *, context=True):
    import numpy as np
    from segment_battles import sample_features
    x, y, w, h = profile["viewport"]
    if x < 0 or y < 0 or x + w > frame.width or y + h > frame.height:
        raise ValueError("Calibrated viewport is outside this recording")
    rgb = np.asarray(frame.to_image().crop((x, y, x + w, y + h)).resize((508, 1080)))
    row = {"t": round(float(frame.pts * frame.time_base), 6),
           "source_pts": frame.pts, "source_time_base": str(frame.time_base),
           **sample_features(rgb, profile, ocr)}
    if context and not row["hud"] and not row["countdown"]:
        records = ocr.read(rgb[160:850])
        text = " ".join(item["text"] for item in records)
        key = re.sub(r"[^A-Z]", "", text.upper())
        row["context_text"], row["battle_starting"] = text, "BATTLESTARTING" in key
        row["result"] = next((value for cue, value in [("YOUWIN", "win"), ("GOODEFFORT", "loss"),
                                                      ("YOULOSE", "loss"), ("DRAW", "draw")] if cue in key), None)
    return row


def coarse_scan(video, profiles, cache, *, rescan=False):
    import av
    from local_ocr import LocalOCR
    video, cache = Path(video), Path(cache)
    source_hash = sha256(video)
    fingerprint = {"detector": VERSION, "source_sha256": source_hash, "profiles": profiles,
                   "frame_policy": "keyframes", "sample_interval_seconds": 0.5}
    if cache.exists() and not rescan:
        with gzip.open(cache, "rt", encoding="utf-8") as stream:
            saved = json.load(stream)
        if saved.get("fingerprint") != fingerprint:
            raise ValueError("Scan inputs changed: use --rescan")
        return saved
    ocr = LocalOCR()
    rows, last_hud, last_context = {name: [] for name in profiles}, {}, {}
    started, next_progress = time.monotonic(), 0
    with av.open(str(video)) as source:
        stream = source.streams.video[0]
        stream.codec_context.thread_count = 4
        stream.codec_context.skip_frame = "NONKEY"
        duration = source.duration / av.time_base
        for frame in source.decode(stream):
            if frame.pts is None:
                continue
            t = float(frame.pts * frame.time_base)
            for name, profile in profiles.items():
                # Intro/lobby text is not needed on every keyframe. Near battle
                # endings retain frequent context to catch short result screens.
                near_end = name in last_hud and t - last_hud[name] <= 40
                context = t - last_context.get(name, -100) >= (1.5 if near_end else 8)
                row = sample_frame(frame, profile, ocr, context=context)
                if context and "context_text" in row:
                    last_context[name] = t
                if row["hud"]:
                    last_hud[name] = t
                rows[name].append(row)
            if time.monotonic() >= next_progress:
                print(json.dumps({"stage": "coarse_scan", "vod_seconds": round(t, 1),
                                  "duration_seconds": round(duration, 1),
                                  "elapsed_seconds": round(time.monotonic() - started, 1)}), flush=True)
                next_progress = time.monotonic() + 30
    result = {"fingerprint": fingerprint, "duration_seconds": duration, "views": rows,
              "elapsed_seconds": round(time.monotonic() - started, 3)}
    temporary = cache.with_name(cache.name + ".incomplete")
    cache.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(temporary, "wt", encoding="utf-8") as output:
        json.dump(result, output, separators=(",", ":"))
    temporary.replace(cache)
    return result


def refine_scan(video, profile, rows, candidates, duration, *, interval=.25):
    """Read narrow entrance/end windows at full decode cadence; retain coarse interiors."""
    import av
    from local_ocr import LocalOCR
    windows = []
    for candidate in candidates:
        active = [row["t"] for row in rows if row["hud"] and candidate["start"] <= row["t"] < candidate["end"]]
        for t in [candidate["first_hud_seconds"], active[-1] if active else candidate["end"]]:
            start, end = max(0, t - 10), min(duration, t + 12)
            if windows and start <= windows[-1][1]:
                windows[-1][1] = max(end, windows[-1][1])
            else:
                windows.append([start, end])
    ocr, fine = LocalOCR(), []
    with av.open(str(video)) as source:
        source.streams.video[0].codec_context.thread_count = 4
        for number, (start, end) in enumerate(windows, 1):
            source.seek(int(max(0, start - 2) * av.time_base))
            last, last_context = -100, -100
            for frame in source.decode(video=0):
                if frame.pts is None:
                    continue
                t = float(frame.pts * frame.time_base)
                if t < start:
                    continue
                if t >= end:
                    break
                if t - last < interval - 1e-6:
                    continue
                last = t
                row = sample_frame(frame, profile, ocr, context=t - last_context >= .5)
                if "context_text" in row:
                    last_context = t
                fine.append(row)
            if number % 4 == 0:
                print(json.dumps({"stage": "refine", "view": profile["id"],
                                  "windows_done": number, "windows_total": len(windows)}), flush=True)
    def in_window(t):
        return any(start <= t < end for start, end in windows)
    combined = sorted([r for r in rows if not in_window(r["t"])] + fine, key=lambda row: row["t"])
    facts = {"samples": combined, "duration_seconds": duration, "sample_interval_seconds": interval}
    return combined, discover_segments(combined, profile["id"], duration, interval)


def annotate_segments(candidates, rows, source_id, view_id, duration):
    """Keep partial edges explicit and bound the clip at the first result after its HUD."""
    output = []
    for candidate in candidates:
        c = copy.deepcopy(candidate)
        c["id"] = f"tw-{source_id}-{view_id}-{len(output) + 1:03d}"
        c["source_id"], c["view_id"] = source_id, view_id
        active = [r for r in rows if c["first_hud_seconds"] <= r["t"] < c["end"] and r["hud"]]
        # Legacy segmentation uses the last result; a live VOD may sit on that
        # screen for minutes. Keep a short result tail after the first result.
        results = [r for r in rows if c["first_hud_seconds"] <= r["t"] <= c["end"] and r.get("result")]
        if results:
            c["end"] = min(duration, results[0]["t"] + 2)
            c["end_method"] = "first_visible_result_plus_two_seconds"
        elif active:
            # A new battle may be minutes away; preserve its resolution but do
            # not turn the whole intervening lobby into a battle clip.
            c["end"] = min(c["end"], active[-1]["t"] + 12, duration)
            c["end_method"] = "last_hud_plus_resolution_tail_result_unverified"
        starts_at_edge = c["first_hud_seconds"] < 6 and not any(q["kind"] == "countdown" for q in c["cues"])
        ends_at_edge = c["end"] >= duration - 1 and not results
        c["incomplete_start"], c["incomplete_end"] = starts_at_edge, ends_at_edge
        c["eligible_for_complete_battle_evaluation"] = not (starts_at_edge or ends_at_edge)
        c["completeness"] = "incomplete_start" if starts_at_edge else "incomplete_end" if ends_at_edge else c["completeness"]
        c["name"] = f"Twitch battle {len(output) + 1:02d} · {view_id}"
        c["review_required"], c["timing_validated"] = True, False
        if starts_at_edge:
            c["notes"].append("Recording starts during this battle; the missing beginning cannot be recovered.")
        if c["end"] - c["start"] >= 15:
            output.append(c)
    return output


def pair_perspectives(views, source_id):
    """Give overlapping simultaneous viewpoints one match ID, without counting twice."""
    groups = []
    for view_id, candidates in views.items():
        for candidate in candidates:
            matches = []
            for group in groups:
                representative = group[0]
                overlap = max(0, min(candidate["end"], representative["end"]) - max(candidate["start"], representative["start"]))
                shortest = min(candidate["end"] - candidate["start"], representative["end"] - representative["start"])
                if not any(item["view_id"] == view_id for item in group) and overlap / shortest >= .75 and abs(candidate["start"] - representative["start"]) <= 12:
                    matches.append((overlap / shortest, group))
            if matches:
                max(matches, key=lambda pair: pair[0])[1].append(candidate)
            else:
                groups.append([candidate])
    groups.sort(key=lambda group: min(c["start"] for c in group))
    for number, group in enumerate(groups, 1):
        for candidate in group:
            candidate["match_id"] = f"tw-{source_id}-match-{number:03d}"
    return groups
