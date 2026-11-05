#!/usr/bin/env python3
"""How right the tracker's health is at the looks where a bar was not read.

    python3 scripts/recording/unread_health.py TRACKED [--no-faints] [--games PREFIX ...] [--pairs SOURCE ...]

TRACKED is a folder of tracked games (each with observations, states, events and track.json, as track.py and
retrack_public.py write them). At every look where one side's bar was not read, the tracker's health for that
Pokémon is set against the next reading of the same Pokémon within 3 s: the screen a moment later, which is a
little lower than the truth at the look by whatever fast moves landed in between. Reported for

  - the first look after a charged move, when it did not read the target's bar (where the charged-move damage
    has to come from the rules);
  - all unread looks within 4 s after a charged move;
  - all other unread looks.

--no-faints leaves out looks in the 10 s before that side's Pokémon faints: there the next "reading" is often
the replacement's bar under the old name. --games keeps only games whose folder name starts with PREFIX.
--pairs SOURCE adds, for the two-screen matches of that source (see paired_energy.py), one view's picture of the
opponent against the other view's own state (paired_state.py), against the other view's own bar reading, and
the energy comparison of paired_energy.py.
"""
import bisect, gzip, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def rows(folder: Path, name: str) -> list:
    path = folder / name
    if not path.exists():
        path = folder / (name + ".gz")
    if not path.exists():
        return []
    with (gzip.open(path, "rt", encoding="utf-8") if path.suffix == ".gz" else open(path, encoding="utf-8")) as f:
        return [json.loads(line) for line in f if line.strip()]


def active(part: dict):
    k = part.get("active")
    return part["pokemon"][k] if isinstance(k, int) and 0 <= k < len(part["pokemon"]) else None


def same(name, mon) -> bool:
    return name is None or name.lower() in (mon["name"].lower(), mon["species"].lower())


SIDES = (("my_hp", "my_species", "me", "my_faint"), ("foe_hp", "foe_species", "opponent", "foe_faint"))


def measure(games: list, no_faints: bool) -> dict:
    out = {"first": [], "after": [], "other": [], "unexplained": 0, "passed": 0, "judged": 0, "games": 0}
    for game in games:
        looks, states, events = rows(game, "observations.jsonl"), rows(game, "states.jsonl"), rows(game, "events.jsonl")
        if not looks or len(looks) != len(states):
            continue
        out["games"] += 1
        out["unexplained"] += json.loads((game / "track.json").read_text())["unexplained"]
        if (game / "verdict.json").exists():
            out["judged"] += 1
            out["passed"] += json.loads((game / "verdict.json").read_text())["verdict"] == "pass"
        charged = {e["t"]: e["event"] for e in events if e["event"] in ("my_charged", "foe_charged")}
        times = [look["t"] for look in looks]
        for key, sp, part, faint in SIDES:
            faints = [e["t"] for e in events if e["event"] == faint]
            target_of = "my_charged" if part == "opponent" else "foe_charged"  # whose charged move hits this side
            for i, look in enumerate(looks):
                mon = active(states[i][part])
                if look.get(key) is not None or mon is None:
                    continue
                if no_faints and any(0 < f - look["t"] <= 10.0 for f in faints):
                    continue
                j = next((j for j in range(i + 1, len(looks)) if looks[j].get(key) is not None), None)
                if j is None or times[j] - look["t"] > 3.0:
                    continue
                later = active(states[j][part])
                if later is None or later["species"] != mon["species"] or not same(looks[j].get(sp), mon):
                    continue
                off = abs(mon["hp_share"] - looks[j][key])
                out["after" if any(0 <= look["t"] - t <= 4.0 for t in charged) else "other"].append(off)
                previous = active(states[i - 1][part]) if i else None
                if charged.get(look["t"]) == target_of and previous and previous["species"] == mon["species"]:
                    out["first"].append(off)
    return out


def summary(offs: list) -> str:
    if not offs:
        return "none"
    n = len(offs)
    return (f"{n:4d} looks | off by {100 * sum(offs) / n:5.1f} points on average | "
            f"within 3% {100 * sum(o <= 0.03 for o in offs) / n:5.1f}% | within 10% {100 * sum(o <= 0.10 for o in offs) / n:5.1f}%")


def pairs(tracked: Path, sources: list) -> None:
    from paired_energy import compare, load, paired_folders
    from paired_state import moments
    folders = [load(f) for f in paired_folders(["--all", str(tracked)] + [x for s in sources for x in ("--source", s)])]
    state_rows, bar, energy = [], [], []
    for a, b in zip(folders[::2], folders[1::2]):
        for watcher, owner in ((a, b), (b, a)):
            state_rows += list(moments(watcher, owner))
            energy += compare(watcher, owner)
            times = [s["t"] + owner["origin"] for s in owner["states"]]
            for look, state in zip(watcher["looks"], watcher["states"]):
                t = look["t"] + watcher["origin"]
                k = bisect.bisect_right(times, t + 0.25) - 1
                if k < 0 or t - times[k] > 1.0 or state["opponent"]["active"] is None:
                    continue
                theirs, me = active(state["opponent"]), active(owner["states"][k]["me"])
                if me is None or theirs["species"] != me["species"] or owner["looks"][k].get("my_hp") is None:
                    continue
                bar.append(abs(theirs["hp_share"] - owner["looks"][k]["my_hp"]))
    print(f"{len(folders) // 2} two-screen matches ({', '.join(sources)}), each seen from both sides")
    for field in ("who is out", "health within 3%", "health within 10%", "shields", "Pokémon left", "all of these but energy"):
        have = [r[field] for r in state_rows if field in r]
        print(f"  against the other view's state: {field:24s} {100 * sum(have) / max(len(have), 1):5.1f}% of {len(have)}")
    print(f"  against the other view's own bar reading: {summary(bar)}")
    if energy:
        off = [abs(r["count"] - r["truth"]) for r in energy]
        moves = [abs(r["count"] - r["truth"]) / max(r["true_gain"], 1) for r in energy]
        print(f"  their energy against their buttons: {len(off)} moments | off by {sum(off) / len(off):.1f} | "
              f"within one fast move {100 * sum(x <= 1.25 for x in moves) / len(moves):.1f}% | "
              f"within two {100 * sum(x <= 2.25 for x in moves) / len(moves):.1f}%")


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return
    tracked = Path(args[0])
    prefixes = [args[i + 1] for i, a in enumerate(args) if a == "--games"]
    sources = [args[i + 1] for i, a in enumerate(args) if a == "--pairs"]
    games = sorted(p.parent for p in tracked.rglob("track.json"))
    if prefixes:
        games = [g for g in games if any(g.name.startswith(p) for p in prefixes)]
    m = measure(games, "--no-faints" in args)
    print(f"{m['games']} games | unexplained health changes {m['unexplained']} | verdicts pass {m['passed']} of {m['judged']}")
    print(f"  first look after a charged move, bar unread: {summary(m['first'])}")
    print(f"  unread bar, within 4 s after a charged move: {summary(m['after'])}")
    print(f"  unread bar, other looks:                     {summary(m['other'])}")
    if sources:
        pairs(tracked, sources)


if __name__ == "__main__":
    main()
