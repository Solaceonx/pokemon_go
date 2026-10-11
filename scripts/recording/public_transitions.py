"""Classify public-footage replacements from local counter evidence.

Low health alone never proves a faint. Counter runs must be uninterrupted,
and a drop belongs to the stint in which it first became visible, even when
confirmation arrives after the new header.
"""
from __future__ import annotations


def counter_changes(rows, key, field, fps):
    required = max(3, round(fps / 2))
    result, value, count, first, last = [], None, 0, None, None
    for row in rows:
        t, current = row["t"], row[key].get(field)
        if current is None:
            value, count, first, last = None, 0, None, None
            continue
        if current != value or last is None or t - last > 1.6 / fps:
            value, count, first = current, 0, t
        count, last = count + 1, t
        if count == required:
            # Neither party size nor shields can increase inside a battle.
            if result and current >= result[-1]["value"]:
                continue
            result.append({"t": t, "first": first, "value": current})
    return result


def replacement_evidence(changes, previous_seen, seen, *, prompt=False):
    for before, after in zip(changes, changes[1:]):
        if (previous_seen < after["first"] <= seen + .05
                and after["t"] <= seen + .6 and after["value"] < before["value"]):
            return {"kind": "faint", "method": "local_party_counter_decrease",
                    "first_visible_seconds": after["first"], "confirmed_seconds": after["t"],
                    "before": before["value"], "after": after["value"]}
    if prompt:
        return {"kind": "faint", "method": "replacement_selection_prompt"}
    return {"kind": "switch", "method": "header_changed_without_local_faint_evidence"}
