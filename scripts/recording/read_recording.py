"""Read one recording in a single pass, with the screen reader from the screen-reader-video-pipeline branch.

    cd <that branch>/screen_reader
    PYTHONPATH=. python <this file> recording.mp4 out_folder [--fps 15] [--text-rate 3] [--header-every 2]

Writes out_folder/readings.jsonl (health bars and header, --fps times a second) and out_folder/text.jsonl
(the announcement text in the middle of the screen, --text-rate times a second), which
scripts/recording/assemble.py turns into looks for the tracker.

Choices made for speed, each checked against a full reading of the same recording:
  - 15 frames a second, not 60: the tracked result is the same down to 10;
  - only the middle band of text: the lower band (the shield prompt) adds nothing the assembly uses;
  - the text finder works on a smaller copy of the crop (it would otherwise enlarge it): about a third of the
    time for 96 of 99 announcements, each of which is on screen for several looks anyway.
"""
import json, sys, time, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
import av, numpy as np
import cv2
from battle_reader import ROOT, BattleReader
from rapidocr_onnxruntime import RapidOCR


class Text:
    """The reader's text recognition, with the finder working at a chosen size (short side, in pixels)."""

    def __init__(self, side: int, threads: int = 4):
        self.engine = RapidOCR(intra_op_num_threads=threads, inter_op_num_threads=1, use_cls=False, det_limit_side_len=side)

    def read(self, rgb):
        result, _ = self.engine(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
        records = []
        for polygon, text, confidence in result or []:
            if confidence >= 0.75:
                points = np.asarray(polygon)
                records.append({"text": text, "confidence": round(float(confidence), 4),
                                "bounds": [round(float(points[:, 0].min())), round(float(points[:, 1].min())),
                                           round(float(points[:, 0].max())), round(float(points[:, 1].max()))]})
        return records


def option(name, default):
    return type(default)(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


video, out_dir = sys.argv[1], Path(sys.argv[2])
fps, text_rate, header_every = option("--fps", 15.0), option("--text-rate", 3.0), option("--header-every", 2.0)
text_scale, profile = option("--text-scale", 0.667), option("--profile", "lyxia-great.json")
out_dir.mkdir(parents=True, exist_ok=True)
ocr = Text(option("--text-side", 320))
reader = BattleReader(ROOT / "profiles" / profile, Text(option("--header-side", 480)), ocr_interval=header_every)
val = lambda x: x.get("value") if isinstance(x, dict) and x.get("status") == "observed" else None
BANDS = (("middle", 0.22, 0.44),)  # shares of the screen's height; the shield prompt lower down is not needed

container = av.open(video); stream = container.streams.video[0]
started, spent = time.time(), {"pixels": 0.0, "header": 0.0, "text": 0.0}
n_frames = n_looks = 0; next_frame = next_text = 0.0; t = 0.0
last_bar = None  # when a health bar was last on screen
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
            # No bar for longer than any charged move lasts: the battle may be over, and the result screen can
            # be brief, so read the screen's text twice a second for a while.
            ended = last_bar is not None and 10.5 < t - last_bar < 40 and t - (before or 0.0) >= 0.5
            r = reader.detect(img, t, frame_index=i, force_ocr=ended)
            spent["header" if reader.last_ocr_time != before else "pixels"] += time.perf_counter() - clock
            row = {"t": round(t, 4), "phase": val(r["phase"]), "ocr": reader.last_ocr_time != before}
            for side, k in (("mine", "m"), ("opponent", "o")):
                x = r[side]; hb = val(x["health_bar"])
                row[k] = {"sp": val(x["species"]), "cp": val(x["cp"]), "sh": val(x["shields_left"]), "left": val(x["pokemon_left"]),
                          "hp": hb["fraction"] if hb else None,
                          "seg": [[g["color"], g["pixels"]] for g in hb["segments"]] if hb else None,
                          "w": hb.get("interior_width_pixels") if hb else None}
            row["result"] = val(r.get("result", {}))
            if row["m"]["hp"] is not None or row["o"]["hp"] is not None: last_bar = t
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
