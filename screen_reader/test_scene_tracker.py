import unittest
from scene_tracker import SceneTracker


def frame(t, phase=None, species="Raichu", opponent="Vigoroth", party=3, foe_bar=True):
    def side(name, count, bar):
        return {"species": {"value": name, "status": "observed"},
                "pokemon_left": {"value": count}, "health_bar": {"value": {"fraction": .5} if bar else None}}
    return {"timestamp_seconds": t, "phase": {"value": phase}, "buttons": [],
            "mine": side(species, 3, True), "opponent": side(opponent, party, foe_bar)}


class SceneTests(unittest.TestCase):
    def test_shield_decline_gap_is_inferred_and_expires(self):
        s = SceneTracker(); s.update(frame(0, "shield_prompt"))
        r = s.update(frame(.1))
        self.assertIsNone(r["phase"]["value"])
        self.assertEqual(r["phase_estimate"]["value"], "opponent_charged_warning")
        self.assertEqual(r["phase_estimate"]["status"], "inferred")
        for i in range(1, 8): r = s.update(frame(i))
        self.assertIsNone(r["phase_estimate"]["value"])

    def test_current_cue_ends_minigame_and_seeking_clears_context(self):
        s = SceneTracker(); s.update(frame(1, "my_charged_minigame"))
        self.assertEqual(s.update(frame(1.2))["phase_estimate"]["value"], "my_charged_minigame")
        self.assertEqual(s.update(frame(1.3, "charged_resolution"))["phase_estimate"]["status"], "observed")
        self.assertIsNone(s.update(frame(.5))["phase_estimate"]["value"])
        self.assertIsNone(s.update(frame(5))["phase_estimate"]["value"])

    def test_party_drop_and_empty_side_need_multiple_signals(self):
        s = SceneTracker(); s.update(frame(0, "normal_fighting"))
        self.assertIsNone(s.update(frame(.1, foe_bar=False))["phase_estimate"]["value"])
        self.assertEqual(s.update(frame(.2, party=2, foe_bar=False))["phase_estimate"]["value"], "opponent_replacement_wait")
        r = s.update(frame(.3, opponent="Mantine", party=2, foe_bar=False))
        self.assertEqual(r["phase_estimate"]["value"], "switching_in")

    def test_count_reset_cannot_carry_previous_battle_context(self):
        s = SceneTracker(); s.update(frame(0, "my_charged_minigame", party=1))
        self.assertIsNone(s.update(frame(.1, party=3))["phase_estimate"]["value"])


if __name__ == "__main__": unittest.main()
