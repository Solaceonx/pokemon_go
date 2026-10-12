"""Frame-by-frame visual battle observations with explicit unknowns and source times."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import time

from button_reader import ROOT, ButtonReader, Image, ImageDraw, cv2, edges, np
from health_reader import read_health_bar, read_card_health
from health_tracker import HealthTracker
from scene_tracker import SceneTracker
from local_ocr import LocalOCR, compact
from battle_io import open_log
from project_paths import game_data_path


def observed(value, **evidence):
    return {"value": value, "status": "observed" if value is not None else "unknown", "evidence": evidence}


def unknown(reason):
    return {"value": None, "status": "unknown", "reason": reason}


class BattleReader:
    def __init__(self, profile, ocr=None, ocr_interval=0.5):
        path = Path(profile)
        self.profile = json.loads(path.read_text(encoding="utf-8"))
        self.templates = [(entry, edges(np.asarray(Image.open(path.parent / entry["file"]).convert("RGB"))))
                          for entry in self.profile["templates"]]
        self.ocr = ocr
        self.ocr_interval = ocr_interval
        self.last_ocr_time = None
        self.text = []
        self.health_tracker = HealthTracker()
        self.scene_tracker = SceneTracker()
        self.species_lexicon = {compact(name): name for name in self.profile["species_lexicon"]}
        self.move_lexicon = {compact(name): name for name in self.profile["known_moves"]}
        data_path = game_data_path()
        if data_path.exists():
            data = json.loads(data_path.read_text(encoding="utf-8"))
            # Header names omit forms. Preserve the visible base name without
            # selecting a Shadow/regional form from a default game-data entry.
            for entry in data["pokemon"]:
                name = re.sub(r"\s*\([^)]*\)", "", entry["speciesName"]).strip()
                self.species_lexicon.setdefault(compact(name), name)
            for entry in data["moves"]:
                self.move_lexicon.setdefault(compact(entry["name"]), entry["name"])

    def _templates(self, edge_image):
        results = []
        for entry, template in self.templates:
            x0, y0, x1, y1 = entry["search"]
            region = edge_image[y0:y1, x0:x1]
            if region.shape[0] < template.shape[0] or region.shape[1] < template.shape[1]:
                continue
            score = float(cv2.minMaxLoc(cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED))[1])
            if score >= (0.60 if entry["kind"] == "phase" else 0.48):
                results.append({**entry, "match_score": round(score, 4)})
        return results

    def _header(self, side, text_fresh):
        y0, y1 = self.profile["name_y"]
        area = (0, 235) if side == "mine" else (280, 508)
        rows = [r for r in self.text if area[0] <= sum(r["bounds"][::2])/2 <= area[1]
                and y0 <= sum(r["bounds"][1::2])/2 <= y1]
        cp = next((r for r in rows if re.fullmatch(r"CP\s*\d{1,5}", r["text"], re.I)), None)
        lexicon = self.species_lexicon
        name = next((r for r in rows if compact(r["text"]) in lexicon), None)
        def field(record, value):
            if record is None:
                return unknown("No recognized header text at the most recent OCR observation")
            result = observed(value, raw_text=record["text"], ocr_confidence=record["confidence"],
                              observed_at_seconds=self.last_ocr_time, bounds_normalized_frame=record["bounds"])
            if record.get("method"):
                result["evidence"]["method"] = record["method"]
            if not text_fresh:
                result["status"] = "stale"
            return result
        return {"species": field(name, lexicon[compact(name["text"])] if name else None),
                "cp": field(cp, int(re.search(r"\d+", cp["text"]).group()) if cp else None)}

    def _markers(self, rgb, side):
        y = self.profile["marker_y"]
        party_x = [26, 54, 82] if side == "mine" else [427, 455, 482]
        shield_x = [118, 143] if side == "mine" else [365, 389]
        def patch(x, radius):
            return cv2.cvtColor(rgb[y-radius:y+radius+1, x-radius:x+radius+1], cv2.COLOR_RGB2HSV)
        party = []
        for x in party_x:
            hsv = patch(x, 6)
            red = ((hsv[:, :, 0] < 12) | (hsv[:, :, 0] > 170)) & (hsv[:, :, 1] > 120) & (hsv[:, :, 2] > 130)
            if float(red.mean()) > 0.10:
                party.append(True)
            elif float(np.median(hsv[:, :, 2])) < 135:
                party.append(False)
            else:
                party.append(None)
        shields = []
        for x in shield_x:
            hsv = patch(x, 5)
            hue = float(np.median(hsv[:, :, 0])); value = float(np.median(hsv[:, :, 2]))
            if 110 <= hue <= 170 and value > 160:
                shields.append(True)
            elif 110 <= hue <= 170 and value < 145:
                shields.append(False)
            else:
                shields.append(None)
        # Never read sky/field/background at marker positions as zero counts.
        party_count = sum(party) if None not in party else None
        shield_count = sum(shields) if None not in shields and party_count is not None else None
        return observed(party_count, marker_states=party), observed(shield_count, marker_states=shields)

    def detect(self, image, timestamp, frame_index=None, viewport=None, force_ocr=False):
        image = image.convert("RGB")
        if viewport is None:
            viewport = self.profile["viewport"] if image.width >= image.height else [0, 0, image.width, image.height]
        vx, vy, vw, vh = map(int, viewport)
        if min(vw, vh) <= 0 or vx < 0 or vy < 0 or vx+vw > image.width or vy+vh > image.height:
            raise ValueError("Invalid gameplay viewport")
        if abs((vw/vh)/(508/1080)-1) > 0.08:
            raise ValueError("Viewport does not match this calibrated layout")
        phone = image.crop((vx, vy, vx+vw, vy+vh)).resize((508, 1080))
        rgb = np.asarray(phone)
        text_fresh = False
        if self.ocr and (force_ocr or self.last_ocr_time is None or timestamp-self.last_ocr_time >= self.ocr_interval-1e-6):
            self.text = self.ocr.read(rgb)
            # Small header/move text is easily lost when OCR scales a whole phone
            # frame. Read enlarged strips, then map every box back to phone pixels.
            header_low=max(0,self.profile["name_y"][0]-12)
            header_high=min(1080,self.profile["name_y"][1]+12)
            for low, high, method in [(header_low,header_high,"enlarged_header_ocr"), (900,1050,"enlarged_move_ocr")]:
                records=self.ocr.read(cv2.resize(rgb[low:high], None, fx=2, fy=2))
                if method=="enlarged_header_ocr" and records:
                    self.text=[r for r in self.text if not low<=sum(r["bounds"][1::2])/2<=high]
                for r in records:
                    x0,y0,x1,y1=r["bounds"]
                    self.text.append({**r,"bounds":[round(x0/2),round(low+y0/2),round(x1/2),round(low+y1/2)],"method":method})
            self.last_ocr_time = timestamp
            text_fresh = True
        matches = self._templates(edges(rgb))
        phase_matches = [r for r in matches if r["kind"] == "phase"]
        priority = {"choose_next": 6, "shield_prompt": 5, "opponent_charged_warning": 4,
                    "opponent_charged_resolution": 3, "my_charged_minigame": 2}
        selected = max(phase_matches, key=lambda r: (priority.get(r["phase"], 0), r["match_score"])) if phase_matches else None
        phase = selected["phase"] if selected else "unknown"
        phase_evidence = {"method": "template", "cue": selected["cue"], "match_score": selected["match_score"]} if selected else {}
        usable_text = self.text if text_fresh else []
        result = None
        for record in usable_text:
            key = compact(record["text"])
            if key in {"YOUWIN", "GOOD EFFORT".replace(" ", ""), "YOULOSE", "DRAW"}:
                result = {"YOUWIN": "win", "GOODEFFORT": "loss", "YOULOSE": "loss", "DRAW": "draw"}[key]
                phase = "result"
                phase_evidence = {"method": "ocr", "raw_text": record["text"], "ocr_confidence": record["confidence"]}
            elif key.startswith("GO") and key[2:] in self.species_lexicon and record["bounds"][1] > 180:
                phase = "switching_in"
                phase_evidence = {"method": "ocr", "raw_text": record["text"], "ocr_confidence": record["confidence"]}
            elif "USED" in key and record["bounds"][1] > 180:
                phase = "charged_resolution"
                phase_evidence = {"method": "ocr", "raw_text": record["text"]}
            elif "ATTACKINCOMING" in key or "USEAPROTECTSHIELD" in key:
                phase = "shield_prompt"
                phase_evidence = {"method":"ocr","raw_text":record["text"]}
            elif "SWITCHINANEWPOKEMON" in key:
                phase = "choose_next"
                phase_evidence = {"method":"ocr","raw_text":record["text"]}
            elif key in {"GETREADY","SWIPE"} or key.startswith("SWIPE"):
                phase = "my_charged_minigame"
                phase_evidence = {"method":"ocr","raw_text":record["text"]}
        def point(x, y):
            return [round(vx+x/508*vw), round(vy+y/1080*vh)]
        def box(bounds):
            return point(bounds[0], bounds[1])+point(bounds[2], bounds[3])

        buttons = []
        charges = [r for r in matches if r["kind"] == "charge"]
        canonical_moves = self.move_lexicon
        for record in usable_text:
            if record["bounds"][1] > 880 and compact(record["text"]) in canonical_moves:
                slot = 0 if sum(record["bounds"][::2])/2 < 254 else 1
                charges = [r for r in charges if r["slot"] != slot]
                charges.append({"kind": "charge", "slot": slot,
                                "move": canonical_moves[compact(record["text"])], "match_score": record["confidence"]})
        active_name = self._header("mine", text_fresh)["species"]["value"]
        allowed_moves = self.profile.get("team_moves", {}).get(active_name)
        if allowed_moves:
            charges = [r for r in charges if r["move"] in allowed_moves]
        if phase == "unknown" and len({r["slot"] for r in charges}) < 2:
            # Exact slot geometry plus both marker rows guards against treating touch
            # rings or charge-minigame bubbles as the normal combat buttons.
            mine_cp = self._header("mine", text_fresh)["cp"]
            opponent_cp = self._header("opponent", text_fresh)["cp"]
            if mine_cp["value"] is not None and opponent_cp["value"] is not None:
                area = cv2.cvtColor(rgb[900:1040], cv2.COLOR_RGB2GRAY)
                circles = cv2.HoughCircles(cv2.GaussianBlur(area, (5, 5), 0), cv2.HOUGH_GRADIENT, 1, 90,
                                           param1=60, param2=15, minRadius=35, maxRadius=65)
                located = []
                for slot, (cx, cy) in enumerate(self.profile["charge_centers"]):
                    if circles is not None and any(abs(c[0]-cx) <= 14 and abs(c[1]+900-cy) <= 14 for c in circles[0]):
                        located.append(slot)
                if len(located) == 2:
                    for slot in located:
                        if not any(r["slot"] == slot for r in charges):
                            charges.append({"kind": "charge", "slot": slot, "move": None, "match_score": 0,
                                            "method": "paired_circle_geometry"})
        if phase not in {"shield_prompt", "choose_next", "my_charged_minigame", "result"}:
            for slot, (cx, cy) in enumerate(self.profile["charge_centers"]):
                labels = [r for r in charges if r["slot"] == slot]
                if not labels:
                    continue
                label = max(labels, key=lambda r: r["match_score"])
                enabled, evidence = ButtonReader._charge_evidence(rgb, (cx, cy))
                buttons.append({"id": f"charge_{slot}", "kind": "charge", "move": label["move"],
                                "tap_px": point(cx, cy), "bounds_px": box([cx-52, cy-53, cx+52, cy+53]),
                                "visually_enabled": enabled, "evidence": evidence,
                                "identity_status": "observed" if label["move"] else "unknown",
                                "energy": unknown("Pixel fill has not been calibrated to energy units"),
                                "second_use_ready": unknown("Second-use energy indicator not calibrated")})
            if buttons and phase == "unknown" and all(self._header(s,text_fresh)["cp"]["value"] is not None for s in ["mine","opponent"]):
                phase = "normal_fighting"
                phase_evidence = {"method": "charge_labels", "labels": [b["move"] for b in buttons]}

        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
        mask = cv2.inRange(hsv, np.array([65, 35, 70]), np.array([110, 255, 255]))
        contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        card_bounds = []
        if phase == "choose_next":
            for record in usable_text:
                if re.fullmatch(r"CP\s*\d{1,5}", record["text"], re.I) and record["bounds"][1] > 770:
                    x = sum(record["bounds"][::2])/2; y = record["bounds"][3]+55
                    card_bounds.append([round(x-48), round(y-49), round(x+48), round(y+49)])
        elif phase not in {"my_charged_minigame", "shield_prompt", "result"}:
            for contour in contours:
                x, y, w, h = cv2.boundingRect(contour)
                if 415 <= x <= 480 and 605 <= y <= 755 and 50 <= w <= 90 and 50 <= h <= 90 and 0.75 <= w/h <= 1.30:
                    bounds = [x, y, x+w, y+h]
                    if not any(abs(x-old[0]) < 12 and abs(y-old[1]) < 12 for old in card_bounds):
                        card_bounds.append(bounds)
            for record in usable_text:
                if re.fullmatch(r"CP\s*\d{1,5}", record["text"], re.I) and 590 <= record["bounds"][1] <= 755 and record["bounds"][0] > 405:
                    cx = sum(record["bounds"][::2])/2
                    cy = sum(record["bounds"][1::2])/2+23
                    bounds = [round(cx-37), round(cy-37), round(cx+37), round(cy+37)]
                    if not any(abs(bounds[0]-old[0]) < 15 and abs(bounds[1]-old[1]) < 15 for old in card_bounds):
                        card_bounds.append(bounds)
        bench = []
        for bounds in sorted(card_bounds):
            cx = (bounds[0]+bounds[2])/2; cy = (bounds[1]+bounds[3])/2
            replacement = phase == "choose_next"
            slot = ("center" if 220 < cx < 290 else "left" if cx < 254 else "right") if replacement else ("top" if cy < 700 else "bottom")
            card_health = read_card_health(rgb, bounds)
            identity_text = [r for r in usable_text if bounds[0]-15 <= sum(r["bounds"][::2])/2 <= bounds[2]+15 and bounds[1]-35 <= r["bounds"][1] <= bounds[3]+30]
            cp_record = next((r for r in identity_text if re.fullmatch(r"CP\s*\d{1,5}", r["text"], re.I)), None)
            bench.append({"slot": slot, "species": unknown("Species sprite matching and team mapping not available"),
                          "cp": observed(int(re.search(r"\d+", cp_record["text"]).group())) if cp_record else unknown("No readable card CP"),
                          "health": observed(card_health), "bounds_px": box(bounds)})
            buttons.append({"id": f"{'replacement' if replacement else 'switch'}_{slot}",
                            "kind": "replacement" if replacement else "switch", "tap_px": point(cx, cy),
                            "bounds_px": box(bounds), "visually_enabled": True if replacement else None})

        if phase == "shield_prompt":
            # Locate the colored hexagonal shield, not the prompt or decline text.
            shield_mask = cv2.inRange(hsv[810:1010, 155:355], np.array([110, 45, 100]), np.array([175, 255, 255]))
            shield_mask = cv2.morphologyEx(shield_mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
            shield_contours, _ = cv2.findContours(shield_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for contour in sorted(shield_contours, key=cv2.contourArea, reverse=True):
                x, y, w, h = cv2.boundingRect(contour)
                if 55 <= w <= 160 and 65 <= h <= 175 and cv2.contourArea(contour) > 1800:
                    bounds = [x+155, y+810, x+155+w, y+810+h]
                    value = float(np.median(hsv[y+810:y+810+h, x+155:x+155+w, 2]))
                    buttons.append({"id": "shield", "kind": "shield", "tap_px": point(x+155+w/2, y+810+h/2),
                                    "bounds_px": box(bounds), "visually_enabled": True if value > 160 else None})
                    break
        sides = {}
        for side in ["mine", "opponent"]:
            header = self._header(side, text_fresh)
            health = read_health_bar(rgb, self.profile["health_regions"][side], self.profile["hp_width"])
            if health:
                health["bounds_px"] = box(health.pop("bounds"))
                health["note"] = "Measured on a 508-pixel normalized frame; no integer-HP guarantee"
            party, shields = self._markers(rgb, side)
            if header["cp"]["value"] is None:
                party = unknown("No recognized battle header to validate the marker locations")
                shields = unknown("No recognized battle header to validate the marker locations")
            sides[side] = {**header, "health_bar": observed(health), "shields_left": shields,
                           "pokemon_left": party, "energy": unknown("Requires verified move data and event reconstruction"),
                           "attack_stage": unknown("No persistent stage indicator calibrated"),
                           "defense_stage": unknown("No persistent stage indicator calibrated")}
        messages = [r for r in usable_text if r["bounds"][1] > 180 and
                    any(key in compact(r["text"]) for key in ["USED", "EFFECTIVE", "ATTACKROSE", "ATTACKFELL", "DEFENSEROSE", "DEFENSEFELL", "NICE", "GREAT", "EXCELLENT", "NOPROTECT"])]
        grades = [compact(r["text"]) for r in messages if compact(r["text"]) in {"NICE", "GREAT", "EXCELLENT"}]
        return self.health_tracker.update(self.scene_tracker.update({"schema_version": "battle-observation-v1", "profile": self.profile["id"],
                "frame_index": frame_index, "timestamp_seconds": round(timestamp, 6), "viewport_px": [vx, vy, vw, vh],
                "phase": observed(phase if phase != "unknown" else None, **phase_evidence),
                "mine": sides["mine"], "opponent": sides["opponent"], "buttons": buttons, "bench": bench,
                "charge_result": observed(grades[0]) if grades else unknown("No readable minigame grade"),
                "swipe_targets": unknown("Not yet calibrated; moving particles are not assumed to be targets"),
                "switch_cooldown_seconds": unknown("No validated countdown detector"),
                "battle_clock_seconds": unknown("Phone clock and prompt countdowns are not battle clocks"),
                "shield_decision_seconds": unknown("Prompt countdown digits not calibrated"),
                "result": observed(result), "messages": messages,
                "text_observation": {"observed_at_seconds": self.last_ocr_time, "fresh_this_frame": text_fresh, "records": self.text},
                "fast_move_tap_px": point(254, 580) if phase == "normal_fighting" else None}))


class EventTracker:
    """Log visual changes with time bounds. A bar change is not a verified fast hit."""
    def __init__(self):
        self.previous = None
        self.last_named_phase = None
        self.last_phase_time = None
        self.messages = {}
        self.count_history = {}
        self.identity_history = {}

    def update(self, reading):
        timestamp = reading["timestamp_seconds"]
        previous = self.previous
        events = []
        def event(kind, side=None, interval=None, **data):
            events.append({"kind": kind, "side": side, "observed_at_seconds": timestamp,
                           "frame_index": reading["frame_index"], "source_time_interval_seconds": interval or [timestamp, timestamp],
                           "data": data})
        phase = reading["phase"]["value"]
        if phase is not None and phase != self.last_named_phase:
            event("visual_phase_cue", phase=phase, evidence=reading["phase"]["evidence"],
                  meaning="First detected cue; not proof of the input-acceptance boundary")
            self.last_named_phase = phase
            self.last_phase_time = timestamp
        if previous and 0 < timestamp-previous["timestamp_seconds"] <= 0.2:
            interval = [previous["timestamp_seconds"], timestamp]
            for side in ["mine", "opponent"]:
                current_side = reading[side]; previous_side = previous[side]
                before = previous_side["health_bar"]["value"]; after = current_side["health_bar"]["value"]
                same_known_identity = (current_side["species"]["value"] is not None and current_side["species"]["value"] == previous_side["species"]["value"] and
                                       current_side["cp"]["value"] == previous_side["cp"]["value"])
                if before and after and before["interior_width_pixels"] == after["interior_width_pixels"] and same_known_identity:
                    delta = after["fraction"]-before["fraction"]
                    if abs(delta) >= max(after["pixel_resolution_fraction"], before["pixel_resolution_fraction"])*0.8:
                        event("health_bar_change", side, interval, before_fraction=before["fraction"], after_fraction=after["fraction"],
                              delta_fraction=round(delta, 5), cause="unknown", verified_fast_move=False,
                              integer_hp_delta=None, pending_damage_interpretation="unknown")
        for side in ["mine", "opponent"]:
            for field in ["shields_left", "pokemon_left"]:
                current = reading[side][field]["value"]
                key = (side, field)
                before = self.count_history.get(key)
                if current is not None:
                    if before is not None and current != before["value"]:
                        event("shield_count_change" if field == "shields_left" else "party_marker_change", side,
                              [before["time"], timestamp], before=before["value"], after=current,
                              interpretation="possible_reset_or_video_cut" if current > before["value"] else "visual_count_decreased")
                    self.count_history[key] = {"value": current, "time": timestamp}
            identity = reading[side]["species"]
            if identity["status"] == "observed" and identity["value"] is not None:
                before = self.identity_history.get(side)
                if before is not None and before["value"] != identity["value"]:
                    event("active_identity_change", side, [before["time"], timestamp], before=before["value"], after=identity["value"],
                          voluntary_switch=None, switch_timer_started=False)
                self.identity_history[side] = {"value": identity["value"], "time": timestamp}
        for message in reading["messages"]:
            key = compact(message["text"])
            if timestamp-self.messages.get(key, -100) > 1.0:
                event("battle_text", raw_text=message["text"], confidence=message["confidence"], bounds=message["bounds"])
            self.messages[key] = timestamp
        self.previous = reading
        return events


def annotate_battle(image, reading):
    output = image.copy().convert("RGB"); draw = ImageDraw.Draw(output)
    vx, vy, vw, vh = reading["viewport_px"]
    draw.text((vx+8, vy+155), "phase: "+str(reading["phase"]["value"]), fill="white", stroke_width=1, stroke_fill="black")
    for side in ["mine", "opponent"]:
        hp = reading[side]["health_bar"]["value"]
        if hp:
            x0, y0, x1, y1 = hp["bounds_px"]
            draw.rectangle((x0, y0, x1, y1), outline="#ffd34d", width=2)
            draw.text((x0, y0-15), f"{side}: {hp['fraction']:.1%}", fill="#ffd34d", stroke_width=1, stroke_fill="black")
    for button in reading["buttons"]:
        color = "#35e898" if button["visually_enabled"] is True else ("#ffb84d" if button["visually_enabled"] is False else "#72b9ff")
        draw.rectangle(button["bounds_px"], outline=color, width=2)
        x, y = button["tap_px"]; draw.ellipse((x-4, y-4, x+4, y+4), fill=color)
        text = button["id"]
        width = draw.textbbox((0, 0), text)[2]
        x0 = max(vx, min(button["bounds_px"][0], vx+vw-width-2))
        draw.text((x0, button["bounds_px"][1]-15), text, fill=color, stroke_width=1, stroke_fill="black")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--viewport")
    parser.add_argument("--start", type=float, default=0)
    parser.add_argument("--seconds", type=float)
    parser.add_argument("--ocr-interval", type=float, default=0.5)
    parser.add_argument("--no-ocr", action="store_true")
    parser.add_argument("--compress-logs", action="store_true", help="Write observations/events as lossless .jsonl.gz without plain duplicates")
    args = parser.parse_args()
    if args.start < 0 or (args.seconds is not None and args.seconds <= 0) or args.ocr_interval <= 0:
        parser.error("Invalid time interval")
    viewport = list(map(int, args.viewport.split(","))) if args.viewport else None
    if viewport is not None and len(viewport) != 4:
        parser.error("viewport needs x,y,width,height")
    args.output.mkdir(parents=True, exist_ok=True)
    reader = BattleReader(args.profile, None if args.no_ocr else LocalOCR(), args.ocr_interval)
    if args.input.suffix.lower() not in {".mp4", ".mov", ".mkv"}:
        with Image.open(args.input) as image:
            reading = reader.detect(image, 0, viewport=viewport, force_ocr=True)
            (args.output / "observation.json").write_text(json.dumps(reading, indent=2), encoding="utf-8")
            annotate_battle(image, reading).save(args.output / "annotated.png")
        print(json.dumps({"phase": reading["phase"]["value"], "output": str(args.output)}))
        return
    import av
    tracker = EventTracker(); counts = {}; count = 0; events_count = 0; last_progress = time.monotonic()
    suffix = ".jsonl.gz" if args.compress_logs else ".jsonl"
    with av.open(str(args.input)) as container, open_log(args.output / ("observations"+suffix), "wt") as observations, open_log(args.output / ("events"+suffix), "wt") as events_output:
        stream = container.streams.video[0]; stream.codec_context.thread_count = 2
        rate = float(stream.average_rate) if stream.average_rate else None
        manifest = {"source": str(args.input.resolve()), "profile": reader.profile["id"],
                    "fps": rate, "meets_30_fps_minimum": rate is not None and rate >= 29.97,
                    "original_phone_recording": False, "timing_validated": False,
                    "start_seconds": args.start, "requested_duration_seconds": args.seconds,
                    "ocr_interval_seconds": args.ocr_interval, "processed_every_decoded_frame": True,
                    "audio_hit_detection": "not_implemented", "engine_replay": "not_connected",
                    "frame_index_semantics": "decoded ordinal after seek, not absolute source-frame number",
                    "timestamp_basis": "source presentation timestamp; never inferred from frame count",
                    "log_compression": "gzip" if args.compress_logs else "none",
                    "observations_file": "observations"+suffix, "events_file": "events"+suffix}
        container.seek(int(args.start*av.time_base))
        first_time = None; last_time = None; source_gaps = []
        for index, frame in enumerate(container.decode(video=0)):
            if frame.time is None or frame.time < args.start:
                continue
            if args.seconds is not None and frame.time >= args.start+args.seconds:
                break
            if first_time is None:
                first_time = frame.time
            if last_time is not None and rate and frame.time-last_time > 2/rate:
                source_gaps.append({"before": last_time, "after": frame.time})
            reading = reader.detect(frame.to_image(), frame.time, index, viewport)
            reading["source_pts"] = frame.pts
            reading["source_time_base"] = str(frame.time_base)
            observations.write(json.dumps(reading)+"\n")
            events = tracker.update(reading)
            for event in events:
                events_output.write(json.dumps(event)+"\n")
            events_count += len(events); count += 1; last_time = frame.time
            phase = reading["phase"]["value"] or "unknown"; counts[phase] = counts.get(phase, 0)+1
            if time.monotonic()-last_progress > 20:
                print(json.dumps({"processed_frames": count, "source_seconds": round(frame.time, 2)}), flush=True)
                last_progress = time.monotonic()
        manifest.update({"processed_frames": count, "events": events_count, "phase_counts": counts,
                         "first_timestamp_seconds": first_time, "last_timestamp_seconds": last_time, "source_timestamp_gaps": source_gaps})
        (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest), flush=True)


if __name__ == "__main__":
    main()
