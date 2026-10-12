import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from button_reader import Image
from build_viewer import compact
from import_source import checksum
from refine_saved_readings import display_patch, merge_patch, refine


class RefinementTests(unittest.TestCase):
    def test_sparse_patch_preserves_omitted_values_and_observed_zero(self):
        before = {"t": 0, "phase": {"value": None}, "mine": {"cp": {"value": 1492},
            "shields_left": {"value": None}}, "opponent": {"cp": {"value": 1499}}}
        after = {**before, "mine": {**before["mine"], "shields_left": {"value": 0, "status": "observed"}}}
        delta = display_patch(before, after)
        self.assertEqual(set(delta), {"mine"})
        self.assertEqual(merge_patch(before, delta), after)
        self.assertIsNone(before["mine"]["shields_left"]["value"])

    def test_publishing_preserves_raw_and_archives_only_changed_display(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name); video = folder / "video.mp4"
            video.write_bytes(b"video-input")
            profile = folder / "layout.json"
            profile.write_text(json.dumps({"marker_y": 104, "name_y": [70, 98]}))
            side = {k: {"value": None, "status": "unknown"} for k in
                    ["species", "cp", "health_bar", "shields_left", "pokemon_left", "energy"]}
            raw = [{"timestamp_seconds": i*.04, "frame_index": i,
                "phase": {"value": None, "status": "unknown"}, "mine": dict(side), "opponent": dict(side),
                "coordinates_basis": "battle_clip_frame", "buttons": [], "messages": [],
                "text_observation": {"records": [], "fresh_this_frame": False}} for i in range(2)]
            raw_path = folder / "screen_readings.jsonl.gz"
            with gzip.open(raw_path, "wt", encoding="utf-8") as stream:
                for r in raw: stream.write(json.dumps(r)+"\n")
            original_raw = raw_path.read_bytes()
            previous = {"readings": [compact(r) for r in raw], "states": [{"t": 0, "state": "keep"}],
                "prediction_provenance": {"profile_sha256": checksum(profile), "video_sha256": checksum(video)}}
            package = folder / "viewer-data.json.gz"
            original_package = gzip.compress(json.dumps(previous).encode())
            package.write_bytes(original_package)
            (folder / "battle.json").write_text(json.dumps({"id": "fixture", "analysis_status": "analyzed_with_unknowns",
                "video_file": "video.mp4", "frames": 2}))
            class Frame:
                def __init__(self, t): self.time = t
                def to_image(self): return Image.new("RGB", (508, 1080), (10, 100, 210))
            with patch("refine_saved_readings.av.open") as opened:
                opened.return_value.__enter__.return_value.decode.return_value = iter([Frame(0), Frame(.04)])
                result = refine(folder, profile)
            self.assertEqual(result["frames"], 2)
            current = json.loads(gzip.decompress(package.read_bytes()))
            self.assertEqual(current["states"], previous["states"])
            self.assertEqual(raw_path.read_bytes(), original_raw)
            archives = list((folder / "analysis-archive").glob("*/viewer-data.json.gz"))
            self.assertEqual([p.read_bytes() for p in archives], [original_package])
            self.assertEqual(list((folder / "analysis-archive").rglob("*.mp4")), [])
            self.assertTrue(refine(folder, profile)["reused_refinement"])
            self.assertEqual(len(list((folder / "analysis-archive").iterdir())), 1)


if __name__ == "__main__": unittest.main()
