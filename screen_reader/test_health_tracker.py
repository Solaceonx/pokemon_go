import unittest
from health_tracker import HealthTracker, integer_hp_range


def reading(t, filled=70, species="Raichu", phase="normal_fighting", segments=None, width=140):
    side = {"species": {"value": species, "evidence": {"observed_at_seconds": t}},
            "cp": {"value": 1495}, "health_bar": {"value": {
                "filled_pixels": filled, "interior_width_pixels": width,
                "bounds_px": [10, 20, 154, 32],
                "segments": segments if segments is not None else [{"color": "cyan", "pixels": filled}]}}}
    return {"timestamp_seconds": t, "phase": {"value": phase}, "mine": side, "opponent": side.copy()}


class HealthTests(unittest.TestCase):
    def settle(self, tracker, **kwargs):
        result = None
        for t in [0, .04, .08, .12]:
            result = tracker.update(reading(t, **kwargs))["mine"]["health_estimate"]
        return result

    def test_fraction_without_unverified_maximum(self):
        result = self.settle(HealthTracker())
        self.assertEqual(result["status"], "estimated")
        self.assertEqual(result["pixel_fraction"], [70, 140])
        self.assertIsNone(result["integer_hp_range"])

    def test_integer_grid_and_damage_range(self):
        tracker = HealthTracker({"mine:Raichu:1495": 120})
        result = self.settle(tracker)
        self.assertEqual(result["integer_hp_range"], [57, 63])
        for t in [.16, .20, .24, .28]:
            result = tracker.update(reading(t, filled=56))["mine"]["health_estimate"]
        self.assertEqual(result["integer_hp_range"], [45, 51])
        # First confirmed lower plateau bounds the aggregate loss, never a hit count.
        tracker2 = HealthTracker({"mine:Raichu:1495": 120})
        self.settle(tracker2)
        found_damage = False
        for t in [.16, .20, .24, .28]:
            estimate = tracker2.update(reading(t, filled=56))["mine"]["health_estimate"]
            if estimate.get("integer_damage_range"):
                found_damage = True
                self.assertEqual(estimate["integer_damage_range"], [6, 18])
        self.assertTrue(found_damage)

    def test_offline_source_times_keep_clip_alignment_and_original_log(self):
        import gzip, json, tempfile
        from pathlib import Path
        from estimate_health import run
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); folder = root / "battle"; folder.mkdir()
            rows = []
            for t in [0,.04,.08,.12]:
                row = reading(t+52.4)
                row["source_timestamp_seconds"] = t+52.4
                row["timestamp_seconds"] = t
                rows.append(row)
            raw = folder / "screen_readings.jsonl.gz"
            with gzip.open(raw, "wt") as stream:
                for row in rows: stream.write(json.dumps(row)+"\n")
            original = raw.read_bytes()
            package = folder / "viewer-data.json.gz"
            with gzip.open(package, "wt") as stream:
                json.dump({"readings":[{"t":r["timestamp_seconds"],"mine":{},"opponent":{}} for r in rows]},stream)
            run(root)
            with gzip.open(package, "rt") as stream: data = json.load(stream)
            estimate = data["readings"][-1]["mine"]["health_estimate"]
            self.assertEqual(estimate["status"], "estimated")
            self.assertAlmostEqual(estimate["settled_since_seconds"], 0)
            self.assertEqual(raw.read_bytes(), original)

    def test_animation_and_empty_candidate_unknown(self):
        self.assertEqual(self.settle(HealthTracker(), segments=[{"color":"cyan","pixels":50},{"color":"red","pixels":20}])["status"], "unknown")
        self.assertEqual(self.settle(HealthTracker(), filled=0, segments=[])["status"], "unknown")

    def test_new_clip_identity_uses_clip_time_for_integer_health(self):
        import gzip, json, tempfile
        from pathlib import Path
        from estimate_health import run
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); folder = root / "battle"; folder.mkdir()
            rows = []
            for t in [0, .04, .08, .12]:
                row = reading(t)
                row["coordinates_basis"] = "battle_clip_frame"
                row["source_timestamp_seconds"] = t+842.48
                rows.append(row)
            raw = folder / "screen_readings.jsonl.gz"
            with gzip.open(raw, "wt", encoding="utf-8") as stream:
                for row in rows: stream.write(json.dumps(row)+"\n")
            original = raw.read_bytes()
            package = folder / "viewer-data.json.gz"
            prior = gzip.compress(json.dumps({"readings": [
                {"t": r["timestamp_seconds"], "mine": {}, "opponent": {}} for r in rows]}).encode())
            package.write_bytes(prior)
            run(root, {"mine:Raichu:1495": 120})
            data = json.loads(gzip.decompress(package.read_bytes()))
            estimate = data["readings"][-1]["mine"]["health_estimate"]
            self.assertEqual(estimate["status"], "estimated")
            self.assertEqual(estimate["integer_hp_range"], [57, 63])
            self.assertAlmostEqual(estimate["settled_since_seconds"], 0)
            self.assertEqual(raw.read_bytes(), original)
            archived = list((folder / "analysis-archive").glob("*/viewer-data.json.gz"))
            self.assertEqual(len(archived), 1)
            self.assertEqual(archived[0].read_bytes(), prior)
            self.assertEqual(data["health_estimation_provenance"]["supplied_maximum_hp"], {"mine:Raichu:1495": 120})

    def test_visible_unknown_scene_can_settle_but_inferred_animation_cannot(self):
        self.assertEqual(self.settle(HealthTracker(), phase=None)["status"], "estimated")
        tracker = HealthTracker()
        for t in [0, .04, .08, .12]:
            r = reading(t, phase=None)
            r["phase_estimate"] = {"value": "my_charged_minigame", "status": "inferred"}
            estimate = tracker.update(r)["mine"]["health_estimate"]
        self.assertEqual(estimate["status"], "unknown")

    def test_one_pixel_jitter_and_outline_jitter_settle(self):
        tracker = HealthTracker()
        for i, t in enumerate([0,.04,.08,.12]):
            row = reading(t, filled=70+i%2)
            row["mine"]["health_bar"]["value"]["bounds_px"][0] += i%2
            result = tracker.update(row)["mine"]["health_estimate"]
        self.assertEqual(result["status"], "estimated")

    def test_switch_phase_gap_and_apparent_heal(self):
        tracker = HealthTracker(); self.settle(tracker)
        self.assertEqual(tracker.update(reading(.16, phase="choose_next"))["mine"]["health_estimate"]["status"], "unknown")
        self.assertEqual(tracker.update(reading(1))["mine"]["health_estimate"]["status"], "settling")
        tracker = HealthTracker(); self.settle(tracker)
        for t in [.16,.20,.24,.28]:
            result = tracker.update(reading(t,filled=100))["mine"]["health_estimate"]
        self.assertEqual(result["status"], "conflict")
        self.assertEqual(tracker.update(reading(.32, species="Corsola", filled=140))["mine"]["health_estimate"]["status"], "settling")

    def test_impossible_integer_grid_and_invalid_maximum(self):
        self.assertIsNone(integer_hp_range([.501,.509], 100))
        with self.assertRaises(ValueError): integer_hp_range([0,1], 0)


if __name__ == "__main__": unittest.main()
