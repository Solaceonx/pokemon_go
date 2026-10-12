"""Track the saved public clips again from their saved readings, to try a change on all of them at once.

    python3 scripts/recording/retrack_public.py OUT_FOLDER [--told] [assemble options ...]

Works from games/twitch/<clip>/raw/ (no video needed) and writes each clip's tracked game to OUT_FOLDER/<clip>,
leaving the published folders alone. --told gives each view of a two-screen match the fast moves the other
player's own buttons show (a first pass works those out), to see what knowing them is worth.
Any other options are passed to assemble.py.
"""
import json, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).resolve().parent))
from pogo.gamedata import GameData
from public_fast import prepare_team
from vod_track import augment_cp


def assemble_and_track(clip: Path, out: Path, extra: list, gd: GameData, told: dict | None = None) -> None:
    out.mkdir(parents=True, exist_ok=True)
    raw = clip / "raw"
    done = subprocess.run([sys.executable, ROOT / "scripts/recording/assemble.py", raw / "readings-refined.jsonl.gz", raw / "text.jsonl.gz", out,
                           "--public-footage", "--single-clip", *extra], cwd=ROOT, capture_output=True, text=True)
    if not (out / "team.json").exists():
        raise RuntimeError(done.stdout[-300:] + done.stderr[-300:])
    augment_cp(out, raw)
    prepare_team(out, gd)
    if told is not None:
        (out / "foes.json").write_text(json.dumps(told))
    elif (out / "foes.json").exists():
        (out / "foes.json").unlink()
    subprocess.run([sys.executable, ROOT / "scripts/track.py", out], cwd=ROOT, capture_output=True, text=True)


def main() -> None:
    args = sys.argv[1:]
    out_root, told_mode = Path(args[0]), "--told" in args
    extra = [a for a in args[1:] if a != "--told"]
    gd = GameData()
    ids = {v["speciesName"]: k for k, v in gd.species.items()}
    clips = sorted((ROOT / "games" / "twitch").glob("tw-*"))
    for clip in clips:
        try:
            assemble_and_track(clip, out_root / clip.name, extra, gd)
        except Exception as error:  # noqa: BLE001
            print(f"{clip.name}: {str(error)[:200]}")
    if told_mode:  # second pass for two-screen matches: each view is told what the other player's own buttons show
        match = {}
        for clip in clips:
            match.setdefault(json.loads((clip / "source.json").read_text())["match_id"], []).append(clip)
        for views in (v for v in match.values() if len(v) == 2):
            for me, other in (views, views[::-1]):
                own = json.loads((out_root / other.name / "player-fast-inference.json").read_text())
                told = {ids[name]: fit["selected"] for name, fit in own.items() if fit.get("selected") and name in ids}
                assemble_and_track(me, out_root / me.name, extra, gd, told)
                print(f"{me.name} told: {told}")


if __name__ == "__main__":
    main()
