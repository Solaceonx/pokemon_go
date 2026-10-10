"""Experimental faster OCR for calibrated layouts; not the frozen baseline.

Read fixed header lines directly, detect scene text in smaller regions, and retain
full enlarged-strip fallback when recognition is uncertain. No copied baseline
values or predictions are used as truth.
"""
import json
import re
from pathlib import Path
from local_ocr import LocalOCR, compact
from button_reader import ROOT, cv2
from project_paths import game_data_path


class RegionOCR(LocalOCR):
    def __init__(self, profile):
        super().__init__()
        self.profile = json.loads(Path(profile).read_text(encoding="utf-8"))
        data = json.loads(game_data_path().read_text(encoding="utf-8"))
        self.species = {compact(re.sub(r"\s*\([^)]*\)", "", p["speciesName"]).strip()) for p in data["pokemon"]}
        self.moves = {compact(p["name"]) for p in data["moves"]}
        self.header_complete = False
        self.header_visible = True
        self.moves_complete = False
        self.controls_hidden = False
        self.calls = {"direct_lines": 0, "region_detection": 0, "strip_fallback": 0, "skipped_duplicate": 0}

    def _detect_region(self, rgb, bounds):
        x0, y0, x1, y1 = bounds
        self.calls["region_detection"] += 1
        records = super().read(rgb[y0:y1, x0:x1])
        for record in records:
            a, b, c, d = record["bounds"]
            record["bounds"] = [a+x0, b+y0, c+x0, d+y0]
            record["method"] = "region_text_detection"
        return records

    def read(self, rgb):
        if rgb.shape[:2] != (1080, 508):
            is_header = rgb.shape[0] < 180
            if (is_header and (self.header_complete or not self.header_visible)) or (not is_header and (self.moves_complete or self.controls_hidden or not self.header_visible)):
                self.calls["skipped_duplicate"] += 1
                return []
            self.calls["strip_fallback"] += 1
            return super().read(rgb)
        low, high = self.profile["name_y"]
        bounds = [[12, low-5, 134, high+3], [135, low-5, 214, high+3],
                  [299, low-5, 385, high+3], [385, low-5, 505, high+3]]
        lines = [cv2.cvtColor(rgb[y0:y1, x0:x1], cv2.COLOR_RGB2BGR) for x0, y0, x1, y1 in bounds]
        results, _ = self.engine.text_rec(lines)
        self.calls["direct_lines"] += len(lines)
        records = []
        validated = []
        for index, ((text, confidence), box) in enumerate(zip(results, bounds)):
            expected = bool(re.fullmatch(r"CP\s*\d{1,5}", text, re.I)) if index in {1, 2} else compact(text) in self.species
            valid = confidence >= .80 and expected
            validated.append(valid)
            if valid:
                records.append({"text": text, "confidence": round(float(confidence), 4),
                                "bounds": box, "method": "fixed_header_line_recognition"})
        self.header_complete = len(validated) == 4 and all(validated)
        hsv = cv2.cvtColor(rgb[max(0, low-5):high+3], cv2.COLOR_RGB2HSV)
        pale = (hsv[:, :, 1] < 70) & (hsv[:, :, 2] > 185)
        self.header_visible = all(float(pale[:, a:b].mean()) > .30 for a, b in [(12, 214), (299, 505)])
        # Announcements/grades are central; bench CP and replacement/shield UI
        # appear lower down. Keep these regions separate from the tiny headers.
        central = self._detect_region(rgb, [0, 180, 508, 595])
        records += central
        self.controls_hidden = any(any(cue in compact(r["text"]) for cue in
            ["GETREADY", "SWIPE", "ATTACKINCOMING", "USEAPROTECTSHIELD", "USED"]) or
            compact(r["text"]) in {"NICE", "GREAT", "EXCELLENT"} for r in central)
        if not self.controls_hidden:
            records += self._detect_region(rgb, [0, 595, 508, 1080])
        move_slots = {0 if (r["bounds"][0]+r["bounds"][2])/2 < 254 else 1
                      for r in records if r["bounds"][1] > 880 and compact(r["text"]) in self.moves}
        self.moves_complete = len(move_slots) == 2
        return records
