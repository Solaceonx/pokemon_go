"""Compare assistant-reviewed frames separately from independent human accuracy."""
import bisect
import gzip
import json
from pathlib import Path
from dataset_tools import ROOT, digest


def check(labels, root=ROOT):
    details = []
    for label in labels:
        if label.get("provenance") != "assistant_visual_review" or not label.get("reviewed_without_predictions"):
            raise ValueError("This report only accepts explicit assistant visual reviews")
        image = root / label["image"]
        if digest(image) != label["image_sha256"]:
            raise ValueError("Reviewed image changed")
        folder = root / "battles" / label["battle_id"]
        meta = json.loads((folder / "battle.json").read_text(encoding="utf-8"))
        with gzip.open(folder / "viewer-data.json.gz", "rt", encoding="utf-8") as f:
            package = json.load(f)
        rows = package["readings"]
        t = label["clip_seconds"]
        index = bisect.bisect_right([r["t"] for r in rows], t+1e-9)-1
        row = rows[index] if index >= 0 and t-rows[index]["t"] <= 1/meta["fps"]+.01 else {}
        fields = [("phase", label["phase"], row.get("phase_estimate", row.get("phase", {})))]
        for side in ["mine", "opponent"]:
            fields += [(side+"."+field, truth, row.get(side, {}).get(field, {}))
                       for field, truth in label.get(side, {}).items()]
        for field, expected, observed in fields:
            status = observed.get("status", "unknown")
            value = observed.get("value")
            details.append({"battle_id": label["battle_id"], "clip_seconds": t, "field": field,
                "expected": expected, "value": value, "status": status,
                "matching_known_value": value == expected if value is not None else None,
                "fresh_covered": value is not None and status in {"observed", "inferred"},
                "prediction_seconds": row.get("t")})
    return {"role": "assistant_visual_development_checks_not_independent_human_accuracy",
            "notes": "Header labels describe displayed text; sprite/animation identity and applied HP are not independently verified. Cached text keeps its stale status.",
            "reviewed_frames": len(labels), "reviewed_fields": len(details),
            "matching_known_values": sum(d["matching_known_value"] is True for d in details),
            "conflicting_known_values": sum(d["matching_known_value"] is False for d in details),
            "unknown_values": sum(d["value"] is None for d in details), "details": details}


if __name__ == "__main__":
    labels = [json.loads(line) for line in (ROOT / "dataset/assistant-visual-review.jsonl").read_text(encoding="utf-8").splitlines()]
    result = check(labels)
    (ROOT / "output/assistant-visual-checks.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "details"}))
