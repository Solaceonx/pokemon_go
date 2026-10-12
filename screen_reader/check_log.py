"""Compare visual observations with timestamped engine/ground-truth snapshots."""
import argparse
from bisect import bisect_left
import json
from pathlib import Path
from battle_io import read_jsonl


def compare(observations, expected, max_skew=0.05):
    observations = sorted(observations, key=lambda row: row["timestamp_seconds"])
    times = [row["timestamp_seconds"] for row in observations]
    checks = []
    for snapshot in expected:
        timestamp = snapshot["timestamp_seconds"]
        i = bisect_left(times, timestamp)
        indexes = [j for j in [i-1, i] if 0 <= j < len(times)]
        best = min(indexes, key=lambda j: abs(times[j]-timestamp)) if indexes else None
        reading = observations[best] if best is not None and abs(times[best]-timestamp) <= max_skew else None
        for side in ["mine", "opponent"]:
            for field, expected_value in snapshot.get(side, {}).items():
                row = {"timestamp_seconds": timestamp, "side": side, "field": field, "expected": expected_value}
                if reading is None:
                    checks.append({**row, "status": "no_matching_frame"}); continue
                if field in {"hp", "health_fraction"}:
                    health = reading[side]["health_bar"]["value"]
                    if health is None:
                        checks.append({**row, "status": "unreadable"}); continue
                    if field == "hp":
                        max_hp = snapshot[side].get("max_hp")
                        if max_hp is None or max_hp <= 0:
                            checks.append({**row, "status": "missing_max_hp"}); continue
                        actual = health["fraction"]*max_hp
                        error = abs(actual-expected_value)
                        pixel_unit = health["pixel_resolution_fraction"]*max_hp
                        status = "resolution_limited" if pixel_unit > 1 else ("pass" if error <= 1 else "mismatch")
                        checks.append({**row, "status": status, "measured_hp_equivalent": round(actual, 3),
                                       "absolute_error_hp": round(error, 3), "hp_per_normalized_pixel": round(pixel_unit, 3)})
                    else:
                        error = abs(health["fraction"]-expected_value)
                        checks.append({**row, "status": "pass" if error <= 0.01 else "mismatch",
                                       "measured": health["fraction"], "absolute_error_fraction": round(error, 5)})
                elif field != "max_hp":
                    actual = reading[side].get(field)
                    if not isinstance(actual, dict) or actual.get("status") != "observed":
                        checks.append({**row, "status": "unreadable_or_stale"}); continue
                    checks.append({**row, "status": "pass" if actual["value"] == expected_value else "mismatch", "measured": actual["value"]})
    summary = {}
    for check in checks:
        summary[check["status"]] = summary.get(check["status"], 0)+1
    return {"checks": checks, "summary": summary,
            "engine_replay_performed": False,
            "note": "Comparison of supplied snapshots only; unreadable or resolution-limited readings never count as passes."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("observations", type=Path)
    parser.add_argument("expected", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-skew", type=float, default=0.05)
    args = parser.parse_args()
    if args.max_skew < 0:
        parser.error("max skew must be nonnegative")
    observations = list(read_jsonl(args.observations))
    expected = list(read_jsonl(args.expected))
    result = compare(observations, expected, args.max_skew)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result["summary"]))


if __name__ == "__main__":
    main()
