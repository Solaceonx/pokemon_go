import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import import_video
import launch_viewer


class LauncherTests(unittest.TestCase):
    def test_only_matching_local_server_version_is_reused(self):
        for version, expected in [("older", False), ("current", True)]:
            response = io.BytesIO(json.dumps({"schema": "battle-viewer-library-v1",
                                             "server_fingerprint": version}).encode())
            with patch("launch_viewer.urllib.request.urlopen", return_value=response), \
                 patch("launch_viewer.server_fingerprint", return_value="current"):
                self.assertEqual(launch_viewer.ready("http://127.0.0.1:1234"), expected)

    def test_saved_connection_accepts_only_local_server(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / "output").mkdir()
            saved = root / "output/viewer-server.json"
            with patch.object(launch_viewer, "ROOT", root):
                self.assertEqual(launch_viewer.connection_url(), launch_viewer.URL)
                saved.write_text(json.dumps({"url": "https://example.com:1234"}))
                self.assertEqual(launch_viewer.connection_url(), launch_viewer.URL)
                saved.write_text(json.dumps({"url": "http://127.0.0.1:4321"}))
                self.assertEqual(launch_viewer.connection_url(), "http://127.0.0.1:4321")

    def test_import_refines_exported_battles_with_selected_profile(self):
        profile = Path("calibrated-layout.json")
        with patch("refine_saved_readings.refine", return_value={"reused_refinement": True}) as refine:
            result = import_video.refine_imported_battles({"exports": [{"id": "a"}, {"id": "b"}]}, profile)
            self.assertEqual(len(result), 2)
            self.assertEqual(refine.call_args_list[0].args, (import_video.ROOT / "battles/a", profile))
            self.assertEqual(refine.call_args_list[1].args, (import_video.ROOT / "battles/b", profile))


if __name__ == "__main__":
    unittest.main()
