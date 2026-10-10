"""Regression checks on manually inspected frames, including non-calibration frames."""
import unittest
from button_reader import ROOT, ButtonReader, Image, TemporalGate
from image_fixtures import load_image


class ReaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reader = ButtonReader()

    def read(self, second):
        with load_image(ROOT / "samples" / f"henry-{second}.png") as image:
            return self.reader.detect(image, (706, 0, 508, 1080))

    def test_animations_do_not_offer_charge_or_fast_move_targets(self):
        for second in [100, 110, 115, 121, 125, 130, 150, 160, 170, 210, 240, 280, 310, 360, 410, 419, 421, 430]:
            with self.subTest(second=second):
                reading = self.read(second)
                self.assertEqual(reading["phase"], "unknown")
                self.assertIsNone(reading["fast_move_tap_px"])
                self.assertFalse(any(b["kind"] == "charge" for b in reading["buttons"]))

    def test_uncharged_controls(self):
        reading = self.read(191)
        charge = {b["id"]: b for b in reading["buttons"] if b["kind"] == "charge"}
        self.assertEqual(set(charge), {"charge_0", "charge_1"})
        self.assertIs(charge["charge_0"]["visually_enabled"], False)
        self.assertIs(charge["charge_1"]["visually_enabled"], False)

    def test_ready_controls_with_partly_obscured_label(self):
        reading = self.read(420.2)
        charge = {b["id"]: b for b in reading["buttons"] if b["kind"] == "charge"}
        self.assertEqual(set(charge), {"charge_0", "charge_1"})
        self.assertIs(charge["charge_0"]["visually_enabled"], True)
        self.assertIsNone(charge["charge_0"]["name"])
        self.assertIs(charge["charge_1"]["visually_enabled"], True)

    def test_fading_control_is_unknown(self):
        charge = [b for b in self.read(420.6)["buttons"] if b["kind"] == "charge"]
        self.assertIs(charge[0]["visually_enabled"], None)

    def test_replacement_buttons_and_no_fast_move(self):
        reading = self.read(300.2)
        self.assertEqual(reading["phase"], "replacement")
        self.assertEqual({b["id"] for b in reading["buttons"]}, {"replacement_left", "replacement_right"})
        self.assertTrue(all(b["visually_enabled"] is True for b in reading["buttons"]))
        self.assertIsNone(reading["fast_move_tap_px"])

    def test_switch_position_does_not_shift_when_one_card_remains(self):
        switches = [b for b in self.read(180)["buttons"] if b["kind"] == "switch"]
        self.assertEqual([b["id"] for b in switches], ["switch_bottom"])
        self.assertIsNone(switches[0]["visually_enabled"])

    def test_portrait_resize_maps_back_to_input_pixels(self):
        with load_image(ROOT / "samples/henry-420.4.png") as image:
            phone = image.crop((706, 0, 1214, 1080)).resize((1016, 2160))
            reading = self.reader.detect(phone)
        charge = [b for b in reading["buttons"] if b["kind"] == "charge"]
        self.assertEqual([b["tap_px"] for b in charge], [[296, 1956], [722, 1956]])

    def test_unconfigured_aspect_ratio_and_landscape_are_rejected(self):
        for size in [(1920, 1080), (800, 1080)]:
            with self.assertRaises(ValueError):
                self.reader.detect(Image.new("RGB", size))

    def test_blank_screen_has_no_targets(self):
        reading = self.reader.detect(Image.new("RGB", (508, 1080)))
        self.assertEqual(reading["buttons"], [])
        self.assertIsNone(reading["fast_move_tap_px"])

    def test_gate_requires_repeat_and_resets_on_gap(self):
        gate = TemporalGate()
        first = gate.update(self.read(420.4), 0.0)
        self.assertFalse(any(b["confirmed_enabled"] for b in first["buttons"]))
        second = gate.update(self.read(420.4), 0.2)
        self.assertTrue(all(b["confirmed_enabled"] for b in second["buttons"] if b["kind"] == "charge"))
        third = gate.update(self.read(420.4), 1.2)
        self.assertFalse(any(b["confirmed_enabled"] for b in third["buttons"]))

    def test_gate_resets_when_controls_disappear(self):
        gate = TemporalGate()
        gate.update(self.read(420.4), 0.0)
        gate.update(self.read(420.4), 0.2)
        hidden = gate.update(self.read(421), 0.4)
        self.assertFalse(hidden["combat_controls_stable"])
        reading = gate.update(self.read(420.4), 0.6)
        self.assertFalse(any(b["confirmed_enabled"] for b in reading["buttons"]))


if __name__ == "__main__":
    unittest.main()
