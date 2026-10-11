"""Read broadcaster labels separately from the phone UI and reject replay clips."""
from __future__ import annotations

import copy
import gzip
import json
from pathlib import Path
import re
import time

from vod_media import sha256


def marker_scan(video, regions, cache):
    import av
    import numpy as np
    from local_ocr import LocalOCR
    cache = Path(cache)
    fingerprint = {"source_sha256": sha256(video), "regions": regions,
                   "code_sha256": sha256(__file__)}
    if cache.exists():
        with gzip.open(cache, "rt", encoding="utf-8") as source:
            found = json.load(source)
        if found.get("fingerprint") == fingerprint:
            return found["markers"]
    ocr, markers = LocalOCR(), []
    started, progress = time.monotonic(), 0
    with av.open(str(video)) as source:
        stream = source.streams.video[0]
        stream.codec_context.thread_count = 4
        stream.codec_context.skip_frame = "NONKEY"
        for frame in source.decode(stream):
            if frame.pts is None:
                continue
            rgb = frame.to_ndarray(format="rgb24")
            t = float(frame.pts * frame.time_base)
            for region in regions:
                x, y, w, h = region["rect"]
                if x < 0 or y < 0 or x + w > frame.width or y + h > frame.height:
                    raise ValueError("Broadcast label region is outside the video")
                text = " ".join(item["text"] for item in ocr.read(rgb[y:y+h, x:x+w])
                                if item["confidence"] >= .75)
                key = re.sub(r"[^A-Z]", "", text.upper())
                if region["cue"] in key:
                    markers.append({"t": round(t, 6), "kind": region["kind"], "text": text})
            if time.monotonic() >= progress:
                print(json.dumps({"stage": "broadcast_labels", "vod_seconds": round(t, 1)}), flush=True)
                progress = time.monotonic() + 30
    temporary = cache.with_name(cache.name + ".incomplete")
    cache.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(temporary, "wt", encoding="utf-8") as output:
        json.dump({"fingerprint": fingerprint, "markers": markers,
                   "elapsed_seconds": round(time.monotonic() - started, 3)}, output, separators=(",", ":"))
    temporary.replace(cache)
    return markers


def filter_broadcast(views, markers):
    """Keep live intervals, with explicit receipts for discarded replay candidates."""
    replay_times = sorted(marker["t"] for marker in markers if marker["kind"] == "replay")
    replay_runs = []
    for t in replay_times:
        if replay_runs and t - replay_runs[-1][-1] <= 5:
            replay_runs[-1].append(t)
        else:
            replay_runs.append([t])
    runs = [(run[0], run[-1]) for run in replay_runs if len(run) >= 2]
    kept, excluded = {}, []
    for view, candidates in views.items():
        kept[view] = []
        for original in candidates:
            candidate = copy.deepcopy(original)
            first_hud = candidate["first_hud_seconds"]
            # The phone headers appear during the broadcaster's entrance
            # transition, before its REPLAY badge is fully readable.
            if any(begin - 10 <= first_hud <= end + 5 for begin, end in runs):
                excluded.append({**candidate, "excluded_reason": "broadcast_replay"})
                continue
            tails = [begin for begin, end in runs if first_hud + 10 < begin < candidate["end"]]
            if tails:
                candidate["end"] = min(candidate["end"], min(tails) - .5)
                candidate["notes"].append("A labelled broadcast replay after this interval was removed.")
            results = [marker for marker in markers if marker["kind"] == "match_win"
                       and first_hud <= marker["t"] < candidate["end"]]
            if results:
                candidate["end"] = min(candidate["end"], results[0]["t"] + 2)
                candidate["end_method"] = "broadcast_match_win_plus_two_seconds"
                candidate["completeness"] = ("incomplete_start" if candidate["incomplete_start"]
                                             else "broadcast_result_visible")
                candidate["incomplete_end"] = False
                candidate["eligible_for_complete_battle_evaluation"] = not candidate["incomplete_start"]
            candidate["source_segment_kind"] = "live_candidate"
            kept[view].append(candidate)
    return kept, excluded
