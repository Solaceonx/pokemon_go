#!/usr/bin/env python3
"""One readable record of a tracked battle: who did what, when, and how sure we are.

    python3 scripts/recording/game_record.py games/<name> [games/<name> ...] [--print]
    python3 scripts/recording/game_record.py --all [--print]      every tracked game under games/

Puts together what assemble.py, track.py and verdict.py already wrote in a game's folder (timeline.json,
states.jsonl, events.jsonl, state.json, track.json, verdict.json, each plain or .gz) and, for public footage,
source.json. Writes beside them:

    game.json   the record, for programs (the format is in docs/game_record.md)
    game.txt    the same as a play-by-play, for people (--print also shows it here)

Nothing is read from the video and nothing is tracked again: after changing the assembly or the tracker, re-run
them and then this. Standard library only.
"""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "game-record-v1"
INPUTS = ("events.jsonl", "source.json", "state.json", "states.jsonl", "timeline.json", "track.json", "verdict.json")
SIDES = ("mine", "theirs")
KEY = {"mine": "me", "theirs": "opponent"}  # the tracker's name for each side in a state
OTHER = {"mine": "theirs", "theirs": "mine"}
# The first look after a charged move comes about 10 s after its cue (13.5 s at most so far, with Cramorant's prey).
CUE_WINDOW = 16.0
# Tracker events that are something a player did, and what kind of action each is. The rest are deductions or notes.
ACTION = {"my_charged": "charged", "foe_charged": "charged", "my_switch": "switch", "foe_switch": "switch",
          "my_faint": "faint", "foe_faint": "faint"}
MARK = {"inferred": "*", "guessed": "?"}  # in game.txt, after a move worked out or only assumed


# reading what the pipeline wrote

def _path(folder: Path, name: str) -> Path | None:
    return next((p for p in (folder / name, folder / (name + ".gz")) if p.exists()), None)


def _open(path: Path):
    return gzip.open(path, "rt", encoding="utf-8") if path.suffix == ".gz" else open(path, encoding="utf-8")


def _rows(folder: Path, name: str) -> list[dict]:
    path = _path(folder, name)
    if path is None:
        return []
    with _open(path) as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _json(folder: Path, name: str) -> dict | None:
    path = _path(folder, name)
    if path is None:
        return None
    with _open(path) as stream:
        return json.load(stream)


class Names:
    """Display names and costs for the ids the tracker writes, from everything the states mention."""

    def __init__(self, states: list[dict]):
        self.names: dict[str, str] = {}
        self.costs: dict[str, int] = {}
        for st in states:
            for key in KEY.values():
                for p in st[key]["pokemon"]:
                    self.names[p["species"]] = p["name"]
                    self.names[p["fast_move"]["id"]] = p["fast_move"]["name"]
                    for m in p["charged_moves"]:
                        self.names[m["id"]] = m["name"]
                        self.costs[m["id"]] = m["energy"]
            theirs = (st.get("matchup") or {}).get("theirs") or {}
            for m in theirs.get("every_fast_move_possible", []) + theirs.get("every_charged_move_possible", []):
                self.names[m["id"]] = m["name"]
                if "energy" in m:
                    self.costs[m["id"]] = m["energy"]

    def __call__(self, key: str | None) -> str | None:
        if key is None:
            return None
        return self.names.get(key) or key.replace("_", " ").title()


def _active(part: dict) -> dict | None:
    k = part.get("active")
    return part["pokemon"][k] if isinstance(k, int) and 0 <= k < len(part["pokemon"]) else None


def _same(part: dict, mon: dict | None) -> dict | None:
    """The same Pokémon in another state."""
    return next((p for p in part["pokemon"] if mon and p["species"] == mon["species"]), None)


def _look(states: list[dict], t: float) -> int:
    """The look at time t: the tracker writes one state per look, at that look's time."""
    k = 0
    for i, st in enumerate(states):
        if st["t"] > t + 0.01:
            break
        k = i
    return k


def _snapshot(st: dict) -> dict:
    """The tracker's picture at one look, cut down to what a reader needs."""
    out = {}
    for side, key in KEY.items():
        part, mon = st[key], _active(st[key])
        entry = {"active": mon["name"] if mon else None, "shields": part["shields"], "left": part["left"]}
        if mon:
            entry.update(hp=mon["hp"], hp_max=mon["hp_max"], hp_share=mon["hp_share"])
            if side == "theirs":
                entry["energy"] = list(mon.get("energy_range") or [mon["energy"], mon["energy"]])
                entry["energy_ceiling"] = mon.get("energy_by_clock")
            else:
                entry["energy"] = mon["energy"]
        out[side] = entry
    return out


# the record

def _team(part: dict, theirs: bool, name: Names) -> list[dict]:
    out = []
    for p in part["pokemon"]:
        fast = p["fast_move"]
        if p.get("cp_read_from_screen"):
            cp_from = "screen"
        else:
            cp_from = "assumed" if theirs or p.get("stats_assumed") else "team sheet"
        entry = {"species": p["species"], "name": p["name"], "known_from": p["known_from"], "cp": p["cp"],
                 "cp_from": cp_from, "stats_assumed": p["stats_assumed"], "fainted": p["fainted"],
                 "hp_share_at_end": p["hp_share"],
                 "fast_move": {"id": fast["id"], "name": fast["name"], "turns": fast["turns"],
                               "energy_gain": fast["energy_gain"], "known_from": fast["known_from"]},
                 "charged_moves": [{"id": m["id"], "name": m["name"], "energy": m["energy"],
                                    "known_from": m["known_from"], "times_used": m["times_used"]}
                                   for m in p["charged_moves"]]}
        if theirs:
            odds = p.get("fast_move_odds") or {}
            if fast["known_from"] != "inferred" and len(odds) > 1:
                entry["fast_move"]["odds"] = {name(m): q for m, q in odds.items()}
            seen = {m["id"] for m in p["charged_moves"] if m["times_used"]}
            rest = {name(m): q for m, q in (p.get("charged_move_odds") or {}).items() if m not in seen and q < 1}
            if rest and len(seen) < 2:
                entry["other_charged_moves"] = rest
        out.append(entry)
    return out


def _source(source: dict | None, timeline: dict, verdict: dict) -> dict:
    if source:
        return {"kind": "public_footage", "url": source.get("source_url"), "view": source.get("view_id"),
                "match_id": source.get("match_id"),
                "clip_seconds": [source.get("source_start_seconds"), source.get("source_end_seconds")],
                "incomplete_start": bool(source.get("incomplete_start")),
                "incomplete_end": bool(source.get("incomplete_end")), "dataset_role": verdict.get("dataset_role")}
    return {"kind": "public_footage" if timeline.get("public_footage") else "own_recording"}


def _take_cue(cues: dict, side: str, t: float, used: dict) -> dict | None:
    """The earliest charged-move cue of this side not yet matched, in the window before the look that showed it."""
    for i, cue in enumerate(cues[side]):
        if i not in used[side] and t - CUE_WINDOW <= cue["t"] <= t + 0.01:
            used[side].add(i)
            return cue
    return None


def _charged(e: dict, side: str, prev: dict, here: dict, cue: dict | None, name: Names, seen: dict | None) -> dict:
    """A charged move. prev is the look before it, here the first look after it, seen what that look read."""
    mine, other = KEY[side], KEY[OTHER[side]]
    user, target = _active(prev[mine]), _active(prev[other])
    after = _same(here[other], target)
    move_id = e.get("move")
    cost = name.costs.get(move_id) if move_id else None
    # The damage the rules give this move on this target (typical stats for the opponent).
    facts = ((prev.get("matchup") or {}).get("ours" if side == "mine" else "theirs") or {}).get("charged") or []
    expected = next((m["damage"] for m in facts if m.get("id") == move_id), None)
    out = {"kind": "charged", "t": cue["t"] if cue else e["t"], "fighting_turn": prev["fighting_turns"], "side": side,
           "pokemon": user["name"] if user else None,
           "move": name(move_id) if move_id else (cue or {}).get("move"), "move_id": move_id,
           # Named on screen if its cue carried the name; otherwise the tracker picked it from damage or energy.
           "move_known_from": "seen" if cue and cue.get("move") else ("inferred" if move_id else None),
           "cost": cost}
    if side == "mine":
        # The count clamps at zero after paying, so a count that was short shows up as zero left.
        left = _same(here[mine], user)
        had = left["energy"] + cost if left and cost is not None and left["energy"] > 0 else (user or {}).get("energy")
        out["energy_before"] = had
    else:
        low, high = (e.get("energy_before") or [None, None])[:2]
        had = high
        out["energy_before"] = [low, high]
        out["energy_ceiling"] = e.get("energy_before_by_clock")
    if cost is not None and had is not None and had < cost:
        out["energy_short_by"] = cost - had
    # The tracker takes the damage off only when that look read the target's bar (or the bar lagged behind it);
    # with no reading, its health after is still the health before. None: the looks were not available.
    bar_read = None if seen is None else seen.get("foe_hp" if side == "mine" else "my_hp") is not None
    out.update(target=target["name"] if target else None, shielded=bool(e.get("shielded")),
               target_hp_before=target["hp"] if target else None, target_hp_after=after["hp"] if after else None,
               target_hp_max=target["hp_max"] if target else None, target_bar_read=bar_read,
               expected_damage=1 if e.get("shielded") else expected, resolved_t=e["t"], cue=cue is not None,
               state=_snapshot(here))
    return out


def _deduction(e: dict, name: Names) -> dict | None:
    kind = e["event"]
    ruled = [name(m) for m in e.get("ruled_out", [])]
    if kind == "foe_fast_learned":
        if e.get("misfit") and not ruled:
            how = "fits the size and timing of its hits on our bar"
        elif e.get("misfit"):
            how = "fits its hits on our bar best of the moves not ruled out"
        else:
            how = "every other fast move ruled out by effectiveness words or energy"
        what, side, value = "fast move", "theirs", e["move"]
    elif kind == "foe_fast_confirmed":
        what, side, value, how = "fast move", "theirs", e["move"], "every other fast move ruled out"
    elif kind in ("foe_move_learned", "my_move_learned"):
        what, value, how = "charged move", e["move"], "thrown on screen, not one of the moves assumed"
        side = "theirs" if kind.startswith("foe") else "mine"
    elif kind == "my_seen":
        what, side, value, how = "team member", "mine", e["species"], "first seen on screen"
    else:
        return None
    return {"t": e["t"], "side": side, "pokemon": name(e.get("species")), "what": what, "value": name(value),
            "how": how, "ruled_out": ruled}


def _fighting(states, k0, k1, last, until, events, looks, steps, final) -> dict | None:
    """The fighting from look k0 (just after the previous action) to look k1 (the next action, or the end).
    last is the last look that belongs to this stretch."""
    a, b = states[k0], states[k1]
    turns = b["fighting_turns"] - a["fighting_turns"]
    if turns <= 0:
        return None
    out = {"kind": "fighting", "t": a["t"], "until": until, "fighting_turn": a["fighting_turns"], "turns": turns}
    for side, key in KEY.items():
        mon = _active(a[key])
        if mon is None:
            continue
        fast = final[side].get(mon["species"], mon)["fast_move"]  # the final belief, not the one at the time
        bar = steps.get(OTHER[side]) or []  # their hits land on the other side's bar
        out[side] = {"pokemon": mon["name"], "fast_move": fast["name"], "fast_move_known_from": fast["known_from"],
                     "fast_moves_if_no_pause": turns // max(1, fast["turns"]),
                     "hits_seen": sum(1 for step in bar if a["t"] < step[0] <= until)}
    inside = [e["event"] for e, k in zip(events, looks) if k0 < k <= last]
    if inside.count("unexplained"):
        out["unexplained_health_changes"] = inside.count("unexplained")
    if inside.count("my_energy_read"):
        out["my_energy_corrected"] = inside.count("my_energy_read")
    out["state"] = _snapshot(states[max(k0, last)])
    return out


def build(folder: Path) -> dict:
    """The record of the tracked game in this folder."""
    folder = Path(folder)
    states, events = _rows(folder, "states.jsonl"), _rows(folder, "events.jsonl")
    final = _json(folder, "state.json") or (states[-1] if states else None)
    if not states or not events or final is None:
        raise ValueError(f"{folder}: not a tracked game (needs states.jsonl, events.jsonl and state.json from track.py)")
    timeline = _json(folder, "timeline.json") or {}
    verdict = _json(folder, "verdict.json") or {}
    track = _json(folder, "track.json") or {}
    source = _json(folder, "source.json")
    looked = {round(o["t"], 2): o for o in _rows(folder, "observations.jsonl")}  # what each look read
    name = Names(states + [final])
    by_species = {side: {p["species"]: p for p in final[key]["pokemon"]} for side, key in KEY.items()}
    cues = {side: sorted((c for c in timeline.get("charged", []) if c.get("side") == side), key=lambda c: c["t"])
            for side in SIDES}
    used = {side: set() for side in SIDES}
    looks = [_look(states, e["t"]) for e in events]
    steps = timeline.get("steps") or {}

    first = states[0]
    their_lead = next((_active(st["opponent"]) for st in states if _active(st["opponent"])), None)
    actions = [{"kind": "start", "t": first["t"], "fighting_turn": first["fighting_turns"],
                "mine": (_active(first["me"]) or {}).get("name"), "theirs": (their_lead or {}).get("name"),
                "incomplete_start": bool((source or {}).get("incomplete_start")), "state": _snapshot(first)}]
    deductions = []
    since = 0  # the look the fighting under way started from
    for e, k in zip(events, looks):
        kind = ACTION.get(e["event"])
        if kind is None:
            found = _deduction(e, name)
            if found:
                deductions.append(found)
            continue
        side = "mine" if e["event"].startswith("my_") else "theirs"
        prev, here = states[max(0, k - 1)], states[k]
        if kind == "charged":
            seen = looked.get(round(here["t"], 2)) if looked else None
            action = _charged(e, side, prev, here, _take_cue(cues, side, e["t"], used), name, seen)
        else:
            gone = _active(prev[KEY[side]])
            action = {"kind": kind, "t": e["t"], "fighting_turn": here["fighting_turns"], "side": side}
            if kind == "switch":
                action.update({"from": gone["name"] if gone else None, "to": name(e.get("to"))})
            else:
                action.update(pokemon=gone["name"] if gone else None, next=name(e.get("next")))
            action["state"] = _snapshot(here)
        fight = _fighting(states, since, k, k - 1, action["t"], events, looks, steps, by_species)
        if fight:
            actions.append(fight)
        actions.append(action)
        since = k
    end = timeline["end"] if timeline.get("end") is not None else states[-1]["t"]
    fight = _fighting(states, since, len(states) - 1, len(states) - 1, end, events, looks, steps, by_species)
    if fight:
        actions.append(fight)

    result = timeline.get("result")
    if result:
        result_from = "result screen"
    elif verdict.get("result"):
        result, result_from = verdict["result"], "who had Pokémon left"
    else:
        result_from = "unknown"
    left = {"mine": final["me"]["left"], "theirs": final["opponent"]["left"]}
    actions.append({"kind": "end", "t": end, "fighting_turn": final["fighting_turns"], "result": result,
                    "result_from": result_from, "left": left, "state": _snapshot(final)})

    def count(kind, side, test=lambda a: True):
        return sum(1 for a in actions if a["kind"] == kind and a.get("side") == side and test(a))

    return {
        "schema": SCHEMA, "game": folder.name, "source": _source(source, timeline, verdict),
        "result": {"value": result, "from": result_from, "left": left},
        "seconds": end, "fighting_turns": final["fighting_turns"],
        "checks": {"verdict": verdict.get("verdict"), "failed": verdict.get("failed", []),
                   "notes": verdict.get("notes", []),
                   "unexplained_health_changes": track.get("unexplained", final.get("warnings"))},
        "teams": {"mine": _team(final["me"], False, name), "theirs": _team(final["opponent"], True, name),
                  "theirs_unseen": final["opponent"].get("unseen")},
        "summary": {"charged": {s: count("charged", s) for s in SIDES},
                    "charged_shielded": {s: count("charged", s, lambda a: a["shielded"]) for s in SIDES},
                    "shields_left": {s: final[KEY[s]]["shields"] for s in SIDES},
                    "switches": {s: count("switch", s) for s in SIDES},
                    "faints": {s: count("faint", s) for s in SIDES}},
        "actions": actions,
        "deductions": deductions,
        "built_from": sorted(path.name for path in (_path(folder, n) for n in INPUTS) if path),
    }


# the play-by-play

def _clock(t: float | None) -> str:
    if t is None:
        return "?"
    minutes, seconds = divmod(round(abs(t), 1), 60)
    return f"{'-' if t < 0 else ''}{int(minutes)}:{seconds:04.1f}"


def _share(hp, hp_max) -> str:
    return f"{round(100 * hp / hp_max)}%" if hp is not None and hp_max else "?"


def _moves(p: dict) -> str:
    fast = p["fast_move"]["name"] + MARK.get(p["fast_move"]["known_from"], "")
    return fast + " | " + ", ".join(m["name"] + MARK.get(m["known_from"], "") for m in p["charged_moves"])


def _say(a: dict) -> str:
    we = "We" if a.get("side") == "mine" else "They"
    our = "Our" if a.get("side") == "mine" else "Their"
    kind = a.get("kind")
    if kind is None:  # a deduction
        if a["what"] == "team member":
            return f". {a['how']}: {a['value']}"
        why = a["how"] + (f"; ruled out {', '.join(a['ruled_out'])}" if a["ruled_out"] else "")
        return f". worked out: {our.lower()} {a['pokemon']} has {a['value']} ({why})"
    if kind == "start":
        return f"Start: {a['mine'] or '?'} vs {a['theirs'] or '?'}" + \
            (" (the clip begins mid-battle)" if a["incomplete_start"] else "")
    if kind == "fighting":
        parts = [f"{s['pokemon']} ~{s['fast_moves_if_no_pause']} {s['fast_move']}{MARK.get(s['fast_move_known_from'], '')}"
                 f" ({s['hits_seen']} seen)" for s in (a.get("mine"), a.get("theirs")) if s]
        flags = []
        if a.get("unexplained_health_changes"):
            flags.append(f"{a['unexplained_health_changes']} unexplained health change(s)")
        if a.get("my_energy_corrected"):
            flags.append(f"our energy reset from the buttons {a['my_energy_corrected']}x")
        return f"fight to {_clock(a['until'])}, {a['turns']} turn{'s' * (a['turns'] != 1)}: " + "; ".join(parts) + \
            (f"  [{'; '.join(flags)}]" if flags else "")
    if kind == "charged":
        had, ceiling = a["energy_before"], ""
        if isinstance(had, list):
            low, high = had
            energy = "?" if high is None else str(high) if low == high else f"{low}-{high}"
            if a.get("energy_ceiling") is not None and a["energy_ceiling"] != high:
                ceiling = f", clock allows {a['energy_ceiling']}"
        else:
            energy = "?" if had is None else str(had)
        energy += (f" of {a['cost']}" if a["cost"] is not None else "") + " energy" + ceiling
        move = (a["move"] or "an unnamed charged move") + ("*" if a["move_known_from"] == "inferred" else "")
        before = _share(a["target_hp_before"], a["target_hp_max"])
        if a["shielded"]:
            hit = f"{a['target']} shielded"
        elif a["target_bar_read"] is False and a["target_hp_after"] == a["target_hp_before"]:
            # Tracked before 2026-11-04, when the tracker left the health alone with no reading of the bar.
            guess = f"; the move does ~{_share(a['expected_damage'], a['target_hp_max'])}" if a["expected_damage"] else ""
            hit = f"{a['target']} {before} -> ? (bar not read{guess})"
        elif a["target_bar_read"] is False:
            hit = f"{a['target']} {before} -> {_share(a['target_hp_after'], a['target_hp_max'])} (bar not read; by the rules)"
        else:
            hit = f"{a['target']} {before} -> {_share(a['target_hp_after'], a['target_hp_max'])}"
        flags = []
        if a.get("energy_short_by"):
            flags.append(f"short by {a['energy_short_by']} energy by our count")
        if not a["cue"]:
            flags.append("no cue read; time is the look's")
        return f"{we} throw {move} ({a['pokemon']}, {energy}) -> {hit}" + \
            (f"  [{'; '.join(flags)}]" if flags else "")
    if kind == "switch":
        return f"{we} switch {a['from'] or '?'} -> {a['to']}"
    if kind == "faint":
        return f"{our} {a['pokemon'] or '?'} faints; {a['next']} comes in"
    if kind == "end":
        result = f"{a['result'].upper()} ({a['result_from']})" if a["result"] else "result unknown"
        return f"End: {result}; Pokémon left: us {a['left']['mine']}, them {a['left']['theirs']}"
    return kind


def text(rec: dict) -> str:
    src, res, checks = rec["source"], rec["result"], rec["checks"]
    where = "own recording" if src["kind"] == "own_recording" else \
        "public footage" + (f", {src['view']} view" if src.get("view") else "")
    result = f"{res['value'].upper()} ({res['from']})" if res["value"] else "result unknown"
    lines = [f"{rec['game']} . {where} . {result} . {_clock(rec['seconds'])}, {rec['fighting_turns']} fighting turns"]
    if src.get("url"):
        start, stop = src["clip_seconds"]
        lines.append(f"Source: {src['url']}, {start}-{stop} s" + (" (starts mid-battle)" if src["incomplete_start"] else "")
                     + (" (ends early)" if src["incomplete_end"] else ""))
    lines.append(f"Checks: {checks['verdict'] or 'not run'}")
    lines += [f"  failed: {f}" for f in checks["failed"]] + [f"  note: {n}" for n in checks["notes"]]
    if src["kind"] == "public_footage":
        lines.append("Mine = the player whose screen this is.")
    for side, title in (("mine", "Mine"), ("theirs", "Theirs")):
        unseen = rec["teams"]["theirs_unseen"] if side == "theirs" else 0
        lines += ["", title + (f" ({unseen} not seen)" if unseen else "")]
        for p in rec["teams"][side]:
            cp = f"CP {p['cp']}" + ("?" if p["cp_from"] == "assumed" else "")
            lines.append(f"  {p['name']:<12} {cp:<9} {_moves(p)}" + ("  [fainted]" if p["fainted"] else ""))
    lines += ["  plain = seen or told   * = worked out from the screen   ? = assumed, not confirmed", ""]
    # Deductions go in by time; actions keep their own order.
    deductions, i = sorted(rec["deductions"], key=lambda d: d["t"]), 0
    for a in rec["actions"]:
        while i < len(deductions) and deductions[i]["t"] < a["t"]:
            lines.append(f"  {_clock(deductions[i]['t']):>7}  {_say(deductions[i])}")
            i += 1
        if a["kind"] == "fighting" and a["turns"] <= 1 and not any((a.get(s) or {}).get("hits_seen") for s in SIDES):
            continue  # a moment between two actions; it stays in game.json
        lines.append(f"  {_clock(a['t']):>7}  {_say(a)}")
    lines += [f"  {_clock(d['t']):>7}  {_say(d)}" for d in deductions[i:]]
    return "\n".join(lines) + "\n"


def tracked(root: Path) -> list[Path]:
    """Every folder under root that track.py has run in."""
    found = {p.parent for pattern in ("states.jsonl", "states.jsonl.gz") for p in Path(root).rglob(pattern)}
    return sorted(f for f in found if _path(f, "events.jsonl") and _path(f, "state.json"))


def write(folder: Path) -> dict:
    rec = build(folder)
    (folder / "game.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (folder / "game.txt").write_text(text(rec), encoding="utf-8")
    return rec


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if args else 2
    show = "--print" in args
    folders = [Path(a) for a in args if a not in ("--print", "--all")]
    if "--all" in args:
        folders += tracked(ROOT / "games")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    skipped = 0
    for folder in folders:
        try:
            rec = write(folder)
        except (ValueError, KeyError, TypeError, IndexError, json.JSONDecodeError, OSError) as err:
            skipped += 1
            print(f"SKIP {folder}: {type(err).__name__}: {err}")
            continue
        s = rec["summary"]
        print(f"{folder}: {len(rec['actions'])} actions, {s['charged']['mine'] + s['charged']['theirs']} charged moves, "
              f"result {rec['result']['value'] or 'unknown'} ({rec['result']['from']}); checks {rec['checks']['verdict'] or 'not run'}")
        if show:
            print(text(rec))
    if skipped:
        print(f"{skipped} of {len(folders)} skipped")
    return 1 if skipped else 0


if __name__ == "__main__":
    sys.exit(main())
