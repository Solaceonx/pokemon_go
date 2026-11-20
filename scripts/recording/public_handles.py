"""Validate opt-in public gameplay handles without exporting arbitrary screen text.

This is separate from the frozen screen reader. Witnesses must be visually checked
against the public game UI before setting ``verified``; this module checks the
receipt's structure, not whether an OCR guess matches a source frame.
"""
from __future__ import annotations

import math
import re


def validate(payload: dict) -> dict:
    """Return an allowlisted receipt, rejecting unreviewed or extra fields."""
    if not isinstance(payload, dict) or set(payload) != {
        "schema", "source_url", "source_id", "battle_id", "public_trainer_handles"
    }:
        raise ValueError("Unexpected handle receipt fields")
    if payload["schema"] != "public-trainer-handles-v1":
        raise ValueError("Unsupported handle receipt schema")
    sid = payload["source_id"]
    if not isinstance(sid, str) or not re.fullmatch(r"[0-9]+", sid):
        raise ValueError("Invalid Twitch source id")
    if payload["source_url"] != "https://www.twitch.tv/videos/" + sid:
        raise ValueError("Handle witnesses must refer to the public source")
    battle = payload["battle_id"]
    if not isinstance(battle, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,150}", battle):
        raise ValueError("Invalid battle id")
    entries = payload["public_trainer_handles"]
    if not isinstance(entries, list) or len(entries) > 2:
        raise ValueError("At most one handle per side")
    sides = set()
    clean = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"side", "handle", "verified", "witnesses"}:
            raise ValueError("Unexpected handle entry fields")
        side = entry["side"]
        if side not in ("own", "foe") or side in sides:
            raise ValueError("Invalid or duplicate side")
        sides.add(side)
        handle = entry["handle"]
        if (not isinstance(handle, str) or not 1 <= len(handle) <= 64
                or any(not c.isalnum() for c in handle)):
            raise ValueError("Expected a single in-game handle, not unrestricted text")
        if entry["verified"] is not True:
            raise ValueError("Unverified handles cannot be published")
        witnesses = entry["witnesses"]
        if not isinstance(witnesses, list) or not 2 <= len(witnesses) <= 20:
            raise ValueError("Repeated source witnesses required")
        times = set()
        for witness in witnesses:
            if not isinstance(witness, dict) or set(witness) != {"source_seconds", "screen"}:
                raise ValueError("Unexpected witness fields")
            stamp = witness["source_seconds"]
            if (isinstance(stamp, bool) or not isinstance(stamp, (int, float))
                    or not math.isfinite(stamp) or stamp < 0):
                raise ValueError("Invalid source timestamp")
            if witness["screen"] not in ("versus", "result"):
                raise ValueError("Expected a game UI witness")
            times.add(stamp)
        if len(times) < 2:
            raise ValueError("Witnesses must come from distinct source frames")
        clean.append({"side": side, "handle": handle, "verified": True,
                      "witnesses": [dict(w) for w in witnesses]})
    return {"schema": payload["schema"], "source_url": payload["source_url"],
            "source_id": sid, "battle_id": battle, "public_trainer_handles": clean}


def appearances(receipts: list[dict]) -> list[dict]:
    """Group verified game appearances; do not infer identities or preferences."""
    grouped = {}
    seen = {}
    for payload in receipts:
        receipt = validate(payload)
        for entry in receipt["public_trainer_handles"]:
            key = (receipt["source_id"], receipt["battle_id"], entry["side"])
            if key in seen:
                if seen[key] != entry["handle"]:
                    raise ValueError("Conflicting handle receipts for one battle side")
                continue
            seen[key] = entry["handle"]
            grouped.setdefault(entry["handle"], []).append({
                "source_url": receipt["source_url"], "battle_id": receipt["battle_id"],
                "side": entry["side"], "witnesses": entry["witnesses"],
            })
    return [{"handle": name, "observed_battles": len(rows), "appearances": rows}
            for name, rows in sorted(grouped.items())]
