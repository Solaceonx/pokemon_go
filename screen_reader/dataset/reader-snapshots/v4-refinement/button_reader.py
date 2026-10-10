"""Calibrated, offline battle-control reader. Does not send taps to a device."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
if (ROOT / "tools/python-libs").exists():
    sys.path.insert(0, str(ROOT / "tools/python-libs"))

import cv2
import numpy as np
from PIL import Image, ImageDraw


def edges(rgb):
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    return cv2.Canny(gray, 25, 70)


class ButtonReader:
    """A layout profile is mandatory; positions are never inferred from video borders."""

    def __init__(self, profile_path=ROOT / "profiles/henry.json"):
        profile_path = Path(profile_path)
        self.profile = json.loads(profile_path.read_text(encoding="utf-8"))
        self.templates = []
        for entry in self.profile["labels"]:
            image = np.asarray(Image.open(profile_path.parent / entry["file"]).convert("RGB"))
            self.templates.append((entry, edges(image)))
        self.modal = edges(np.asarray(Image.open(profile_path.parent / self.profile["replacement_label"]).convert("RGB")))

    def _match(self, screen, template, region):
        x0, y0, x1, y1 = map(int, region)
        area = screen[y0:y1, x0:x1]
        if min(area.shape) == 0 or area.shape[0] < template.shape[0] or area.shape[1] < template.shape[1]:
            return 0.0
        result = cv2.matchTemplate(area, template, cv2.TM_CCOEFF_NORMED)
        return float(cv2.minMaxLoc(result)[1])

    @staticmethod
    def _charge_evidence(rgb, center):
        # Ready buttons have a full-size colored disk and a bright circular rim.
        # Uncharged buttons have a smaller disk with a dark upper portion.
        # Ignore the much larger rings drawn by the recording's touch overlay.
        x, y = center
        x0, y0 = max(0, x-72), max(0, y-72)
        patch = rgb[y0:min(rgb.shape[0], y+73), x0:min(rgb.shape[1], x+73)]
        hsv = cv2.cvtColor(patch, cv2.COLOR_RGB2HSV)
        yy, xx = np.indices(patch.shape[:2]); yy += y0; xx += x0
        radius = np.sqrt((xx-x)**2 + (yy-y)**2)
        inner = radius < 38
        colored = (hsv[:, :, 1] > 45) & (hsv[:, :, 2] > 90)
        fill = float(colored[inner].mean())
        upper = inner & (yy < y-5)
        upper_fill = float(colored[upper].mean())
        # Require a rim at the expected button radius, rather than any Hough circle.
        angles = np.linspace(0, 2*math.pi, 72, endpoint=False)[:, None]
        radii = np.arange(44, 68)[None, :]
        px = np.rint(x+radii*np.cos(angles)).astype(int)
        py = np.rint(y+radii*np.sin(angles)).astype(int)
        valid = (px >= 0) & (px < rgb.shape[1]) & (py >= 0) & (py < rgb.shape[0])
        pixels = rgb[np.clip(py, 0, rgb.shape[0]-1), np.clip(px, 0, rgb.shape[1]-1)].astype(int)
        support = valid & (pixels.min(axis=2) > 170) & (pixels.max(axis=2)-pixels.min(axis=2) < 75)
        rim = float(support.any(axis=1).mean())
        if rim > 0.70 and fill > 0.55 and upper_fill > 0.45:
            enabled = True
        elif rim < 0.45 and upper_fill < 0.40:
            enabled = False
        else:
            enabled = None
        return enabled, {"bright_rim_fraction": round(rim, 3), "colored_disk_fraction": round(fill, 3), "upper_colored_fraction": round(upper_fill, 3)}

    def detect(self, image, viewport=None):
        image = image.convert("RGB")
        # viewport uses source-image pixel coordinates, x,y,width,height.
        if viewport is None:
            if image.width >= image.height:
                raise ValueError("A landscape video frame needs --viewport x,y,width,height; exclude creator overlays.")
            viewport = (0, 0, image.width, image.height)
        vx, vy, vw, vh = viewport
        if min(vw, vh) <= 0 or vx < 0 or vy < 0 or vx+vw > image.width or vy+vh > image.height:
            raise ValueError("Viewport is outside the supplied image.")
        reference_aspect = self.profile["width"] / self.profile["height"]
        if abs(vw/vh/reference_aspect-1) > 0.06:
            raise ValueError("Screenshot aspect ratio differs from the calibrated profile. Calibrate a device profile first.")
        resized = image.crop((vx, vy, vx+vw, vy+vh)).resize((508, 1080), Image.Resampling.LANCZOS)
        rgb = np.asarray(resized)
        edge_image = edges(rgb)
        modal_score = self._match(edge_image, self.modal, (80, 820, 430, 905))
        replacement = modal_score >= 0.62

        def point(x, y):
            return [round(vx+x/508*vw), round(vy+y/1080*vh)]

        def box(x0, y0, x1, y1):
            return point(x0, y0) + point(x1, y1)

        buttons = []
        label_matches = []
        charge_candidates = []
        for slot, cx in enumerate([148, 361]):
            candidates = []
            for entry, template in self.templates:
                for scale in [0.65, 1.0, 1.5]:
                    tw = max(2, round(template.shape[1]*scale))
                    th = max(2, round(template.shape[0]*scale))
                    scaled = cv2.resize(template, (tw, th), interpolation=cv2.INTER_NEAREST)
                    score = self._match(edge_image, scaled, (max(0, cx-112), 886, min(508, cx+112), 946))
                    candidates.append((score, entry["name"]))
            score, name = max(candidates)
            label_matches.append(round(score, 3))
            charge_candidates.append((slot, cx, score, name))
        companion_label_present = max(label_matches) >= 0.46
        for slot, cx, score, name in charge_candidates:
            enabled, evidence = self._charge_evidence(rgb, (cx, 978))
            # A fully illuminated icon can locate an obscured-label button, provided
            # another charge label establishes that the combat-control layout is present.
            icon_fallback = companion_label_present and enabled is True and score < 0.46
            if (score >= 0.46 or icon_fallback) and not replacement:
                buttons.append({"id": f"charge_{slot}", "kind": "charge", "name": None if icon_fallback else name,
                                "visible": True, "visually_enabled": enabled,
                                "tap_px": point(cx, 978), "tap_normalized": [round(cx/508, 4), round(978/1080, 4)],
                                "bounds_px": box(cx-52, 925, cx+52, 1031),
                                "match_score": round(score, 3), "evidence": evidence,
                                "detection_method": "icon_with_companion_label" if icon_fallback else "label_template"})

        # Detect teal rounded card borders. Square aspect distinguishes them from HP bars.
        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
        mask = cv2.inRange(hsv, np.array([65, 35, 70]), np.array([110, 255, 255]))
        contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        cards = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if replacement:
                valid = 115 <= x <= 380 and 892 <= y <= 920 and 65 <= w <= 110 and 65 <= h <= 110
            else:
                valid = 415 <= x <= 480 and 605 <= y <= 755 and 50 <= w <= 90 and 50 <= h <= 90
            if not valid or not 0.75 <= w/h <= 1.30:
                continue
            if any(abs(x-c[0]) < 12 and abs(y-c[1]) < 12 for c in cards):
                continue
            cards.append((x, y, w, h))
        cards.sort(key=lambda c: (c[1], c[0]))
        phase = "replacement" if replacement else ("combat_controls" if buttons else "unknown")
        for x, y, w, h in cards:
            border = hsv[y:y+h, x:x+w]
            teal = (border[:, :, 0] >= 65) & (border[:, :, 0] <= 110) & (border[:, :, 1] > 35)
            brightness = float(np.median(border[:, :, 2][teal])) if teal.any() else 0.0
            # A visible card does not prove switch cooldown is over. Only the replacement
            # prompt is sufficient evidence of an immediately offered selection here.
            slot = ("left" if x < 254 else "right") if replacement else ("top" if y < 700 else "bottom")
            buttons.append({"id": f"{'replacement' if replacement else 'switch'}_{slot}",
                            "kind": "replacement" if replacement else "switch", "visible": True,
                            "visually_enabled": True if replacement else None,
                            "tap_px": point(x+w/2, y+h/2),
                            "tap_normalized": [round((x+w/2)/508, 4), round((y+h/2)/1080, 4)],
                            "bounds_px": box(x, y, x+w, y+h),
                            "evidence": {"teal_border_brightness": round(brightness, 1), "cooldown": "not_applicable" if replacement else "unknown"}})
        return {"profile": self.profile["id"], "phase": phase,
                "viewport_px": list(viewport), "buttons": buttons,
                "fast_move_tap_px": point(254, 580) if phase == "combat_controls" else None,
                "fast_move_tap_normalized": [0.5, round(580/1080, 4)] if phase == "combat_controls" else None,
                "diagnostics": {"charge_label_match_scores": label_matches, "replacement_prompt_score": round(modal_score, 3)},
                "requires_temporal_confirmation": True}


class TemporalGate:
    """Require two consecutive observations; reset on hidden controls or frame gaps."""
    def __init__(self, max_gap_seconds=0.75):
        self.previous = None
        self.previous_time = None
        self.max_gap = max_gap_seconds

    def update(self, reading, timestamp):
        adjacent = self.previous_time is not None and 0 < timestamp-self.previous_time <= self.max_gap
        same_phase = adjacent and self.previous["phase"] == reading["phase"]
        previous_buttons = {b["id"]: b for b in self.previous["buttons"]} if same_phase else {}
        for button in reading["buttons"]:
            before = previous_buttons.get(button["id"])
            # Identity and location must also agree; cards can reorder after a faint.
            consistent = before is not None and before.get("name") == button.get("name") and np.linalg.norm(np.array(before["tap_normalized"])-button["tap_normalized"]) < 0.02
            button["confirmed_enabled"] = bool(consistent and button["visually_enabled"] is True and before["visually_enabled"] is True)
        reading["combat_controls_stable"] = bool(same_phase and reading["phase"] == "combat_controls")
        self.previous = reading
        self.previous_time = timestamp
        return reading


def annotate(image, reading):
    annotated = image.copy().convert("RGB")
    draw = ImageDraw.Draw(annotated)
    for b in reading["buttons"]:
        state = b["visually_enabled"]
        color = "#35e898" if state is True else ("#ffb84d" if state is False else "#72b9ff")
        draw.rectangle(b["bounds_px"], outline=color, width=3)
        x, y = b["tap_px"]
        draw.ellipse((x-5, y-5, x+5, y+5), fill=color)
        label = f"{b['id']}: { {True: 'ready', False: 'not ready', None: 'unknown'}[state]}"
        label_width = draw.textbbox((0, 0), label)[2]
        vx, vy, vw, vh = reading["viewport_px"]
        label_x = max(vx, min(b["bounds_px"][0], vx+vw-label_width-3))
        draw.text((label_x, b["bounds_px"][1]-15), label, fill=color, stroke_width=1, stroke_fill="black")
    if reading["fast_move_tap_px"]:
        x, y = reading["fast_move_tap_px"]
        draw.ellipse((x-8, y-8, x+8, y+8), outline="white", width=3)
        draw.text((x+12, y), "fast move", fill="white", stroke_width=1, stroke_fill="black")
    draw.text((reading["viewport_px"][0]+10, 125), reading["phase"], fill="white", stroke_width=1, stroke_fill="black")
    return annotated


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--profile", type=Path, default=ROOT / "profiles/henry.json")
    parser.add_argument("--viewport", help="x,y,width,height in input pixels")
    parser.add_argument("--output", type=Path, default=ROOT / "output")
    parser.add_argument("--start", type=float, default=0)
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--fps", type=float, default=2)
    args = parser.parse_args()
    viewport = tuple(map(int, args.viewport.split(","))) if args.viewport else None
    if viewport is not None and len(viewport) != 4:
        parser.error("--viewport needs four integers")
    reader = ButtonReader(args.profile)
    args.output.mkdir(parents=True, exist_ok=True)
    if args.input.suffix.lower() not in {".mp4", ".mov", ".mkv"}:
        with Image.open(args.input) as source:
            reading = reader.detect(source, viewport)
            (args.output / f"{args.input.stem}.json").write_text(json.dumps(reading, indent=2), encoding="utf-8")
            annotate(source, reading).save(args.output / f"{args.input.stem}-buttons.png")
        print(json.dumps(reading, indent=2))
        return
    if args.fps <= 0 or args.seconds <= 0 or args.start < 0:
        parser.error("fps and seconds must be positive; start must be nonnegative")
    import av
    gate = TemporalGate()
    next_time = args.start
    counts = {}
    with av.open(str(args.input)) as container, (args.output / "observations.jsonl").open("w", encoding="utf-8") as output:
        container.streams.video[0].codec_context.thread_count = 2
        container.seek(int(args.start*av.time_base))
        for frame in container.decode(video=0):
            if frame.time is None or frame.time < next_time:
                continue
            if frame.time >= args.start+args.seconds:
                break
            reading = gate.update(reader.detect(frame.to_image(), viewport), frame.time)
            reading["timestamp_seconds"] = round(frame.time, 3)
            output.write(json.dumps(reading)+"\n")
            counts[reading["phase"]] = counts.get(reading["phase"], 0)+1
            next_time = frame.time+1/args.fps
    print(json.dumps({"phase_counts": counts, "output": str(args.output / "observations.jsonl")}))


if __name__ == "__main__":
    main()
