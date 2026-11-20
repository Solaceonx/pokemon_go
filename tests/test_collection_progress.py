import json
from pathlib import Path
import tempfile
import unittest

from scripts.recording.collection_progress import summarize


class CollectionProgressTests(unittest.TestCase):
    def test_pending_and_completed_not_double_counted_and_raw_fields_omitted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipts = root / "frozen-reader/.vod/collection/worker-a/receipts"
            receipts.mkdir(parents=True)
            def save(name, payload):
                (receipts / name).write_text(json.dumps(payload), encoding="utf8")
            save("123-cuts.json", {"source_id": "123", "tracking_pending": True, "cuts_saved": 3})
            save("124-cuts.json", {"source_id": "124", "tracking_pending": True, "cuts_saved": 2})
            save("123.json", {"source_id": "123", "done": True, "battles_saved": 3,
                             "cuts_saved": 3, "league_mix": {"open_great_league": 3, "ultra": 1},
                             "raw_ocr": "MUST NOT EXPORT"})
            save("123-source-retirement.json", {"deleted": True, "source_bytes": 987})
            data = summarize(root)
            self.assertEqual(data["vods_done"], 1)
            self.assertEqual(data["battles_saved"], 3)
            self.assertEqual(data["verified_cuts_tracking_pending"], 2)
            self.assertEqual(data["disk"]["full_source_bytes_retired"], 987)
            self.assertNotIn("MUST NOT EXPORT", json.dumps(data))

    def test_excluded_vod_counts_as_examined_without_saved_battles(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipts = root / "frozen-reader/.vod/collection/worker-b/receipts"
            receipts.mkdir(parents=True)
            (receipts / "125.json").write_text(json.dumps({"source_id": "125", "done": True,
                "battles_saved": 0, "league_mix": {"restricted": 7}}), encoding="utf8")
            data = summarize(root)
            self.assertEqual(data["vods_done"], 1)
            self.assertEqual(data["battles_saved"], 0)

    def test_duplicate_collector_receipts_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for worker in ("worker-a", "worker-b"):
                receipts = root / "frozen-reader/.vod/collection" / worker / "receipts"
                receipts.mkdir(parents=True)
                (receipts / "123.json").write_text(json.dumps({"source_id": "123", "done": True}))
            with self.assertRaises(ValueError):
                summarize(root)

    def test_raw_ocr_cannot_be_published_as_league_label(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipts = root / "frozen-reader/.vod/collection/worker-a/receipts"
            receipts.mkdir(parents=True)
            (receipts / "123.json").write_text(json.dumps({"source_id": "123", "done": True,
                "league_mix": {"unrestricted screen text": 1}}))
            with self.assertRaises(ValueError):
                summarize(root)
