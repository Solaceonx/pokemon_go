import copy
import unittest

from scripts.recording.public_handles import appearances, validate


def receipt():
    return {"schema": "public-trainer-handles-v1", "source_id": "123",
            "source_url": "https://www.twitch.tv/videos/123", "battle_id": "123-001",
            "public_trainer_handles": [{"side": "foe", "handle": "Example123",
                "verified": True, "witnesses": [
                    {"source_seconds": 10.0, "screen": "versus"},
                    {"source_seconds": 10.5, "screen": "versus"}]}]}


class PublicHandleTests(unittest.TestCase):
    def test_verified_receipt_and_duplicate_appearance(self):
        value = receipt()
        self.assertEqual(validate(value), value)
        self.assertEqual(appearances([value, copy.deepcopy(value)])[0]["observed_battles"], 1)

    def test_unrestricted_text_and_unverified_guesses_rejected(self):
        for key, value in (("handle", "notification: new message"), ("verified", False),
                           ("raw_ocr", "unrestricted text")):
            data = receipt()
            data["public_trainer_handles"][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate(data)

    def test_distinct_source_game_ui_witnesses_required(self):
        for stamp, screen in ((10, "versus"), (float("nan"), "versus"),
                              (True, "versus"), (11, "chat")):
            data = receipt()
            data["public_trainer_handles"][0]["witnesses"][1] = {
                "source_seconds": stamp, "screen": screen}
            with self.subTest(stamp=stamp, screen=screen), self.assertRaises(ValueError):
                validate(data)

    def test_wrong_source_and_conflicting_side_rejected(self):
        data = receipt()
        data["source_url"] = "https://example.com/123"
        with self.assertRaises(ValueError):
            validate(data)
        first, second = receipt(), receipt()
        second["public_trainer_handles"][0]["handle"] = "Different123"
        with self.assertRaises(ValueError):
            appearances([first, second])


if __name__ == "__main__":
    unittest.main()
