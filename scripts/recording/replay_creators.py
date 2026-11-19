"""Replay cached creator records with local backups and resumable checkpoints.

No download or OCR is repeated. Failed consistency verdicts are retained. A
processing error keeps the previous export and makes this command fail.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

from vod import ROOT, bootstrap, reader_location
from vod_media import sha256, write_json
import vod_track


def metrics(folder):
    load = lambda name: json.loads((folder / name).read_text(encoding='utf-8'))
    verdict, track = load('verdict.json'), load('track.json')
    return {'verdict': verdict['verdict'], 'failed': verdict['failed'],
            'result': verdict.get('result'), 'unexplained': track['unexplained'],
            'rejected': track['rejected'], 'looks': track['looks']}


def locate_clip(folder):
    source = json.loads((folder / 'source.json').read_text(encoding='utf-8'))
    # Media roots are resolved from the existing export, never guessed ordinals.
    matches = [p for p in (ROOT / '.vod').glob('*/battles/' + source['id'])
               if (p / 'battle.json').is_file()]
    matches = [p for p in matches if json.loads((p / 'battle.json').read_text(
        encoding='utf-8')).get('video_sha256') == source.get('video_sha256')]
    if len(matches) != 1:
        raise ValueError(f'Expected exactly one matching cached clip for {folder.name}')
    meta = json.loads((matches[0] / 'battle.json').read_text(encoding='utf-8'))
    if sha256(matches[0] / meta['video_file']) != source['video_sha256']:
        raise ValueError(f'Cached clip bytes changed for {folder.name}')
    return matches[0]


def install_record(staged, folder, work):
    """Install a complete package; retain the previous one outside Git."""
    if (not staged.resolve().is_relative_to(work.resolve()) or
            not folder.resolve().is_relative_to((ROOT / 'games/creators').resolve()) or
            not work.resolve().is_relative_to((ROOT / '.vod').resolve())):
        raise ValueError('Record installation escaped its permitted folders')
    previous = work / 'previous-export' / folder.parent.name / (folder.name + '-' + uuid.uuid4().hex)
    previous.parent.mkdir(parents=True, exist_ok=True)
    moved = False
    try:
        if folder.exists():
            folder.rename(previous)
            moved = True
        staged.rename(folder)
    except Exception:
        if moved and not folder.exists():
            previous.rename(folder)
        raise


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--work', type=Path, required=True, help='Private .vod folder for backups and checkpoints')
    ap.add_argument('--reader-dir', type=Path)
    ap.add_argument('--source', action='append', default=[])
    ap.add_argument('--channel', action='append', default=[])
    ap.add_argument('--resume', action='store_true')
    ap.add_argument('--skip-index', action='store_true', help='Defer catalog rebuild for disjoint channel workers; rebuild once after all finish')
    args = ap.parse_args()
    work = args.work.resolve()
    if not work.is_relative_to((ROOT / '.vod').resolve()):
        ap.error('Backups and private diagnostics must stay under .vod')
    reader = reader_location(args.reader_dir)
    bootstrap(reader)
    code = {p.relative_to(ROOT).as_posix(): sha256(p) for p in [
        Path(__file__).resolve(), ROOT / 'scripts/recording/vod_track.py',
        ROOT / 'scripts/recording/assemble.py', ROOT / 'scripts/recording/vod_markers.py',
        ROOT / 'scripts/recording/creator_impact.py', ROOT / 'scripts/recording/creator_lifecycle.py',
        ROOT / 'scripts/recording/creator_state.py',
        ROOT / 'scripts/recording/creator_health.py',
        ROOT / 'scripts/recording/creator_observations.py',
        ROOT / 'scripts/recording/native_health.py',
        ROOT / 'scripts/recording/creator_frames.py',
        ROOT / 'scripts/recording/native_controls.py', ROOT / 'scripts/recording/creator_controls.py',
        ROOT / 'scripts/recording/creator_energy.py', ROOT / 'scripts/recording/buttons.py',
        ROOT / 'scripts/recording/creator_native_faints.py',
        ROOT / 'scripts/recording/creator_faint_support.py', ROOT / 'scripts/recording/creator_identity.py',
        ROOT / 'scripts/recording/creator_event_ledger.py',
        ROOT / 'scripts/recording/creator_move_labels.py',
        ROOT / 'scripts/recording/creator_charge_evidence.py',
        ROOT / 'scripts/recording/creator_announcements.py',
        ROOT / 'scripts/recording/public_state.py', ROOT / 'scripts/recording/state_continuity.py',
        ROOT / 'scripts/track.py',
        ROOT / 'scripts/recording/public_transitions.py', ROOT / 'scripts/recording/game_record.py',
        ROOT / 'scripts/recording/verdict.py', ROOT / 'pogo/tracker.py']}
    receipt_path = work / 'replay.json'
    if receipt_path.exists():
        if not args.resume:
            ap.error('Receipt already exists; use --resume or choose a new work folder')
        receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
        if receipt['code_sha256'] != code:
            ap.error('Replay code changed; use a new work folder')
    else:
        if args.resume:
            ap.error('No saved replay to resume')
        records = []
        for p in sorted((ROOT / 'games/creators').glob('*/*/game.json')):
            folder = p.parent
            if args.channel and folder.parent.name not in args.channel:
                continue
            if args.source and folder.name.split('-')[0] not in args.source:
                continue
            clip = locate_clip(folder)
            relative = folder.relative_to(ROOT / 'games/creators')
            backup = work / 'backup' / relative
            # Do not overwrite an earlier baseline on an interrupted start.
            if backup.exists():
                ap.error('Backup already exists without a receipt; choose a new work folder')
            shutil.copytree(folder, backup)
            raw = clip / 'tracking-raw'
            records.append({'record': folder.relative_to(ROOT).as_posix(),
                            'clip': clip.relative_to(ROOT).as_posix(), 'before': metrics(backup),
                            'raw_sha256': {name: sha256(raw / name) for name in
                                           ['screen.jsonl.gz', 'readings.jsonl.gz', 'text.jsonl.gz']}})
        if not records:
            ap.error('No matching canonical creator records')
        receipt = {'schema': 'creator-replay-v1', 'started_utc': datetime.now(timezone.utc).isoformat(),
                   'code_sha256': code, 'records': records, 'complete': False,
                   'accuracy_verified': False}
        write_json(receipt_path, receipt)
    for row in receipt['records']:
        if 'after' in row:
            continue
        folder, clip = ROOT / row['record'], ROOT / row['clip']
        try:
            raw = clip / 'tracking-raw'
            if any(sha256(raw / name) != expected for name, expected in row['raw_sha256'].items()):
                raise ValueError('Cached raw readings changed since the baseline')
            staged_root = work / 'staged' / folder.parent.name
            summary = vod_track.track_clip(clip, reader, creator_root=staged_root)
            staged = ROOT / summary['creator_game_folder']
            if staged.name != folder.name:
                raise ValueError('Replayed record identity differs from its baseline')
            subprocess.run([sys.executable, str(ROOT / 'scripts/recording/game_record.py'), str(staged)],
                           check=True, cwd=ROOT, capture_output=True)
            install_record(staged, folder, work)
            summary['creator_game_folder'] = folder.relative_to(ROOT).as_posix()
            row['after'] = metrics(folder)
            report = folder.parent / 'report.json'
            kept = json.loads(report.read_text(encoding='utf-8')) if report.exists() else []
            kept = [item for item in kept if item['id'] != summary['id']]
            write_json(report, sorted(kept + [summary], key=lambda item: item['id']))
            row.pop('error', None)
        except Exception as error:
            row['error'] = {'type': type(error).__name__, 'message': str(error)}
        write_json(receipt_path, receipt)
        print(json.dumps({'record': row['record'], 'processed': 'after' in row,
                          'verdict': row.get('after', {}).get('verdict')}), flush=True)
    if not args.skip_index:
        subprocess.run([sys.executable, str(ROOT / 'scripts/index_games.py')], cwd=ROOT, check=True)
    receipt['catalog_rebuild_deferred'] = args.skip_index
    receipt['complete'] = all('after' in r for r in receipt['records'])
    receipt['verdict_counts'] = dict(Counter(r.get('after', {}).get('verdict', 'processing_error')
                                           for r in receipt['records']))
    write_json(receipt_path, receipt)
    print(json.dumps({'complete': receipt['complete'], 'verdict_counts': receipt['verdict_counts']}))
    return 0 if receipt['complete'] else 1


if __name__ == '__main__':
    sys.exit(main())
