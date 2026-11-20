"""Read cut public footage once, then assemble, track and publish playback data.

Videos and the screen-reader runtime stay in the local library. Compressed
observations retain source PTS, layout and code fingerprints for reproduction.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import gzip
import hashlib
import inspect
import json
import os
import re
from pathlib import Path
import subprocess
import shutil
import sys
import time

from vod import ROOT, HERE, bootstrap, reader_location
from vod_media import sha256, write_json

VERSION = "vod-state-v1"


def load_gz(path):
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def rows(path):
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def profile_for(reader, meta, output):
    base = "henry-great.json" if meta["creator"].casefold() == "homeslicehenry" else "reis-great.json"
    calibrated = meta.get('vod_intake_fingerprint', {}).get('layout', {}).get('views', [])
    view = next((v for v in calibrated if v['id'] == meta.get('view_id')), None)
    if view and view.get('base_profile'):
        base = view['base_profile']
    path = reader / "profiles" / base
    layout = json.loads(path.read_text(encoding="utf-8"))
    layout.update(id=VERSION + "-" + meta["creator"], viewport=meta["viewport"],
                  known_moves=[], team_moves={})
    # Charge templates encode the old owner's moveset. Identity must instead
    # come from current OCR; shared phase cues can be reused.
    layout["templates"] = [{**entry, "file": str((path.parent / entry["file"]).resolve())}
                           for entry in layout["templates"] if entry["kind"] == "phase"]
    write_json(output, layout)
    return output


def fingerprint(reader, profile, meta, fps, text_rate, seconds):
    names = ["battle_reader.py", "button_reader.py", "health_reader.py", "health_tracker.py",
             "scene_tracker.py", "adaptive_reader.py", "roi_ocr.py", "local_ocr.py", "build_viewer.py"]
    return {"version": VERSION, "video_sha256": meta["video_sha256"],
            "alignment_sha256": sha256(profile.parent.parent / "frame_alignment.jsonl.gz")
            if (profile.parent.parent / "frame_alignment.jsonl.gz").exists() else None,
            "profile_sha256": sha256(profile), "fps": fps, "text_rate": text_rate,
            "seconds": seconds, "reader_sha256": {n: sha256(reader / n) for n in names},
            "templates_sha256": {Path(e["file"]).name: sha256(e["file"])
                                  for e in json.loads(profile.read_text())["templates"]}}


def verify_clip_source(folder, meta):
    """A cached measurement must never bypass verification of its media."""
    folder=Path(folder).resolve()
    video=(folder/meta['video_file']).resolve()
    if not video.is_relative_to(folder):
        raise ValueError('Clip media escaped its battle folder')
    if sha256(video)!=meta['video_sha256']:
        raise ValueError('Clip bytes differ from the verified export')
    return video


def read_clip(folder, reader, *, fps=15, text_rate=3, seconds=None):
    meta = json.loads((folder / "battle.json").read_text(encoding="utf-8"))
    video=verify_clip_source(folder,meta)
    bootstrap(reader)
    from adaptive_reader import AdaptiveReader
    from vod_ocr import VodOCR
    from battle_reader import EventTracker
    from build_viewer import compact
    from buttons import measure
    import av
    import numpy as np

    raw = folder / "tracking-raw"
    raw.mkdir(exist_ok=True)
    profile = profile_for(reader, meta, raw / "profile.json")
    ident = fingerprint(reader, profile, meta, fps, text_rate, seconds)
    ident["read_code_sha256"] = hashlib.sha256((inspect.getsource(read_clip) + inspect.getsource(profile_for)
                                               + inspect.getsource(fingerprint)).encode()).hexdigest()
    ident["ocr_sha256"] = sha256(HERE / "vod_ocr.py")
    ident["alignment_sha256"] = sha256(folder / "frame_alignment.jsonl.gz")
    receipt = raw / "read.json"
    if receipt.exists() and json.loads(receipt.read_text())["fingerprint"] == ident:
        return json.loads(receipt.read_text())
    if (raw / "screen.jsonl.gz").exists():
        raise ValueError("Raw readings differ from this reader; use a new version or archive them explicitly")
    ocr = VodOCR(profile)
    reader_instance, event_reader = AdaptiveReader(profile, ocr=ocr, ocr_interval=1 / text_rate), EventTracker()
    aligned = iter(rows(folder / "frame_alignment.jsonl.gz"))
    filenames = ["screen.jsonl.gz", "readings.jsonl.gz", "text.jsonl.gz", "screen_events.jsonl.gz"]
    streams = [gzip.open(raw / (n + ".incomplete"), "wt", encoding="utf-8", compresslevel=6) for n in filenames]
    put = lambda stream, row: stream.write(json.dumps(row, separators=(",", ":"), ensure_ascii=False) + "\n")
    count, decoded, next_at = 0, 0, 0.0
    counts = Counter()
    started = progress = time.monotonic()
    try:
        with av.open(str(video)) as media:
            media.streams.video[0].codec_context.thread_count = 2
            for index, frame in enumerate(media.decode(video=0)):
                alignment = next(aligned)
                decoded += 1
                t = frame.time
                if t is None or abs(alignment["clip_seconds"] - t) > .001:
                    raise ValueError("Frame PTS differs from original source alignment")
                if seconds is not None and t >= seconds:
                    break
                if t + 1e-6 < next_at:
                    continue
                next_at += 1 / fps
                image = frame.to_image()
                ocr.at = t
                reading = reader_instance.detect(image, t, index, meta["viewport"])
                for side in ("mine", "opponent"):
                    for key in ("species", "cp"):
                        field = reading[side][key]
                        if field.get("value") is not None:
                            bounds = field.get("evidence", {}).get("bounds_normalized_frame")
                            match = next((r for r in ocr.header if r["bounds"] == bounds), None)
                            if match:
                                field["evidence"]["observed_at_seconds"] = ocr.last_header
                                if abs(t - ocr.last_header) > 1e-5:
                                    field["status"] = "stale"
                reading.update(clip_pts=frame.pts, clip_time_base=str(frame.time_base),
                               source_pts=alignment["source_pts"], source_time_base=alignment["source_time_base"],
                               source_timestamp_seconds=alignment["source_seconds"], coordinates_basis="battle_clip_frame")
                put(streams[0], reading)
                val = lambda f: f.get("value") if f.get("status") == "observed" else None
                slim = {"t": round(t, 6), "phase": val(reading["phase"]),
                        "ocr": reading["text_observation"]["fresh_this_frame"], "result": val(reading["result"])}
                for side, key in [("mine", "m"), ("opponent", "o")]:
                    s = reading[side]
                    hp = val(s["health_bar"])
                    slim[key] = {"sp": val(s["species"]), "cp": val(s["cp"]),
                                 "sh": val(s["shields_left"]), "left": val(s["pokemon_left"]),
                                 "hp": hp["fraction"] if hp else None,
                                 "seg": [[z["color"], z["pixels"]] for z in hp["segments"]] if hp else None,
                                 "w": hp["interior_width_pixels"] if hp else None}
                normalized = np.asarray(image.resize((508, 1080)))
                buttons = measure(normalized)
                slim["b"] = {k[0]: [v["fill"], int(v["present"]), int(v["ready"])] for k, v in buttons.items()}
                slim["cm"] = [next((b["move"] for b in reading["buttons"]
                                   if b["id"] == f"charge_{i}" and b.get("identity_status") == "observed"), None)
                              for i in (0, 1)]
                put(streams[1], slim)
                if slim["ocr"]:
                    text = [["middle" if r["bounds"][1] < 650 else "lower", r["text"]]
                            for r in reading["text_observation"]["records"] if r["bounds"][1] > 180]
                    put(streams[2], {"t": round(t, 6), "text": text})
                for event in event_reader.update(reading):
                    put(streams[3], {"t": t, "event": event})
                count += 1
                counts[reading["phase_estimate"].get("value") or "unknown"] += 1
                if time.monotonic() - progress > 20:
                    print(json.dumps({"battle": folder.name, "seconds": round(t, 1), "readings": count}), flush=True)
                    progress = time.monotonic()
    finally:
        for stream in streams:
            stream.close()
    if not count:
        raise ValueError("No video frames read")
    for name in filenames:
        (raw / (name + ".incomplete")).replace(raw / name)
    result = {"fingerprint": ident, "sampled_frames": count, "decoded_frames": decoded,
              "video_seconds": t, "wall_seconds": round(time.monotonic() - started, 2),
              "phase_counts": dict(counts), "coverage": "partial" if seconds else "full_clip",
              "python": sys.version.split()[0], "av": av.__version__}
    write_json(receipt, result)
    return result


def run_step(script, *args):
    done = subprocess.run([sys.executable, str(script), *map(str, args)], cwd=ROOT, env={**os.environ, "PYTHONUTF8": "1"},
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    if done.returncode not in (0, 1) or (done.returncode and "Traceback" in done.stderr):
        raise RuntimeError((done.stderr or done.stdout)[-2000:])
    return {"exit_code": done.returncode, "output": done.stdout}


def plain_rows(path):
    if not path.exists() and path.with_name(path.name + ".gz").exists():
        return list(rows(path.with_name(path.name + ".gz")))
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def augment_cp(game, raw):
    readings = list(rows(raw / "readings-refined.jsonl.gz"))
    origin = json.loads((game / "timeline.json").read_text())["clip_origin_seconds"]
    looks = plain_rows(game / "observations.jsonl")
    for look in looks:
        for prefix, side in (("my", "m"), ("foe", "o")):
            species = look.get(prefix + "_species")
            seen = [r for r in readings if r["t"] <= look["t"] + origin + 1e-6
                    and r["t"] >= look["t"] + origin - 3
                    and r[side]["sp"] == species and r[side]["cp"] is not None]
            if seen:
                look[prefix + "_cp"] = seen[-1][side]["cp"]
    (game / "observations.jsonl").write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in looks), encoding="utf-8")


def enforce_coverage(verdict, meta):
    out = {**verdict, "failed": list(verdict.get("failed", [])), "notes": list(verdict.get("notes", []))}
    if meta.get("incomplete_start"):
        out["failed"].append("coverage: clip starts mid-match; initial energy, shields and team history are unknown")
    if meta.get("incomplete_end"):
        out["failed"].append("coverage: ending is truncated")
    out.update(verdict="fail" if out["failed"] else "pass", full_game_state_verified=False,
               evaluation_kind="internal_consistency_not_accuracy", match_id=meta.get("match_id"),
               dataset_role=meta.get("boundary_candidate", {}).get("dataset_role", "unassigned"))
    return out


def switch_time_left(remaining, reading_time, state_time):
    """Switch cooldown continues through animations between model observations."""
    return round(max(0, remaining - max(0, reading_time - state_time)), 1) if remaining is not None else None


def confirmed_empty_bars(readings, rich):
    """Require a local counter drop and a continuous, matching bar outline.

    Expanded searches also find battlefield lines during animations. Neither
    a zero candidate nor a result screen is independent faint evidence.
    """
    from public_transitions import counter_changes
    intervals = [b['t'] - a['t'] for a, b in zip(readings, readings[1:]) if b['t'] > a['t']]
    if not intervals:
        return set()
    step = sorted(intervals)[len(intervals) // 2]
    detailed = {round(r['timestamp_seconds'], 6): r for r in rich}
    accepted = set()
    for key, side in (('m', 'mine'), ('o', 'opponent')):
        changes = counter_changes(readings, key, 'left', 1 / step)
        drops = [after for before, after in zip(changes, changes[1:])
                 if after['value'] == before['value'] - 1]
        for index, row in enumerate(readings):
            value = row[key]
            if value.get('hp') != 0 or value.get('seg') != [] or not value.get('w'):
                continue
            if not any(row['t'] - .75 <= c['first'] <= row['t'] + 2 for c in drops):
                continue
            current = detailed.get(round(row['t'], 6), {}).get(side, {}).get('health_bar', {}).get('value')
            bounds = current.get('bounds_px') if current else None
            if not bounds or index == 0:
                continue
            # Do not bridge a missing sample or a camera cut to a different bar.
            previous = readings[index - 1]
            bar = detailed.get(round(previous['t'], 6), {}).get(side, {}).get('health_bar', {}).get('value')
            old_bounds = bar.get('bounds_px') if bar else None
            if (row['t'] - previous['t'] <= 1.6 * step and previous[key].get('hp') is not None
                    and 0 < previous[key]['hp'] <= .15 and old_bounds
                    and all(abs(a - b) <= 6 for a, b in zip(bounds, old_bounds))):
                accepted.add((round(row['t'], 6), key))
    return accepted


def creator_readings(raw):
    """Adapt measured empty bars and explicit result text; retain source logs.

    Only independently corroborated zero bars survive as zero-length segments.
    A result or a surrender dialog never manufactures a knockout.
    """
    readings = list(rows(raw / 'readings-refined.jsonl.gz'))
    rich_path = raw / 'screen-refined.jsonl.gz'
    confirmed = confirmed_empty_bars(readings, list(rows(rich_path))) if rich_path.exists() else set()
    zero, rejected_zero, results, surrenders = [], [], [], []
    by_time = {round(r['t'], 6): r for r in readings}
    for r in readings:
        for side in ('m', 'o'):
            value = r[side]
            if value.get('hp') == 0 and value.get('seg') == [] and (value.get('w') or 0) > 0:
                item = {'t': r['t'], 'side': side}
                if (round(r['t'], 6), side) in confirmed:
                    value['seg'] = [['cyan', 0]]
                    zero.append(item)
                else:
                    rejected_zero.append(item)
    for record in rows(raw / 'text.jsonl.gz'):
        text = ' '.join(part for _, part in record['text'])
        if re.search(r'\bsurrender\s+and\s+exit\b', text, re.I):
            surrenders.append(record['t'])
        matched = [value for expression, value in ((r'\byou\W*win\b', 'win'),
                    (r'\bgood\W*effort\b', 'loss')) if re.search(expression, text, re.I)]
        if record['t'] < 20 or len(matched) != 1:
            continue
        reading = by_time.get(round(record['t'], 6))
        if reading is not None and reading.get('result') in (None, matched[0]):
            reading['result'] = matched[0]
            results.append({'t': record['t'], 'value': matched[0], 'method': 'explicit_result_words'})
    target = raw / 'readings-creator.jsonl.gz'
    data = ''.join(json.dumps(r, separators=(',', ':')) + '\n' for r in readings).encode()
    target.write_bytes(gzip.compress(data, mtime=0))
    audit = {'schema': 2, 'source_sha256': sha256(raw / 'readings-refined.jsonl.gz'),
             'text_sha256': sha256(raw / 'text.jsonl.gz'), 'derived_sha256': sha256(target),
             'rich_sha256': sha256(rich_path) if rich_path.exists() else None,
             'empty_bar_measurements_preserved': zero,
             'uncorroborated_empty_bars_ignored': rejected_zero, 'result_evidence': results,
             'surrender_dialog_seconds': surrenders, 'knockouts_inferred_from_result': 0,
             'surrender_dialog_confirms_exit': False,
             'raw_readings_unchanged': True}
    write_json(raw / 'creator-evidence.json', audit)
    return target, audit


def retain_counter_looks(game, readings_path):
    """Keep observed counter changes even when no health/move was visible."""
    from public_transitions import counter_changes
    readings = list(rows(readings_path))
    timeline = json.loads((game / 'timeline.json').read_text(encoding='utf-8'))
    origin = timeline['clip_origin_seconds']
    looks = plain_rows(game / 'observations.jsonl')
    if len(readings) < 2:
        return
    intervals = sorted(b['t'] - a['t'] for a, b in zip(readings, readings[1:]) if b['t'] > a['t'])
    fps = 1 / intervals[len(intervals) // 2]
    by_time = {round(look['t'], 6): look for look in looks}
    additions = []
    for key, prefix in (('m', 'my'), ('o', 'foe')):
        changes = counter_changes(readings, key, 'left', fps)
        for change in changes[1:]:
            at = round(change['t'] - origin, 6)
            if at < 0 or at > timeline['end']:
                continue
            look = by_time.setdefault(at, {'t': at})
            field = prefix + '_left'
            look[field] = min(look.get(field, 3), change['value'])
            additions.append({'t': at, 'side': key, 'value': change['value'],
                              'first_visible': change['first'], 'confirmed': change['t']})
    # Counters cannot revive a fainted team member on a later sparse look.
    minimum = {}
    ordered = sorted(by_time.values(), key=lambda row: row['t'])
    for look in ordered:
        for field in ('my_left', 'foe_left'):
            if look.get(field) is not None:
                minimum[field] = min(minimum.get(field, 3), look[field])
                look[field] = minimum[field]
    (game / 'observations.jsonl').write_text(''.join(json.dumps(r, separators=(',', ':')) + '\n'
                                                   for r in ordered), encoding='utf-8')
    write_json(game / 'counter-evidence.json', {'schema': 1, 'observed_changes': additions,
                                              'result_based_faints': 0})


def publish(folder, game, verdict, reader):
    bootstrap(reader)
    from build_viewer import compact
    from run_video_pipeline import archive_analysis
    from public_state import PublicState
    meta = json.loads((folder / "battle.json").read_text(encoding="utf-8"))
    raw = folder / "tracking-raw"
    receipt = json.loads((raw / "read.json").read_text())
    target = folder / "viewer-data.json.gz"
    previous = load_gz(target)
    timeline = json.loads((game / "timeline.json").read_text()) if (game / "timeline.json").exists() else {}
    origin = timeline.get("clip_origin_seconds", 0)
    states = [{"t": round(origin + s["t"], 6), "state": s} for s in plain_rows(game / "states.jsonl")] if (game / "states.jsonl").exists() else []
    observations = [{"t": round(origin + s["t"], 6), "look": s} for s in plain_rows(game / "observations.jsonl")] if (game / "observations.jsonl").exists() else []
    events = [{"t": round(origin + s["t"], 6), "event": s} for s in plain_rows(game / "events.jsonl")] if (game / "events.jsonl").exists() else []
    gm = json.loads((ROOT / "data/gamemaster.json").read_text(encoding="utf-8"))
    move_names={m['moveId']:m['name'] for m in gm['moves']}
    legal_moves={}
    from visible_vocabulary import display_species
    for pokemon in gm['pokemon']:
        species_name=pokemon['speciesName']
        if display_species(species_name)==species_name:
            species_name=species_name.split(' (')[0]
        legal_moves.setdefault(species_name,set()).update(
            name for mid in pokemon['chargedMoves']+pokemon.get('extraChargedMoves',[]) if mid in move_names
            for name in [move_names[mid],move_names[mid].split(' (')[0]])
    ledger = PublicState({m["name"]: m["energy"] for m in gm["moves"] if m["energy"] > 0},
                         incomplete_start=meta.get("incomplete_start", False),legal_moves=legal_moves,
                         extra_moves={m['name'] for m in gm['moves'] if m.get('isMegaMove')},
                         form_events=json.loads((game/'creator-forms.json').read_text(encoding='utf8'))['events']
                             if (game/'creator-forms.json').exists() else (),
                         stage_reset_events=json.loads((game/'creator-stage-resets.json').read_text(encoding='utf8'))['events']
                             if (game/'creator-stage-resets.json').exists() else (),
                         stat_notice_events=json.loads((game/'creator-stat-notices.json').read_text(encoding='utf8'))['events']
                             if (game/'creator-stat-notices.json').exists() else ())
    display, statuses = [], Counter()
    at = 0
    if (game/'creator-measurements.json').exists():
        from creator_frames import measured_frames
        source_frames = measured_frames(raw, timeline,
            json.loads((game/'creator-lifecycle.json').read_text(encoding='utf-8')))
    else:
        source_frames = zip(rows(raw / "screen-refined.jsonl.gz"), rows(raw / "readings-refined.jsonl.gz"), strict=True)
    for raw_frame, slim in source_frames:
        if abs(raw_frame["timestamp_seconds"] - slim["t"]) > .00001:
            raise ValueError("Rich and compact frame logs differ in time")
        frame = compact(raw_frame)
        if raw_frame.get('native_source'):
            frame['native_source'] = raw_frame['native_source']
        frame["game_state"] = ledger.update(raw_frame, slim)
        while at + 1 < len(states) and states[at + 1]["t"] <= frame["t"]:
            at += 1
        model = states[at] if states and states[at]["t"] <= frame["t"] <= states[-1]["t"] else None
        for side, model_side in (("mine", "me"), ("opponent", "opponent")):
            visible = frame[side]
            public_side = frame["game_state"]["sides"][side]
            public_mon = public_side["pokemon"].get(public_side["active"])
            if model:
                team = model["state"][model_side]
                active = team["pokemon"][team["active"]] if team["active"] is not None and team["active"] < len(team["pokemon"]) else None
                # Inferred energy belongs to this active identity only. Never
                # label a model's default IV-derived HP or moves as observed.
                if (not (game/'creator-measurements.json').exists() and active
                        and visible["species"].get("value") == active["name"] and not meta.get("incomplete_start")):
                    known = active["fast_move"]["known_from"]
                    visible["energy"] = {"value": active["energy"], "status": "inferred",
                        "range": active.get("energy_range"),
                        "evidence": {"method": "tracker_rules_and_button_fill", "fast_move_source": known,
                                     "tracker_clip_seconds": model["t"], "accuracy_verified": False}}
                identity_matches = active and (visible["species"].get("value") == active["name"] or
                    (public_mon and public_side["active_status"] == "retained" and public_mon["species"]["value"] == active["name"]))
                if identity_matches:
                    visible["model"] = {"fast_move": active["fast_move"], "charged_moves": active["charged_moves"],
                        "energy": active['energy'], "energy_range": active.get('energy_range'),
                        "attack_stage": active["attack_stage"], "defense_stage": active["defense_stage"],
                        "switch_ready_in": switch_time_left(team.get("switch_ready_in"), frame["t"], model["t"]), "status": "inferred",
                        "stats_assumed": active["stats_assumed"], "accuracy_verified": False}
                    visible["model"]["switch_timer_rule"] = "elapsed_video_time_including_charged_animations"
            if public_mon and public_mon["energy"].get("status") == "estimated":
                interval = public_mon["energy"]["value"]
                visible["energy"] = {"value": interval[0] if interval[0] == interval[1] else None,
                    "range": interval, "status": "estimated", "evidence": public_mon["energy"]}
            elif (game/'creator-measurements.json').exists():
                value = public_mon['energy'] if public_mon else {'value': None, 'status': 'unknown', 'reason': 'No confirmed active identity'}
                interval = value.get('value')
                visible['energy'] = {'value': None, 'range': interval,
                    'status': value['status'], 'evidence': value}
            for key in ("species", "cp", "health_bar", "shields_left", "pokemon_left", "energy"):
                statuses[f"{side}.{key}.{visible[key]['status']}"] += 1
        display.append(frame)
    bookmarks = previous.get("bookmarks", []) or [{"t": max(0, origin + c["t"]),
                "name": ("Our " if c["side"] == "mine" else "Opponent ") + (c["move"] or "charged attack")}
                for c in timeline.get("charged", [])]
    provenance = {**receipt["fingerprint"], "coverage": receipt["coverage"], "sample_interval_seconds": 1/receipt["fingerprint"]["fps"],
                  "every_decoded_frame": False, "source_start_seconds": meta["source_start_seconds"],
                  "native_health_sample_hz": 12 if (game/'creator-measurements.json').exists() else None,
                  "maximum_hp_supplied": False, "causal_screen_readings": True,
                  "tracker_timeline": "offline_reconstruction_with_assumptions",
                  "processing_sha256": {name: sha256(ROOT / name) for name in
                    ("scripts/recording/assemble.py", "scripts/recording/public_transitions.py", "scripts/recording/vod_track.py", "scripts/recording/public_state.py",
                     "scripts/recording/state_continuity.py", "scripts/recording/vod_markers.py", "scripts/recording/public_fast.py", "scripts/recording/vod_pairs.py",
                     "scripts/recording/buttons.py", "scripts/recording/verdict.py", "data/vod_tracking_layouts.json",
                     "scripts/track.py", "pogo/tracker.py", "data/gamemaster.json",
                     "scripts/recording/creator_health.py", "scripts/recording/creator_observations.py",
                     "scripts/recording/creator_frames.py", "scripts/recording/native_health.py",
                     "scripts/recording/visible_vocabulary.py",
                     "scripts/recording/creator_model.py",
                     "scripts/recording/native_controls.py", "scripts/recording/creator_controls.py",
                     "scripts/recording/creator_energy.py", "scripts/recording/creator_native_faints.py",
                     "scripts/recording/creator_identity.py", "scripts/recording/creator_faint_support.py",
                     "scripts/recording/creator_event_ledger.py", "scripts/recording/creator_move_labels.py", "scripts/recording/creator_forms.py",
                     "scripts/recording/creator_form_captions.py",
                     "scripts/recording/creator_stage_resets.py",
                     "scripts/recording/creator_stat_notices.py",
                     "scripts/recording/creator_charge_evidence.py", "scripts/recording/creator_announcements.py")}}
    if (game/'creator-measurements.json').exists():
        provenance['ocr_context_sample_interval_seconds'] = provenance['sample_interval_seconds']
        provenance['sample_interval_seconds'] = 1/12
    data = {**previous, "readings": display, "states": states, "observations": observations, "events": events,
            "screen_events": list(rows(raw / "screen_events.jsonl.gz")), "origin": origin,
            "bookmarks": bookmarks, "tracking_verdict": verdict, "prediction_provenance": provenance}
    ledger_path = game / "continuity.jsonl.gz"
    with gzip.GzipFile(filename=str(ledger_path), mode="wb", mtime=0) as stream:
        for row in display:
            stream.write((json.dumps({"t": row["t"], "game_state": row["game_state"],
                                     **({'native_source': row['native_source']} if row.get('native_source') else {})},
                                    separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8"))
    temporary = target.with_name("viewer-data.incomplete.json.gz")
    temporary.write_bytes(gzip.compress(json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8"), compresslevel=6, mtime=0))
    if sha256(temporary) != sha256(target):
        archive_analysis(folder)
        temporary.replace(target)
    else:
        temporary.unlink()
    summary = {"id": folder.name, "sampled_frames": len(display), "coverage": receipt["coverage"],
               "tracking_verdict": verdict, "field_status_counts": dict(statuses), "full_game_state_verified": False,
               "model_states": len(states), "raw_data_bytes": sum(p.stat().st_size for p in raw.iterdir() if p.is_file()),
               "provenance": provenance}
    write_json(folder / "analysis-summary.json", summary)
    meta.update(analysis_status="analyzed_with_unknowns" if receipt["coverage"] == "full_clip" else "partial",
                tracking_consistency=verdict["verdict"], full_game_state_verified=False,
                reading_interval_seconds=1/receipt["fingerprint"]["fps"])
    meta["analysis_archive_bytes"] = sum(p.stat().st_size for p in (folder / "analysis-archive").rglob("*") if p.is_file())
    meta["saved_data_bytes"] = sum(p.stat().st_size for p in folder.rglob("*") if p.is_file() and p.name != meta["video_file"])
    write_json(folder / "battle.json", meta)
    return summary


def without_raw_text(value):
    """Creator exports contain typed observations, never unrestricted OCR prose."""
    if isinstance(value, dict):
        return {k: without_raw_text(v) for k, v in value.items()
                if k not in {'raw_text', 'text', 'text_observation', 'trainer', 'trainer_name', 'nickname'}}
    if isinstance(value, list):
        return [without_raw_text(v) for v in value]
    return value


def creator_export(folder, game, meta, root):
    """Keep the creator's canonical source-N folder separate from old Twitch views."""
    ordinal = re.search(r'match-(\d+(?:-r[0-9a-f]{8})?)$', meta['match_id'])
    if not ordinal:
        raise ValueError('Creator match requires a numeric battle ordinal')
    number = ordinal.group(1)
    name = meta['reference_id'] + '-' + number
    if meta.get('view_id') != 'pov':
        name += '-' + meta['view_id']
    exported = Path(root) / name
    exported.mkdir(parents=True, exist_ok=True)
    allowed = ['team.json', 'observations.jsonl', 'states.jsonl', 'events.jsonl', 'source-events.jsonl', 'continuity.jsonl', 'creator-evidence.json', 'counter-evidence.json', 'terminal-impact.json', 'creator-lifecycle.json', 'creator-state-reconciliation.json', 'creator-measurements.json',
               'state.json', 'track.json', 'timeline.json', 'verdict.json', 'model-support.json', 'creator-forms.json', 'creator-stage-resets.json', 'creator-stat-notices.json']
    for name in allowed:
        path = game / name
        packed = path.with_name(name + '.gz')
        if not path.exists() and not packed.exists():
            continue
        if name.endswith('.jsonl'):
            values = plain_rows(path)
            data = ''.join(json.dumps(without_raw_text(v), separators=(',', ':'))+'\n' for v in values).encode()
            (exported / (name + '.gz')).write_bytes(gzip.compress(data, mtime=0))
        else:
            value = load_gz(packed) if not path.exists() else json.loads(path.read_text(encoding='utf-8'))
            write_json(exported / name, without_raw_text(value))
    source = {k: meta.get(k) for k in ('id', 'match_id', 'view_id', 'source_url', 'source_sha256',
              'video_sha256', 'source_start_seconds', 'source_end_seconds', 'source_viewport',
              'incomplete_start', 'incomplete_end')}
    source.update(channel=Path(root).name, dataset_role='creator_footage',
                  privacy={'unrestricted_ocr_text_exported':False, 'video_or_frames_exported':False},
                  observations_accuracy_verified=False)
    write_json(exported / 'source.json', source)
    return exported


def track_clip(folder, reader, *, creator_root=None):
    sys.path.insert(0, str(ROOT))
    from pogo.gamedata import GameData
    from verdict import verdict as decide
    from public_fast import prepare_team
    from vod_markers import refine
    from vod_pairs import reconcile
    meta = json.loads((folder / "battle.json").read_text(encoding="utf-8"))
    raw, game = folder / "tracking-raw", folder / "tracker"
    game.mkdir(exist_ok=True)
    try:
        verify_clip_source(folder,meta)
        bootstrap(reader)
        refine(folder, raw, rows)
        evidence_path, evidence = creator_readings(raw) if creator_root is not None else (raw / 'readings-refined.jsonl.gz', None)
        measurements = None
        text_path=raw/'text.jsonl.gz'
        if evidence is not None:
            from creator_identity import acquire_identities, enrich_readings
            acquire_identities(folder, raw)
            evidence_path = enrich_readings(evidence_path, raw)
            from native_controls import acquire_controls
            acquire_controls(folder, raw)
            from creator_move_labels import acquire_labels
            acquire_labels(folder, raw)
            phase_folder = game / 'source-phase'
            phase_folder.mkdir(exist_ok=True)
            run_step(HERE / "assemble.py", evidence_path, raw / "text.jsonl.gz", phase_folder,
                     "--public-footage", "--single-clip")
            if not (phase_folder/'timeline.json').exists():
                raise ValueError('Source phase extraction failed before native health refinement')
            from creator_announcements import acquire_releases
            text_path=acquire_releases(folder,raw,json.loads((phase_folder/'timeline.json').read_text(encoding='utf8')))
            if text_path!=raw/'text.jsonl.gz':
                run_step(HERE/'assemble.py',evidence_path,text_path,phase_folder,'--public-footage','--single-clip')
            from creator_health import derive
            evidence_path, measurements = derive(folder, raw, evidence_path,
                json.loads((phase_folder/'timeline.json').read_text(encoding='utf-8')))
            write_json(game/'creator-measurements.json', measurements)
        assembled = run_step(HERE / "assemble.py", evidence_path, text_path, game,
                             "--public-footage", "--single-clip")
        (game / "assembly.log").write_text(assembled["output"], encoding="utf-8")
        if not (game / "team.json").exists():
            raise ValueError(assembled["output"])
        augment_cp(game, raw)
        if evidence is not None:
            retain_counter_looks(game, evidence_path)
            write_json(game / 'creator-evidence.json', evidence)
            from creator_impact import apply_impact
            terminal = apply_impact(folder, raw, game)
            from creator_lifecycle import apply_lifecycle
            apply_lifecycle(folder, raw, game, GameData())
            from creator_native_faints import apply_native_faints
            apply_native_faints(game, raw)
        paired = reconcile(folder, game)
        prepare_team(game, GameData())
        if evidence is not None:
            from creator_state import reconcile_creator_state
            reconcile_creator_state(game, raw)
            if measurements is not None:
                from creator_observations import reconcile_source_shields
                observed_looks = plain_rows(game/'observations.jsonl')
                shield_evidence = reconcile_source_shields(observed_looks,
                    json.loads((game/'timeline.json').read_text(encoding='utf-8')), measurements['counters'])
                (game/'observations.jsonl').write_bytes(''.join(json.dumps(r)+'\n' for r in observed_looks).encode('utf-8'))
                measurements['shield_reconciliation'] = shield_evidence
                write_json(game/'creator-measurements.json', measurements)
                from creator_state import update_output_digest
                update_output_digest(game)
        availability = None
        if evidence is not None:
            from creator_model import support
            availability = support(json.loads((game/'timeline.json').read_text(encoding='utf8')),
                json.loads((game/'team.json').read_text(encoding='utf8')), GameData())
            write_json(game/'model-support.json', availability)
        if availability and availability['status'] == 'unavailable':
            from creator_model import unavailable
            result = unavailable(game, availability)
        else:
            tracked = run_step(ROOT / "scripts/track.py", game)
            (game / "track.log").write_text(tracked["output"], encoding="utf-8")
            if evidence is not None:
                from creator_impact import record_faint
                record_faint(game, terminal)
            result = decide(game, GameData())
            blind = game / "blind"
            blind.mkdir(exist_ok=True)
            for name in ("team.json", "observations.jsonl"):
                shutil.copyfile(game / name, blind / name)
            run_step(ROOT / "scripts/track.py", blind, "--blind")
            result["blind_energy_check"] = json.loads((blind / "track.json").read_text())
        if evidence is not None:
            from creator_event_ledger import source_events
            observable = source_events(json.loads((game/'timeline.json').read_text(encoding='utf8')),
                json.loads((game/'creator-lifecycle.json').read_text(encoding='utf8')), measurements or {})
            from creator_forms import derive as derive_forms
            forms = derive_forms(raw, json.loads((game/'timeline.json').read_text(encoding='utf8')), observable)
            write_json(game/'creator-forms.json', forms)
            from creator_stat_notices import derive as derive_stat_notices
            notices = derive_stat_notices(raw)
            write_json(game/'creator-stat-notices.json',notices)
            from creator_stage_resets import derive as derive_resets
            resets = derive_resets(raw,json.loads((game/'timeline.json').read_text(encoding='utf8')),observable+notices['events']+forms['events'])
            write_json(game/'creator-stage-resets.json',resets)
            observable = sorted(observable+forms['events']+resets['events']+notices['events'], key=lambda e: (e['t'], e['kind'], str(e.get('side'))))
            (game/'source-events.jsonl').write_bytes(''.join(json.dumps(r,separators=(',',':'))+'\n' for r in observable).encode('utf8'))
        result["paired_move_names_recovered"] = len(paired)
        verify_clip_source(folder,meta)
    except Exception as error:
        if creator_root is not None:
            # Keep the previous complete export intact on a diagnostic failure.
            # Publishing old states with a new error verdict creates a mixed run.
            write_json(game / 'tracking-error.json', {'game': folder.name,
                       'error_type': type(error).__name__, 'message': str(error),
                       'creator_export_updated': False})
            raise RuntimeError(f'{folder.name}: creator replay failed; previous export retained') from error
        result = {"game": folder.name, "verdict": "fail", "failed": [str(error)], "notes": []}
    result = enforce_coverage(result, meta)
    result["game"] = folder.name
    receipt = json.loads((raw / "read.json").read_text())
    if receipt["coverage"] != "full_clip":
        result["verdict"] = "fail"
        result["failed"].append("coverage: only part of the saved clip was analyzed")
    write_json(game / "verdict.json", result)
    summary = publish(folder, game, result, reader)
    if creator_root is not None:
        exported = creator_export(folder, game, meta, creator_root)
        summary['creator_game_folder'] = exported.relative_to(ROOT).as_posix()
        for directory in (game, game / 'blind'):
            for path in directory.glob('*.jsonl'):
                data = path.read_bytes()
                packed = path.with_name(path.name + '.gz')
                packed.write_bytes(gzip.compress(data, mtime=0))
                if gzip.decompress(packed.read_bytes()) != data:
                    raise ValueError('Compressed creator log differs from input')
                path.unlink()
        return summary
    # Repository exports compress repetitive state logs. Local media and raw
    # OCR stay outside Git; only gzip observations and the reproducible result
    # are copied here, never the video or a runtime installation.
    exported = ROOT / "games/twitch" / folder.name
    exported.mkdir(parents=True, exist_ok=True)
    for p in game.iterdir():
        if not p.is_file() or (p.suffix not in (".json", ".jsonl") and p.name != "continuity.jsonl.gz"):
            continue
        if p.suffix == ".jsonl":
            (exported / (p.name + ".gz")).write_bytes(gzip.compress(p.read_bytes(), mtime=0))
        else:
            shutil.copyfile(p, exported / p.name)
    (exported / "raw").mkdir(exist_ok=True)
    for name in ("readings.jsonl.gz", "readings-refined.jsonl.gz", "text.jsonl.gz", "markers.json"):
        shutil.copyfile(raw / name, exported / "raw" / name)
    write_json(exported / "raw/read.json", json.loads((raw / "read.json").read_text()))
    write_json(exported / "source.json", {k: meta.get(k) for k in
        ("id", "match_id", "view_id", "source_url", "source_sha256", "video_sha256", "source_start_seconds",
         "source_end_seconds", "source_viewport", "incomplete_start", "incomplete_end")})
    for directory in (game, game / "blind"):
        for path in directory.glob("*.jsonl"):
            packed = path.with_name(path.name + ".gz")
            packed.write_bytes(gzip.compress(path.read_bytes(), mtime=0))
            if gzip.decompress(packed.read_bytes()) != path.read_bytes():
                raise ValueError("Compressed state log differs from its input")
            path.unlink()
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reader-dir", type=Path)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--only", action="append")
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--fps", type=float, default=15)
    parser.add_argument("--text-rate", type=float, default=3)
    parser.add_argument("--seconds", type=float)
    parser.add_argument("--stage", choices=("read", "track"), default="track")
    parser.add_argument('--creator', choices=('reis2occasion', 'homeslicehenry', 'itsaxn'))
    args = parser.parse_args()
    if args.jobs < 1 or args.jobs > 4 or args.fps <= 0 or args.text_rate <= 0:
        parser.error("Use 1â€“4 workers and positive sampling rates")
    reader = reader_location(args.reader_dir)
    creator_root = ROOT / 'games/creators' / args.creator if args.creator else None
    folders = sorted(p.parent for p in args.library.glob("*/battle.json")
                     if not args.only or p.parent.name in args.only)
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        def one(folder):
            read = read_clip(folder, reader, fps=args.fps, text_rate=args.text_rate, seconds=args.seconds)
            return track_clip(folder, reader, creator_root=creator_root) if args.stage == "track" else read
        pending = {pool.submit(one, f): f for f in folders}
        report = []
        for task in as_completed(pending):
            result = task.result()
            report.append(result)
            print(json.dumps({"id": pending[task].name, "readings": result.get("sampled_frames"),
                              "states": result.get("model_states"), "verdict": result.get("tracking_verdict", {})}), flush=True)
        if args.stage == "track":
            paired = [f for f in folders if json.loads((f / "battle.json").read_text())["view_id"] in ("left", "right")]
            second = {pool.submit(track_clip, f, reader, creator_root=creator_root): f for f in paired}
            revised = {}
            for task in as_completed(second):
                result = task.result()
                revised[result["id"]] = result
                print(json.dumps({"paired": result["id"], "verdict": result["tracking_verdict"]["verdict"],
                                  "recovered_move_names": result["tracking_verdict"].get("paired_move_names_recovered", 0)}), flush=True)
            report = [revised.get(r["id"], r) for r in report]
    if args.stage == "track":
        path = creator_root / 'report.json' if creator_root else ROOT / "games/twitch/report.json"
        kept = json.loads(path.read_text()) if path.exists() else []
        kept = [r for r in kept if r["id"] not in {r["id"] for r in report}]
        write_json(path, sorted(kept + report, key=lambda r: r["id"]))


if __name__ == "__main__":
    main()
