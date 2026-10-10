"""Run the screen reader over every frame of a recording and save one compact line per frame."""
import json, sys, time, warnings
warnings.filterwarnings("ignore")
import av
from battle_reader import ROOT, BattleReader
from local_ocr import LocalOCR

video, out_path = sys.argv[1], sys.argv[2]
reader = BattleReader(ROOT / "profiles" / "lyxia-great.json", LocalOCR(), ocr_interval=1.0)
val = lambda x: x.get("value") if isinstance(x, dict) and x.get("status") == "observed" else None
c = av.open(video); v = c.streams.video[0]
t0 = time.time(); n = 0; plain = []
with open(out_path, "w") as out:
    for i, frame in enumerate(c.decode(v)):
        t = float(frame.pts * v.time_base)
        before = reader.last_ocr_time
        s = time.perf_counter()
        r = reader.detect(frame.to_image(), t, frame_index=i)
        dt = 1000 * (time.perf_counter() - s)
        did_ocr = reader.last_ocr_time != before
        if not did_ocr:
            plain.append(dt)
        row = {"t": round(t, 4), "phase": val(r["phase"]), "ocr": did_ocr}
        for side, k in (("mine", "m"), ("opponent", "o")):
            x = r[side]
            hb = val(x["health_bar"])
            row[k] = {"sp": val(x["species"]), "cp": val(x["cp"]), "sh": val(x["shields_left"]), "left": val(x["pokemon_left"]),
                      "hp": hb["fraction"] if hb else None, "seg": [[g["color"], g["pixels"]] for g in hb["segments"]] if hb else None,
                      "w": hb.get("interior_width_pixels") if hb else None}
        row["buttons"] = [b.get("id") for b in r.get("buttons", [])]
        row["charge_result"] = val(r.get("charge_result", {}))
        row["switch_cd"] = val(r.get("switch_cooldown_seconds", {}))
        row["clock"] = val(r.get("battle_clock_seconds", {}))
        row["shield_secs"] = val(r.get("shield_decision_seconds", {}))
        row["result"] = val(r.get("result", {}))
        out.write(json.dumps(row) + "\n")
        n += 1
plain.sort()
print(f"{n} frames in {time.time() - t0:.0f} s; per frame without text reading: median {plain[len(plain)//2]:.1f} ms, 99th {plain[int(0.99*len(plain))]:.1f} ms")
