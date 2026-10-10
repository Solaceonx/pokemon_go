"""Build one portable viewer; decode only the selected battle's compressed data."""
import base64
import gzip
import json
from pathlib import Path
from build_viewer import ROOT
from battle_library import scan_library, viewer_entry


def build(battles=None):
    library = Path(battles) if battles else ROOT / "battles"
    sources = []
    for meta in scan_library(library):
        entry = viewer_entry(meta)
        entry["initial_time"] = 5 if meta["id"] == "reis-01" else 0
        entry["loaded"] = False
        if entry["data_url"]:
            entry["embedded_data"] = base64.b64encode((library / meta["id"] / meta["viewer_data_file"]).read_bytes()).decode("ascii")
        sources.append(entry)
    manifest_path = ROOT / "dataset/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    storage_path = ROOT / "output/storage-report.json"
    payload = {"sources": sources,
               "dataset": {"partitions": {c["battle_id"]: c["partition"] for c in manifest.get("clips", [])},
                           "test_role": manifest.get("test_role")},
               "storage": json.loads(storage_path.read_text(encoding="utf-8")) if storage_path.exists() else None}
    packed = gzip.compress(json.dumps(payload, separators=(",", ":")).encode("utf-8"), compresslevel=6, mtime=0)
    html = (ROOT / "viewer_template.html").read_text(encoding="utf-8").replace("__TRACKER_DATA__", base64.b64encode(packed).decode("ascii"))
    html = html.replace("__VALUES_SCRIPT__", (ROOT / "viewer_values.js").read_text(encoding="utf-8"))
    temporary = ROOT / "battle_viewer.incomplete.html"
    temporary.write_text(html, encoding="utf-8")
    temporary.replace(ROOT / "battle_viewer.html")
    print(json.dumps({"battles": len(sources), "html_bytes": len(html.encode("utf-8")),
                      "decompression": "selected_battle_only", "video_bytes_embedded": 0}))


if __name__ == "__main__": build()
