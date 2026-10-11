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
from vod_segments import annotate_segments, coarse_scan, discover_segments, pair_perspectives
from vod_broadcast import cue_matches, filter_broadcast, marker_scan
from vod import align_paired_coverage, coalesce_paired_fragments, compatible_export, refine_result_markers, result_refinement_windows, select_battles


@unittest.skipUnless(importlib.util.find_spec("av"), "video checks require the reader's PyAV environment")
class TimestampTests(unittest.TestCase):
    def source(self, folder, *, all_keyframes=False):
        import av
        import numpy as np
        path = Path(folder) / "video.mp4"
        with av.open(str(path), "w", format="mpegts", options={"mpegts_copyts": "1"}) as container:
            stream = container.add_stream("libx264", rate=15)
            stream.width, stream.height, stream.pix_fmt = 192, 320, "yuv420p"
            stream.options = {"preset": "ultrafast", "tune": "zerolatency"}
            if all_keyframes:
                stream.codec_context.gop_size = 1
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

    def test_bounded_discovery_excludes_later_frames_and_rejects_different_window_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.source(folder, all_keyframes=True)
            vod_media.normalize_source(path)
            fake_ocr = SimpleNamespace(read=lambda image: [{'text': 'REPLAY', 'confidence': 1}])
            with patch.dict(sys.modules, {'local_ocr': SimpleNamespace(LocalOCR=lambda: fake_ocr)}), patch(
                    'vod_segments.sample_frame', side_effect=lambda frame, profile, ocr, **kwargs:
                        {'t': float(frame.pts * frame.time_base), 'hud': False, 'countdown': False}):
                cache = Path(folder) / 'bounded.json.gz'
                found = coarse_scan(path, {'left': {}}, cache, scan_end=.5)
                self.assertEqual(found['duration_seconds'], .5)
                self.assertEqual(len(found['views']['left']), 8)
                self.assertTrue(all(r['t'] < .5 for r in found['views']['left']))
                with self.assertRaisesRegex(ValueError, 'Scan inputs changed'):
                    coarse_scan(path, {'left': {}}, cache, scan_end=.75)
                markers = marker_scan(path, [{'rect': [0, 0, 20, 20], 'kind': 'replay', 'cue': 'REPLAY'}],
                                      Path(folder) / 'markers.json.gz', scan_end=.5)
                self.assertEqual(len(markers), 8)
                self.assertTrue(all(m['t'] < .5 for m in markers))

    def test_partial_download_is_not_normalized(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'video.mp4.part'
            path.write_bytes(b'not complete')
            with self.assertRaises(ValueError):
                vod_media.normalize_source(path)
            self.assertEqual(path.read_bytes(), b'not complete')

    def test_brief_result_between_keyframes_is_found_in_refined_window(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.source(folder)
            vod_media.normalize_source(path)
            fake_ocr = SimpleNamespace(read=lambda image: [{'text':'GAME WIN!', 'confidence':1}]
                if image[:,:,2].mean() > 50 else [])
            region = {'rect':[0,0,20,20], 'kind':'match_win', 'cue':'GAMEWIN'}
            with patch.dict(sys.modules, {'local_ocr':SimpleNamespace(LocalOCR=lambda:fake_ocr)}):
                self.assertEqual(marker_scan(path,[region],Path(folder)/'keys.gz'), [])
                markers = refine_result_markers(path,[region],[[.5,1.5]],Path(folder)/'fine.gz')
                self.assertTrue(markers)
                self.assertTrue(all(.5 <= m['t'] < 1.5 for m in markers))

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
    def test_result_refinement_skips_known_peer_ends_and_partial_source_edges(self):
        base = {'start':100,'end':280,'completeness':'result_unseen_or_edited',
                'eligible_for_complete_battle_evaluation':True}
        self.assertEqual(result_refinement_windows({'left':[base],'right':[{**base,'completeness':'result_visible'}]},400), [])
        self.assertEqual(result_refinement_windows({'left':[{**base,'eligible_for_complete_battle_evaluation':False}]},400), [])
        self.assertEqual(result_refinement_windows({'left':[base],'right':[base]},400), [[268,282]])
    def test_paired_end_covers_delayed_result_and_attributes_its_evidence(self):
        shared = {'start':655.5, 'incomplete_start':False, 'incomplete_end':False,
                  'end_method':'last_hud_tail', 'notes':[]}
        left = {**shared,'id':'left-1','view_id':'left','end':833.75,'completeness':'result_visible','notes':[]}
        right = {**shared,'id':'right-1','view_id':'right','end':829.25,'completeness':'result_unseen_or_edited','notes':[]}
        align_paired_coverage([[left,right]])
        self.assertEqual(right['end'],833.75)
        self.assertEqual(right['completeness'],'paired_result_visible')
        self.assertEqual(right['paired_boundary_evidence']['own_end'],829.25)
        self.assertEqual(right['paired_boundary_evidence']['result_views'][0]['view_id'],'left')
        self.assertEqual(left['completeness'],'result_visible')

    def test_paired_end_never_restores_missing_source_edge(self):
        views = self.fragmented_pair()
        left, right = views['left'][0], views['right'][1]
        left['view_id'], right['view_id'] = 'left','right'
        right['incomplete_start'] = True
        before = json.loads(json.dumps([left,right]))
        align_paired_coverage([[left,right]])
        self.assertEqual([left,right],before)

    def fragmented_pair(self):
        shared = {'source_id':'official', 'start':1709.132333, 'end':1875.952333,
            'completeness':'result_visible', 'eligible_for_complete_battle_evaluation':True,
            'incomplete_start':False, 'incomplete_end':False, 'start_method':'first_hud_context',
            'end_method':'visible_result', 'end_uncertainty_seconds':2, 'cues':[], 'notes':[]}
        anchor = {**shared, 'id':'left-1'}
        first = {**shared, 'id':'right-1', 'end':1728.566333, 'completeness':'result_unseen_or_edited'}
        second = {**shared, 'id':'right-2', 'start':1728.432333, 'start_method':'entry_gap_or_edit'}
        return {'left':[anchor], 'right':[first, second]}

    def test_peer_interval_recovers_complete_view_split_by_animation(self):
        views = self.fragmented_pair()
        result = coalesce_paired_fragments(views)
        self.assertEqual(len(result['right']), 1)
        self.assertEqual(result['right'][0]['start'], views['right'][0]['start'])
        self.assertEqual(result['right'][0]['end'], views['right'][1]['end'])
        self.assertEqual(result['right'][0]['completeness'], 'result_visible')
        self.assertEqual(len(result['right'][0]['paired_fragment_join']['fragments']), 2)
        self.assertEqual(len(views['right']), 2)

    def test_peer_join_does_not_swallow_new_game_countdown(self):
        views = self.fragmented_pair()
        views['right'][1]['cues'] = [{'kind':'countdown','t':1728.5}]
        self.assertEqual(coalesce_paired_fragments(views), views)

    def test_peer_join_requires_contiguous_same_source_coverage(self):
        views = self.fragmented_pair()
        views['right'][1]['start'] += 5
        self.assertEqual(coalesce_paired_fragments(views), views)
        views = self.fragmented_pair()
        views['right'][1]['source_id'] = 'another_recording'
        self.assertEqual(coalesce_paired_fragments(views), views)

    def test_live_game_immediately_after_replay_is_not_discarded(self):
        replay = {'first_hud_seconds':2081.25, 'start':2079.75, 'end':2107.0, 'notes':[],
                  'incomplete_start':False, 'incomplete_end':False}
        live = {**replay, 'first_hud_seconds':2108.5, 'start':2107.0, 'end':2260.0}
        markers = [{'t':float(t),'kind':'replay'} for t in range(2078,2107,2)]
        kept, excluded = filter_broadcast({'left':[replay,live]}, markers)
        self.assertEqual(len(kept['left']), 1)
        self.assertEqual(kept['left'][0]['first_hud_seconds'], live['first_hud_seconds'])
        self.assertEqual(kept['left'][0]['end'], live['end'])
        self.assertEqual(len(excluded), 1)
        self.assertEqual(excluded[0]['first_hud_seconds'], replay['first_hud_seconds'])

    def test_official_result_graphics_accept_calibrated_font_readings(self):
        region = {'cue': 'GAMEWIN', 'cues': ['GAMEWIN', 'GAMIWIN', 'MATCHWIN']}
        self.assertTrue(cue_matches(region, 'GAMI WINI'))
        self.assertTrue(cue_matches(region, 'MATCH WIN!'))
        self.assertFalse(cue_matches(region, 'Swinub used Icy Wind!'))
        self.assertFalse(cue_matches(region, 'No Protect Shields remaining'))

    def test_existing_replay_cue_keeps_its_single_cue_behavior(self):
        self.assertTrue(cue_matches({'cue':'REPLAY'}, 'REPLAY'))
        self.assertFalse(cue_matches({'cue':'REPLAY'}, 'GAME WIN!'))

    def selection_candidates(self):
        return {view: [{'id': f'{view}-{i}', 'match_id': f'match-{i}', 'view_id': view,
                       'first_hud_seconds': i * 100, 'eligible_for_complete_battle_evaluation': True,
                       'completeness': 'result_visible'} for i in (3, 1, 2)] for view in ('left', 'right')}

    def test_battle_limit_counts_games_not_player_views(self):
        found = select_battles(self.selection_candidates(), 2, required_views={'left', 'right'})
        self.assertEqual([c['id'] for c in found], ['left-1', 'right-1', 'left-2', 'right-2'])

    def test_complete_pair_selection_skips_partial_unpaired_and_resultless_games(self):
        views = self.selection_candidates()
        views['right'][1]['eligible_for_complete_battle_evaluation'] = False
        views['left'][2]['completeness'] = 'result_unseen_or_edited'
        views['right'].append({**views['right'][0], 'id': 'right-4', 'match_id': 'match-4', 'first_hud_seconds': 400})
        found = select_battles(views, 2, True, {'left', 'right'})
        self.assertEqual([c['id'] for c in found], ['left-3', 'right-3'])

    def test_nonpositive_battle_limit_is_rejected(self):
        with self.assertRaises(ValueError):
            select_battles(self.selection_candidates(), 0)

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
