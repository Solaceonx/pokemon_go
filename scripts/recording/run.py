"""Recordings in, tracked games and a pass/fail report out, with nobody watching.

    python3 scripts/recording/run.py recording.mp4 [more.mp4 ...] [--jobs 2] [--reread] [--fps 15]

For each recording: read it once (slow; kept, compressed, in games/<name>/raw/), split it into battles,
and for each battle assemble the looks, run the tracker and apply the checks in verdict.py.
Battles go to games/<name>-1, games/<name>-2, ...; the report goes to games/report.json.

Reading needs the screen reader, which is not part of this branch (see README.md here). It is looked for in
.reader/ at the top of the project, or wherever these point:
  READER_PYTHON  a Python 3.12 with av, opencv, onnxruntime and rapidocr-onnxruntime
  READER_DIR     the screen_reader folder of the screen-reader-video-pipeline branch
Everything after reading is plain python3 and can be re-run at any time without the reader.
"""
import concurrent.futures, gzip, json, os, re, shutil, subprocess, sys, tempfile, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pogo.gamedata import GameData
from verdict import verdict

HERE = Path(__file__).resolve().parent


def run(*cmd, cwd=ROOT, env=None):
    done = subprocess.run([str(c) for c in cmd], cwd=cwd, env=env, capture_output=True, text=True)
    if done.returncode not in (0, 1):  # track.py and verdict.py return 1 for "finished, with problems"
        raise RuntimeError((done.stderr or done.stdout).strip().splitlines()[-1] if (done.stderr or done.stdout).strip() else "failed")
    return done.stdout


def read(video: Path, raw: Path, extra: list) -> dict:
    """Run the screen reader over one recording and keep its output compressed."""
    # By default the reader lives in .reader/ at the top of the project (not in git): py312 is its Python
    # environment and branch is a checkout of screen-reader-video-pipeline.
    python = os.environ.get("READER_PYTHON") or str(ROOT / ".reader" / "py312" / "bin" / "python")
    reader = os.environ.get("READER_DIR") or str(ROOT / ".reader" / "branch" / "screen_reader")
    if not Path(python).exists() or not Path(reader).exists():
        raise RuntimeError("the screen reader is not set up: see scripts/recording/README.md")
    profiles = Path(reader) / "profiles"
    if not (profiles / "lyxia-great.json").exists():  # the layout we use, built on the reader's own iPhone layout
        shutil.copy(HERE / "lyxia-great.json", profiles / "lyxia-great.json")
        if not (profiles / "lyxia-great").exists():
            shutil.copytree(profiles / "reis-great", profiles / "lyxia-great")
    with tempfile.TemporaryDirectory() as tmp:
        run(python, HERE / "read_recording.py", video, tmp, *extra, cwd=reader, env={**os.environ, "PYTHONPATH": "."})
        raw.mkdir(parents=True, exist_ok=True)
        for name in ("readings.jsonl", "text.jsonl"):
            with open(Path(tmp) / name, "rb") as src, gzip.open(raw / (name + ".gz"), "wb", compresslevel=9) as dst:
                shutil.copyfileobj(src, dst)
        shutil.copy(Path(tmp) / "read.json", raw / "read.json")
    return json.loads((raw / "read.json").read_text())


def one(video: Path, reread: bool, extra: list, gd: GameData) -> list[dict]:
    name = re.sub(r"[^a-z0-9]+", "-", video.stem.lower()).strip("-")
    raw = ROOT / "games" / name / "raw"
    started = time.time()
    try:
        timing = read(video, raw, extra) if reread or not (raw / "readings.jsonl.gz").exists() else json.loads((raw / "read.json").read_text())
        sources = (raw / "readings.jsonl.gz", raw / "text.jsonl.gz")
        count = int(run(sys.executable, HERE / "assemble.py", *sources, raw, "--count").strip() or 0)
    except Exception as err:  # noqa: BLE001 - one bad recording must not stop the batch
        return [{"game": name, "verdict": "fail", "failed": [f"reading: {err}"], "notes": [], "recording": str(video)}]
    if not count:
        return [{"game": name, "verdict": "fail", "failed": ["no battle found in the recording"], "notes": [], "recording": str(video)}]
    out = []
    for k in range(1, count + 1):
        game = ROOT / "games" / f"{name}-{k}"
        try:
            run(sys.executable, HERE / "assemble.py", *sources, game, "--battle", k)
            run(sys.executable, ROOT / "scripts" / "track.py", game)
            v = verdict(game, gd)
        except Exception as err:  # noqa: BLE001
            v = {"game": game.name, "verdict": "fail", "failed": [f"tracking: {err}"], "notes": []}
        else:
            (game / "verdict.json").write_text(json.dumps(v, indent=1) + "\n")
        v.update(recording=str(video), read_seconds=timing.get("seconds"), video_seconds=timing.get("video_seconds"))
        out.append(v)
    out[0]["wall_seconds"] = round(time.time() - started, 1)
    return out


def main() -> int:
    args = sys.argv[1:]
    def take(flag, default):
        if flag in args:
            i = args.index(flag); value = args[i + 1]; del args[i:i + 2]; return value
        return default
    jobs, fps = int(take("--jobs", 2)), take("--fps", None)
    reread = "--reread" in args
    videos = [Path(a).expanduser().resolve() for a in args if not a.startswith("--")]
    if not videos:
        print(__doc__); return 2
    extra = ["--fps", fps] if fps else []
    gd, report = GameData(), []
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        for verdicts in pool.map(lambda v: one(v, reread, extra, gd), videos):
            for v in verdicts:
                report.append(v)
                print(f"{v['verdict'].upper():4s} {v['game']}: " + (f"{v.get('result') or 'no result'}, {v.get('looks')} looks, {v.get('charged_moves')} charged moves; " if "looks" in v else "")
                      + ("; ".join(v["failed"] + v["notes"]) or "all checks clean"), flush=True)
    path = ROOT / "games" / "report.json"
    kept = [v for v in (json.loads(path.read_text()) if path.exists() else []) if v["game"] not in {r["game"] for r in report}]
    path.write_text(json.dumps(kept + report, indent=1) + "\n")
    passed = sum(v["verdict"] == "pass" for v in report)
    print(f"{passed} of {len(report)} battles passed; report in games/report.json")
    return 0 if passed == len(report) else 1


if __name__ == "__main__":
    sys.exit(main())
