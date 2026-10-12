"""Check portable public state records, with optional viewer and model comparisons."""
import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
import re
import subprocess

from vod import ROOT


def check(exports, reader=None, baseline=None):
    if baseline and not re.fullmatch(r"[0-9a-fA-F]{7,40}", baseline):
        raise ValueError("Use a commit checksum for --baseline")
    folders = sorted(exports.glob("tw-*"))
    if not folders:
        raise ValueError("No Twitch exports found")
    checks, statuses = [], Counter()
    for folder in folders:
        viewer = None
        if reader:
            with gzip.open(reader / "battles" / folder.name / "viewer-data.json.gz", "rt", encoding="utf-8") as stream:
                viewer = json.load(stream)["readings"]
        count, previous = 0, -1
        with gzip.open(folder / "continuity.jsonl.gz", "rt", encoding="utf-8") as stream:
            for count, line in enumerate(stream, 1):
                row = json.loads(line)
                state = row["game_state"]
                if not previous < row["t"] or state["t"] != row["t"] or state["schema"] != "public-game-state-v2":
                    raise ValueError(f"Invalid state time/schema in {folder.name} row {count}")
                previous = row["t"]
                if viewer is not None:
                    if count > len(viewer) or viewer[count - 1]["game_state"] != state or viewer[count - 1]["t"] != row["t"]:
                        raise ValueError(f"Viewer differs from export in {folder.name} row {count}")
                    if state["controls"] != viewer[count - 1]["buttons"]:
                        raise ValueError(f"Controls differ from current frame in {folder.name} row {count}")
                if state["pending_attack"]:
                    statuses["frames_with_pending_attack"] += 1
                for side in state["sides"].values():
                    for mon in side["pokemon"].values():
                        for name in ("species", "cp", "health", "energy"):
                            field = mon[name]
                            statuses[f"{name}.{field['status']}"] += 1
                            if field["status"] == "pending" and field["value"] != field.get("last_known_value"):
                                raise ValueError(f"Pending value lost provenance in {folder.name}")
                            if name == "energy" and field["value"] is not None:
                                if not all(type(value) is int and 0 <= value <= 100 for value in field["value"]):
                                    raise ValueError(f"Energy must have whole-unit bounds in {folder.name}")
        if not count or (viewer is not None and count != len(viewer)):
            raise ValueError(f"Missing continuity frames in {folder.name}")
        unchanged = []
        if baseline:
            for name in ("observations.jsonl.gz", "states.jsonl.gz", "events.jsonl.gz"):
                before = subprocess.check_output(["git", "show", f"{baseline}:games/twitch/{folder.name}/{name}"], cwd=ROOT)
                if before != (folder / name).read_bytes():
                    raise ValueError(f"Model output differs: {folder.name}/{name}")
                unchanged.append(name)
        checks.append({"id": folder.name, "frames": count, "export_matches_viewer": True if reader else None,
                       "model_outputs_unchanged": unchanged if baseline else None})
    return {"passed": True, "views": len(checks), "sampled_frames": sum(c["frames"] for c in checks),
            "baseline_commit": baseline, "viewer_comparison_run": bool(reader),
            "model_comparison_run": bool(baseline), "field_lifecycles": dict(statuses), "checks": checks,
            "accuracy_verified": False,
            "limits": "Persistence and provenance only; this does not measure recognition accuracy."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exports", type=Path, default=ROOT / "games/twitch")
    parser.add_argument("--reader-dir", type=Path)
    parser.add_argument("--baseline", help="Commit checksum for byte comparisons of model observations/states/events")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = check(args.exports.resolve(), args.reader_dir.resolve() if args.reader_dir else None, args.baseline)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in ("checks", "field_lifecycles")}))


if __name__ == "__main__":
    main()
