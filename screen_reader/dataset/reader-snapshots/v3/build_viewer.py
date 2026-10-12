"""Rebuild the local video viewer with embedded, timestamp-aligned tracking logs."""
import json
import gzip
import base64
from pathlib import Path
from battle_io import read_jsonl
from battle_library import scan_library, viewer_entry

ROOT = Path(__file__).resolve().parent


def lines(path):
    if not path.exists() and path.with_suffix(path.suffix + ".gz").exists():
        path = path.with_suffix(path.suffix + ".gz")
    return list(read_jsonl(path))


def compact(reading):
    result = {"t": reading["timestamp_seconds"], "phase": reading["phase"],
              "buttons": reading.get("buttons", []), "messages": reading.get("messages", [])}
    if "phase_estimate" in reading:
        result["phase_estimate"] = reading["phase_estimate"]
    for side in ["mine", "opponent"]:
        result[side] = {key: reading[side][key] for key in
                        ["species", "cp", "health_bar", "shields_left", "pokemon_left", "energy"]}
        if "health_estimate" in reading[side]:
            result[side]["health_estimate"] = reading[side]["health_estimate"]
    return result


def build():
    references = json.loads((ROOT / "reference_manifest.json").read_text())["references"]
    sources = []
    for ref, names in zip(references, [["reis-opening-log", "reis-battle-log"], ["henry-battle-log"]]):
        by_time = {}
        for name in names:
            for row in lines(ROOT / "output" / name / "observations.jsonl"):
                by_time[row["timestamp_seconds"]] = compact(row)
        readings = [by_time[t] for t in sorted(by_time)]
        sources.append({"id": ref["id"], "name": ref["creator"], "video": ref["file"],
                        "audio": ref["audio"], "fps": ref["fps"], "readings": readings,
                        "states": [], "observations": [], "events": [], "bookmarks": []})
    folder = ROOT / "tracker_bundle/games/reis_first_battle_partial"
    alignment = lines(folder / "source_alignment.jsonl")
    states = lines(folder / "states.jsonl")
    observations = lines(folder / "observations.jsonl")
    if not len(alignment) == len(states) == len(observations):
        raise ValueError("Tracker outputs and source alignment have different lengths")
    for a, s, o in zip(alignment, states, observations):
        if abs(a["t"] - s["t"]) > 0.011 or abs(a["t"] - o["t"]) > 0.00001:
            raise ValueError("Tracker output does not match source alignment")
    sources[0]["states"] = [{"t": a["source_seconds"], "state": s} for a, s in zip(alignment, states)]
    sources[0]["observations"] = [{"t": a["source_seconds"], "look": o} for a, o in zip(alignment, observations)]
    # Events use battle-relative time. The reviewed origin is explicit, not a
    # fabricated frame-count offset or the beginning of an extracted clip.
    review = json.loads((ROOT / "fixtures/reis-opening-export-review.json").read_text())
    origin = review["battle_start_source_seconds"]
    sources[0]["origin"] = origin
    sources[0]["events"] = [{"t": e["t"] + origin, "event": e} for e in lines(folder / "events.jsonl")]
    sources[0]["bookmarks"] = [
        {"t": 5, "name": "Battle begins"}, {"t": 16, "name": "After Body Slam"},
        {"t": 35, "name": "Shield choice"}, {"t": 46.566667, "name": "Ice minigame"},
        {"t": 54.733333, "name": "Our replacement"}, {"t": 78, "name": "Opponent replacement"}]
    library = scan_library(ROOT / "battles")
    if library:
        sources = []
        for meta in library:
            entry = viewer_entry(meta)
            if entry["data_url"]:
                with gzip.open(ROOT / entry["data_url"], "rt", encoding="utf-8") as stream:
                    entry.update(json.load(stream))
            entry["initial_time"] = 5 if meta["id"] == "reis-01" else 0
            entry["loaded"] = True
            sources.append(entry)
    storage_path = ROOT / "output/storage-report.json"
    storage = json.loads(storage_path.read_text()) if storage_path.exists() else None
    dataset_path = ROOT / "dataset/manifest.json"
    dataset = json.loads(dataset_path.read_text(encoding="utf-8")) if dataset_path.exists() else {}
    split = {"partitions": {c["battle_id"]: c["partition"] for c in dataset.get("clips", [])},
             "test_role": dataset.get("test_role")}
    payload = json.dumps({"sources": sources, "storage": storage, "dataset": split}, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    payload = base64.b64encode(gzip.compress(payload, compresslevel=6, mtime=0)).decode("ascii")
    html = (ROOT / "viewer_template.html").read_text(encoding="utf-8").replace("__TRACKER_DATA__", payload)
    html = html.replace("__VALUES_SCRIPT__", (ROOT / "viewer_values.js").read_text(encoding="utf-8"))
    (ROOT / "battle_viewer.html").write_text(html, encoding="utf-8")
    print(json.dumps({"viewer": str(ROOT / "battle_viewer.html"), "screen_frames": [len(s["readings"]) for s in sources], "battles": len(library), "tracker_states": len(states)}))


if __name__ == "__main__":
    build()
