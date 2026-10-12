"""Refine faint markers from pixels without repeating OCR or replacing raw logs."""
import gzip
import json
from pathlib import Path
import time

from vod_media import sha256, write_json
from vod import ROOT


def party_patch(hsv, np):
    red = ((hsv[:, :, 0] < 12) | (hsv[:, :, 0] > 170)) & (hsv[:, :, 1] > 120) & (hsv[:, :, 2] > 130)
    dark = hsv[:, :, 2] < 135
    if float(red.mean()) > .10:
        return True
    # A dark marker need not occupy half of a 13x13 patch: outline compression
    # and a small row offset put pale header pixels around the empty circle.
    if float(dark.mean()) > .16:
        return False
    return None


def refine(folder, raw, iter_rows):
    import av
    import cv2
    import numpy as np
    from health_reader import read_health_bar
    from health_tracker import HealthTracker
    from buttons import one
    health_tracker = HealthTracker()
    meta = json.loads((folder / "battle.json").read_text(encoding="utf-8"))
    profile = json.loads((raw / "profile.json").read_text(encoding="utf-8"))
    calibration_path = ROOT / "data/vod_tracking_layouts.json"
    calibration = json.loads(calibration_path.read_text())["layouts"].get(f"{meta['reference_id']}:{meta['view_id']}")
    fingerprint = {"video_sha256": meta["video_sha256"], "screen_sha256": sha256(raw / "screen.jsonl.gz"),
                   "slim_sha256": sha256(raw / "readings.jsonl.gz"), "profile_sha256": sha256(raw / "profile.json"),
                   "code_sha256": sha256(__file__), "button_calibration_sha256": sha256(calibration_path),
                   "button_measurement_sha256": sha256(ROOT / "scripts/recording/buttons.py")}
    receipt = raw / "markers.json"
    if receipt.exists() and json.loads(receipt.read_text())["fingerprint"] == fingerprint:
        return
    rich = iter(iter_rows(raw / "screen.jsonl.gz"))
    slim = iter(iter_rows(raw / "readings.jsonl.gz"))
    reading, short = next(rich), next(slim)
    names = ["screen-refined.jsonl.gz", "readings-refined.jsonl.gz"]
    streams = [gzip.open(raw / (n + ".incomplete"), "wt", encoding="utf-8") for n in names]
    count = 0
    try:
        with av.open(str(folder / meta["video_file"])) as media:
            media.streams.video[0].codec_context.thread_count = 2
            for index, frame in enumerate(media.decode(video=0)):
                if index < reading["frame_index"]:
                    continue
                if index != reading["frame_index"]:
                    raise ValueError("Refinement differs from original frame ordinal")
                rgb = np.asarray(frame.to_image().resize((508, 1080)))
                if calibration:
                    discs = [one(rgb, x, calibration["center_y"], calibration["radius"]) for x in calibration["centers_x"]]
                    short["b"] = {key: [v["fill"], int(v["present"]), int(v["ready"])] for key, v in zip(("l", "r"), discs)}
                    for button in reading["buttons"]:
                        if button["id"] not in ("charge_0", "charge_1"):
                            continue
                        slot = int(button["id"][-1]); disc = discs[slot]
                        cx, cy = calibration["centers_x"][slot], calibration["center_y"]
                        button["tap_px"] = [round(cx*frame.width/508), round(cy*frame.height/1080)]
                        button["bounds_px"] = [round((cx-52)*frame.width/508), round((cy-53)*frame.height/1080),
                                               round((cx+52)*frame.width/508), round((cy+53)*frame.height/1080)]
                        button["visually_enabled"] = disc["ready"] if disc["present"] else None
                        button["disc_measurement"] = disc
                for side, key in (("mine", "m"), ("opponent", "o")):
                    if reading[side]["health_bar"].get("value") is None:
                        region = [5, 240, 225, 900] if side == "mine" else [230, 240, 505, 850]
                        bar = read_health_bar(rgb, region, profile["hp_width"])
                        if bar:
                            x0, y0, x1, y1 = bar.pop("bounds")
                            bar["bounds_px"] = [round(x0*frame.width/508), round(y0*frame.height/1080),
                                                round(x1*frame.width/508), round(y1*frame.height/1080)]
                            bar["measurement_region"] = region
                            reading[side]["health_bar"] = {"value": bar, "status": "observed", "evidence": {
                                "method": "expanded_species_height_region", "observed_at_seconds": reading["timestamp_seconds"]}}
                            short[key].update(hp=bar["fraction"], seg=[[z["color"], z["pixels"]] for z in bar["segments"]],
                                              w=bar["interior_width_pixels"])
                    cp = reading[side]["cp"]
                    bounds = cp.get("evidence", {}).get("bounds_normalized_frame")
                    seen = cp.get("evidence", {}).get("observed_at_seconds")
                    if cp.get("value") is None or not bounds or seen is None or not 0 <= frame.time - seen <= .75:
                        continue
                    y = round((bounds[1] + bounds[3]) / 2 + profile["marker_y"] - sum(profile["name_y"]) / 2)
                    left, right = (12, 211) if side == "mine" else (301, 499)
                    panel = cv2.cvtColor(rgb[round(bounds[3]) + 1:y + 9, left:right], cv2.COLOR_RGB2HSV)
                    if not panel.size or float(((panel[:, :, 1] < 75) & (panel[:, :, 2] > 175)).mean()) < .35:
                        continue
                    states = [party_patch(cv2.cvtColor(rgb[y-6:y+7, x-6:x+7], cv2.COLOR_RGB2HSV), np)
                              for x in ([26, 54, 82] if side == "mine" else [427, 455, 482])]
                    value = sum(states) if None not in states else None
                    reading[side]["pokemon_left"] = {"value": value, "status": "observed" if value is not None else "unknown",
                        "evidence": {"method": "refined_dark_marker_area", "marker_states": states, "marker_y": y,
                                     "frame_index": index, "observed_at_seconds": reading["timestamp_seconds"]}}
                    short[key]["left"] = value
                health_tracker.update(reading)
                for stream, row in zip(streams, (reading, short)):
                    stream.write(json.dumps(row, separators=(",", ":"), ensure_ascii=False) + "\n")
                count += 1
                reading, short = next(rich, None), next(slim, None)
                if reading is None or short is None:
                    if reading is not short:
                        raise ValueError("Rich and slim logs have different lengths")
                    break
    finally:
        for stream in streams:
            stream.close()
    if reading is not None:
        raise ValueError("Video ended before all saved readings")
    for name in names:
        (raw / (name + ".incomplete")).replace(raw / name)
    write_json(receipt, {"fingerprint": fingerprint, "refined_samples": count, "repeated_ocr": False,
                         "raw_readings_preserved": True})
