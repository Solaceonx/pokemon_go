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
    base = "henry-great.json" if meta["creator"] == "homeslicehenry" else "reis-great.json"
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


def read_clip(folder, reader, *, fps=15, text_rate=3, seconds=None):
    bootstrap(reader)
    from adaptive_reader import AdaptiveReader
    from vod_ocr import VodOCR
    from battle_reader import EventTracker
    from build_viewer import compact
    from buttons import measure
    import av
    import numpy as np

    meta = json.loads((folder / "battle.json").read_text(encoding="utf-8"))
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
    video = folder / meta["video_file"]
    if sha256(video) != meta["video_sha256"]:
        raise ValueError("Clip bytes differ from the verified export")
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
    ledger = PublicState({m["name"]: m["energy"] for m in gm["moves"] if m["energy"] > 0},
                         incomplete_start=meta.get("incomplete_start", False))
    display, statuses = [], Counter()
    at = 0
    for raw_frame, slim in zip(rows(raw / "screen-refined.jsonl.gz"), rows(raw / "readings-refined.jsonl.gz"), strict=True):
        if abs(raw_frame["timestamp_seconds"] - slim["t"]) > .00001:
            raise ValueError("Rich and compact frame logs differ in time")
        frame = compact(raw_frame)
        frame["game_state"] = ledger.update(raw_frame, slim)
        while at + 1 < len(states) and states[at + 1]["t"] <= frame["t"]:
            at += 1
        model = states[at] if states and states[at]["t"] <= frame["t"] <= states[-1]["t"] else None
        for side, model_side in (("mine", "me"), ("opponent", "opponent")):
            visible = frame[side]
            if model:
                team = model["state"][model_side]
                active = team["pokemon"][team["active"]] if team["active"] is not None and team["active"] < len(team["pokemon"]) else None
                # Inferred energy belongs to this active identity only. Never
                # label a model's default IV-derived HP or moves as observed.
                if active and visible["species"].get("value") == active["name"] and not meta.get("incomplete_start"):
                    known = active["fast_move"]["known_from"]
                    visible["energy"] = {"value": active["energy"], "status": "inferred",
                        "range": active.get("energy_range"),
                        "evidence": {"method": "tracker_rules_and_button_fill", "fast_move_source": known,
                                     "tracker_clip_seconds": model["t"], "accuracy_verified": False}}
                if active and visible["species"].get("value") == active["name"]:
                    visible["model"] = {"fast_move": active["fast_move"], "charged_moves": active["charged_moves"],
                        "attack_stage": active["attack_stage"], "defense_stage": active["defense_stage"],
                        "switch_ready_in": team.get("switch_ready_in"), "status": "inferred",
                        "stats_assumed": active["stats_assumed"], "accuracy_verified": False}
            public_side = frame["game_state"]["sides"][side]
            public_mon = public_side["pokemon"].get(public_side["active"])
            if public_mon and public_mon["energy"].get("status") == "estimated":
                interval = public_mon["energy"]["value"]
                visible["energy"] = {"value": interval[0] if interval[0] == interval[1] else None,
                    "range": interval, "status": "estimated", "evidence": public_mon["energy"]}
            for key in ("species", "cp", "health_bar", "shields_left", "pokemon_left", "energy"):
                statuses[f"{side}.{key}.{visible[key]['status']}"] += 1
        display.append(frame)
    bookmarks = previous.get("bookmarks", []) or [{"t": max(0, origin + c["t"]),
                "name": ("Our " if c["side"] == "mine" else "Opponent ") + (c["move"] or "charged attack")}
                for c in timeline.get("charged", [])]
    provenance = {**receipt["fingerprint"], "coverage": receipt["coverage"], "sample_interval_seconds": 1/receipt["fingerprint"]["fps"],
                  "every_decoded_frame": False, "source_start_seconds": meta["source_start_seconds"],
                  "maximum_hp_supplied": False, "causal_screen_readings": True,
                  "tracker_timeline": "offline_reconstruction_with_assumptions",
                  "processing_sha256": {name: sha256(ROOT / name) for name in
                    ("scripts/recording/assemble.py", "scripts/recording/vod_track.py", "scripts/recording/public_state.py",
                     "scripts/recording/vod_markers.py", "scripts/recording/public_fast.py", "scripts/recording/vod_pairs.py",
                     "scripts/recording/buttons.py", "scripts/recording/verdict.py", "data/vod_tracking_layouts.json",
                     "scripts/track.py", "pogo/tracker.py", "data/gamemaster.json")}}
    data = {**previous, "readings": display, "states": states, "observations": observations, "events": events,
            "screen_events": list(rows(raw / "screen_events.jsonl.gz")), "origin": origin,
            "bookmarks": bookmarks, "tracking_verdict": verdict, "prediction_provenance": provenance}
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


def track_clip(folder, reader):
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
        refine(folder, raw, rows)
        assembled = run_step(HERE / "assemble.py", raw / "readings-refined.jsonl.gz", raw / "text.jsonl.gz", game,
                             "--public-footage", "--single-clip")
        (game / "assembly.log").write_text(assembled["output"], encoding="utf-8")
        if not (game / "team.json").exists():
            raise ValueError(assembled["output"])
        augment_cp(game, raw)
        paired = reconcile(folder, game)
        prepare_team(game, GameData())
        tracked = run_step(ROOT / "scripts/track.py", game)
        (game / "track.log").write_text(tracked["output"], encoding="utf-8")
        result = decide(game, GameData())
        result["paired_move_names_recovered"] = len(paired)
        blind = game / "blind"
        blind.mkdir(exist_ok=True)
        for name in ("team.json", "observations.jsonl"):
            shutil.copyfile(game / name, blind / name)
        run_step(ROOT / "scripts/track.py", blind, "--blind")
        result["blind_energy_check"] = json.loads((blind / "track.json").read_text())
    except Exception as error:
        result = {"game": folder.name, "verdict": "fail", "failed": [str(error)], "notes": []}
    result = enforce_coverage(result, meta)
    result["game"] = folder.name
    receipt = json.loads((raw / "read.json").read_text())
    if receipt["coverage"] != "full_clip":
        result["verdict"] = "fail"
        result["failed"].append("coverage: only part of the saved clip was analyzed")
    write_json(game / "verdict.json", result)
    summary = publish(folder, game, result, reader)
    # Repository exports compress repetitive state logs. Local media and raw
    # OCR stay outside Git; only gzip observations and the reproducible result
    # are copied here, never the video or a runtime installation.
    exported = ROOT / "games/twitch" / folder.name
    exported.mkdir(parents=True, exist_ok=True)
    for p in game.iterdir():
        if not p.is_file() or p.suffix not in (".json", ".jsonl"):
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
    args = parser.parse_args()
    if args.jobs < 1 or args.jobs > 4 or args.fps <= 0 or args.text_rate <= 0:
        parser.error("Use 1–4 workers and positive sampling rates")
    reader = reader_location(args.reader_dir)
    folders = sorted(p.parent for p in args.library.glob("tw-*/battle.json")
                     if not args.only or p.parent.name in args.only)
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        def one(folder):
            read = read_clip(folder, reader, fps=args.fps, text_rate=args.text_rate, seconds=args.seconds)
            return track_clip(folder, reader) if args.stage == "track" else read
        pending = {pool.submit(one, f): f for f in folders}
        report = []
        for task in as_completed(pending):
            result = task.result()
            report.append(result)
            print(json.dumps({"id": pending[task].name, "readings": result.get("sampled_frames"),
                              "states": result.get("model_states"), "verdict": result.get("tracking_verdict", {})}), flush=True)
        if args.stage == "track":
            paired = [f for f in folders if json.loads((f / "battle.json").read_text())["view_id"] in ("left", "right")]
            second = {pool.submit(track_clip, f, reader): f for f in paired}
            revised = {}
            for task in as_completed(second):
                result = task.result()
                revised[result["id"]] = result
                print(json.dumps({"paired": result["id"], "verdict": result["tracking_verdict"]["verdict"],
                                  "recovered_move_names": result["tracking_verdict"].get("paired_move_names_recovered", 0)}), flush=True)
            report = [revised.get(r["id"], r) for r in report]
    if args.stage == "track":
        path = ROOT / "games/twitch/report.json"
        kept = json.loads(path.read_text()) if path.exists() else []
        kept = [r for r in kept if r["id"] not in {r["id"] for r in report}]
        write_json(path, sorted(kept + report, key=lambda r: r["id"]))


if __name__ == "__main__":
    main()
