import copy
import gzip
import json
from pathlib import Path
import tempfile
import unittest

from validate_library import validate_battle


class IntegrityTests(unittest.TestCase):
    def fixture(self, folder, mutation=None):
        estimate = {"status": "unknown", "fraction": None}
        side = {"species": {"value": "Raichu", "evidence": {"observed_at_seconds": 0}},
                "cp": {"value": 1492}, "health_estimate": estimate,
                "health_bar": {"value": None}, "shields_left": {"value": None},
                "pokemon_left": {"value": None}, "energy": {"value": None}}
        raw = [{"timestamp_seconds": i/10, "frame_index": i,
                "source_pts": 1000+i*10, "source_time_base": "1/100",
                "source_timestamp_seconds": 10+i/10, "phase": {"value": None},
                "mine": copy.deepcopy(side), "opponent": copy.deepcopy(side)} for i in range(2)]
        from build_viewer import compact
        display = [compact(r) for r in raw]
        alignment = [{"clip_frame_index": i, "clip_seconds": i/10,
            "source_pts": 1000+i*10, "source_time_base": "1/100", "source_seconds": 10+i/10} for i in range(2)]
        if mutation: mutation(raw, display, alignment)
        with gzip.open(folder / "screen_readings.jsonl.gz", "wt", encoding="utf-8") as f:
            for r in raw: f.write(json.dumps(r)+"\n")
        with gzip.open(folder / "frame_alignment.jsonl.gz", "wt", encoding="utf-8") as f:
            for r in alignment: f.write(json.dumps(r)+"\n")
        package = {"readings": display, "prediction_provenance": {"coverage": "full_clip"}}
        (folder / "viewer-data.json.gz").write_bytes(gzip.compress(json.dumps(package).encode()))
        return {"id": "check", "frames": 2, "fps": 10, "duration_seconds": .2,
                "video_file": "video.mp4", "viewer_data_file": "viewer-data.json.gz",
                "analysis_status": "analyzed_with_unknowns"}

    def test_matching_unknowns_and_original_pts_are_valid_integrity(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name)
            result = validate_battle(folder, self.fixture(folder), check_media=False)
            self.assertTrue(result["passed"])
            self.assertEqual(result["scene_classified_fraction"], 0)

    def test_future_identity_evidence_is_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name)
            def change(raw, display, alignment):
                raw[0]["mine"]["species"]["evidence"]["observed_at_seconds"] = .1
            result = validate_battle(folder, self.fixture(folder, change), check_media=False)
            self.assertFalse(result["passed"])
            self.assertIn("future", result["problems"][0])

    def test_missing_frames_and_wrong_source_alignment_are_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name)
            def change(raw, display, alignment):
                display.pop()
                raw[0]["source_pts"] = 1010
            result = validate_battle(folder, self.fixture(folder, change), check_media=False)
            self.assertFalse(result["passed"])
            self.assertTrue(any("counts differ" in p for p in result["problems"]))
            self.assertTrue(any("PTS differs" in p for p in result["problems"]))


if __name__ == "__main__": unittest.main()
