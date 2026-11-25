# Each minigame's rating (ratings.rating) beside the log's icons_seen. grade_each.py MEDIA_DIR LOG...
import json, sys
from pathlib import Path
sys.path.insert(0, "scripts/live")
from ratings import rating
from rapidocr_onnxruntime import RapidOCR
ocr = RapidOCR()
media = Path(sys.argv[1])
mg = []
for f in sys.argv[2:]:
    rows = [json.loads(l) for l in open(f)]
    ep = next(r["epoch"] for r in rows if r["kind"] == "start")
    mg += [(ep + r["t"], Path(f).stem, r) for r in rows if r["kind"] == "minigame"]
for d in sorted(media.glob("minigame-*")):
    t = int(d.name.split("-")[1])
    near = min(mg, key=lambda m: abs(m[0] - t))
    print(d.name, rating(d, ocr), "icons_seen", near[2].get("icons_seen"), near[1], round(near[2]["t"], 1), "dt", round(near[0] - t, 1))
