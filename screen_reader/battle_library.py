"""Read battle folders without depending on a stale generated catalog."""
import json
from pathlib import Path


def scan_library(root):
    root = Path(root).resolve()
    battles = []
    for path in root.glob("*/battle.json"):
        try:
            if not path.resolve().is_relative_to(root):
                continue
            meta = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(meta, dict):
                continue
            if meta.get("segment_status") == "combined_superseded":
                continue
            folder = path.parent
            video = (folder / meta.get("video_file", "video.mp4")).resolve()
            view = (folder / meta.get("viewer_data_file", "viewer-data.json.gz")).resolve()
            if not video.is_relative_to(folder.resolve()) or not view.is_relative_to(folder.resolve()):
                continue
            if not video.is_file() or not view.is_file():
                continue
            # Directory name is the stable path id, regardless of supplied JSON.
            meta["id"] = folder.name
            meta["video_bytes"] = video.stat().st_size
            view_stat = view.stat()
            meta["analysis_revision"] = f"{view_stat.st_mtime_ns}:{view_stat.st_size}"
            meta["saved_data_bytes"] = sum(p.stat().st_size for p in folder.rglob("*")
                if p.is_file() and p != video and ".incomplete." not in p.name)
            battles.append(meta)
        except (OSError, ValueError, TypeError):
            continue
    # Also accept an already-cut MP4 dropped into the root or a subfolder.
    # Do not invent frame rate, battle origin, or accompanying analysis for it.
    for video in [*root.glob("*.mp4"), *root.glob("*/*.mp4")]:
        if video.parent != root and (video.parent / "battle.json").exists():
            continue
        if ".incomplete." in video.name or not video.resolve().is_relative_to(root):
            continue
        relative = video.relative_to(root).as_posix()
        battles.append({"id": "video-"+relative.removesuffix(".mp4").replace("/", "-"),
                        "name": video.stem, "creator": "Local recording", "fps": None,
                        "video_bytes": video.stat().st_size, "saved_data_bytes": 0,
                        "relative_video": relative, "viewer_data_file": None,
                        "analysis_status": "not_analyzed", "completeness": "unreviewed",
                        "duration_seconds": 0, "audio_in_video": True})
    return sorted(battles, key=lambda b: (0 if b.get("reference_id") == "qSaL7jM9NbA" else 1, b["id"]))


def viewer_entry(meta, prefix="battles/"):
    return {"id": meta["id"], "name": meta.get("name", meta["id"]),
            "reference_id": meta.get("reference_id"), "creator": meta.get("creator", "Local recording"),
            "video": prefix + meta.get("relative_video", meta["id"] + "/" + meta.get("video_file", "video.mp4")),
            "data_url": prefix + meta["id"] + "/" + meta["viewer_data_file"] if meta.get("viewer_data_file") else None,
            "fps": meta.get("fps", 30), "duration": meta.get("duration_seconds", 0),
            "source_start": meta.get("source_start_seconds", 0),
            "video_bytes": meta["video_bytes"], "saved_data_bytes": meta["saved_data_bytes"],
            "completeness": meta.get("completeness", "unknown"), "analysis_status": meta.get("analysis_status", "not_analyzed"),
            "dataset_role": meta.get("boundary_candidate", {}).get("dataset_role"),
            "incomplete_start": meta.get("incomplete_start", False), "incomplete_end": meta.get("incomplete_end", False),
            "analysis_revision": meta.get("analysis_revision"),
            "audio_in_video": meta.get("audio_in_video", True), "isClip": True,
            "readings": [], "states": [], "observations": [], "events": [], "bookmarks": []}
