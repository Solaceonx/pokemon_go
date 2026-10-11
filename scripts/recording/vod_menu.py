"""Small Windows entry point for the two calibrated Twitch pilot recordings."""
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main():
    layouts = json.loads((ROOT / 'data/vod_layouts.json').read_text(encoding='utf-8'))['layouts']
    choices = list(layouts.items())
    print('Cut Twitch recordings into battles\n')
    for index, (_, layout) in enumerate(choices, 1):
        print(f'{index}. {layout["channel"]} - recording {layout["source_ids"][0]}')
    print('\nThese two screen layouts have been measured. Other recordings need a layout first.')
    selected = input('Choose 1 or 2: ').strip()
    if selected not in {str(i) for i in range(1, len(choices) + 1)}:
        print('No recording selected.')
        return 2
    key, layout = choices[int(selected) - 1]
    command = [sys.executable, str(HERE / 'vod.py'),
               f'https://www.twitch.tv/videos/{layout["source_ids"][0]}',
               '--layout', key, '--download']
    library = ROOT.parent / 'pokemon-go-screen-reader'
    if (library / 'sources').is_dir() and (library / 'battles').is_dir():
        command += ['--sources-root', str(library / 'sources'), '--library', str(library / 'battles'),
                    '--reader-dir', str(library), '--downloader', str(library / 'tools/yt-dlp.exe')]
        clips = library / 'battles'
    else:
        clips = ROOT / '.vod/battles'
    print('\nThis keeps one original recording and reuses matching battle clips.')
    result = subprocess.run(command, cwd=ROOT)
    if result.returncode == 0:
        check = [sys.executable, str(HERE / 'vod_verify.py'), layout['source_ids'][0], '--library', str(clips)]
        if (library / 'segment_battles.py').is_file():
            check += ['--reader-dir', str(library)]
        result = subprocess.run(check, cwd=ROOT)
        if result.returncode:
            print('\nA saved video failed verification. See media-validation.json in the report folder.')
            return result.returncode
        if (library / 'build_lazy_viewer.py').is_file() and clips == library / 'battles':
            subprocess.run([sys.executable, str(library / 'build_lazy_viewer.py')], cwd=library, check=True)
            subprocess.run([sys.executable, str(library / 'launch_viewer.py')], cwd=library, check=True)
        print('\nBattle clips are ready. Their game-state analysis is still pending.')
        print(f'Report: {ROOT / ".vod/runs" / layout["source_ids"][0] / "run.json"}')
    else:
        print('\nThe job stopped. Partial downloads are kept so they can be resumed.')
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
