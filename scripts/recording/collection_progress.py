"""Summarize the owned Task46 collection without publishing media or raw text."""
from __future__ import annotations

import argparse
import collections
import datetime
import json
from pathlib import Path
import re
import shutil

LEAGUES = {"open_great_league", "restricted", "restricted_cup", "restricted_laic_cup",
           "laic_cup", "ultra", "ultra_league", "master_league", "mega_great_league",
           "mega_ultra_league", "mega_master_league", "unknown", "unverified",
           "not_battle", "other_league", "other_non_open"}


def count(value) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("Expected a nonnegative integer count")
    return value


def date_tag(value):
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-?[0-9]{2}-?[0-9]{2}", value):
        raise ValueError("Unexpected date tag")
    datetime.date.fromisoformat(value)
    return value


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def tree_bytes(folder: Path) -> int:
    unique = {}
    if folder.exists():
        for path in folder.rglob("*"):
            if path.is_file():
                value = path.stat()
                unique[(value.st_dev, value.st_ino)] = value.st_size
    return sum(unique.values())


def summarize(work: Path) -> dict:
    """Count completed VOD receipts once; distinguish saved cuts from tracking."""
    work = work.resolve()
    workers = work / "frozen-reader" / ".vod" / "collection"
    completed, pending, owners = {}, {}, {}
    retired = 0
    storage = collections.Counter()
    for worker in ("worker-a", "worker-b"):
        root = workers / worker
        for key, folder in (("source_cache_bytes", "sources"), ("retained_cuts_bytes", "cuts"),
                            ("record_bytes", "records"), ("witness_bytes", "witnesses"),
                            ("run_and_receipt_bytes", "runs"), ("run_and_receipt_bytes", "receipts")):
            storage[key] += tree_bytes(root / folder)
        receipt_root = root / "receipts"
        for path in sorted(receipt_root.glob("*.json")):
            receipt = load(path)
            if path.name.endswith("-source-retirement.json"):
                if receipt.get("deleted") is True:
                    retired += count(receipt["source_bytes"])
                continue
            if not re.fullmatch(r"[0-9]+\.json", path.name):
                if path.name.endswith("-cuts.json") and receipt.get("tracking_pending"):
                    pending[receipt["source_id"]] = count(receipt.get("cuts_saved", 0))
                continue
            sid = receipt["source_id"]
            if sid != path.stem or not isinstance(sid, str) or not sid.isdigit():
                raise ValueError("Receipt/source mismatch")
            if sid in owners:
                raise ValueError("One source has receipts from both collectors")
            owners[sid] = worker
            if receipt.get("done") is True:
                mix = receipt.get("league_mix", {})
                if not isinstance(mix, dict) or set(mix) - LEAGUES:
                    raise ValueError("Unexpected league mix labels")
                completed[sid] = {"source_id": sid,
                    "battles_saved": count(receipt.get("battles_saved", 0)),
                    "cuts_saved": count(receipt.get("cuts_saved", 0)),
                    "league_mix": {k: count(v) for k, v in mix.items()},
                    "upload_date": date_tag(receipt.get("upload_date")),
                    "in_game_date": date_tag(receipt.get("in_game_date"))}
    for sid in completed:
        pending.pop(sid, None)
    league = collections.Counter()
    for row in completed.values():
        league.update(row["league_mix"])
    free = shutil.disk_usage(work).free
    return {"schema": "task46-collection-progress-v1",
            "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "vods_done": len(completed),
            "battles_saved": sum(r["battles_saved"] for r in completed.values()),
            "cuts_in_completed_vods": sum(r["cuts_saved"] for r in completed.values()),
            "league_mix_detected_candidates_in_completed_vods": dict(league),
            "vods_with_verified_cuts_tracking_pending": len(pending),
            "verified_cuts_tracking_pending": sum(pending.values()),
            "disk": {**dict(storage), "full_source_bytes_retired": retired,
                     "drive_free_bytes": free, "minimum_free_bytes": 25_000_000_000},
            "completed_sources": sorted(completed.values(), key=lambda r: int(r["source_id"]), reverse=True),
            "notes": ["Completed receipts count processing, not verified full-state accuracy.",
                      "League mix counts detected candidates; accepted saved battles are open Great League only.",
                      "Existing cuts outside this collection are excluded."]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-root", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    result = summarize(args.work_root)
    rendered = json.dumps(result, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
