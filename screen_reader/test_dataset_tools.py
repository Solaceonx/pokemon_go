import unittest
import tempfile
from pathlib import Path
from dataset_tools import digest
from dataset_tools import annotation_tasks, normalize_label, score_labels, validate_manifest


def clip(battle="reis-01", source="reis", partition="train", begin=0, end=10, sha="a"):
    return {"battle_id": battle, "source_id": source, "partition": partition,
            "source_start_seconds": begin, "source_end_seconds": end,
            "clip_duration_seconds": end-begin, "fps": 30, "video_sha256": sha}


def manifest(clips):
    return {"clips": clips, "test_role": "previously_exposed_regression"}


class DatasetTests(unittest.TestCase):
    def test_no_source_or_identical_content_leakage(self):
        for clips in ([clip(), clip("reis-02", partition="test", begin=10, end=20, sha="b")],
                      [clip(), clip("henry-01", "henry", "test")]):
            with self.assertRaises(ValueError):
                validate_manifest(manifest(clips), check_hashes=False)

    def test_nonoverlapping_grouped_split(self):
        clips = [clip(), clip("reis-02", begin=10, end=20, sha="b"),
                 clip("henry-01", "henry", "test", sha="c")]
        self.assertEqual(validate_manifest(manifest(clips), check_hashes=False), {"train": 2, "test": 1})
        clips[1]["source_start_seconds"] = 9
        with self.assertRaises(ValueError):
            validate_manifest(manifest(clips), check_hashes=False)

    def test_tasks_are_deterministic_and_not_labels(self):
        m = manifest([clip()])
        tasks = annotation_tasks(m, 5)
        self.assertEqual([r["clip_seconds"] for r in tasks], [0, 5])
        self.assertEqual(tasks, annotation_tasks(m, 5))
        self.assertTrue(all(normalize_label(t, m["clips"]) is None for t in tasks))

    def test_no_test_labels_means_unavailable(self):
        result = score_labels(manifest([clip()]), [], {})
        self.assertIsNone(result["accuracy_among_covered"])
        self.assertIsNone(result["coverage_fraction"])
        self.assertEqual(result["status"], "awaiting_independent_human_labels")

    def test_future_rows_and_stale_predictions_do_not_count_as_covered(self):
        m = manifest([clip()])
        labels = [{"battle_id": "reis-01", "clip_seconds": 1, "phase": "normal_fighting",
                   "provenance": "human_review"}]
        for rows in ([{"t": 1.01, "phase": {"value": "normal_fighting", "status": "observed"}}],
                     [{"t": 0.8, "phase": {"value": "normal_fighting", "status": "observed"}}],
                     [{"t": 1, "phase": {"value": "normal_fighting", "status": "stale"}}]):
            result = score_labels(m, labels, {"reis-01": {"readings": rows}}, "train")
            self.assertEqual(result["covered_field_count"], 0)
            self.assertEqual(result["correct_fraction_all_labels"], 0)

    def test_health_point_must_fit_human_range_and_unknown_is_explicit(self):
        m = manifest([clip()])
        label = {"battle_id": "reis-01", "clip_seconds": 1, "provenance": "human_review",
                 "mine": {"health_fraction_range": [0.4, 0.44]}, "opponent": {"species": None}}
        row = {"t": 1, "mine": {"health_estimate": {"status": "estimated", "fraction": 0.5,
                                                     "fraction_range": [0.2, 0.8]}},
               "opponent": {"species": {"value": None, "status": "unknown"}}}
        result = score_labels(m, [label], {"reis-01": {"readings": [row]}}, "train")
        self.assertEqual(result["covered_field_count"], 1)
        self.assertEqual(result["correct_field_count"], 0)
        self.assertEqual(result["unscorable_human_field_count"], 1)

    def test_prediction_exposed_and_uncertain_truth_are_not_accuracy(self):
        m = manifest([clip()])
        labels = [{"battle_id": "reis-01", "clip_seconds": 1, "phase": "unknown",
                   "provenance": "human_review"},
                  {"battle_id": "reis-01", "clip_seconds": 1, "phase": "normal_fighting",
                   "provenance": "human_review", "reviewed_without_predictions": False}]
        result = score_labels(m, labels, {}, "train")
        self.assertEqual(result["unscorable_human_field_count"], 1)
        self.assertEqual(result["prediction_exposed_label_count"], 1)
        self.assertIsNone(result["accuracy_among_covered"])

    def test_video_hash_detects_changed_media(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / "clip.mp4"
            path.write_bytes(b"original media")
            c = clip()
            c.update(video="clip.mp4", video_bytes=path.stat().st_size, video_sha256=digest(path))
            self.assertEqual(validate_manifest(manifest([c]), root), {"train": 1, "test": 0})
            path.write_bytes(b"modified media")
            with self.assertRaises(ValueError):
                validate_manifest(manifest([c]), root)

    def test_source_label_time_maps_to_clip(self):
        c = clip(begin=50, end=60)
        label = normalize_label({"source_id": "reis", "timestamp_seconds": 54,
                                 "label_source": "user", "phase": "choose_next_after_my_faint"}, [c])
        self.assertEqual(label["clip_seconds"], 4)
        self.assertEqual(label["phase"], "choose_next")


if __name__ == "__main__":
    unittest.main()
