"""Compare saved VOD transitions with a small, visually reviewed regression set.

python scripts/recording/check_transition_labels.py [--revision COMMIT] [--output report.json]
"""
from __future__ import annotations
import argparse
import gzip
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def check(labels, read):
    details = []
    totals = {name: {"correct": 0, "expected": 0, "extra": 0} for name in ("assembly", "model")}
    for clip in labels["clips"]:
        folder = f"games/twitch/{clip['id']}"
        source = json.loads(read(folder + "/source.json"))
        if source["video_sha256"] != clip["video_sha256"]:
            raise ValueError("Labels refer to a different video")
        timeline = json.loads(read(folder + "/timeline.json"))
        events = [json.loads(line) for line in gzip.decompress(read(folder + "/events.jsonl.gz")).splitlines()]
        for side, expected in clip["transitions"].items():
            assembled = [(item["name"].lower(), "faint" if item["faint"] else "switch") for item in timeline["field"][side][1:]]
            prefix = "my" if side == "mine" else "foe"
            modeled = [(item.get("next", item.get("to", "")).lower(), item["event"].split("_")[-1]) for item in events
                       if item["event"] in (prefix + "_faint", prefix + "_switch")]
            wanted = [(item["name"].lower(), item["kind"]) for item in expected]
            for method, observed in (("assembly", assembled), ("model", modeled)):
                correct = sum(a == b for a, b in zip(wanted, observed))
                totals[method]["correct"] += correct
                totals[method]["expected"] += len(wanted)
                totals[method]["extra"] += max(0, len(observed) - len(wanted))
                details.append({"clip": clip["id"], "side": side, "method": method, "correct": correct,
                                "expected": wanted, "observed": observed})
    return {"evaluation_role": labels["evaluation_role"], "scope": labels["scope"], "clips": len(labels["clips"]),
            "totals": totals, "passed": all(t["correct"] == t["expected"] and not t["extra"] for t in totals.values()),
            "details": details}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", type=Path, default=ROOT / "data/vod_transition_labels.json")
    parser.add_argument("--revision")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    def read(path):
        if args.revision:
            return subprocess.check_output(["git", "show", f"{args.revision}:{path}"], cwd=ROOT)
        return (ROOT / path).read_bytes()
    result = check(json.loads(args.labels.read_text(encoding="utf-8")), read)
    result["revision"] = args.revision or "working_tree"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "details"}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
