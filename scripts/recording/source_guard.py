"""Windows read leases and byte checks for retained VOD inputs.

The lease denies normal write opens. Hash rechecks remain required; this does not
claim to explain any earlier mismatch or prevent every filesystem filter change.
This module does not delete media. Paired-retirement verification returns exact
eligible paths for the existing, separately authorized cleanup layer.
"""
from __future__ import annotations

import argparse
import ctypes
from contextlib import ExitStack, contextmanager, nullcontext
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def facts(path):
    path = Path(path)
    with path.open('rb') as stream:
        before = os.fstat(stream.fileno())
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            digest.update(chunk)
        after = os.fstat(stream.fileno())
    fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns')
    if any(getattr(before, k) != getattr(after, k) for k in fields):
        raise ValueError('Source identity/size/time changed during hashing')
    return {'sha256': digest.hexdigest(), 'bytes': after.st_size,
            'device': after.st_dev, 'inode': after.st_ino, 'mtime_ns': after.st_mtime_ns}


class ReadLease:
    """Hold a Windows read handle denying write access; optionally allow rename."""
    def __init__(self, path, *, allow_replace=False):
        self.path = Path(path).resolve()
        self.allow_replace = allow_replace
        self.handle = None

    def __enter__(self):
        if os.name != 'nt':
            raise RuntimeError('Mandatory file-sharing read leases require Windows')
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong,
                                      ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p]
        kernel.CreateFileW.restype = ctypes.c_void_p
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        share = 1 | (4 if self.allow_replace else 0)  # READ, optionally DELETE; never WRITE
        handle = kernel.CreateFileW(str(self.path), 0x80000000, share, None, 3, 0x80, None)
        if handle is None or handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        self.kernel, self.handle = kernel, handle
        return self

    def __exit__(self, *exc):
        if self.handle is not None:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def owned_files(source_dir):
    """Only these two completed media names are eligible, never .part files."""
    source_dir = Path(source_dir).resolve()
    if not source_dir.name.isdigit():
        raise ValueError('Expected an exact numeric source directory')
    result = {}
    for name in ('video.mp4', 'raw-original.ts'):
        path = (source_dir / name).resolve()
        if not path.is_relative_to(source_dir) or path.parent != source_dir:
            raise ValueError('Source target escapes its exact input directory')
        if path.is_file():
            result[name] = path
    return result


def preserve_raw(source_dir, expected_sha):
    """Create one original-input hardlink before normalization, without copying."""
    source_dir = Path(source_dir).resolve()
    paths = owned_files(source_dir)
    if 'video.mp4' not in paths or list(source_dir.glob('*.part*')):
        raise ValueError('A completed source with no partial download is required')
    before = facts(paths['video.mp4'])
    if before['sha256'] != expected_sha:
        raise ValueError('Raw source differs from the recorded download')
    raw = source_dir / 'raw-original.ts'
    if not raw.exists():
        os.link(paths['video.mp4'], raw)
    backup = facts(raw)
    if (backup['sha256'] != expected_sha or backup['device'] != before['device']
            or backup['inode'] != before['inode']):
        raise ValueError('Raw preservation is not the expected original hardlink')
    return {'schema': 'vod-raw-hardlink-v1', 'source_id': source_dir.name,
            'raw': backup, 'one_physical_raw_copy': True}


def checked_pair(source_dir, expected):
    """Verify both exact inputs; count an inode once when calculating bytes."""
    paths = owned_files(source_dir)
    if set(paths) != {'video.mp4', 'raw-original.ts'} or set(expected) != set(paths):
        raise ValueError('Both exact full-source paths and expected hashes are required')
    actual = {name: facts(path) for name, path in paths.items()}
    for name, value in actual.items():
        if value['sha256'] != expected[name]:
            raise ValueError('Retained source bytes changed: ' + name)
    unique = {(v['device'], v['inode']): v['bytes'] for v in actual.values()}
    return {'schema': 'vod-paired-source-check-v1', 'source_id': Path(source_dir).name,
            'files': actual, 'unique_inode_bytes': sum(unique.values()),
            'logical_path_bytes': sum(v['bytes'] for v in actual.values()),
            'media_deleted': False}


def guarded_command(source_dir, expected, command):
    """Keep immutable full-source reads across a child command, rechecking after."""
    with ExitStack() as stack:
        for path in owned_files(source_dir).values():
            stack.enter_context(ReadLease(path))
        before = checked_pair(source_dir, expected)
        process = subprocess.run(command, check=False)
        after = checked_pair(source_dir, expected)
    if before != after:
        raise ValueError('Source evidence changed while the reader ran')
    return {'schema': 'vod-guarded-command-v1', 'exit_code': process.returncode,
            'source_pair': after, 'normal_write_access_denied_during_command': True,
            'filesystem_filter_immunity_claimed': False}


@contextmanager
def normalized_input(source_dir, raw_sha, normalize):
    """Preserve raw input, run the unchanged normalizer, then hold read leases.

    ``normalize(video_path, record_path)`` must return the frozen normalizer's
    media facts. A mismatch aborts rather than relabelling any earlier evidence.
    """
    source_dir = Path(source_dir).resolve()
    raw, video = source_dir / 'raw-original.ts', source_dir / 'video.mp4'
    if raw.is_file() and facts(raw)['sha256'] == raw_sha and not os.path.samefile(raw, video):
        preservation = {'schema': 'vod-raw-resume-v1', 'raw': facts(raw),
                        'previously_preserved_raw_verified': True}
    else:
        preservation = preserve_raw(source_dir, raw_sha)
    with ExitStack() as stack:
        stack.enter_context(ReadLease(raw, allow_replace=True))
        result = normalize(video, source_dir / 'source.json')
        # Tighten raw sharing after the replacement. Opening the second lease
        # while the first remains live avoids an unprotected transition.
        stack.enter_context(ReadLease(raw))
        stack.enter_context(ReadLease(video))
        expected = {'raw-original.ts': raw_sha, 'video.mp4': result['sha256']}
        before = checked_pair(source_dir, expected)
        record = json.loads((source_dir / 'source.json').read_text(encoding='utf-8-sig'))
        if record.get('media', {}).get('sha256') != expected['video.mp4']:
            raise ValueError('Normalizer result and recorded source metadata disagree')
        try:
            yield {'schema': 'vod-normalized-input-lease-v1', 'expected': expected,
                   'raw_preservation': preservation, 'source_pair': before,
                   'normalized_media': result,
                   'filesystem_filter_immunity_claimed': False}
        finally:
            if checked_pair(source_dir, expected) != before:
                raise ValueError('Paired source changed during guarded reads')
            current_record = json.loads((source_dir / 'source.json').read_text(encoding='utf-8-sig'))
            if current_record.get('media', {}).get('sha256') != expected['video.mp4']:
                raise ValueError('Recorded source provenance changed during guarded reads')


def retire_verified_pair(worker, worker_root, sid, expected, ops):
    """Retire a paired input ONLY after nonempty accepted cuts were verified.

    This deliberately refuses uncut excluded sources. Their deletion remains
    subject to the owner's separate, pending approval.
    """
    root = Path(worker_root).resolve()
    if worker not in ('worker-a', 'worker-b') or ops.worker_root(worker).resolve() != root:
        raise ValueError('Worker source root mismatch')
    source = root / 'sources' / 'twitch' / sid
    if not isinstance(sid, str) or not sid.isdigit() or source.resolve().parent != (root / 'sources/twitch').resolve():
        raise ValueError('Invalid exact source id')
    run = root / 'runs' / sid
    manifest = json.loads((run / 'battle-candidates.json').read_text(encoding='utf-8-sig'))
    if not manifest.get('export_selection', {}).get('clip_ids'):
        raise ValueError('Paired cleanup requires accepted verified cuts; uncut sources are refused')
    pair = checked_pair(source, expected)
    normalized, raw = pair['files']['video.mp4'], pair['files']['raw-original.ts']
    shared = (normalized['device'], normalized['inode']) == (raw['device'], raw['inode'])
    # Existing authorized retirement performs all source/cut/alignment/freeze
    # checks. It deletes only video.mp4; raw remains recoverable until recheck.
    retirement = ops.retire(worker, sid)
    if not retirement.get('deleted') or retirement.get('reason') != 'all_accepted_cuts_verified':
        raise ValueError('Normalized-source retirement did not prove accepted cuts')
    standard = root / 'receipts' / (sid + '-source-retirement.json')
    parent_sha = facts(standard)['sha256']
    try:
        if ops.retained_after_retirement(root, sid, manifest) is not True:
            raise ValueError('Accepted cut retirement proof is unavailable')
        lease = ReadLease(source / 'raw-original.ts', allow_replace=True) if os.name == 'nt' else nullcontext()
        with lease:
            if facts(source / 'raw-original.ts')['sha256'] != expected['raw-original.ts']:
                raise ValueError('Raw original changed before final cleanup')
            (source / 'raw-original.ts').unlink()
    except Exception:
        retirement['source_bytes'] = 0 if shared else normalized['bytes']
        retirement['raw_original_retained'] = True
        ops.write(standard, retirement)
        raise
    retirement.update(source_bytes=pair['unique_inode_bytes'], raw_original_retained=False,
        normalized_path_bytes=normalized['bytes'], raw_path_bytes=raw['bytes'],
        prior_normalized_retirement_sha256=parent_sha, unique_inode_accounting=True,
        paired_full_sources_retired=True)
    ops.write(standard, retirement)
    return retirement


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, required=True)
    parser.add_argument('--expected', type=Path, required=True,
                        help='JSON mapping video.mp4 and raw-original.ts to their exact hashes')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command:
        parser.error('A reader command is required after --')
    result = guarded_command(args.source_dir,
        json.loads(args.expected.read_text(encoding='utf-8-sig')), command)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + '\n', encoding='utf8')
    raise SystemExit(result['exit_code'])


if __name__ == '__main__':
    main()
