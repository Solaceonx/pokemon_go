"""Read the announcement text in the middle of the screen and the shield prompt, a few times a second."""
import json, sys, time, warnings
warnings.filterwarnings("ignore")
import av, numpy as np
from local_ocr import LocalOCR
video, out_path, rate = sys.argv[1], sys.argv[2], float(sys.argv[3])
ocr = LocalOCR()
c = av.open(video); v = c.streams.video[0]
t0 = time.time(); next_t = float(sys.argv[4]) if len(sys.argv) > 4 else 0.0; n = 0  # optional: second to start from
with open(out_path, "w") as out:
    for frame in c.decode(v):
        t = float(frame.pts * v.time_base)
        if t < next_t: continue
        next_t = t + 1.0 / rate
        img = frame.to_image()
        w, h = img.size
        texts = []
        for name, (a, b) in (("middle", (0.22, 0.44)), ("prompt", (0.64, 0.80))):
            band = np.asarray(img.crop((0, int(a * h), w, int(b * h))).resize((w * 2 // 3, int((b - a) * h * 2 / 3))))
            for r in ocr.read(band):
                if r.get("text", "").strip(): texts.append([name, r["text"].strip()])
        out.write(json.dumps({"t": round(t, 3), "text": texts}) + "\n"); n += 1
        if n == 8: print(f"about {(time.time() - t0) / 8:.2f} s per look", flush=True)
print(f"{n} looks in {time.time() - t0:.0f} s")
