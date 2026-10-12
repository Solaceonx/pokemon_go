"""One-click Windows entry point for the calibrated battle library."""
from pathlib import Path
import subprocess
import sys
from vod import ROOT, HERE, reader_location


def main():
    reader = reader_location(ROOT.parent / 'pokemon-go-screen-reader')
    library = reader / 'battles'
    if not library.exists():
        raise ValueError('The battles folder is missing. Cut the recordings first.')
    print('Tracking battle videos. Matching saved readings will be reused.\n', flush=True)
    done = subprocess.run([sys.executable, str(HERE / 'vod_track.py'), '--reader-dir', str(reader),
                           '--library', str(library), '--jobs', '2'], cwd=ROOT)
    if done.returncode:
        print('Tracking stopped; completed readings are retained.')
        return done.returncode
    subprocess.run([sys.executable, str(reader / 'build_lazy_viewer.py')], cwd=reader, check=True)
    subprocess.run([sys.executable, str(reader / 'launch_viewer.py')], cwd=reader, check=True)
    print('\nThe viewer is ready. Consistency results and uncertain values are saved with each clip.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
