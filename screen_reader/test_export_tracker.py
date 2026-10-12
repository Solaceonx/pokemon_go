import unittest
from export_tracker import export


def reading(t, status="observed"):
    side = {"species": {"status": status, "value": "Raichu"},
            "cp": {"status": status, "value": 1500},
            "health_bar": {"status": "observed", "value": {"fraction": 0.75}},
            "energy": {"status": "inferred", "value": 50}}
    return {"timestamp_seconds": t, "mine": side, "opponent": {}}


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.review = {"battle_start_source_seconds": 5,
                       "reviewed_fighting_intervals": [[5, 6], [16, 17]]}

    def test_excludes_animations_and_hidden_or_unreviewed_fields(self):
        rows, sources, pending = export([reading(5), reading(10), reading(16)], self.review)
        self.assertEqual([r["t"] for r in rows], [0, 11])
        self.assertNotIn("my_hp", rows[0])
        self.assertNotIn("my_energy", rows[0])
        self.assertEqual(sources[1]["source_seconds"], 16)
        self.assertEqual(pending, [])

    def test_stale_identity_is_not_reexported(self):
        rows, _, _ = export([reading(5, "stale")], self.review)
        self.assertEqual(rows, [])

    def test_charged_event_attached_once_after_animation(self):
        self.review["charged_events"] = [{"source_seconds": 13, "side": "foe", "move": "Body Slam"}]
        rows, _, pending = export([reading(5), reading(16), reading(17)], self.review)
        self.assertNotIn("foe_charged", rows[0])
        self.assertEqual(rows[1]["foe_move"], "Body Slam")
        self.assertNotIn("foe_charged", rows[2])
        self.assertFalse(pending)

    def test_multiple_events_cannot_be_silently_collapsed(self):
        self.review["charged_events"] = [{"source_seconds": t, "side": "my", "move": "Volt Tackle"} for t in [10, 12]]
        with self.assertRaisesRegex(ValueError, "Two my charged"):
            export([reading(5), reading(16)], self.review)

    def test_approved_measured_hp_only(self):
        self.review["approved_health"] = {"5": {"my": 0.73188}}
        rows, _, _ = export([reading(5)], self.review)
        self.assertEqual(rows[0]["my_hp"], 0.73188)


if __name__ == "__main__":
    unittest.main()
