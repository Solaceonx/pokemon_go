import hashlib
from pathlib import Path
import tempfile
import unittest

from scripts.recording.reader_freeze import verify


class ReaderFreezeTests(unittest.TestCase):
    def test_changes_and_missing_files_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "screen_reader").mkdir()
            (root / "reader.py").write_bytes(b"frozen")
            (root / "screen_reader" / "external.py").write_bytes(b"external")
            digest = lambda b: hashlib.sha256(b).hexdigest()
            manifest = {"reader_version": "test", "commit": "abc",
                        "processing_sha256": {"reader.py": digest(b"frozen")},
                        "external_reader_files_sha256": {"external.py": digest(b"external")}}
            self.assertTrue(verify(root, manifest)["unchanged"])
            (root / "reader.py").write_bytes(b"changed")
            (root / "screen_reader" / "external.py").unlink()
            result = verify(root, manifest)
            self.assertFalse(result["unchanged"])
            self.assertEqual({f["reason"] for f in result["failures"]},
                             {"changed", "missing_or_unreadable"})

    def test_paths_cannot_escape_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            result = verify(Path(directory), {"reader_version": "test", "commit": "abc",
                "processing_sha256": {"../escape.py": "a" * 64},
                "external_reader_files_sha256": {}})
            self.assertEqual(result["failures"][0]["reason"], "outside_snapshot")

    def test_external_overlay_overrides_repository_snapshot_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "screen_reader").mkdir()
            (root / "screen_reader" / "reader.py").write_bytes(b"external")
            manifest = {"reader_version": "test", "commit": "abc",
                        "files_sha256": {"screen_reader/reader.py": "0" * 64},
                        "processing_sha256": {}, "external_reader_files_sha256": {
                            "reader.py": hashlib.sha256(b"external").hexdigest()}}
            self.assertTrue(verify(root, manifest)["unchanged"])


if __name__ == "__main__":
    unittest.main()
