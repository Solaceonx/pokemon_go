import json
import tempfile
import unittest
from pathlib import Path
from battle_library import scan_library
from organize_battles import remap_view
from serve_viewer import byte_range
from serve_viewer import make_handler
from http.server import ThreadingHTTPServer
import threading
import urllib.request
import urllib.error
import os


class LibraryTests(unittest.TestCase):
    def test_remaps_source_times_without_changing_tracker_battle_time(self):
        source = {"origin": 105, "readings": [{"t": 99}, {"t": 101}, {"t": 120}],
                  "states": [{"t": 106, "state": {"t": 1}}]}
        view = remap_view(source, 100, 120)
        self.assertEqual(view["readings"], [{"t": 1}])
        self.assertEqual(view["states"], [{"t": 6, "state": {"t": 1}}])
        self.assertEqual(view["origin"], 5)

    def test_folder_scan_finds_new_battles_and_ignores_path_escape(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            folder = root / "battle1"
            folder.mkdir()
            (folder / "video.mp4").write_bytes(b"video")
            (folder / "viewer-data.json.gz").write_bytes(b"data")
            meta = {"id": "not-the-path", "video_file": "video.mp4", "viewer_data_file": "viewer-data.json.gz"}
            path = folder / "battle.json"
            path.write_text(json.dumps(meta))
            self.assertEqual(scan_library(root)[0]["id"], "battle1")
            meta["segment_status"] = "combined_superseded"
            path.write_text(json.dumps(meta))
            self.assertEqual(scan_library(root), [])
            meta.pop("segment_status")
            meta["video_file"] = "../../outside.mp4"
            path.write_text(json.dumps(meta))
            self.assertEqual(scan_library(root), [])

    def test_ranges_for_video_seeking(self):
        self.assertEqual(byte_range(None, 100), (0, 99, False))
        self.assertEqual(byte_range("bytes=20-29", 100), (20, 29, True))
        self.assertEqual(byte_range("bytes=90-", 100), (90, 99, True))
        self.assertEqual(byte_range("bytes=-10", 100), (90, 99, True))
        self.assertEqual(byte_range("bytes=90-200", 100), (90, 99, True))
        for header in ["bytes=100-", "bytes=5-2", "bytes=-0", "bytes=0-1,5-6"]:
            with self.assertRaises(ValueError):
                byte_range(header, 100)

    def test_unfinished_analysis_does_not_refresh_current_package(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            folder = root / "battle1"
            folder.mkdir()
            (folder / "video.mp4").write_bytes(b"video")
            package = folder / "viewer-data.json.gz"
            package.write_bytes(b"data")
            (folder / "battle.json").write_text(json.dumps({"video_file": "video.mp4",
                "viewer_data_file": "viewer-data.json.gz"}))
            before = scan_library(root)[0]
            (folder / "screen_readings.incomplete.jsonl.gz").write_bytes(b"unfinished" * 100)
            during = scan_library(root)[0]
            self.assertEqual(before["saved_data_bytes"], during["saved_data_bytes"])
            self.assertEqual(before["analysis_revision"], during["analysis_revision"])
            stamp = package.stat().st_mtime_ns+1_000_000
            package.write_bytes(b"more")
            os.utime(package, ns=(stamp, stamp))
            after = scan_library(root)[0]
            self.assertEqual(before["saved_data_bytes"], after["saved_data_bytes"])
            self.assertNotEqual(before["analysis_revision"], after["analysis_revision"])

    def test_raw_video_is_available_without_invented_analysis(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / "my-battle.mp4").write_bytes(b"video")
            row = scan_library(root)[0]
            self.assertEqual(row["analysis_status"], "not_analyzed")
            self.assertIsNone(row["fps"])
            self.assertEqual(row["relative_video"], "my-battle.mp4")

    def test_server_refreshes_folder_and_serves_real_byte_ranges(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            battles = root / "battles"
            battles.mkdir()
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(root, battles))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                with urllib.request.urlopen(base+"/api/battles") as response:
                    self.assertEqual(json.load(response)["sources"], [])
                (battles / "new.mp4").write_bytes(bytes(range(100)))
                with urllib.request.urlopen(base+"/api/battles") as response:
                    self.assertEqual(len(json.load(response)["sources"]), 1)
                request = urllib.request.Request(base+"/battles/new.mp4", headers={"Range":"bytes=20-29"})
                with urllib.request.urlopen(request) as response:
                    self.assertEqual(response.status, 206)
                    self.assertEqual(response.read(), bytes(range(20,30)))
                    self.assertEqual(response.headers["Content-Range"], "bytes 20-29/100")
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(base+"/battles/%2e%2e/outside.txt")
                self.assertEqual(error.exception.code, 403)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


if __name__ == "__main__":
    unittest.main()
