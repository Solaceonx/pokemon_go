#!/usr/bin/env python3
"""The battle tables in docs/live_battles_<DATE>.md, made from the records and games/live/notes.json (task 45), so
that what went wrong is written in one place and the copies cannot drift.

    python3 scripts/live/battle_tables.py           rewrite every table
    python3 scripts/live/battle_tables.py --check   exit 1 if any table is not what it would be made as

In each docs/live_battles_<YYYY-MM-DD>.md, the lines between the two markers below are replaced by one row per GO
Battle League battle of that date: stamp, result, their team (notes.json's "their_team" where the analysis corrected
the tracker's), what went wrong and whether it is fixed (notes.json).
Standard library only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GAMES = ROOT / "games" / "live"
DOCS = ROOT / "docs"
BEGIN = "<!-- battles: made by scripts/live/battle_tables.py from games/live/notes.json; edit notes.json, not here -->"
END = "<!-- /battles -->"


def display(name: str | None, species: str) -> str:
    """'Stunfisk (Galarian)' -> 'Galarian Stunfisk', 'Charizard (Mega X)' -> 'Mega Charizard X'."""
    name = name or species
    if not name.endswith(")") or " (" not in name:
        return name
    base, form = name[:-1].split(" (", 1)
    if form.startswith("Mega"):
        rest = form[4:].strip()
        return f"Mega {base} {rest}".strip()
    if form in ("Galarian", "Alolan", "Hisuian", "Paldean", "Shadow"):
        return f"{form} {base}"
    return name


def cell(text) -> str:
    return (text or "").replace("|", "/").replace("\n", " ").strip()


def table(date: str) -> list[str]:
    notes = json.loads((GAMES / "notes.json").read_text(encoding="utf-8"))
    rows = ["| Stamp | Result | Their team | What went wrong | Fixed |", "|---|---|---|---|---|"]
    for path in sorted(GAMES.glob(f"{date.replace('-', '')}-*/game.json")):
        rec = json.loads(path.read_text(encoding="utf-8"))
        if rec["source"]["mode"] != "league":
            continue
        stamp = path.parent.name
        note = notes.get(stamp) or {}
        result = rec["result"]["value"] or ""
        if result == "fragment":
            result = f"fragment of {rec['result'].get('fragment_of')}"
        # their team as the record has it (the tracker's final belief), unless the analysis corrected it
        theirs = note.get("their_team") or ", ".join(display(p.get("name"), p["species"]) for p in rec["teams"]["theirs"])
        cells = [stamp, result, theirs, cell(note.get("went_wrong")), cell(note.get("fixed"))]
        rows.append("|" + "|".join(f" {c} " if c else " " for c in cells) + "|")
    return rows


def rebuilt(path: Path) -> str | None:
    text = path.read_text(encoding="utf-8")
    if BEGIN not in text or END not in text:
        return None
    head, rest = text.split(BEGIN, 1)
    _, tail = rest.split(END, 1)
    date = path.stem.replace("live_battles_", "")
    return head + BEGIN + "\n" + "\n".join(table(date)) + "\n" + END + tail


def main(argv) -> int:
    stale = []
    for path in sorted(DOCS.glob("live_battles_*.md")):
        new = rebuilt(path)
        if new is None:
            continue
        if new != path.read_text(encoding="utf-8"):
            stale.append(path.name)
            if "--check" not in argv:
                path.write_text(new, encoding="utf-8")
    if "--check" in argv:
        if stale:
            print("not made from notes.json:", ", ".join(stale))
        return 1 if stale else 0
    print("rewritten:", ", ".join(stale) or "none")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
