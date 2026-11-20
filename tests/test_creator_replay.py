"""A failed replay installation must not destroy a previous complete record."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/recording'))
import replay_creators


class Installation(unittest.TestCase):
    def fixture(self, root):
        work = root / '.vod/replay'
        folder = root / 'games/creators/channel/123-001'
        staged = work / 'staged/channel/123-001'
        folder.mkdir(parents=True)
        staged.mkdir(parents=True)
        (folder / 'game.json').write_text('old')
        (staged / 'game.json').write_text('new')
        return work, folder, staged

    def test_success_retains_the_previous_package_outside_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work, folder, staged = self.fixture(root)
            with patch.object(replay_creators, 'ROOT', root):
                replay_creators.install_record(staged, folder, work)
            self.assertEqual((folder / 'game.json').read_text(), 'new')
            retained = list((work / 'previous-export/channel').glob('*/game.json'))
            self.assertEqual(len(retained), 1)
            self.assertEqual(retained[0].read_text(), 'old')

    def test_failed_install_restores_the_previous_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work, folder, staged = self.fixture(root)
            rename = Path.rename

            def fail_staged(path, target):
                if path == staged:
                    raise OSError('simulated interrupted install')
                return rename(path, target)

            with patch.object(replay_creators, 'ROOT', root), patch.object(Path, 'rename', fail_staged):
                with self.assertRaisesRegex(OSError, 'interrupted install'):
                    replay_creators.install_record(staged, folder, work)
            self.assertEqual((folder / 'game.json').read_text(), 'old')
            self.assertEqual((staged / 'game.json').read_text(), 'new')

    def test_record_outside_creator_library_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work, folder, staged = self.fixture(root)
            with patch.object(replay_creators, 'ROOT', root):
                with self.assertRaisesRegex(ValueError, 'permitted folders'):
                    replay_creators.install_record(staged, root / 'unrelated', work)
            self.assertEqual((folder / 'game.json').read_text(), 'old')


if __name__ == '__main__':
    unittest.main()
