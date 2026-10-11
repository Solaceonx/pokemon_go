"""Decode exported VOD clips and check every saved frame against its alignment log."""
import argparse
import gzip
import json
from pathlib import Path
import time

from vod import ROOT, bootstrap, reader_location
from vod_media import sha256, write_json


def verify(source_id, library):
    import av
    library = Path(library).resolve()
    run = ROOT / '.vod/runs' / str(source_id)
    manifest = json.loads((run / 'battle-candidates.json').read_text(encoding='utf-8'))
    clips, failures = [], []
    started = time.monotonic()
    for candidates in manifest['views'].values():
        for candidate in candidates:
            folder = library / candidate['id']
            try:
                if not folder.resolve().is_relative_to(library):
                    raise ValueError('Clip folder escapes library')
                meta = json.loads((folder / 'battle.json').read_text(encoding='utf-8'))
                video = folder / meta['video_file']
                if not video.resolve().is_relative_to(folder.resolve()):
                    raise ValueError('Video path escapes clip folder')
                if sha256(video) != meta['video_sha256']:
                    raise ValueError('Saved clip checksum differs')
                if meta['boundary_candidate'] != candidate:
                    raise ValueError('Saved clip has different boundaries')
                count, previous, maximum_error = 0, -1, 0
                with av.open(str(video)) as source, gzip.open(folder / 'frame_alignment.jsonl.gz', 'rt', encoding='utf-8') as alignment:
                    for frame in source.decode(video=0):
                        line = alignment.readline()
                        if not line:
                            raise ValueError('Video has more frames than its alignment log')
                        row = json.loads(line)
                        t = float(frame.pts * frame.time_base)
                        if t <= previous or row['clip_frame_index'] != count:
                            raise ValueError('Frame times or alignment indices are not increasing')
                        error = max(abs(t - row['clip_seconds']),
                                    abs(row['source_seconds'] - meta['source_start_seconds'] - t))
                        maximum_error = max(maximum_error, error)
                        if error > 1 / meta['fps'] + .001:
                            raise ValueError('Clip timing disagrees with its source alignment')
                        if not candidate['start'] - .001 <= row['source_seconds'] < candidate['end']:
                            raise ValueError('Saved frame lies outside proposed cut')
                        previous, count = t, count + 1
                    if alignment.readline():
                        raise ValueError('Alignment log has more frames than the video')
                    if count != meta['frames']:
                        raise ValueError('Decoded frame count differs from metadata')
                    if abs(source.duration / av.time_base - (candidate['end'] - meta['source_start_seconds'])) > .12:
                        raise ValueError('Saved duration disagrees with cut interval')
                    if (source.streams.video[0].width, source.streams.video[0].height) != tuple(meta['source_viewport'][2:]):
                        raise ValueError('Saved crop dimensions differ from layout')
                    if bool(source.streams.audio) != meta['audio_in_video']:
                        raise ValueError('Audio presence differs from metadata')
                clips.append({'id': candidate['id'], 'decoded_frames': count,
                              'maximum_alignment_error_seconds': round(maximum_error, 7),
                              'video_bytes': video.stat().st_size,
                              'saved_data_bytes': sum(p.stat().st_size for p in folder.iterdir() if p.is_file() and p != video)})
                print(json.dumps({'stage': 'validate', 'clip': candidate['id'], 'decoded_frames': count}), flush=True)
            except (OSError, ValueError, KeyError, TypeError) as error:
                failures.append({'id': candidate['id'], 'error': str(error)})
    report = {'source_id': str(source_id), 'media_checks_passed': not failures,
              'checked_clips': clips, 'failures': failures,
              'total_decoded_frames': sum(c['decoded_frames'] for c in clips),
              'saved_data_bytes': sum(c['saved_data_bytes'] for c in clips),
              'elapsed_seconds': round(time.monotonic() - started, 3),
              'game_states_verified': False, 'battle_boundaries_exactly_verified': False}
    write_json(run / 'media-validation.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source_id', type=int)
    parser.add_argument('--library', type=Path, default=ROOT / '.vod/battles')
    parser.add_argument('--reader-dir', type=Path)
    args = parser.parse_args()
    bootstrap(reader_location(args.reader_dir))
    report = verify(args.source_id, args.library)
    print(json.dumps(report))
    return int(not report['media_checks_passed'])


if __name__ == '__main__':
    raise SystemExit(main())
