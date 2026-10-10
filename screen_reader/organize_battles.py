"""Create reviewed per-battle phone clips and compressed, aligned library data."""
import argparse
import gzip
import json
import math
import sys
from fractions import Fraction
from pathlib import Path

from battle_io import read_jsonl, open_log
from build_viewer import compact

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "tools/python-libs"))
import av


def cut(ref, spec, folder):
    target = folder / "video.mp4"
    temp = folder / "video.incomplete.mp4"
    fps = ref["fps"]
    start = math.ceil(spec["start"] * fps - 1e-6) / fps
    end = spec["end"]
    x, y, width, height = ref["viewport"]
    frames = 0
    with av.open(str(ROOT / ref["file"])) as video, av.open(str(ROOT / ref["audio"])) as audio:
        video.streams.video[0].codec_context.thread_count = 2
        video.seek(int(max(0, start - 1) * av.time_base))
        audio.seek(int(start * av.time_base))
        with av.open(str(temp), "w", options={"movflags": "+faststart"}) as out:
            vs = out.add_stream("libx264", rate=fps)
            vs.width, vs.height, vs.pix_fmt = width, height, "yuv420p"
            vs.options = {"crf": "23", "preset": "veryfast"}
            vs.codec_context.thread_count = 2
            audio_out = out.add_stream_from_template(audio.streams.audio[0])

            def audio_packets():
                for packet in audio.demux(audio.streams.audio[0]):
                    if packet.pts is None or packet.dts is None:
                        continue
                    timestamp = float(packet.pts * packet.time_base)
                    if timestamp < start:
                        continue
                    if timestamp >= end:
                        break
                    offset = round(start / float(packet.time_base))
                    packet.pts -= offset
                    packet.dts -= offset
                    packet.stream = audio_out
                    yield packet

            packets = iter(audio_packets())
            pending_audio = next(packets, None)

            def mux_video(packet):
                nonlocal pending_audio
                vt = float(packet.dts * packet.time_base)
                while pending_audio is not None and float(pending_audio.dts * pending_audio.time_base) <= vt:
                    out.mux(pending_audio)
                    pending_audio = next(packets, None)
                out.mux(packet)

            for frame in video.decode(video=0):
                if frame.time < start - 1e-6:
                    continue
                if frame.time >= end:
                    break
                pixels = frame.to_ndarray(format="rgb24")[y:y+height, x:x+width]
                cropped = av.VideoFrame.from_ndarray(pixels, format="rgb24")
                cropped.pts = round((frame.time-start)*fps)
                cropped.time_base = Fraction(1, fps)
                for packet in vs.encode(cropped):
                    mux_video(packet)
                frames += 1
            for packet in vs.encode():
                mux_video(packet)
            while pending_audio is not None:
                out.mux(pending_audio)
                pending_audio = next(packets, None)
    if not frames:
        raise ValueError("Empty video segment")
    temp.replace(target)
    with av.open(str(target)) as saved:
        duration = saved.duration / av.time_base
        if len(saved.streams.video) != 1 or len(saved.streams.audio) != 1:
            raise ValueError("Clip is missing video or audio")
    return start, duration, frames


def remap_view(source, start, end):
    # Original source PTS remain in canonical screen logs; display time is local
    # to this clip. No frame number is used to guess a battle's origin.
    view = {key: [] for key in ["readings", "states", "observations", "events", "bookmarks"]}
    for key in view:
        for row in source.get(key, []):
            if start <= row["t"] < end:
                view[key].append({**row, "t": round(row["t"]-start, 6)})
    if source.get("origin") is not None and start <= source["origin"] < end:
        view["origin"] = source["origin"] - start
    return view


def source_data():
    refs = json.loads((ROOT / "reference_manifest.json").read_text())["references"]
    sources = {}
    for ref, names in zip(refs, [["reis-opening-log", "reis-battle-log"], ["henry-battle-log"]]):
        by_time = {}
        for name in names:
            for row in read_jsonl(ROOT / "output" / name / "observations.jsonl"):
                by_time[row["timestamp_seconds"]] = row
        rows = [by_time[t] for t in sorted(by_time)]
        sources[ref["id"]] = {"readings": [compact(row) for row in rows], "raw": rows}
    folder = ROOT / "tracker_bundle/games/reis_first_battle_partial"
    alignment = list(read_jsonl(folder / "source_alignment.jsonl"))
    states = list(read_jsonl(folder / "states.jsonl"))
    observations = list(read_jsonl(folder / "observations.jsonl"))
    if not len(alignment) == len(states) == len(observations):
        raise ValueError("Tracker alignment mismatch")
    reis = sources[refs[0]["id"]]
    reis["states"] = [{"t": a["source_seconds"], "state": s} for a, s in zip(alignment, states)]
    reis["observations"] = [{"t": a["source_seconds"], "look": o} for a, o in zip(alignment, observations)]
    origin = json.loads((ROOT / "fixtures/reis-opening-export-review.json").read_text())["battle_start_source_seconds"]
    reis["origin"] = origin
    reis["events"] = [{"t": e["t"]+origin, "event": e} for e in read_jsonl(folder / "events.jsonl")]
    reis["bookmarks"] = [{"t": t, "name": name} for t, name in [(5,"Battle begins"),(16,"After Body Slam"),(35,"Shield choice"),(46.566667,"Ice minigame"),(54.733333,"Our replacement"),(78,"Opponent replacement")]]
    return refs, sources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", help="Create one battle id for a quick check")
    args = parser.parse_args()
    specs = json.loads((ROOT / "fixtures/battle-segments-v2.json").read_text(encoding="utf-8"))["segments"]
    refs, sources = source_data()
    refs = {r["id"]: r for r in refs}
    library = ROOT / "battles"
    library.mkdir(exist_ok=True)
    for spec in specs:
        if args.only and spec["id"] != args.only:
            continue
        ref = refs[spec["source_id"]]
        folder = library / spec["id"]
        folder.mkdir(exist_ok=True)
        if (folder / "battle.json").exists():
            previous = json.loads((folder / "battle.json").read_text())
            if previous.get("encoding_crf") == 23:
                print(spec["id"], "already organized", flush=True)
                continue
        start, duration, frames = cut(ref, spec, folder)
        source = sources[spec["source_id"]]
        view = remap_view(source, start, spec["end"])
        metadata = {"schema": "battle-library-v1", "id": spec["id"],
                    "name": spec["name"], "creator": ref["creator"], "reference_id": ref["id"],
                    "source_url": ref["url"], "source_video": ref["file"],
                    "source_start_seconds": start, "source_end_seconds": spec["end"],
                    "duration_seconds": duration, "fps": ref["fps"], "frames": frames,
                    "video_file": "video.mp4", "viewer_data_file": "viewer-data.json.gz",
                    "audio_in_video": True, "viewport": [0, 0, ref["viewport"][2], ref["viewport"][3]],
                    "encoding_crf": 23,
                    "source_viewport": ref["viewport"], "source_edited": True,
                    "timing_validated": False, "boundary_review": "visual survey; approximate context boundaries",
                    "completeness": spec.get("completeness", "countdown_and_ending_visible"),
                    "analysis_status": "partial" if view["readings"] else "not_analyzed",
                    "notes": spec.get("notes", [])}
        if "origin" in view:
            metadata["battle_start_seconds"] = view["origin"]
        payload = json.dumps(view, separators=(",", ":")).encode()
        with gzip.open(folder / "viewer-data.json.gz", "wb", compresslevel=6) as stream:
            stream.write(payload)
        with open_log(folder / "screen_readings.jsonl.gz", "wt") as stream:
            for row in source["raw"]:
                t = row["timestamp_seconds"]
                if start <= t < spec["end"]:
                    stream.write(json.dumps({**row, "timestamp_seconds": round(t-start, 6),
                                             "source_timestamp_seconds": t,
                                             "coordinates_basis": "original_source_frame"})+"\n")
        # Keep tracker input/output time bases intact, and supply explicit local
        # clip alignment separately. Do not run the tracker for unanalyzed battles.
        for key, filename, field in [("observations","observations.jsonl","look"),
                                      ("states","states.jsonl","state"), ("events","events.jsonl","event")]:
            if view[key]:
                (folder / filename).write_text("".join(json.dumps(row[field])+"\n" for row in view[key]))
        if not view["observations"]:
            (folder / "observations.jsonl").write_text("")
        (folder / "source_alignment.jsonl").write_text("".join(json.dumps({"t": row["look"]["t"],
                        "clip_seconds": row["t"], "source_seconds": row["t"]+start})+"\n" for row in view["observations"]))
        team = json.loads((ROOT / "tracker_bundle/games/reis_first_battle_partial/team.json").read_text()) if view["states"] else {"pokemon": []}
        (folder / "team.json").write_text(json.dumps(team, indent=2)+"\n")
        report = (f"# {spec['name']}\n\nSource: {ref['url']}\n\nSource interval: {start:.3f}–{spec['end']:.3f}s. Clip time zero corresponds to source {start:.3f}s. Original phone region retained at {ref['viewport'][2]}×1080 and {ref['fps']} fps; re-encoded H.264 CRF 23. Commentary audio is muxed once into the clip.\n\n"
                  f"Completeness: {metadata['completeness']}. Source is edited creator footage; playback speed/internal cuts and input boundaries are not validated.\n\n"
                  f"Analysis: {metadata['analysis_status']}; {len(view['readings'])} saved screen frames, {len(view['states'])} tracker states. Missing analysis is not an empty/zero game state.\n\n"
                  "Canonical screen log coordinates/source PTS refer to the original video. Clip display times are remapped explicitly. Tracker t retains its battle-relative time; source_alignment.jsonl links that t to clip and source times.\n\n"
                  "Existing source videos/logs are preserved. Game data and runtime are shared, not copied into this folder.\n")
        (folder / "report.md").write_text(report, encoding="utf-8")
        metadata["video_bytes"] = (folder / "video.mp4").stat().st_size
        metadata["saved_data_bytes"] = sum(p.stat().st_size for p in folder.iterdir() if p.is_file() and p.name != "video.mp4")
        (folder / "battle.json").write_text(json.dumps(metadata, indent=2)+"\n")
        print(json.dumps({"battle": spec["id"], "seconds": duration, "video_mb": round(metadata["video_bytes"]/1e6, 2), "screen_frames": len(view["readings"])}), flush=True)
    catalog = [json.loads(p.read_text()) for p in sorted(library.glob("*/battle.json"))]
    (library / "catalog.json").write_text(json.dumps({"schema":"battle-library-v1", "battles":catalog}, indent=2)+"\n")
    print("Library contains", len(catalog), "battles", flush=True)


if __name__ == "__main__":
    main()
