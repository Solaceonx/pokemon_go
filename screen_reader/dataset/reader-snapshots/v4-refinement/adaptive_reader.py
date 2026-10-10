"""Experimental layout adaptation, kept separate from the frozen v3 reader.

Header OCR anchors the marker row instead of assuming a fixed vertical position.
Readable minigame grades supply a scene cue. No hidden energy or HP is inferred.
"""
from battle_reader import BattleReader, observed, unknown
from button_reader import cv2
from local_ocr import compact
from roi_ocr import RegionOCR
from scene_tracker import SceneTracker


class GradeSceneTracker(SceneTracker):
    def update(self, reading):
        text = reading.get("text_observation", {})
        grade = next((r for r in text.get("records", [])
                      if text.get("fresh_this_frame") and
                      compact(r["text"]) in {"NICE", "GREAT", "EXCELLENT"} and
                      r.get("confidence", 0) >= .85 and
                      180 < r["bounds"][1] < r["bounds"][3] < 550 and
                      r["bounds"][2]-r["bounds"][0] > 25), None)
        phase = reading["phase"].get("value")
        if grade and phase in {None, "normal_fighting", "my_charged_minigame"}:
            reading["phase_before_refinement"] = reading["phase"]
            reading["phase"] = observed("my_charged_minigame",
                method="central_minigame_grade_ocr", raw_text=grade["text"],
                ocr_confidence=grade["confidence"], bounds=grade["bounds"])
            # A grade belongs to the swipe sequence, even if a stale charge
            # label accidentally still established normal controls.
            reading["buttons"] = []
            reading["fast_move_tap_px"] = None
        return super().update(reading)


class AdaptiveReader(BattleReader):
    def __init__(self, profile, ocr=None, ocr_interval=.5):
        super().__init__(profile, ocr or RegionOCR(profile), ocr_interval)
        self.scene_tracker = GradeSceneTracker()
        self.detect_time = None

    def detect(self, image, timestamp, *args, **kwargs):
        self.detect_time = timestamp
        reading = super().detect(image, timestamp, *args, **kwargs)
        reading["reader_variant"] = "experimental_adaptive_v4"
        return reading

    def _markers(self, rgb, side):
        cp = self._header(side, self.detect_time == self.last_ocr_time)["cp"]
        evidence = cp.get("evidence", {})
        bounds = evidence.get("bounds_normalized_frame")
        seen = evidence.get("observed_at_seconds")
        if (cp.get("value") is None or not bounds or seen is None or
                not 0 <= self.detect_time-seen <= .75):
            reason = "No recent header anchor for marker positions"
            return unknown(reason), unknown(reason)
        anchor = (bounds[1]+bounds[3])/2
        expected_anchor = sum(self.profile["name_y"])/2
        if abs(anchor-expected_anchor) > 16:
            reason = "Header anchor differs too far from the calibrated layout"
            return unknown(reason), unknown(reason)
        y = round(anchor+self.profile["marker_y"]-expected_anchor)
        left, right = (12, 211) if side == "mine" else (301, 499)
        # Recent OCR alone cannot establish that a disappearing header is still
        # visible. Require the pale panel around the marker row in THIS frame.
        hsv = cv2.cvtColor(rgb[round(bounds[3])+1:y+9, left:right], cv2.COLOR_RGB2HSV)
        if not hsv.size or float(((hsv[:, :, 1] < 75) & (hsv[:, :, 2] > 175)).mean()) < .35:
            reason = "Header panel is hidden or occluded in this frame"
            return unknown(reason), unknown(reason)
        original = self.profile["marker_y"]
        try:
            self.profile["marker_y"] = y
            party, shields = super()._markers(rgb, side)
        finally:
            self.profile["marker_y"] = original
        for field in [party, shields]:
            field["evidence"].update(method="header_anchored_marker_row",
                marker_y=y, header_cp_bounds=bounds, header_observed_at_seconds=seen)
        return party, shields
