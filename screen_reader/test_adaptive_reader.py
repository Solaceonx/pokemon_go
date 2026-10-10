import copy
import unittest
from adaptive_reader import AdaptiveReader, GradeSceneTracker
from battle_reader import ROOT, Image
from test_scene_tracker import frame
from image_fixtures import load_image


class GradeCueTests(unittest.TestCase):
    def test_grade_stops_normal_controls_and_context_expires(self):
        tracker = GradeSceneTracker()
        r = frame(0, "normal_fighting")
        r["text_observation"] = {"fresh_this_frame": True, "records": [
            {"text": "EXCELLENT!", "confidence": .99, "bounds": [70, 280, 443, 331]}]}
        r["buttons"] = [{"kind": "charge"}]
        r["fast_move_tap_px"] = [254, 580]
        tracker.update(r)
        self.assertEqual(r["phase"]["value"], "my_charged_minigame")
        self.assertEqual(r["phase_before_refinement"]["value"], "normal_fighting")
        self.assertEqual(r["buttons"], [])
        self.assertIsNone(r["fast_move_tap_px"])
        for i in range(1, 14): r = tracker.update(frame(i))
        self.assertIsNone(r["phase_estimate"]["value"])

    def test_stale_or_outside_grade_cannot_create_minigame(self):
        base = frame(0)
        base["text_observation"] = {"fresh_this_frame": True, "records": [
            {"text": "GREAT", "confidence": .99, "bounds": [70, 280, 443, 331]}]}
        for change in ["stale", "header", "low_confidence", "competing_cue"]:
            r = copy.deepcopy(base)
            if change == "stale": r["text_observation"]["fresh_this_frame"] = False
            if change == "header": r["text_observation"]["records"][0]["bounds"] = [20, 65, 150, 90]
            if change == "low_confidence": r["text_observation"]["records"][0]["confidence"] = .60
            if change == "competing_cue": r["phase"]["value"] = "shield_prompt"
            GradeSceneTracker().update(r)
            self.assertNotEqual(r["phase"]["value"], "my_charged_minigame", change)


class AdaptiveImageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reader = AdaptiveReader(ROOT / "profiles/henry-great.json")

    def test_shifted_header_and_grade(self):
        with Image.open(ROOT / "fixtures/visual-review/henry-04.png") as image:
            r = self.reader.detect(image, 15, force_ocr=True)
        self.assertEqual(r["phase"]["value"], "my_charged_minigame")
        self.assertEqual(r["charge_result"]["value"], "EXCELLENT")
        for side in ["mine", "opponent"]:
            self.assertEqual(r[side]["shields_left"]["value"], 2)
            self.assertEqual(r[side]["pokemon_left"]["value"], 3)
            self.assertAlmostEqual(r[side]["shields_left"]["evidence"]["marker_y"], 96, delta=1)
        self.assertEqual(self.reader.profile["marker_y"], 104)
        self.assertEqual(r["buttons"], [])
        self.assertIsNone(r["mine"]["health_estimate"]["fraction"])

    def test_existing_layout_and_current_hidden_panel(self):
        with load_image(ROOT / "samples/8O7kDtNZs6Y/180.png") as image:
            r = self.reader.detect(image, 180, force_ocr=True)
            x, y, w, h = self.reader.profile["viewport"]
            hidden = image.crop((x, y, x+w, y+h))
        self.assertEqual(r["mine"]["shields_left"]["value"], 2)
        self.assertEqual(r["opponent"]["pokemon_left"]["value"], 3)
        # Keep the recent OCR cache but remove the actual HUD.
        hidden.paste((20, 120, 220), (0, 55, 508, 140))
        r = self.reader.detect(hidden, 180.04)
        for side in ["mine", "opponent"]:
            self.assertIsNone(r[side]["shields_left"]["value"])
            self.assertIsNone(r[side]["pokemon_left"]["value"])


if __name__ == "__main__": unittest.main()
