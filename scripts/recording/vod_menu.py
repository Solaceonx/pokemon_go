"""Windows entry point: extract the whole recording, including partial battles."""
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def intake_command(url, layout, reader, run):
    command = [sys.executable, str(HERE / 'vod.py'), url, '--layout', layout,
               '--download', '--resegment', '--run-dir', str(run)]
    if (reader / 'sources').is_dir() and (reader / 'battles').is_dir():
        command += ['--sources-root', str(reader / 'sources'), '--library', str(reader / 'battles'),
                    '--reader-dir', str(reader), '--downloader', str(reader / 'tools/yt-dlp.exe')]
    return command


def main():
    from vod import bootstrap, reader_location
    reader = reader_location(ROOT.parent / 'pokemon-go-screen-reader')
    bootstrap(reader)
    from import_source import canonical_source
    layouts = json.loads((ROOT / 'data/vod_layouts.json').read_text(encoding='utf-8'))['layouts']
    choices = list(layouts.items())
    print('Extract every battle from a recording\n')
    for index, (_, layout) in enumerate(choices, 1):
        print(f'{index}. {layout["channel"]} - recording {layout["source_ids"][0]}')
    print('\nYou can also paste a completed Twitch VOD or YouTube video link.')
    print('The whole recording is scanned. Battles with clipped starts or endings are kept.')
    selected = input('Recording number or video link: ').strip()
    if selected in {str(i) for i in range(1, len(choices) + 1)}:
        key, layout = choices[int(selected) - 1]
        url = f'https://www.twitch.tv/videos/{layout["source_ids"][0]}'
    else:
        key, url = 'auto', selected
    try:
        platform, identity, url = canonical_source(url)
    except ValueError as error:
        print(str(error))
        return 2
    run = ROOT / '.vod/runs' / f'{platform}-{identity}-full'
    command = intake_command(url, key, reader, run)
    clips = reader / 'battles' if (reader / 'battles').is_dir() else ROOT / '.vod/battles'
    print('\nThe original and matching saved clips are reused. Scanning can take several minutes.')
    result = subprocess.run(command, cwd=ROOT)
    if result.returncode:
        print('\nThe job stopped. Partial downloads and scan receipts are retained for resume.')
        return result.returncode
    summary = json.loads((run / 'run.json').read_text(encoding='utf-8'))
    if not summary['scan_coverage']['full_recording_scanned'] or summary['scan_coverage']['selection_limited']:
        print('\nThis was a limited scan, so it cannot be presented as the full recording.')
        return 2
    check = [sys.executable, str(HERE / 'vod_verify.py'), identity,
             '--run-dir', str(run), '--library', str(clips), '--reader-dir', str(reader)]
    result = subprocess.run(check, cwd=ROOT)
    if result.returncode:
        print('\nA saved video failed verification. See media-validation.json in the report folder.')
        return result.returncode
    if (reader / 'build_lazy_viewer.py').is_file() and clips == reader / 'battles':
        subprocess.run([sys.executable, str(reader / 'build_lazy_viewer.py')], cwd=reader, check=True)
        subprocess.run([sys.executable, str(reader / 'launch_viewer.py')], cwd=reader, check=True)
    print(f"\nScanned the full recording: {summary['export_selection']['unique_battles']} battle candidates, "
          f"{len(summary['exports'])} player videos. Partial battles are included.")
    print('Video extraction is complete. The battle count still needs review; game-state tracking is a separate step.')
    print(f'Report: {run / "run.json"}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
