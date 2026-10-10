"""Read one recording in a single pass, with the screen reader from the screen-reader-video-pipeline branch.

    cd <that branch>/screen_reader
    PYTHONPATH=. python <this file> recording.mp4 out_folder [--fps 15] [--text-rate 3] [--header-every 2] [--text-scale 0.4]

Writes out_folder/readings.jsonl (health bars and header, --fps times a second) and out_folder/text.jsonl
(the announcement text in the middle of the screen and the shield prompt, --text-rate times a second),
which scripts/recording/assemble.py turns into looks for the tracker. The frame rates are deliberately low:
the tracked result on full 60-a-second readings is the same at 10 a second.
"""
import json, sys, time, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
import av, numpy as np
from battle_reader import ROOT, BattleReader
from local_ocr import LocalOCR


def option(name, default):
    return type(default)(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


video, out_dir = sys.argv[1], Path(sys.argv[2])
fps, text_rate, header_every = option("--fps", 15.0), option("--text-rate", 3.0), option("--header-every", 2.0)
text_scale, profile = option("--text-scale", 0.4), option("--profile", "lyxia-great.json")
out_dir.mkdir(parents=True, exist_ok=True)
ocr = LocalOCR()
reader = BattleReader(ROOT / "profiles" / profile, ocr, ocr_interval=header_every)
val = lambda x: x.get("value") if isinstance(x, dict) and x.get("status") == "observed" else None
BANDS = (("middle", 0.22, 0.44), ("prompt", 0.64, 0.80))  # shares of the screen's height

container = av.open(video); stream = container.streams.video[0]
started, spent = time.time(), {"pixels": 0.0, "header": 0.0, "text": 0.0}
n_frames = n_looks = 0; next_frame = next_text = 0.0; t = 0.0
with open(out_dir / "readings.jsonl", "w") as frames_out, open(out_dir / "text.jsonl", "w") as text_out:
    for i, frame in enumerate(container.decode(stream)):
        t = float(frame.pts * stream.time_base)
        want_frame, want_text = t >= next_frame - 1e-6, t >= next_text - 1e-6
        if not (want_frame or want_text):
            continue
        img = frame.to_image()
        if want_frame:
            next_frame = max(next_frame + 1.0 / fps, t + 0.5 / fps)
            before, clock = reader.last_ocr_time, time.perf_counter()
            r = reader.detect(img, t, frame_index=i)
            spent["header" if reader.last_ocr_time != before else "pixels"] += time.perf_counter() - clock
            row = {"t": round(t, 4), "phase": val(r["phase"]), "ocr": reader.last_ocr_time != before}
            for side, k in (("mine", "m"), ("opponent", "o")):
                x = r[side]; hb = val(x["health_bar"])
                row[k] = {"sp": val(x["species"]), "cp": val(x["cp"]), "sh": val(x["shields_left"]), "left": val(x["pokemon_left"]),
                          "hp": hb["fraction"] if hb else None,
                          "seg": [[g["color"], g["pixels"]] for g in hb["segments"]] if hb else None,
                          "w": hb.get("interior_width_pixels") if hb else None}
            row["result"] = val(r.get("result", {}))
            frames_out.write(json.dumps(row) + "\n"); n_frames += 1
        if want_text:
            next_text = max(next_text + 1.0 / text_rate, t + 0.5 / text_rate)
            clock = time.perf_counter()
            w, h = img.size; found = []
            for name, a, b in BANDS:
                band = img.crop((0, int(a * h), w, int(b * h))).resize((int(w * text_scale), int((b - a) * h * text_scale)))
                found += [[name, x["text"].strip()] for x in ocr.read(np.asarray(band)) if x.get("text", "").strip()]
            spent["text"] += time.perf_counter() - clock
            text_out.write(json.dumps({"t": round(t, 3), "text": found}) + "\n"); n_looks += 1
took = time.time() - started
summary = {"video_seconds": round(t, 1), "seconds": round(took, 1), "times_real_time": round(took / max(t, 1e-9), 2),
           "frames": n_frames, "text_looks": n_looks, **{f"{k}_seconds": round(v, 1) for k, v in spent.items()},
           "fps": fps, "text_rate": text_rate, "header_every": header_every, "text_scale": text_scale}
(out_dir / "read.json").write_text(json.dumps(summary, indent=1) + "\n")
print(json.dumps(summary))
