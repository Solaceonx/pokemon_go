"""Count abstention causes on saved frames; these are not accuracy scores."""
import gzip
import json
from collections import Counter
from pathlib import Path
from battle_library import scan_library


def diagnose(root):
    result = {}
    for meta in scan_library(root):
        if not meta.get("viewer_data_file"):
            continue
        package = root / meta["id"] / meta["viewer_data_file"]
        with gzip.open(package, "rt", encoding="utf-8") as stream:
            rows = json.load(stream)["readings"]
        if not rows:
            continue
        sides = {}
        for side in ("mine", "opponent"):
            status = Counter(); reasons = Counter(); scenes = Counter()
            for row in rows:
                estimate = row[side].get("health_estimate", {})
                status[estimate.get("status", "not_estimated")] += 1
                if estimate.get("reason"):
                    reasons[estimate["reason"]] += 1
                scenes[row["phase"].get("value") or "unclassified"] += 1
            sides[side] = {"frames": len(rows), "health_status": dict(status),
                           "estimated_frame_fraction": status["estimated"]/len(rows),
                           "abstention_reasons": dict(reasons.most_common()), "scenes": dict(scenes)}
        result[package.parent.name] = {"analysis_status": meta["analysis_status"],
            "decoded_frames": len(rows), "expected_clip_frames": meta.get("frames"),
            "full_frame_count_matches": len(rows) == meta.get("frames"), "sides": sides}
    return {"meaning": "Coverage and abstention counts on active saved readings; these are not ground-truth accuracy", "battles": result}


if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    data = diagnose(root / "battles")
    (root / "output/health-diagnostics.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(json.dumps(data))
