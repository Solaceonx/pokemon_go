import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from import_source import canonical_source, import_source, checksum


class SourceTests(unittest.TestCase):
    def test_installed_python_downloader_works_without_bundled_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            info = {"id": "qSaL7jM9NbA", "is_live": False, "uploader": "reference"}
            with patch("importlib.util.find_spec", return_value=object()), \
                 patch("import_source.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout=json.dumps(info))) as process, \
                 patch("import_source.subprocess.check_output", return_value="2026.08.19"):
                result = import_source("https://youtu.be/qSaL7jM9NbA", root=root)
            self.assertEqual(process.call_args.args[0][1:3], ["-m", "yt_dlp"])
            self.assertEqual(result["analysis_status"], "metadata_only")
            self.assertFalse(list(root.rglob("*.mp4")))

    def test_invalid_explicit_downloader_is_not_silently_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("import_source.subprocess.run") as process:
                with self.assertRaisesRegex(ValueError, "selected downloader"):
                    import_source("https://youtu.be/qSaL7jM9NbA", root=root, executable=root/"missing.exe")
                process.assert_not_called()

    def test_normalize_single_sources(self):
        self.assertEqual(canonical_source('https://youtu.be/qSaL7jM9NbA?t=40'),
                         ('youtube','qSaL7jM9NbA','https://www.youtube.com/watch?v=qSaL7jM9NbA'))
        self.assertEqual(canonical_source('https://www.twitch.tv/videos/123456?t=10s'),
                         ('twitch','123456','https://www.twitch.tv/videos/123456'))

    def test_reject_channels_other_hosts_and_path_ids(self):
        for url in ['https://www.twitch.tv/reis','https://youtube.com/playlist?list=abc',
                    'https://youtube.com.fake/watch?v=qSaL7jM9NbA','https://youtu.be/../../file',
                    'http://youtu.be/qSaL7jM9NbA','https://user:pass@youtu.be/qSaL7jM9NbA']:
            with self.assertRaises(ValueError):canonical_source(url)

    def test_reuse_and_modified_media_detection_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);folder=root/'sources/youtube/qSaL7jM9NbA';folder.mkdir(parents=True)
            media=folder/'video.mp4';media.write_bytes(b'known video')
            record={'media_file':media.relative_to(root).as_posix(),'media':{'sha256':checksum(media)}}
            (folder/'source.json').write_text(json.dumps(record))
            with patch('import_source.subprocess.run') as network:
                result=import_source('https://youtu.be/qSaL7jM9NbA',True,root)
                self.assertTrue(result['reused_existing_media']);network.assert_not_called()
                media.write_bytes(b'changed')
                with self.assertRaises(ValueError):import_source('https://youtu.be/qSaL7jM9NbA',True,root)


if __name__=='__main__':unittest.main()
