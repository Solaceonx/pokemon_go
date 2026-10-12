"""Keep one playable source copy and retain the original Twitch timestamp offset."""
from __future__ import annotations

from fractions import Fraction
import hashlib
import json
from pathlib import Path
import time


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".incomplete")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def media_facts(path):
    import av
    with av.open(str(path)) as source:
        stream = source.streams.video[0]
        frame = next(source.decode(stream), None)
        if frame is None or frame.pts is None:
            raise ValueError("Source has no timestamped video frame")
        return {"width": stream.width, "height": stream.height,
                "fps": float(stream.average_rate) if stream.average_rate else None,
                "duration_seconds": source.duration / av.time_base if source.duration else None,
                "first_video_seconds": float(frame.pts * frame.time_base),
                "container_start_seconds": (source.start_time or 0) / av.time_base,
                "container": source.format.name, "audio_included": bool(source.streams.audio),
                "bytes": Path(path).stat().st_size, "sha256": sha256(path)}


def normalize_source(path, record_path=None):
    """Remux transport-stream downloads to MP4 without re-encoding or a second final copy.

    The input and output packet counts and timestamp order must match. The original
    source is replaced only after the new file decodes and passes those checks.
    Its original container timestamps can be recovered by adding the saved offset.
    """
    import av
    path = Path(path)
    if not path.is_file() or path.name.endswith(".part"):
        raise ValueError("A completed download is required")
    before = media_facts(path)
    record_path = Path(record_path or path.parent / "source.json")
    record = json.loads(record_path.read_text(encoding="utf-8")) if record_path.exists() else {}
    expected_duration = record.get("duration_seconds")
    if expected_duration and before["duration_seconds"] and abs(expected_duration - before["duration_seconds"]) > 1:
        raise ValueError("Downloaded duration differs from VOD metadata: resume missing segments before cutting")
    prior = record.get("timestamp_normalization")
    journal = path.with_name("timestamp-normalization.json")
    if journal.exists():
        intent = json.loads(journal.read_text(encoding="utf-8"))
        if intent.get("normalized_sha256") == before["sha256"]:
            record["timestamp_normalization"], record["media"] = intent, before
            write_json(record_path, record)
            return before
    if prior and prior.get("normalized_sha256") == before["sha256"]:
        return before
    # Native Twitch HLS downloads may be MPEG-TS despite the .mp4 extension.
    if "mpegts" not in before["container"] and abs(before["container_start_seconds"]) < .05:
        return before
    offset = Fraction(str(before["container_start_seconds"]))
    temporary = path.with_name("video.normalizing.incomplete.mp4")
    counts, first_times, last_times = {}, {}, {}
    started = time.monotonic()
    with av.open(str(path)) as source, av.open(str(temporary), "w", options={"movflags": "+faststart"}) as output:
        mapping, output_indexes = {}, {}
        for stream in source.streams:
            if stream.type in {"video", "audio"}:
                mapping[stream.index] = output.add_stream_from_template(stream)
                output_indexes[stream.index] = mapping[stream.index].index
                counts[stream.index] = 0
        previous = {}
        for packet in source.demux():
            index = packet.stream.index
            if index not in mapping or packet.dts is None or packet.pts is None:
                continue
            timestamp = Fraction(packet.dts) * packet.time_base
            if index in previous and timestamp <= previous[index]:
                raise ValueError("Non-monotonic source timestamps: discontinuities need explicit handling")
            if index in previous and timestamp - previous[index] > .5:
                raise ValueError("Source has a packet timestamp gap: missing segments require review")
            previous[index] = timestamp
            counts[index] += 1
            first_times.setdefault(index, float(Fraction(packet.pts) * packet.time_base))
            last_times[index] = float(Fraction(packet.pts) * packet.time_base)
            shift = round(offset / packet.time_base)
            packet.pts -= shift
            packet.dts -= shift
            packet.stream = mapping[index]
            output.mux(packet)
    after = media_facts(temporary)
    output_counts = {}
    with av.open(str(temporary)) as saved:
        for packet in saved.demux():
            if packet.pts is not None and packet.dts is not None:
                output_counts[packet.stream.index] = output_counts.get(packet.stream.index, 0) + 1
    expected_counts = {output_indexes[index]: count for index, count in counts.items()}
    if expected_counts != output_counts:
        raise ValueError("Remux changed packet counts; original retained")
    if (before["width"], before["height"]) != (after["width"], after["height"]):
        raise ValueError("Remux changed source dimensions; original retained")
    if abs(after["first_video_seconds"] - (before["first_video_seconds"] - float(offset))) > .05:
        raise ValueError("Remux changed video timing; original retained")
    if before["duration_seconds"] and abs(after["duration_seconds"] - before["duration_seconds"]) > .2:
        raise ValueError("Remux changed source duration; original retained")
    normalization = {"method": "packet_copy_mp4_shared_origin", "reencoded": False,
                     "original_container": before["container"], "original_sha256": before["sha256"],
                     "original_bytes": before["bytes"], "container_timestamp_offset_seconds": float(offset),
                     "normalized_sha256": after["sha256"], "packet_counts": counts,
                     "first_original_pts_seconds": first_times, "last_original_pts_seconds": last_times,
                     "elapsed_seconds": round(time.monotonic() - started, 3)}
    # Keep a tiny journal so replacement and the source record can be recovered.
    write_json(journal, normalization)
    temporary.replace(path)
    record["timestamp_normalization"], record["media"] = normalization, after
    write_json(record_path, record)
    return after
