"""Bounded text regions for already-cropped phone footage, with mapped boxes."""
import json
import re
from pathlib import Path

from local_ocr import LocalOCR, compact
from button_reader import cv2, np


class VodOCR(LocalOCR):
    def __init__(self, profile):
        super().__init__()
        from rapidocr_onnxruntime import RapidOCR
        self.engine = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1,
                               use_cls=False, det_limit_side_len=320)
        self.profile = json.loads(Path(profile).read_text())
        self.at = 0
        self.last_lower = -100
        self.last_header = -100
        self.header = []

    def region(self, rgb, low, high, scale=1):
        crop = rgb[low:high]
        if scale != 1:
            crop = cv2.resize(crop, None, fx=scale, fy=scale)
        records = super().read(crop)
        for r in records:
            a, b, c, d = r["bounds"]
            r["bounds"] = [round(a/scale), round(low+b/scale), round(c/scale), round(low+d/scale)]
            r["method"] = "vod_region_ocr"
        return records

    def read(self, rgb):
        # BattleReader also asks for enlarged fallback strips. This reader
        # already reads that strip at native resolution; avoid duplicate OCR.
        if rgb.shape[:2] != (1080, 508):
            return []
        out = []
        low, high = self.profile["name_y"]
        if self.at - self.last_header >= .6:
            self.header = self.region(rgb, low - 8, high + 8, 1.5)
            self.last_header = self.at
        # Retained boxes are explicitly stamped with their true observation
        # time so the VOD adapter never treats cached header text as fresh.
        out.extend({**r, "vod_observed_at": self.last_header} for r in self.header)
        central = self.region(rgb, 180, 650, .67)
        out.extend(central)
        if self.at - self.last_lower >= .6:
            out.extend(self.region(rgb, 650, 1080, .85))
            self.last_lower = self.at
        return out
