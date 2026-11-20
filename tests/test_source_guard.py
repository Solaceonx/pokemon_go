import hashlib
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from scripts.recording.source_guard import ReadLease, checked_pair, facts, preserve_raw, normalized_input, retire_verified_pair


class SourceGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.source = Path(self.temp.name) / '123'
        self.source.mkdir()
        self.video = self.source / 'video.mp4'
        self.video.write_bytes(b'original input')
        self.raw_sha = hashlib.sha256(b'original input').hexdigest()

    def tearDown(self):
        self.temp.cleanup()

    def test_raw_hardlink_not_double_counted(self):
        preserve_raw(self.source, self.raw_sha)
        pair = checked_pair(self.source, {'video.mp4': self.raw_sha, 'raw-original.ts': self.raw_sha})
        self.assertEqual(pair['unique_inode_bytes'], len(b'original input'))
        self.assertEqual(pair['logical_path_bytes'], 2 * len(b'original input'))

    def test_atomic_normalized_replacement_keeps_original_raw(self):
        preserve_raw(self.source, self.raw_sha)
        output = self.source / 'normalized.tmp'
        output.write_bytes(b'normalized different container')
        output.replace(self.video)
        self.assertEqual((self.source / 'raw-original.ts').read_bytes(), b'original input')
        normalized = facts(self.video)['sha256']
        pair = checked_pair(self.source, {'video.mp4': normalized, 'raw-original.ts': self.raw_sha})
        self.assertEqual(pair['unique_inode_bytes'], len(b'original inputnormalized different container'))

    def test_changed_input_refused_without_deletion(self):
        preserve_raw(self.source, self.raw_sha)
        self.video.write_bytes(b'changed')
        with self.assertRaises(ValueError):
            checked_pair(self.source, {'video.mp4': self.raw_sha, 'raw-original.ts': self.raw_sha})
        self.assertTrue(self.video.exists())

    def test_partial_download_refused(self):
        (self.source / 'download.part').write_bytes(b'incomplete')
        with self.assertRaises(ValueError):
            preserve_raw(self.source, self.raw_sha)

    def test_non_source_directory_refused(self):
        with self.assertRaises(ValueError):
            preserve_raw(self.source.parent, self.raw_sha)

    @unittest.skipUnless(os.name == 'nt', 'Windows sharing-mode test')
    def test_read_lease_blocks_write_and_allows_independent_read(self):
        with ReadLease(self.video):
            self.assertEqual(facts(self.video)['sha256'], self.raw_sha)
            with self.assertRaises(OSError):
                self.video.open('r+b')
        with self.video.open('r+b') as stream:
            stream.write(b'X')

    @unittest.skipUnless(os.name == 'nt', 'Windows sharing-mode test')
    def test_normalization_can_replace_link_then_reader_cannot_write_either_input(self):
        import json
        def normalize(video, record):
            temporary = video.with_name('temporary.mp4')
            temporary.write_bytes(b'normalized')
            temporary.replace(video)
            result = facts(video)
            record.write_text(json.dumps({'media': result}))
            return result
        with normalized_input(self.source, self.raw_sha, normalize) as receipt:
            self.assertEqual(receipt['expected']['raw-original.ts'], self.raw_sha)
            for name in ('video.mp4', 'raw-original.ts'):
                with self.assertRaises(OSError):
                    (self.source / name).open('r+b')

    def test_paired_retirement_refuses_uncut_excluded_source(self):
        import json
        root = Path(self.temp.name) / 'worker-b'
        run = root / 'runs/123'
        run.mkdir(parents=True)
        (run / 'battle-candidates.json').write_text(json.dumps({'export_selection': {'clip_ids': []}}))
        ops = SimpleNamespace(retire=Mock(side_effect=AssertionError('must not delete')),
                              worker_root=lambda worker: root)
        with self.assertRaises(ValueError):
            retire_verified_pair('worker-b', root, '123', {}, ops)
        ops.retire.assert_not_called()

    def test_paired_accepted_cleanup_preserves_evidence_and_counts_one_raw_inode(self):
        import json
        root = Path(self.temp.name) / 'worker-b'
        source = root / 'sources/twitch/123'
        run = root / 'runs/123'
        source.mkdir(parents=True)
        run.mkdir(parents=True)
        (source / 'video.mp4').write_bytes(b'accepted source')
        raw_sha = facts(source / 'video.mp4')['sha256']
        preserve_raw(source, raw_sha)
        (run / 'battle-candidates.json').write_text(json.dumps({'export_selection': {'clip_ids': ['one']}}))
        evidence = run / 'proof.json'
        evidence.write_text('{}')
        receipt_file = root / 'receipts/123-source-retirement.json'
        receipt_file.parent.mkdir()
        def write(path, value):
            path.write_text(json.dumps(value))
        def retire(worker, sid):
            self.assertTrue((source / 'raw-original.ts').exists())
            (source / 'video.mp4').unlink()
            value = {'deleted': True, 'reason': 'all_accepted_cuts_verified', 'source_bytes': len(b'accepted source')}
            write(receipt_file, value)
            return value
        verify = Mock(return_value=True)
        ops = SimpleNamespace(worker_root=lambda worker: root, retire=retire,
                              retained_after_retirement=verify, write=write)
        result = retire_verified_pair('worker-b', root, '123',
            {'video.mp4': raw_sha, 'raw-original.ts': raw_sha}, ops)
        self.assertEqual(result['source_bytes'], len(b'accepted source'))
        self.assertFalse((source / 'video.mp4').exists())
        self.assertFalse((source / 'raw-original.ts').exists())
        self.assertTrue(evidence.exists())
        verify.assert_called_once()
