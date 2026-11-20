"""Archive every source-reviewed battle privately, without admitting unknown leagues.

This outer driver uses the frozen cutter and frame/alignment verifier. Its
preflight is deliberately nondeleting; a separate reviewed action must retire
the exact full inputs. Accepted collection manifests and reader code stay intact.
"""
import argparse
import copy
import hashlib
import math
import os
from contextlib import ExitStack
from pathlib import Path

try:
    from . import collection_ops as ops, source_guard
except ImportError:
    import collection_ops as ops
    import source_guard


def counted_facts(path):
    path = Path(path)
    with path.open('rb') as stream:
        before = os.fstat(stream.fileno())
        digest, consumed = hashlib.sha256(), 0
        while True:
            block = stream.read(4 * 1024 * 1024)
            if not block:
                break
            consumed += len(block)
            digest.update(block)
        after = os.fstat(stream.fileno())
    fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns')
    if consumed != before.st_size or any(getattr(before, k) != getattr(after, k) for k in fields):
        raise ValueError('Incomplete counted EOF read or changed file identity')
    return {'sha256': digest.hexdigest(), 'bytes': consumed, 'device': after.st_dev,
            'inode': after.st_ino, 'mtime_ns': after.st_mtime_ns}


def reviewed_candidates(manifest, pending):
    """Reject missing/duplicated raw fragments before any media is created."""
    sid = manifest.get('source_id', '')
    if not isinstance(sid, str) or not sid.isdigit() or sid != pending.get('source_id') or sid in ops.EXCLUDED:
        raise ValueError('Wrong, unsafe or reserved source')
    if (manifest.get('manual_source_context_review_completed') is not True
            or manifest.get('source_reviewed_intake_completed') is not True
            or manifest.get('scan_coverage', {}).get('full_recording_scanned') is not True):
        raise ValueError('Whole-source context and continuous-battle review required')
    coverage = manifest['scan_coverage']
    duration = coverage.get('source_seconds', 0)
    if not duration or coverage.get('scanned_seconds', 0) < duration or coverage.get('selection_limited') is not False:
        raise ValueError('Full, unbounded source scan required')
    raw_rows = {r['id']: r for rows in pending['views'].values() for r in rows}
    raw = [r['id'] for rows in pending['views'].values() for r in rows]
    if not raw or len(raw) != len(set(raw)):
        raise ValueError('Raw source fragments missing or duplicated')
    rows, fragments, seen = [], [], set()
    for view, candidates in manifest['views'].items():
        last_end = -1
        for row in candidates:
            cid = row['id']
            if (not isinstance(cid, str) or Path(cid).name != cid or '/' in cid or '\\' in cid
                    or not cid.startswith('tw-' + sid + '-') or cid in seen):
                raise ValueError('Unsafe or duplicated battle ID')
            if row.get('view_id') != view or row.get('source_id') != sid:
                raise ValueError('Battle source or view differs')
            start, end = row['start'], row['end']
            if not all(isinstance(t, (float, int)) and math.isfinite(t) for t in (start, end)) or not 0 <= start < end <= duration or start < last_end:
                raise ValueError('Invalid or overlapping reviewed battle boundaries')
            if row.get('source_boundary_review') != 'manual_source_frames' or not row.get('raw_fragment_ids'):
                raise ValueError('Battle has no source-reviewed continuous grouping')
            if any(i not in raw_rows or start > raw_rows[i]['start'] or end < raw_rows[i]['end'] for i in row['raw_fragment_ids']):
                raise ValueError('Continuous archive would lose a raw fragment or animation')
            fragments.extend(row['raw_fragment_ids'])
            rows.append(row)
            seen.add(cid)
            last_end = end
    if (not rows or len(fragments) != len(set(fragments)) or set(fragments) != set(raw)
            or manifest.get('raw_fragment_count') != len(raw)):
        raise ValueError('Every frozen raw fragment must occur exactly once')
    return rows


def owned_path(root, *parts):
    root = Path(root).resolve()
    path = root.joinpath(*parts).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError('Archive path escapes owned workspace')
    return path


def inputs(worker, sid):
    root = ops.worker_root(worker).resolve()
    canonical = owned_path(root, 'runs', sid)
    manifest = ops.load(canonical / 'battle-candidates.json')
    ops.verify_source_calibration_proofs(manifest)
    proof_keys = [key for key in manifest['source_calibration_proofs_sha256']
                  if key.endswith('/calibrated-candidates.pending.json')]
    if len(proof_keys) != 1:
        raise ValueError('Exactly one pinned original raw-candidate manifest required')
    pending = ops.load(owned_path(ops.BASE, proof_keys[0]))
    candidates = reviewed_candidates(manifest, pending)
    source_dir = owned_path(root, 'sources', 'twitch', sid)
    record = ops.load(source_dir / 'source.json')
    review = ops.load(canonical / 'league-review.json')
    expected = manifest['fingerprint']['source_sha256']
    if record.get('media', {}).get('sha256') != expected or review.get('source_sha256') != expected:
        raise ValueError('Source record or league-review provenance differs')
    return root, canonical, manifest, candidates, source_dir, record


def source_pair(source_dir, expected):
    result = {name: counted_facts(source_dir / name) for name in ('video.mp4', 'raw-original.ts')}
    if result['video.mp4']['sha256'] != expected:
        raise ValueError('Normalized source differs from reviewed source')
    # Raw discrepancies remain historical evidence even when current bytes agree.
    return result


def archive(worker, sid):
    vod = ops.frozen_modules()
    from vod_verify import verify
    root, canonical, manifest, candidates, source_dir, record = inputs(worker, sid)
    canonical_sha = ops.digest(canonical / 'battle-candidates.json')
    run = owned_path(canonical, 'archival-all-reviewed-v1')
    library = owned_path(root, 'archival-cuts', sid)
    archive_manifest = copy.deepcopy(manifest)
    archive_manifest['archive_only'] = True
    archive_manifest['accepted_collection_admission'] = False
    archive_manifest['export_selection'] = {'clip_ids': [r['id'] for r in candidates],
                                          'purpose': 'private_all_reviewed_battle_archival'}
    if (run / 'battle-candidates.json').exists() and ops.load(run / 'battle-candidates.json') != archive_manifest:
        raise ValueError('Existing archive has a different reviewed manifest')
    with ExitStack() as stack:
        for name in ('video.mp4', 'raw-original.ts'):
            stack.enter_context(source_guard.ReadLease(source_dir / name))
        before = source_pair(source_dir, manifest['fingerprint']['source_sha256'])
        if __import__('shutil').disk_usage(root).free < 50 * 1024**3:
            raise ValueError('Keep the required 50GiB free reserve')
        ops.write(run / 'battle-candidates.json', archive_manifest)
        views = {r['id']: r for r in manifest['fingerprint']['layout']['views']}
        for candidate in candidates:
            cid = candidate['id']
            saved, destination = root / 'cuts' / cid, owned_path(library, cid)
            if saved.is_dir():
                meta = ops.load(saved / 'battle.json')
                if (meta.get('boundary_candidate') != candidate or meta.get('source_sha256') != before['video.mp4']['sha256']
                        or counted_facts(saved / 'video.mp4')['sha256'] != meta['video_sha256']):
                    raise ValueError('Existing accepted cut provenance differs')
                destination.mkdir(parents=True, exist_ok=True)
                for name in ('video.mp4', 'battle.json', 'frame_alignment.jsonl.gz'):
                    original, linked = saved / name, destination / name
                    if linked.exists():
                        if ops.digest(linked) != ops.digest(original):
                            raise ValueError('Existing archival link differs')
                    else:
                        os.link(original, linked)
            else:
                vod.export_one(source_dir / 'video.mp4', candidate, views[candidate['view_id']], library,
                               manifest['fingerprint'], record.get('creator') or manifest['fingerprint']['layout']['channel'],
                               manifest['url'], record, preserve_existing=True)
        validation = verify(sid, library, run)
        if not validation['media_checks_passed']:
            raise ValueError('All retained battle cuts must pass frame/alignment verification')
        after = source_pair(source_dir, manifest['fingerprint']['source_sha256'])
        if before != after or ops.digest(canonical / 'battle-candidates.json') != canonical_sha:
            raise ValueError('Source inputs or canonical accepted manifest changed')
        cut_facts = {r['id']: {name: counted_facts(library / r['id'] / name)
                               for name in ('video.mp4', 'battle.json', 'frame_alignment.jsonl.gz')} for r in candidates}
        proof = {'schema': 'private-reviewed-battle-archive-v1', 'source_id': sid, 'archive_only': True,
                 'done': False, 'source_complete': False, 'accepted_collection_admission': False,
                 'full_game_state_verified': False, 'paired_source_integrity_passed': False,
                 'historical_input_discrepancies_preserved': True, 'source_before': before, 'source_after': after,
                 'canonical_manifest_sha256': canonical_sha, 'archive_manifest_sha256': ops.digest(run / 'battle-candidates.json'),
                 'validation_sha256': ops.digest(run / 'media-validation.json'), 'cuts': cut_facts,
                 'cut_count': len(candidates), 'completed_utc': ops.now(), 'freeze': ops.verify_freeze()}
        ops.write(run / 'archive-proof.json', proof)
    return proof


def preflight(worker, sid):
    root, canonical, manifest, candidates, source_dir, record = inputs(worker, sid)
    run = owned_path(canonical, 'archival-all-reviewed-v1')
    library = owned_path(root, 'archival-cuts', sid)
    proof = ops.load(run / 'archive-proof.json')
    validation = ops.load(run / 'media-validation.json')
    ids = {r['id'] for r in candidates}
    if (not validation['media_checks_passed'] or ids != {r['id'] for r in validation['checked_clips']}
            or ids != set(proof['cuts']) or proof['canonical_manifest_sha256'] != ops.digest(canonical / 'battle-candidates.json')
            or proof['archive_manifest_sha256'] != ops.digest(run / 'battle-candidates.json')
            or proof['validation_sha256'] != ops.digest(run / 'media-validation.json')):
        raise ValueError('Incomplete or changed full archival verification')
    actual = source_pair(source_dir, manifest['fingerprint']['source_sha256'])
    if actual != proof['source_after']:
        raise ValueError('Full-source inputs changed since archival verification')
    for cid in ids:
        for name, expected in proof['cuts'][cid].items():
            if counted_facts(owned_path(library, cid, name)) != expected:
                raise ValueError('A retained cut or alignment changed after verification')
    unique = {(r['device'], r['inode']): r['bytes'] for r in actual.values()}
    result = {'schema': 'private-battle-archive-retirement-preflight-v1', 'source_id': sid,
              'preflight_passed': True, 'deleted': False, 'deletion_authorized': False,
              'requires_separate_root_review': True, 'all_reviewed_cuts_verified': len(ids),
              'accepted_collection_admission': False, 'full_game_state_verified': False,
              'paired_source_integrity_passed': False, 'historical_input_discrepancies_preserved': True,
              'exact_full_source_targets': [{'path': str(source_dir / name), **fact} for name, fact in actual.items()],
              'unique_source_bytes': sum(unique.values()), 'freeze': ops.verify_freeze(), 'captured_utc': ops.now()}
    ops.write(run / 'retirement-preflight.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['archive', 'preflight'])
    parser.add_argument('--work-root', type=Path, default=ops.BASE)
    parser.add_argument('--worker', choices=['worker-a', 'worker-b'], required=True)
    parser.add_argument('--source-id', required=True)
    parser.add_argument('--cpu', type=int, choices=[0, 1, 2], required=True)
    args = parser.parse_args()
    ops.BASE = args.work_root.resolve()
    ops.FROZEN = ops.BASE / 'frozen-reader'
    ops.pin(args.cpu)
    result = archive(args.worker, args.source_id) if args.stage == 'archive' else preflight(args.worker, args.source_id)
    print(__import__('json').dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    main()
