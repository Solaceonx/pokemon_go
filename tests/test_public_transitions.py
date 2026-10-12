"""Regressions for faint counters that precede or lag replacement headers."""
import io
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts/recording"))
from public_transitions import counter_changes, replacement_evidence
from check_transition_labels import check
from verdict import verdict
from pogo.gamedata import GameData
from pogo.tracker import Observation, Tracker

GD = GameData()


class CounterRuns(unittest.TestCase):
    def readings(self, values):
        return [{"t": i / 15, "m": {"left": value}} for i, value in enumerate(values)]

    def test_hidden_frames_break_confirmation(self):
        self.assertEqual(counter_changes(self.readings([2] * 4 + [None] + [2] * 4), "m", "left", 15), [])

    def test_increases_never_restore_fainted_party(self):
        changes = counter_changes(self.readings([3] * 9 + [2] * 9 + [3] * 9 + [1] * 9), "m", "left", 15)
        self.assertEqual([c["value"] for c in changes], [3, 2, 1])

    def test_drop_after_new_header_belongs_to_next_replacement(self):
        changes = [{"t": 100, "first": 99.5, "value": 2}, {"t": 142.7, "first": 142.2, "value": 1}]
        self.assertEqual(replacement_evidence(changes, 106, 140.7)["kind"], "switch")
        self.assertEqual(replacement_evidence(changes, 140.7, 143.7)["kind"], "faint")

    def test_delayed_confirmation_retains_first_visible_time(self):
        changes = [{"t": 1, "first": .5, "value": 3}, {"t": 5.4, "first": 4.9, "value": 2}]
        self.assertEqual(replacement_evidence(changes, 1, 5)["kind"], "faint")

    def test_same_old_faint_is_not_reused(self):
        changes = [{"t": 1, "first": .5, "value": 3}, {"t": 5.4, "first": 4.9, "value": 2}]
        self.assertEqual(replacement_evidence(changes, 6, 10)["kind"], "switch")


class PendingFaints(unittest.TestCase):
    def tracker(self):
        tracker = Tracker(GD, [GD.default(s) for s in ("azumarill", "sableye", "florges")])
        tracker._file = io.StringIO()
        tracker.update(Observation(0, my_species="azumarill", foe_species="melmetal", my_left=3, foe_left=3))
        return tracker

    def events(self, tracker, side):
        return [json.loads(line)["event"] for line in tracker._file.getvalue().splitlines()
                if json.loads(line)["event"].startswith(side)]

    def test_own_counter_drops_before_replacement(self):
        t = self.tracker()
        t.my_switch_at = 20
        t.update(Observation(1, my_species="azumarill", my_left=2))
        t.update(Observation(3, my_species="sableye", my_left=2))
        self.assertEqual(t.me.team[0].hp, 0)
        self.assertEqual(t.my_switch_at, 20)
        self.assertEqual(self.events(t, "my").count("my_faint"), 1)
        self.assertNotIn("my_switch", self.events(t, "my"))
        t.update(Observation(4, my_species="florges", my_left=2))
        self.assertEqual(t.my_switch_at, 49)

    def test_opponent_counter_drops_before_hidden_replacement(self):
        t = self.tracker()
        t.foe_switch_at = 20
        t.update(Observation(1, foe_species="melmetal", foe_left=2))
        t.update(Observation(2))
        t.update(Observation(3, foe_species="quagsire"))
        self.assertEqual(t.foes["melmetal"].mon.hp, 0)
        self.assertEqual(t.foe_switch_at, 20)
        self.assertEqual(self.events(t, "foe").count("foe_faint"), 1)
        t.update(Observation(4, foe_species="clodsire", foe_left=2))
        self.assertEqual(t.foe_switch_at, 49)

    def test_initial_partial_counter_is_not_a_faint(self):
        t = Tracker(GD, [GD.default("azumarill"), GD.default("sableye")])
        t.update(Observation(0, my_species="azumarill", foe_species="melmetal", my_left=2, foe_left=2))
        t.update(Observation(1, my_species="sableye", foe_species="quagsire", my_left=2, foe_left=2))
        self.assertGreater(t.me.team[0].hp, 0)
        self.assertGreater(t.foes["melmetal"].mon.hp, 0)
        self.assertEqual((t.my_switch_at, t.foe_switch_at), (46, 46))


class ReviewedVideoRegressions(unittest.TestCase):
    def test_saved_transitions_match_reviewed_video_labels(self):
        labels = json.loads((ROOT / "data/vod_transition_labels.json").read_text(encoding="utf-8"))
        result = check(labels, lambda path: (ROOT / path).read_bytes())
        self.assertTrue(result["passed"], result["details"])

    def test_unresolved_public_charge_is_a_failure_even_at_clip_end(self):
        result = verdict(ROOT / "games/twitch/tw-2894502346-pov-003", GD)
        self.assertTrue(any("without an observed name" in reason for reason in result["failed"]))
        self.assertTrue(any("resolution and ending are unverified" in note for note in result["notes"]))
        self.assertFalse(any("ended the battle before" in note for note in result["notes"]))


if __name__ == "__main__":
    unittest.main()
