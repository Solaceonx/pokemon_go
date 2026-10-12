"""Register/download one public YouTube video or Twitch VOD for later review.

One source copy, explicit provenance, no guessed battle boundaries or labels.
Without --download this inspects metadata only (existing sources use local data).
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent


def canonical_source(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        raise ValueError("Use a public HTTPS video link")
    host = (parsed.hostname or "").lower()
    if host in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}:
        if host == "youtu.be":
            identity = parsed.path.strip("/")
        elif parsed.path == "/watch":
            identity = parse_qs(parsed.query).get("v", [""])[0]
        else:
            raise ValueError("Use a single YouTube watch link")
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", identity):
            raise ValueError("Invalid YouTube video ID")
        return "youtube", identity, f"https://www.youtube.com/watch?v={identity}"
    if host in {"twitch.tv", "www.twitch.tv"}:
        match = re.fullmatch(r"/videos/(\d+)/?", parsed.path)
        if not match:
            raise ValueError("Use a Twitch VOD link: https://www.twitch.tv/videos/ID")
        return "twitch", match[1], f"https://www.twitch.tv/videos/{match[1]}"
    raise ValueError("Only YouTube videos and Twitch VOD links are supported")


def checksum(path):
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def write_record(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".incomplete.json")
    temporary.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def media_facts(path):
    sys.path.insert(0, str(ROOT / "tools/python-libs"))
    import av
    with av.open(str(path)) as container:
        video = container.streams.video[0]
        first = next(container.decode(video=0), None)
        if first is None:
            raise ValueError("Downloaded media has no decodable video frame")
        return {"width": video.width, "height": video.height,
                "fps": float(video.average_rate) if video.average_rate else None,
                "duration_seconds": container.duration/av.time_base if container.duration else None,
                "audio_included": bool(container.streams.audio), "container": container.format.name,
                "sha256": checksum(path), "bytes": path.stat().st_size,
                "timing_validated": False}


def import_source(url, download=False, root=ROOT, executable=None):
    platform, identity, canonical = canonical_source(url)
    folder = root / "sources" / platform / identity
    record_path = folder / "source.json"
    if record_path.exists():
        record = json.loads(record_path.read_text(encoding="utf-8"))
        media = record.get("media_file")
        if media and (root/media).is_file():
            if checksum(root/media) != record["media"]["sha256"]:
                raise ValueError("Registered video changed; investigate before reusing it")
            return {**record, "reused_existing_media": True}
    references = root / "reference_manifest.json"
    known = [] if not references.exists() else json.loads(references.read_text(encoding="utf-8"))["references"]
    for ref in known:
        if platform == "youtube" and ref["id"] == identity and (root/ref["file"]).is_file():
            record = {"schema": "video-source-v1", "platform": platform, "source_id": identity,
                      "url": canonical, "creator": ref["creator"], "media_file": ref["file"],
                      "media": media_facts(root/ref["file"]), "import_method": "existing_reference",
                      "analysis_status": "existing_reviewed_battle_boundaries", "battle_boundaries_automatic": False}
            write_record(record_path, record)
            return {**record, "reused_existing_media": True}
    downloader = executable or root / "tools/yt-dlp.exe"
    if not downloader.is_file():
        raise ValueError("Install yt-dlp or pass --downloader PATH")
    # A single video stream avoids silently downloading several media copies.
    selector = "bestvideo[ext=mp4][height>=720][height<=1080]/best[ext=mp4][height>=720][height<=1080]"
    common = [str(downloader), "--ignore-config", "--no-playlist", "--no-warnings", "-f", selector]
    process = subprocess.run(common+["--skip-download", "--dump-single-json", canonical],
                             capture_output=True, text=True, encoding="utf-8", timeout=180)
    if process.returncode:
        raise RuntimeError(process.stderr.strip() or "Video metadata could not be read")
    info = json.loads(process.stdout)
    if info.get("entries") is not None or info.get("is_live") or str(info.get("id")) not in {identity, "v"+identity}:
        raise ValueError("Expected one completed video/VOD")
    record = {"schema": "video-source-v1", "platform": platform, "source_id": identity,
              "url": canonical, "title": info.get("title"), "creator": info.get("uploader"),
              "duration_seconds": info.get("duration"), "format_id": info.get("format_id"),
              "width": info.get("width"), "height": info.get("height"), "fps": info.get("fps"),
              "downloader_version": subprocess.check_output([str(downloader), "--version"], text=True).strip(),
              "inspected_at_utc": datetime.now(timezone.utc).isoformat(),
              "analysis_status": "metadata_only", "battle_boundaries_automatic": False}
    if download:
        folder.mkdir(parents=True, exist_ok=True)
        subprocess.run(common+["--no-overwrites", "--fixup", "never", "-o", str(folder/"video.%(ext)s"), canonical], check=True)
        candidates = list(folder.glob("video.mp4"))
        if len(candidates) != 1:
            raise ValueError("Download did not produce one completed MP4; partial files were retained for resume")
        record["media_file"] = candidates[0].relative_to(root).as_posix()
        record["media"] = media_facts(candidates[0])
        record["analysis_status"] = "needs_viewport_and_boundary_review"
    write_record(record_path, record)
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--downloader", type=Path)
    args = parser.parse_args()
    print(json.dumps(import_source(args.url, args.download, executable=args.downloader), ensure_ascii=False))
