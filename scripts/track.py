#!/usr/bin/env python3
"""Build the game state for one battle from a list of looks at the screen.

    python3 scripts/track.py games/example

The folder must hold:
    team.json           the Pokémon on our side that we know about (may be fewer than three)
    observations.jsonl  one look per line, in time order

It writes, in the same folder:
    state.json          the game state after the last look
    states.jsonl        the game state after every look
    events.jsonl        what the tracker concluded happened, one event per line

See docs/agent_instructions.md for the formats.
"""
from __future__ import annotations

import dataclasses
import difflib
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pogo.gamedata import GameData  # noqa: E402
from pogo.tracker import Observation, Tracker, state  # noqa: E402

FIELDS = {f.name for f in dataclasses.fields(Observation)}


def species_id(gd: GameData, text: str) -> str:
    """Accept an id ("ninetales_shadow") or a display name ("Ninetales (Shadow)")."""
    if text in gd.species:
        return text
    by_name = {p["speciesName"].lower(): sid for sid, p in gd.species.items()}
    if text.lower() in by_name:
        return by_name[text.lower()]
    close = difflib.get_close_matches(text.lower(), list(gd.species) + list(by_name), n=3)
    raise ValueError(f"unknown Pokémon {text!r}; closest: {', '.join(close) or 'nothing'}")


def move_id(gd: GameData, text: str) -> str:
    """Accept an id ("DOUBLE_IRON_BASH") or a name ("Double Iron Bash")."""
    if text in gd.moves:
        return text
    by_name = {m.name.lower(): mid for mid, m in gd.moves.items()}
    if text.lower() in by_name:
        return by_name[text.lower()]
    close = difflib.get_close_matches(text.lower(), list(by_name), n=3)
    raise ValueError(f"unknown move {text!r}; closest: {', '.join(close) or 'nothing'}")


def charged_index(gd: GameData, tracker: Tracker, look: dict, number: int) -> int:
    """Which of our charged moves was thrown: given as 0/1, "left"/"right", or the move's name."""
    value = look["my_charged"]
    if isinstance(value, int):
        return value
    if value.lower() in ("left", "right"):
        return 0 if value.lower() == "left" else 1
    mid = move_id(gd, value)
    mon = next((m for m in tracker.me.team if m.build.species_id == look.get("my_species")), tracker.me.mon)
    ids = [m.id for m in mon.build.charged]
    if mid not in ids:
        learned = tracker.learn_my_move(look["t"], tracker.me.team.index(mon), mid)
        if learned is not None:
            return learned
        print(f"line {number}: our {mon.build.name} threw {value}, which is not among the moves listed for it ({', '.join(ids)})")
        return 0
    return ids.index(mid)


def load_team(gd: GameData, sheet: dict):
    builds, known = [], []
    for entry in sheet.get("pokemon", []):
        sid = species_id(gd, entry["species"])
        if entry.get("fast") and entry.get("charged"):
            ivs = tuple(entry["ivs"]) if entry.get("ivs") else None
            moves = [move_id(gd, entry["fast"]), *(move_id(gd, m) for m in entry["charged"])]
            builds.append(gd.build(sid, moves, level=entry.get("level"), ivs=ivs, allow_forms=True))
            known.append(True)
        else:
            builds.append(gd.default(sid, allow_forms=True))  # moves not given: assume the usual ones
            known.append(False)
    return builds, known


def main() -> int:
    energy = "hits" if "--hits" in sys.argv else "rhythm"  # --hits: count energy from health-bar steps instead
    blind = "--blind" in sys.argv  # compare our counted energy with the buttons without correcting it
    sys.argv = [a for a in sys.argv if a not in ("--hits", "--blind")]
    if len(sys.argv) != 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0 if len(sys.argv) == 2 else 2
    folder = Path(sys.argv[1])
    gd = GameData()
    builds, known = load_team(gd, json.loads((folder / "team.json").read_text()))
    tracker = Tracker(gd, builds, path=folder / "events.jsonl", moves_known=known, energy=energy, trust_my_energy=not blind)
    looks = problems = 0
    with (folder / "states.jsonl").open("w") as states:
        for number, line in enumerate((folder / "observations.jsonl").read_text().splitlines(), start=1):
            if not line.strip():
                continue
            try:
                look = json.loads(line)
                look.pop("note", None)
                extra = set(look) - FIELDS
                if extra:
                    raise ValueError(f"unknown field(s) {sorted(extra)}")
                for key in ("my_species", "foe_species"):
                    if look.get(key):
                        look[key] = species_id(gd, look[key])
                if look.get("foe_move"):
                    try:
                        look["foe_move"] = move_id(gd, look["foe_move"])
                    except ValueError as err:  # keep the look; just do without the name
                        print(f"line {number}: {err} (move name ignored)")
                        del look["foe_move"]
                if look.get("my_charged") is not None:
                    look["my_charged"] = charged_index(gd, tracker, look, number)
                obs = Observation(**look)
                if obs.t < tracker.t:
                    raise ValueError(f"time goes backwards ({obs.t} after {tracker.t})")
                tracker.update(obs)
            except (ValueError, TypeError, KeyError) as err:
                problems += 1
                print(f"line {number}: {err}")
                continue
            looks += 1
            states.write(json.dumps(state(tracker)) + "\n")
    final = state(tracker, full=True)
    tracker.close()
    (folder / "state.json").write_text(json.dumps(final, indent=2) + "\n")
    events = Counter(json.loads(line)["event"] for line in (folder / "events.jsonl").read_text().splitlines())
    print(f"{looks} looks read, {problems} rejected; events: " + ", ".join(f"{n} {e}" for e, n in sorted(events.items())))
    print(f"unexplained changes: {tracker.warnings} (each is listed in events.jsonl)")
    (folder / "track.json").write_text(json.dumps({"looks": looks, "rejected": problems, "unexplained": tracker.warnings,
                                                    "energy": energy, "events": dict(sorted(events.items())),
                                                    "my_energy_looks": tracker.energy_checks, "my_energy_overruled": tracker.energy_fixed,
                                                    "my_energy_off_on_average": round(tracker.energy_off / max(tracker.energy_checks, 1), 2)}) + "\n")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
