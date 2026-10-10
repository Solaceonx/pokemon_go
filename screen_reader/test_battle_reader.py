import copy
import unittest
from battle_reader import ROOT, BattleReader, EventTracker, Image, observed, unknown, np
from health_reader import read_health_bar
from local_ocr import LocalOCR
from image_fixtures import load_image


class BattleReaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ocr = LocalOCR()
        cls.readers = {name: BattleReader(ROOT / "profiles" / f"{name}.json", cls.ocr) for name in ["reis-great", "henry-great"]}

    def read(self, profile, second):
        reader = self.readers[profile]
        video = reader.profile["video_id"]
        with load_image(ROOT / "samples" / video / f"{second}.png") as image:
            return reader.detect(image, second, frame_index=0, force_ocr=True)

    def test_reis_header_and_markers_on_non_calibration_frame(self):
        r = self.read("reis-great", 180)
        self.assertEqual((r["mine"]["species"]["value"], r["mine"]["cp"]["value"]), ("Thievul", 1495))
        self.assertEqual((r["opponent"]["species"]["value"], r["opponent"]["cp"]["value"]), ("Electrode", 1499))
        self.assertEqual((r["mine"]["pokemon_left"]["value"], r["opponent"]["pokemon_left"]["value"]), (3, 1))
        self.assertEqual((r["mine"]["shields_left"]["value"], r["opponent"]["shields_left"]["value"]), (1, 2))

    def test_henry_header_and_markers(self):
        r = self.read("henry-great", 180)
        self.assertEqual(r["mine"]["species"]["value"], "Araquanid")
        self.assertEqual(r["opponent"]["cp"]["value"], 1497)
        self.assertEqual(r["mine"]["shields_left"]["value"], 2)
        self.assertEqual(r["opponent"]["pokemon_left"]["value"], 3)

    def test_non_battle_menu_does_not_create_zero_counts_or_buttons(self):
        r = self.read("henry-great", 30)
        self.assertIsNone(r["phase"]["value"])
        self.assertEqual(r["buttons"], [])
        for side in ["mine", "opponent"]:
            self.assertIsNone(r[side]["cp"]["value"])
            self.assertIsNone(r[side]["pokemon_left"]["value"])
            self.assertIsNone(r[side]["shields_left"]["value"])

    def test_shield_prompt_on_separate_henry_frame(self):
        r = self.read("henry-great", 105)
        self.assertEqual(r["phase"]["value"], "shield_prompt")
        self.assertIsNone(r["fast_move_tap_px"])
        self.assertEqual([b["id"] for b in r["buttons"]], ["shield"])
        self.assertIsNone(r["mine"]["shields_left"]["value"])

    def test_charge_minigame_excludes_normal_buttons(self):
        r = self.read("reis-great", 85)
        self.assertEqual(r["phase"]["value"], "my_charged_minigame")
        self.assertEqual(r["charge_result"]["value"], "NICE")
        self.assertFalse(r["buttons"])
        self.assertIsNone(r["swipe_targets"]["value"])

    def test_faint_selection_single_card_layout(self):
        r = self.read("reis-great", 55)
        self.assertEqual(r["phase"]["value"], "choose_next")
        self.assertEqual([b["id"] for b in r["buttons"]], ["replacement_center"])
        self.assertIsNone(r["fast_move_tap_px"])

    def test_move_labels_with_similar_prefix_are_not_confused(self):
        r = self.read("reis-great", 145)
        self.assertEqual(r["phase"]["value"], "switching_in")
        moves = {b["move"] for b in r["buttons"] if b["kind"] == "charge"}
        self.assertEqual(moves, {"Icy Wind", "Night Slash"})
        self.assertNotIn("Night Shade", moves)

    def test_one_use_energy_is_not_invented_from_pixel_fill(self):
        r = self.read("reis-great", 115)
        charges = [b for b in r["buttons"] if b["kind"] == "charge"]
        self.assertEqual(len(charges), 2)
        self.assertTrue(all(b["energy"]["value"] is None for b in charges))
        self.assertTrue(all(b["second_use_ready"]["value"] is None for b in charges))

    def test_raw_health_measurements_and_pending_segment_preservation(self):
        r = self.read("reis-great", 120)
        mine = r["mine"]["health_bar"]["value"]
        opponent = r["opponent"]["health_bar"]["value"]
        self.assertAlmostEqual(mine["fraction"], 0.82, delta=0.02)
        self.assertAlmostEqual(opponent["fraction"], 0.81, delta=0.02)
        self.assertEqual([s["color"] for s in opponent["segments"]], ["cyan", "yellow_or_orange"])
        self.assertEqual(opponent["pending_damage_interpretation"], "unknown")

    def test_switch_cards_read_from_cp_even_when_border_is_dim(self):
        r = self.read("reis-great", 180)
        self.assertEqual({b["id"] for b in r["buttons"]}, {"switch_top", "switch_bottom"})
        self.assertTrue(all(b["visually_enabled"] is None for b in r["buttons"]))

    def test_clock_is_not_read_from_phone_status_bar(self):
        r = self.read("reis-great", 115)
        self.assertIsNone(r["battle_clock_seconds"]["value"])
        self.assertIsNone(r["switch_cooldown_seconds"]["value"])


class HealthPrecisionTests(unittest.TestCase):
    def test_one_pixel_changes_are_measured_without_integer_hp_assumptions(self):
        import cv2
        fractions = []
        for filled in [1, 2, 70, 71, 138]:
            image = np.full((60, 200, 3), 30, dtype=np.uint8)
            cv2.rectangle(image, (20, 20), (163, 31), (220, 220, 220), 1)
            image[23:29, 23:23+filled] = [15, 225, 178]
            result = read_health_bar(image, (0, 0, 200, 60))
            self.assertIsNotNone(result, filled)
            fractions.append(result["fraction"])
            self.assertAlmostEqual(result["fraction"], filled/138, delta=0.01)
        self.assertGreater(fractions[1], fractions[0])
        self.assertGreater(fractions[3], fractions[2])

    def test_bright_battlefield_line_is_not_health(self):
        image = np.full((60, 200, 3), [70, 160, 70], dtype=np.uint8)
        image[20:23, 20:164] = 255
        self.assertIsNone(read_health_bar(image, (0, 0, 200, 60)))

    def test_flash_hole_cannot_be_reported_as_large_health_loss(self):
        image = np.full((60, 200, 3), 30, dtype=np.uint8)
        cv2 = __import__("cv2")
        cv2.rectangle(image, (20, 20), (163, 31), (220, 220, 220), 1)
        image[23:29, 23:143] = [15, 225, 178]
        image[23:29, 50:55] = 245
        result = read_health_bar(image, (0, 0, 200, 60))
        self.assertIsNone(result)

    def test_dark_red_background_in_translucent_tail_is_not_hp(self):
        image = np.full((60, 200, 3), 30, dtype=np.uint8)
        cv2 = __import__("cv2")
        cv2.rectangle(image, (20, 20), (163, 31), (220, 220, 220), 1)
        image[23:29, 23:93] = [15, 225, 178]
        image[23:29, 96:161] = [100, 10, 10]
        result = read_health_bar(image, (0, 0, 200, 60))
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result["fraction"], 70/138, delta=.01)


class EventTrackerTests(unittest.TestCase):
    def reading(self, timestamp, shields=2, species="Thievul", hp=0.8):
        side = {"species": observed(species, observed_at_seconds=timestamp), "cp": observed(1495),
                "health_bar": observed({"fraction": hp, "interior_width_pixels": 138, "pixel_resolution_fraction": 1/138}),
                "shields_left": observed(shields), "pokemon_left": observed(3)}
        return {"timestamp_seconds": timestamp, "frame_index": round(timestamp*30), "phase": observed("normal_fighting"),
                "mine": copy.deepcopy(side), "opponent": copy.deepcopy(side), "messages": []}

    def test_health_change_is_not_claimed_as_fast_move(self):
        tracker = EventTracker(); tracker.update(self.reading(0))
        events = tracker.update(self.reading(1/30, hp=0.75))
        health = [e for e in events if e["kind"] == "health_bar_change"]
        self.assertTrue(health)
        self.assertTrue(all(e["data"]["verified_fast_move"] is False for e in health))
        self.assertTrue(all(e["data"]["integer_hp_delta"] is None for e in health))

    def test_counts_persist_across_hidden_hud_with_honest_time_bounds(self):
        tracker = EventTracker(); tracker.update(self.reading(0))
        hidden = self.reading(3, shields=None)
        tracker.update(hidden)
        events = tracker.update(self.reading(6, shields=1))
        shields = [e for e in events if e["kind"] == "shield_count_change"]
        self.assertEqual(len(shields), 2)
        self.assertEqual(shields[0]["source_time_interval_seconds"], [0, 6])

    def test_identity_change_after_hidden_header_has_interval_not_fake_frame_exact_time(self):
        tracker = EventTracker(); tracker.update(self.reading(0))
        hidden = self.reading(1)
        for side in ["mine", "opponent"]:
            hidden[side]["species"] = unknown("header hidden")
        tracker.update(hidden)
        events = tracker.update(self.reading(2, species="Raichu"))
        changes = [e for e in events if e["kind"] == "active_identity_change"]
        self.assertEqual(changes[0]["source_time_interval_seconds"], [0, 2])
        self.assertFalse(changes[0]["data"]["switch_timer_started"])

    def test_health_geometry_change_does_not_generate_damage(self):
        tracker = EventTracker(); tracker.update(self.reading(0))
        changed = self.reading(1/30, hp=0.78)
        changed["mine"]["health_bar"]["value"]["interior_width_pixels"] = 140
        events = tracker.update(changed)
        self.assertFalse(any(e["kind"] == "health_bar_change" and e["side"] == "mine" for e in events))


if __name__ == "__main__":
    unittest.main()
