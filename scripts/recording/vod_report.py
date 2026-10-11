"""Build a portable pilot manifest and measured storage report, without committing media."""
import argparse
import gzip
import json
from pathlib import Path
import statistics

from vod import ROOT
from vod_media import sha256, write_json


def report(sources_root, library):
    sources, clips = [], []
    for source_id in ['2894502346', '2897295240']:
        run = ROOT / '.vod/runs' / source_id
        manifest = json.loads((run / 'battle-candidates.json').read_text(encoding='utf-8'))
        validation = json.loads((run / 'media-validation.json').read_text(encoding='utf-8'))
        original = json.loads((sources_root / 'twitch' / source_id / 'source.json').read_text(encoding='utf-8'))
        if not validation['media_checks_passed']:
            raise ValueError('Media verification must pass before publishing the pilot report')
        checked = {c['id']: c for c in validation['checked_clips']}
        for candidates in manifest['views'].values():
            for candidate in candidates:
                meta = json.loads((library / candidate['id'] / 'battle.json').read_text(encoding='utf-8'))
                clips.append({key: meta[key] for key in ['id', 'name', 'match_id', 'view_id', 'source_sha256',
                             'video_sha256', 'source_start_seconds', 'source_end_seconds', 'duration_seconds',
                             'video_bytes', 'frames', 'completeness', 'incomplete_start', 'incomplete_end',
                             'eligible_for_complete_battle_evaluation', 'analysis_status']}
                             | {'source_id': source_id, 'source_url': original['url'],
                                'dataset_role': candidate['dataset_role'], 'boundary_review_required': True,
                                'saved_data_bytes': checked[candidate['id']]['saved_data_bytes'],
                                'maximum_alignment_error_seconds': checked[candidate['id']]['maximum_alignment_error_seconds']})
        with gzip.open(run / 'coarse-scan.json.gz', 'rt', encoding='utf-8') as stream:
            scan = json.load(stream)
        own = [c for c in clips if c['source_id'] == source_id]
        sources.append({'source_id': source_id, 'url': original['url'], 'title': original['title'],
                        'creator': original['creator'], 'source_seconds': original['media']['duration_seconds'],
                        'source_bytes': original['media']['bytes'], 'source_sha256': original['media']['sha256'],
                        'source_copies_retained': 1, 'matches': manifest['unique_match_candidates'],
                        'perspective_clips': len(own), 'clip_video_bytes': sum(c['video_bytes'] for c in own),
                        'saved_clip_data_bytes': validation['saved_data_bytes'],
                        'partial_matches': len({c['match_id'] for c in own if c['incomplete_start'] or c['incomplete_end']}),
                        'excluded_replay_perspectives': len(manifest['excluded_candidates']),
                        'decoded_frames_verified': validation['total_decoded_frames'],
                        'coarse_scan_seconds': scan['elapsed_seconds'], 'coarse_scan_policy': 'keyframes',
                        'coarse_scan_notes': 'Measured under concurrent load; this is discovery, not full state reading.',
                        'fingerprint': manifest['fingerprint']})
    source_bytes = sum(s['source_bytes'] for s in sources)
    video_bytes = sum(c['video_bytes'] for c in clips)
    data_bytes = sum(c['saved_data_bytes'] for c in clips)
    complete_views = [c for c in clips if not (c['incomplete_start'] or c['incomplete_end'])]
    artifact = {'schema': 'vod-pilot-report-v1', 'sources': sources, 'clips': clips,
                'unique_match_candidates': sum(s['matches'] for s in sources),
                'perspective_clips': len(clips), 'partial_matches': sum(s['partial_matches'] for s in sources),
                'storage': {'units': 'bytes; MB and GB use decimal units', 'original_video_bytes': source_bytes,
                            'cropped_video_bytes': video_bytes, 'saved_clip_data_bytes': data_bytes,
                            'media_and_clip_data_bytes': source_bytes + video_bytes + data_bytes,
                            'median_complete_view_video_bytes': statistics.median(c['video_bytes'] for c in complete_views),
                            'mean_saved_data_bytes_per_view': data_bytes / len(clips),
                            'excludes': 'Shared runtime, pre-existing library, viewer HTML, scan caches and review images.',
                            'tracking_data_note': 'Saved clip data currently contains alignment and metadata; state tracking will add data.'},
                'validation': {'media_checks_passed': True,
                               'decoded_frames_verified': sum(s['decoded_frames_verified'] for s in sources),
                               'maximum_alignment_error_seconds': max(c['maximum_alignment_error_seconds'] for c in clips),
                               'verification_code_sha256': sha256(Path(__file__).with_name('vod_verify.py'))},
                'dataset': {'split_unit': 'original_source_video', 'development': ['2894502346'],
                            'exposed_regression': ['2897295240'], 'untouched_test': [],
                            'notes': 'Keep paired views together. YouTube overlap is unchecked. No independent accuracy claim.'},
                'tracking_run': False, 'game_state_accuracy_measured': False, 'exact_boundary_accuracy_measured': False}
    browser = ROOT / '.vod/runs/viewer/viewer-validation.json'
    if browser.is_file():
        artifact['validation']['viewer'] = json.loads(browser.read_text(encoding='utf-8'))
    tests = ROOT / '.vod/unit-tests.json'
    if tests.is_file():
        artifact['validation']['unit_tests'] = json.loads(tests.read_text(encoding='utf-8'))
    write_json(ROOT / 'data/vod_pilot_report.json', artifact)
    return artifact


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources-root', type=Path, default=ROOT / '.vod/sources')
    parser.add_argument('--library', type=Path, default=ROOT / '.vod/battles')
    args = parser.parse_args()
    artifact = report(args.sources_root.resolve(), args.library.resolve())
    print(json.dumps({'matches': artifact['unique_match_candidates'], 'clips': artifact['perspective_clips'],
                      'storage': artifact['storage'], 'verified_frames': artifact['validation']['decoded_frames_verified']}))


if __name__ == '__main__':
    main()
