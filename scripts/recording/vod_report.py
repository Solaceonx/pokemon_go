"""Build a portable pilot manifest and measured storage report, without committing media."""
import argparse
import gzip
import json
from pathlib import Path
import statistics

from vod import ROOT
from vod_media import sha256, write_json


def battle_report(clip, summary):
    counts = summary['field_status_counts']
    lines = [f"# {clip['name']}", '', f"Source: {clip['source_url']}",
             f"Source interval: {clip['source_start_seconds']:.3f}-{clip['source_end_seconds']:.3f} seconds.",
             f"Match: `{clip['match_id']}`; view: `{clip['view_id']}`; dataset: `{clip['dataset_role']}`.", '',
             f"Read all saved clip time: {summary['sampled_frames']} samples at 15 Hz, text at 3 Hz; "
             f"{summary['model_states']} reconstructed model states.",
             f"Partial beginning: {clip['incomplete_start']}; partial ending: {clip['incomplete_end']}.", '',
             'Screen evidence includes names/CP, health bars, shields, party markers and visible controls.',
             'Bars can be absent or unsettled during attacks; compression, short sprites and broadcast overlays limit readings.',
             'HP remains a fractional interval. Maximum/integer HP, form and unseen roster are unverified.',
             'Fast moves, modeled energy, stages and switch timing are hypotheses, not screen observations.', '',
             '| Side | Visible health samples | Missing health samples | Estimated energy samples |',
             '|---|---:|---:|---:|']
    for side in ['mine', 'opponent']:
        lines.append(f"| {side} | {counts.get(side+'.health_bar.observed', 0)} | "
                     f"{counts.get(side+'.health_bar.unknown', 0)} | {counts.get(side+'.energy.estimated', 0)} |")
    lines += ['', f"Internal consistency: **{summary['tracking_verdict']['verdict']}**.", '']
    lines += ['- ' + reason for reason in summary['tracking_verdict']['failed']]
    lines += ['', 'Recognition accuracy has not been measured against independent human labels.',
              'The ledger retains unknown and stale values. A final announcement does not fabricate zero HP or a knockout.', '']
    folder = ROOT / 'games/twitch' / clip['id']
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'report.md').write_text('\n'.join(lines), encoding='utf-8')


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
                folder = library / candidate['id']
                meta = json.loads((folder / 'battle.json').read_text(encoding='utf-8'))
                saved_bytes = sum(p.stat().st_size for p in folder.rglob('*') if p.is_file() and p.name != meta['video_file'])
                clips.append({key: meta[key] for key in ['id', 'name', 'match_id', 'view_id', 'source_sha256',
                             'video_sha256', 'source_start_seconds', 'source_end_seconds', 'duration_seconds',
                             'video_bytes', 'frames', 'completeness', 'incomplete_start', 'incomplete_end',
                             'eligible_for_complete_battle_evaluation', 'analysis_status']}
                             | {'source_id': source_id, 'source_url': original['url'],
                                'dataset_role': candidate['dataset_role'], 'boundary_review_required': True,
                                'saved_data_bytes': saved_bytes,
                                'tracking_consistency': meta.get('tracking_consistency', 'not_run'),
                                'maximum_alignment_error_seconds': checked[candidate['id']]['maximum_alignment_error_seconds']})
        with gzip.open(run / 'coarse-scan.json.gz', 'rt', encoding='utf-8') as stream:
            scan = json.load(stream)
        own = [c for c in clips if c['source_id'] == source_id]
        sources.append({'source_id': source_id, 'url': original['url'], 'title': original['title'],
                        'creator': original['creator'], 'source_seconds': original['media']['duration_seconds'],
                        'source_bytes': original['media']['bytes'], 'source_sha256': original['media']['sha256'],
                        'source_copies_retained': 1, 'matches': manifest['unique_match_candidates'],
                        'perspective_clips': len(own), 'clip_video_bytes': sum(c['video_bytes'] for c in own),
                        'saved_clip_data_bytes': sum(c['saved_data_bytes'] for c in own),
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
                            'tracking_data_note': 'Includes raw and refined gzip readings, compressed model states, viewer data, alignment, metadata and retained analysis archives.'},
                'validation': {'media_checks_passed': True,
                               'decoded_frames_verified': sum(s['decoded_frames_verified'] for s in sources),
                               'maximum_alignment_error_seconds': max(c['maximum_alignment_error_seconds'] for c in clips),
                               'verification_code_sha256': sha256(Path(__file__).with_name('vod_verify.py'))},
                'dataset': {'split_unit': 'original_source_video', 'development': ['2894502346'],
                            'exposed_regression': ['2897295240'], 'untouched_test': [],
                            'notes': 'Keep paired views together. YouTube overlap is unchecked. No independent accuracy claim.'},
                'tracking_run': all(c['analysis_status'] != 'not_analyzed' for c in clips),
                'game_state_accuracy_measured': False, 'exact_boundary_accuracy_measured': False}
    tracked = []
    for c in clips:
        path = library / c['id'] / 'analysis-summary.json'
        if path.exists():
            summary = json.loads(path.read_text(encoding='utf-8'))
            battle_report(c, summary)
            tracked.append({'id': c['id'], 'match_id': c['match_id'], 'dataset_role': c['dataset_role'],
                            'sampled_frames': summary['sampled_frames'], 'model_states': summary['model_states'],
                            'verdict': summary['tracking_verdict']})
    if tracked:
        from collections import Counter
        failed = Counter(reason.split(':', 1)[0] for s in tracked for reason in s['verdict']['failed'])
        artifact['tracking'] = {'views_processed': len(tracked), 'sampled_frames': sum(s['sampled_frames'] for s in tracked),
                                'model_states': sum(s['model_states'] for s in tracked),
                                'view_consistency_passes': sum(s['verdict']['verdict'] == 'pass' for s in tracked),
                                'failure_categories': dict(failed), 'results': tracked,
                                'accuracy_verified': False, 'sampling_fps': 15, 'text_rate_hz': 3,
                                'unknowns': ['Exact IVs and maximum HP', 'Unseen teammates and moves',
                                             'Form and Shadow identity', 'Ambiguous fast moves and energy',
                                             'Unverified stage history and exact battle/switch clock']}
    browser = ROOT / '.vod/runs/viewer/viewer-validation.json'
    if browser.is_file():
        artifact['validation']['viewer'] = json.loads(browser.read_text(encoding='utf-8'))
    folder_check = browser.with_name('folder-validation.json')
    if folder_check.is_file():
        artifact['validation']['viewer_folder_import'] = json.loads(folder_check.read_text(encoding='utf-8'))
    tests = ROOT / '.vod/unit-tests.json'
    if tests.is_file():
        artifact['validation']['unit_tests'] = json.loads(tests.read_text(encoding='utf-8'))
    for name, key in [('tracking-validation.json', 'tracking_integrity'),
                      ('simulation-validation.json', 'simulated_tracker_regression'),
                      ('reader-tests.json', 'reader_unit_tests'),
                      ('export-replay-validation.json', 'compressed_export_replay')]:
        path = ROOT / '.vod' / name
        if path.is_file():
            artifact['validation'][key] = json.loads(path.read_text(encoding='utf-8'))
    measurements = ROOT / '.vod/tracking-measurements.json'
    if measurements.is_file() and tracked:
        artifact['tracking']['measurements'] = json.loads(measurements.read_text(encoding='utf-8'))
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
