import unittest
from battle_reader import BattleReader, ROOT, Image
from roi_ocr import RegionOCR
from image_fixtures import load_image


class RegionOCRTests(unittest.TestCase):
    def read(self, profile, second):
        path = ROOT / "profiles" / (profile+".json")
        ocr = RegionOCR(path)
        reader = BattleReader(path, ocr)
        with load_image(ROOT / "samples" / reader.profile["video_id"] / (str(second)+".png")) as image:
            return reader.detect(image, second, force_ocr=True), ocr

    def test_direct_header_recognition_and_normal_buttons(self):
        r, ocr = self.read("henry-great", 180)
        self.assertEqual(r["mine"]["species"]["value"], "Araquanid")
        self.assertEqual(r["opponent"]["cp"]["value"], 1497)
        self.assertEqual(r["phase"]["value"], "normal_fighting")
        self.assertEqual(ocr.calls["strip_fallback"], 0)

    def test_minigame_keeps_headers_and_grade_without_normal_controls(self):
        r, ocr = self.read("reis-great", 85)
        self.assertEqual(r["phase"]["value"], "my_charged_minigame")
        self.assertEqual(r["mine"]["species"]["value"], "Corsola")
        self.assertEqual(r["charge_result"]["value"], "NICE")
        self.assertFalse(r["buttons"])
        self.assertEqual(ocr.calls["strip_fallback"], 0)

    def test_menu_and_hidden_hud_do_not_invent_identity(self):
        for time in [30, 105]:
            r, _ = self.read("henry-great", time)
            for side in ["mine", "opponent"]:
                self.assertIsNone(r[side]["species"]["value"])
                self.assertIsNone(r[side]["cp"]["value"])
                self.assertIsNone(r[side]["pokemon_left"]["value"])
        self.assertEqual(r["phase"]["value"], "shield_prompt")


if __name__ == "__main__": unittest.main()
