"""Test the opponent-energy count against the truth, using two views of the same match.

    python3 scripts/recording/paired_energy.py games/twitch/<left view> games/twitch/<right view> [more pairs ...]

A broadcast that shows both players' screens gives, for each player, what the other screen can only
estimate. Each player's own energy is read off their charged-move buttons (my_energy in their looks); the
other view's tracker counts that same energy from the rhythm of fast moves. This lines the two up in time
and reports how far the count is from the buttons.
"""
import bisect, gzip, json, sys
from pathlib import Path


def load(folder: Path) -> dict:
    lines = lambda name: [json.loads(l) for l in gzip.open(folder / (name + ".gz"), "rt")] if (folder / (name + ".gz")).exists() \
        else [json.loads(l) for l in open(folder / name)]
    timeline = json.loads((folder / "timeline.json").read_text())
    return {"name": folder.name, "origin": timeline.get("clip_origin_seconds", 0.0), "looks": lines("observations.jsonl"),
            "states": lines("states.jsonl")}


def compare(watcher: dict, owner: dict) -> list[dict]:
    """Rows of (truth from the owner's buttons, the watcher's count of it) at matching moments."""
    times = [s["t"] + watcher["origin"] for s in watcher["states"]]
    rows = []
    for look, own in zip(owner["looks"], owner["states"]):
        if "my_energy" not in look:
            continue
        k = bisect.bisect_right(times, look["t"] + owner["origin"] + 0.25) - 1
        if k < 0 or look["t"] + owner["origin"] - times[k] > 1.0:
            continue
        theirs = watcher["states"][k]["opponent"]
        if theirs["active"] is None:
            continue
        seen, me = theirs["pokemon"][theirs["active"]], own["me"]["pokemon"][own["me"]["active"]]
        if seen["species"] != me["species"]:
            continue  # the two views disagree on who is out at this moment: a switch in progress
        rows.append({"truth": look["my_energy"], "count": seen["energy"], "ceiling": seen.get("energy_by_clock"),
                     "gain": seen["fast_move"]["energy_gain"], "true_gain": me["fast_move"]["energy_gain"],
                     "same_fast": seen["fast_move"]["id"] == me["fast_move"]["id"],
                     "under_costs": look["my_energy"] < min(m["energy"] for m in me["charged_moves"]) - 2})
    return rows


def report(label: str, rows: list[dict]) -> None:
    if not rows:
        print(f"{label}: no moments to compare"); return
    diff = [r["count"] - r["truth"] for r in rows]
    size = sorted(abs(d) for d in diff)
    in_moves = [abs(d) / max(r["true_gain"], 1) for d, r in zip(diff, rows)]
    print(f"{label}: {len(rows)} moments | count minus truth {sum(diff) / len(diff):+.1f} on average, size {sum(size) / len(size):.1f}, median {size[len(size) // 2]:.0f}"
          f" | within one fast move {100 * sum(x <= 1.25 for x in in_moves) / len(rows):.0f}%, within two {100 * sum(x <= 2.25 for x in in_moves) / len(rows):.0f}%"
          f" | fast move assumed correctly {100 * sum(r['same_fast'] for r in rows) / len(rows):.0f}%")


def paired_folders(args: list[str]) -> list[Path]:
    """The folders to compare, two by two. Either named outright, or `--all TRACKED [--source ID ...]`: every
    two-screen match among the published clips (games/twitch/<clip>/source.json says which clips belong to one
    match), with the tracked games taken from TRACKED/<clip>."""
    if "--all" not in args:
        return [Path(a) for a in args]
    tracked = Path(args[args.index("--all") + 1])
    sources = {args[i + 1] for i, a in enumerate(args) if a == "--source"}
    matches = {}
    for clip in sorted((Path(__file__).resolve().parents[2] / "games" / "twitch").glob("tw-*")):
        info = json.loads((clip / "source.json").read_text()) if (clip / "source.json").exists() else {}
        whole = info.get("incomplete_start") in (False, "False") and info.get("incomplete_end") in (False, "False")
        if whole and (not sources or clip.name.split("-")[1] in sources) and (tracked / clip.name / "timeline.json").exists():
            matches.setdefault(info.get("match_id"), []).append(tracked / clip.name)
    return [folder for views in matches.values() if len(views) == 2 for folder in views]


if __name__ == "__main__":
    folders = [load(a) for a in paired_folders(sys.argv[1:])]
    print(f"{len(folders) // 2} matches seen from both sides")
    everything, settled = [], []
    for a, b in zip(folders[::2], folders[1::2]):
        for watcher, owner in ((a, b), (b, a)):
            rows = compare(watcher, owner)
            report(f"{watcher['name'][-9:]} counting {owner['name'][-9:]}", rows)
            everything += rows; settled += [r for r in rows if r["under_costs"]]
    report("all pairs", everything)
    report("all pairs, only while the true energy is under both move costs (the buttons at their most reliable)", settled)
    report("  ... and the fast move was assumed correctly", [r for r in settled if r["same_fast"]])
