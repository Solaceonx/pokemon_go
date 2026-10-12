"""Export reviewed visible screen readings into the supplied tracker's format.

Review files explicitly approve fighting intervals, the battle time origin and
charged events. No inferred energy, moves, clocks or unreviewed HP are exported.
"""
import argparse
import json
from pathlib import Path
from battle_io import read_jsonl


def observed(reading):
    if reading.get("status") == "observed":
        return reading.get("value")
    return None


def export(readings, review):
    origin = review["battle_start_source_seconds"]
    intervals = review["reviewed_fighting_intervals"]
    events = sorted(review.get("charged_events", []), key=lambda e: e["source_seconds"])
    output, provenance = [], []
    last_source = None
    consumed = set()
    for reading in sorted(readings, key=lambda r: r["timestamp_seconds"]):
        source = reading["timestamp_seconds"]
        if source < origin or not any(a <= source <= b for a, b in intervals):
            continue
        if last_source is not None and source - last_source < review.get("sample_interval_seconds", 0.5) - 1e-5:
            continue
        look = {"t": round(source - origin, 6)}
        for side, prefix in [("mine", "my"), ("opponent", "foe")]:
            values = reading[side]
            for field, target in [("species", "species"), ("cp", "cp"),
                                  ("shields_left", "shields"), ("pokemon_left", "left")]:
                value = observed(values.get(field, {}))
                if value is not None:
                    if field == "species":
                        value = review.get("visible_species_forms", {}).get(value, value)
                    look[f"{prefix}_{target}"] = value
            # A health reading needs explicit approval at this timestamp. Colored
            # extent alone does not distinguish health from pending-damage animation.
            approved = review.get("approved_health", {}).get(str(source), {})
            if prefix in approved:
                share = approved[prefix]
                if not isinstance(share, (int, float)) or not 0 <= share <= 1:
                    raise ValueError("Approved HP must be a measured share in [0, 1]")
                look[f"{prefix}_hp"] = share
        pending = [(i, e) for i, e in enumerate(events)
                   if i not in consumed and e["source_seconds"] <= source]
        for side in ["my", "foe"]:
            matching = [(i, e) for i, e in pending if e["side"] == side]
            if len(matching) > 1:
                raise ValueError(f"Two {side} charged events before source {source}; add a reviewed look between them")
            if matching:
                i, event = matching[0]
                if event["source_seconds"] < origin:
                    raise ValueError("Charged event precedes battle origin")
                if side == "my":
                    look["my_charged"] = event["move"]
                else:
                    look["foe_charged"] = True
                    if event.get("move"):
                        look["foe_move"] = event["move"]
                consumed.add(i)
        if len(look) == 1:
            continue
        output.append(look)
        provenance.append({"t": look["t"], "source_seconds": source,
                           "source_pts": reading.get("source_pts"),
                           "source_time_base": reading.get("source_time_base")})
        last_source = source
    unconsumed = [e for i, e in enumerate(events) if i not in consumed]
    return output, provenance, unconsumed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("readings", type=Path)
    parser.add_argument("review", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    review = json.loads(args.review.read_text(encoding="utf-8"))
    readings = list(read_jsonl(args.readings))
    looks, sources, pending = export(readings, review)
    if pending:
        raise ValueError("Charged events have no later reviewed fighting look")
    if not looks:
        raise ValueError("No reviewed observations to export")
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "team.json").write_text(json.dumps(review.get("team", {"pokemon": []}), indent=2) + "\n", encoding="utf-8")
    (args.output / "observations.jsonl").write_text("".join(json.dumps(look) + "\n" for look in looks), encoding="utf-8")
    (args.output / "source_alignment.jsonl").write_text("".join(json.dumps(row) + "\n" for row in sources), encoding="utf-8")
    (args.output / "report.md").write_text(review["report"] + f"\n\nExported {len(looks)} observations.\n", encoding="utf-8")
    print(json.dumps({"observations": len(looks), "output": str(args.output)}))


if __name__ == "__main__":
    main()
