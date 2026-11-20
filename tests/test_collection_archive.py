import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.recording import collection_archive as archive


class ReviewedCoverage(unittest.TestCase):
    def setUp(self):
        self.pending = {'source_id': '123', 'views': {'pov': [{'id': 'raw1', 'start': 2, 'end': 8}, {'id': 'raw2', 'start': 9, 'end': 15}]}}
        self.manifest = {'source_id': '123', 'manual_source_context_review_completed': True,
                         'source_reviewed_intake_completed': True, 'raw_fragment_count': 2,
                         'scan_coverage': {'full_recording_scanned': True, 'source_seconds': 20, 'scanned_seconds': 20, 'selection_limited': False},
                         'views': {'pov': [{'id': 'tw-123-reviewed-pov-001', 'source_id': '123', 'view_id': 'pov',
                                           'start': 1, 'end': 16, 'source_boundary_review': 'manual_source_frames',
                                           'raw_fragment_ids': ['raw1', 'raw2']}]}}

    def test_continuous_cut_preserves_internal_animation_gap(self):
        rows = archive.reviewed_candidates(self.manifest, self.pending)
        self.assertEqual((rows[0]['start'], rows[0]['end']), (1, 16))

    def test_missing_fragment_refused(self):
        self.manifest['views']['pov'][0]['raw_fragment_ids'] = ['raw1']
        with self.assertRaises(ValueError): archive.reviewed_candidates(self.manifest, self.pending)

    def test_duplicate_fragment_refused(self):
        self.manifest['views']['pov'][0]['raw_fragment_ids'].append('raw1')
        with self.assertRaises(ValueError): archive.reviewed_candidates(self.manifest, self.pending)

    def test_clipping_original_fragment_refused(self):
        self.manifest['views']['pov'][0]['end'] = 14
        with self.assertRaises(ValueError): archive.reviewed_candidates(self.manifest, self.pending)

    def test_bounded_scan_cannot_retire_whole_source(self):
        self.manifest['scan_coverage']['scanned_seconds'] = 19
        with self.assertRaises(ValueError): archive.reviewed_candidates(self.manifest, self.pending)

    def test_path_escape_id_refused(self):
        self.manifest['views']['pov'][0]['id'] = 'tw-123-../../video.mp4'
        with self.assertRaises(ValueError): archive.reviewed_candidates(self.manifest, self.pending)


class NondeletingPreflight(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.canonical = self.root / 'runs/123'
        self.run = self.canonical / 'archival-all-reviewed-v1'
        self.source = self.root / 'sources/twitch/123'
        self.source.mkdir(parents=True)
        for name in ('video.mp4', 'raw-original.ts'): (self.source / name).write_bytes(name.encode())
        self.cid = 'tw-123-reviewed-pov-001'
        self.folder = self.root / 'archival-cuts/123' / self.cid
        self.folder.mkdir(parents=True)
        for name in ('video.mp4', 'battle.json', 'frame_alignment.jsonl.gz'): (self.folder / name).write_bytes(('saved' + name).encode())
        self.manifest = {'fingerprint': {'source_sha256': archive.counted_facts(self.source / 'video.mp4')['sha256']}}
        self.candidates = [{'id': self.cid}]
        archive.ops.write(self.canonical / 'battle-candidates.json', self.manifest)
        archive.ops.write(self.run / 'battle-candidates.json', {'archive_only': True})
        archive.ops.write(self.run / 'media-validation.json', {'media_checks_passed': True, 'checked_clips': [{'id': self.cid}]})
        proof = {'cuts': {self.cid: {name: archive.counted_facts(self.folder / name) for name in ('video.mp4', 'battle.json', 'frame_alignment.jsonl.gz')}},
                 'canonical_manifest_sha256': archive.ops.digest(self.canonical / 'battle-candidates.json'),
                 'archive_manifest_sha256': archive.ops.digest(self.run / 'battle-candidates.json'),
                 'validation_sha256': archive.ops.digest(self.run / 'media-validation.json'),
                 'source_after': archive.source_pair(self.source, self.manifest['fingerprint']['source_sha256'])}
        archive.ops.write(self.run / 'archive-proof.json', proof)
        self.context = patch.object(archive, 'inputs', return_value=(self.root, self.canonical, self.manifest, self.candidates, self.source, {}))
        self.context.start(); self.addCleanup(self.context.stop)
        freeze = patch.object(archive.ops, 'verify_freeze', return_value={'unchanged': True})
        freeze.start(); self.addCleanup(freeze.stop)

    def test_preflight_preserves_all_files_and_does_not_admit_unknown_league(self):
        before = set(self.root.rglob('*'))
        result = archive.preflight('worker-b', '123')
        self.assertFalse(result['deleted'])
        self.assertFalse(result['deletion_authorized'])
        self.assertFalse(result['paired_source_integrity_passed'])
        self.assertFalse(result['accepted_collection_admission'])
        self.assertTrue(before.issubset(set(self.root.rglob('*'))))
        self.assertEqual(len(result['exact_full_source_targets']), 2)

    def test_changed_saved_video_blocks_preflight(self):
        (self.folder / 'video.mp4').write_bytes(b'changed')
        with self.assertRaises(ValueError): archive.preflight('worker-b', '123')

    def test_changed_alignment_blocks_preflight(self):
        (self.folder / 'frame_alignment.jsonl.gz').write_bytes(b'changed')
        with self.assertRaises(ValueError): archive.preflight('worker-b', '123')

    def test_missing_frame_verified_battle_blocks_preflight(self):
        report = archive.ops.load(self.run / 'media-validation.json')
        report['checked_clips'] = []
        archive.ops.write(self.run / 'media-validation.json', report)
        with self.assertRaises(ValueError): archive.preflight('worker-b', '123')

    def test_changed_full_source_blocks_preflight(self):
        (self.source / 'video.mp4').write_bytes(b'new normalized input')
        with self.assertRaises(ValueError): archive.preflight('worker-b', '123')

    def test_path_escape_refused(self):
        with self.assertRaises(ValueError): archive.owned_path(self.root, '..', 'outside')


if __name__ == '__main__': unittest.main()
