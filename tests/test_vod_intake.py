"""Regression checks for real transport-stream offsets and partial/mirrored battles."""
from fractions import Fraction
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1] / "scripts/recording"
sys.path.insert(0, str(HERE))
import vod_media
from vod_segments import annotate_segments, discover_segments, pair_perspectives
from vod_broadcast import filter_broadcast
from vod import compatible_export


@unittest.skipUnless(importlib.util.find_spec("av"), "video checks require the reader's PyAV environment")
class TimestampTests(unittest.TestCase):
    def source(self, folder):
        import av
        import numpy as np
        path = Path(folder) / "video.mp4"
        with av.open(str(path), "w", format="mpegts", options={"mpegts_copyts": "1"}) as container:
            stream = container.add_stream("libx264", rate=15)
            stream.width, stream.height, stream.pix_fmt = 192, 320, "yuv420p"
            stream.options = {"preset": "ultrafast", "tune": "zerolatency"}
            for i in range(45):
                image = np.zeros((320, 192, 3), dtype="uint8")
                image[:, :, i % 3] = 100 + i
                frame = av.VideoFrame.from_ndarray(image, format="rgb24")
                frame.pts, frame.time_base = 1500 + i, Fraction(1, 15)
                for packet in stream.encode(frame):
                    container.mux(packet)
            for packet in stream.encode():
                container.mux(packet)
        return path

    def decoded(self, path):
        import av
        import hashlib
        with av.open(str(path)) as source:
            return [(float(frame.pts * frame.time_base), hashlib.sha256(frame.to_ndarray(format="rgb24").tobytes()).hexdigest())
                    for frame in source.decode(video=0)]

    def test_nonzero_twitch_origin_is_removed_without_losing_frames(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.source(folder)
            original = self.decoded(path)
            self.assertGreater(original[0][0], 99)
            vod_media.normalize_source(path)
            saved = self.decoded(path)
            self.assertLess(abs(saved[0][0]), .05)
            self.assertEqual([h for _, h in original], [h for _, h in saved])
            self.assertAlmostEqual(original[-1][0] - original[0][0], saved[-1][0] - saved[0][0], places=4)
            self.assertEqual(len(list(Path(folder).glob('*.mp4'))), 1)
            record = json.loads((Path(folder) / 'source.json').read_text())
            self.assertFalse(record['timestamp_normalization']['reencoded'])
            self.assertEqual(record['media']['sha256'], vod_media.sha256(path))

    def test_interrupted_metadata_update_recovers_from_journal(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.source(folder)
            writer = vod_media.write_json
            def fail_source_record(destination, value):
                if Path(destination).name == 'source.json':
                    raise OSError('simulated interruption after media replacement')
                return writer(destination, value)
            with patch.object(vod_media, 'write_json', side_effect=fail_source_record):
                with self.assertRaises(OSError):
                    vod_media.normalize_source(path)
            self.assertTrue(path.is_file())
            self.assertTrue((Path(folder) / 'timestamp-normalization.json').exists())
            vod_media.normalize_source(path)
            record = json.loads((Path(folder) / 'source.json').read_text())
            self.assertEqual(record['media']['sha256'], vod_media.sha256(path))
            self.assertLess(abs(self.decoded(path)[0][0]), .05)

    def test_partial_download_is_not_normalized(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'video.mp4.part'
            path.write_bytes(b'not complete')
            with self.assertRaises(ValueError):
                vod_media.normalize_source(path)
            self.assertEqual(path.read_bytes(), b'not complete')

    def test_incomplete_duration_is_rejected_before_original_is_changed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.source(folder)
            original_hash = vod_media.sha256(path)
            (Path(folder) / 'source.json').write_text(json.dumps({'duration_seconds': 30}))
            with self.assertRaisesRegex(ValueError, 'duration differs'):
                vod_media.normalize_source(path)
            self.assertEqual(vod_media.sha256(path), original_hash)
            self.assertFalse((Path(folder) / 'timestamp-normalization.json').exists())


class BoundaryTests(unittest.TestCase):
    def discover(self, rows, duration):
        # The legacy reader supplies its first-HUD cue. Exercise the extra
        # cues for a broadcast where shields cannot be measured.
        first = next(row['t'] for row in rows if row['hud'])
        legacy = SimpleNamespace(propose_segments=lambda facts, identity: [
            {'start': first, 'first_hud_seconds': first,
             'cues': [{'kind': 'first_visible_hud'}], 'notes': []}])
        with patch.dict(sys.modules, {'segment_battles': legacy}):
            return discover_segments(rows, 'broadcast', duration)

    def candidate(self, start=0, end=200, view='left'):
        return {'start': start, 'end': end, 'first_hud_seconds': start + 1,
                'view_id': view, 'cues': [{'kind': 'first_visible_hud'}],
                'completeness': 'result_unseen_or_edited', 'notes': []}

    def test_midbattle_start_stays_incomplete_and_lobby_tail_is_removed(self):
        rows = [{'t': t, 'hud': t < 60, 'result': 'win' if t in (60, 80, 100) else None} for t in range(201)]
        found = annotate_segments([self.candidate()], rows, '123', 'left', 201)[0]
        self.assertTrue(found['incomplete_start'])
        self.assertFalse(found['eligible_for_complete_battle_evaluation'])
        self.assertEqual(found['end'], 62)

    def test_matching_perspectives_are_one_match_but_adjacent_games_stay_separate(self):
        views = {'left': [self.candidate(0, 100), self.candidate(150, 250)],
                 'right': [self.candidate(2, 101, 'right'), self.candidate(151, 249, 'right')]}
        groups = pair_perspectives(views, '123')
        self.assertEqual(len(groups), 2)
        self.assertEqual(len(groups[0]), 2)
        self.assertEqual(views['left'][0]['match_id'], views['right'][0]['match_id'])
        self.assertNotEqual(views['left'][0]['match_id'], views['left'][1]['match_id'])

    def test_two_overlapping_intervals_on_same_perspective_are_not_merged(self):
        groups = pair_perspectives({'left': [self.candidate(0, 100), self.candidate(5, 105)]}, '123')
        self.assertEqual(len(groups), 2)

    def test_lobby_gap_splits_battles_without_readable_shields_or_results(self):
        rows = [{'t': t, 'hud': t < 60 or t >= 110, 'party': [3, 3],
                 'shields_total': None} for t in range(180)]
        clips = self.discover(rows, 180)
        self.assertEqual(len(clips), 2)
        self.assertEqual(clips[0]['end'], 71)
        self.assertLessEqual(clips[1]['start'], 110)

    def test_sustained_party_reset_splits_rapid_next_game_without_shields(self):
        rows = [{'t': t, 'hud': True, 'party': [3, 3] if t < 40 or t >= 75 else [1, 2],
                 'shields_total': None} for t in range(150)]
        clips = self.discover(rows, 150)
        self.assertEqual(len(clips), 2)
        self.assertEqual(clips[1]['first_hud_seconds'], 75)

    def test_charged_animation_gap_does_not_create_a_second_battle(self):
        rows = [{'t': t, 'hud': not 35 <= t <= 54, 'party': [3, 3],
                 'shields_total': None} for t in range(110)]
        self.assertEqual(len(self.discover(rows, 110)), 1)

    def test_labelled_replays_are_excluded_from_live_match_candidates(self):
        live = {**self.candidate(0, 80), 'incomplete_start': True, 'incomplete_end': False}
        replay = {**self.candidate(110, 150), 'incomplete_start': False, 'incomplete_end': False}
        markers = [{'t': t, 'kind': 'replay'} for t in (112, 114, 116, 118)]
        kept, excluded = filter_broadcast({'left': [live, replay]}, markers)
        self.assertEqual(len(kept['left']), 1)
        self.assertEqual(excluded[0]['excluded_reason'], 'broadcast_replay')
        self.assertTrue(kept['left'][0]['incomplete_start'])

    def test_broadcast_result_bounds_tail_without_inventing_result_side(self):
        live = {**self.candidate(0, 150), 'incomplete_start': True, 'incomplete_end': False}
        kept, excluded = filter_broadcast({'left': [live]}, [{'t': 83, 'kind': 'match_win'}])
        clip = kept['left'][0]
        self.assertEqual(clip['end'], 85)
        self.assertTrue(clip['incomplete_start'])
        self.assertFalse(clip['eligible_for_complete_battle_evaluation'])
        self.assertNotIn('result_side', clip)

    def test_replay_entrance_before_badge_is_not_an_extra_live_match(self):
        replay = {**self.candidate(67, 113.5), 'first_hud_seconds': 68.5,
                  'incomplete_start': False, 'incomplete_end': False}
        kept, excluded = filter_broadcast({'right': [replay]},
                                          [{'t': t, 'kind': 'replay'} for t in (74, 76, 78)])
        self.assertEqual(kept['right'], [])
        self.assertEqual(len(excluded), 1)

    def test_replay_review_can_reuse_unchanged_cuts_but_never_different_video_or_crop(self):
        fingerprint = {'source_sha256': 'abc', 'reader_sha256': {'extract_battles.py': 'encoder'}}
        candidate = self.candidate(119.5, 298.5)
        previous = {'source_sha256': 'abc', 'source_viewport': [508, 56, 448, 976],
                    'encoding_crf': 23, 'vod_intake_fingerprint': fingerprint,
                    'boundary_candidate': {**candidate, 'match_id': 'old-index'}}
        view = {'viewport': [508, 56, 448, 976]}
        self.assertTrue(compatible_export(previous, {**candidate, 'match_id': 'correct-index'}, view, fingerprint))
        self.assertFalse(compatible_export(previous, candidate, {'viewport': [0, 0, 448, 976]}, fingerprint))
        self.assertFalse(compatible_export(previous, {**candidate, 'end': 299}, view, fingerprint))
        self.assertFalse(compatible_export(previous, candidate, view, {**fingerprint, 'source_sha256': 'other'}))


if __name__ == '__main__':
    unittest.main()
