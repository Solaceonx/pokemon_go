"""How much of the game state does one screen get right about the other player? Two views of the same match.

    python3 scripts/recording/paired_state.py games/twitch/<left view> games/twitch/<right view> [more pairs ...]

For every look of one view, its picture of the opponent is set against the other view's picture of itself
at the same moment: who is out, health, shields, Pokémon left, and (where the buttons were read) energy.
A player's own screen is the better witness for all of these, so it stands in for the truth.
"""
import bisect, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from paired_energy import load

FIELDS = ("who is out", "health within 3%", "health within 10%", "shields", "Pokémon left", "energy within one fast move",
          "energy within two", "all of these but energy", "everything, energy within two")


def moments(watcher: dict, owner: dict):
    times = [s["t"] + owner["origin"] for s in owner["states"]]
    for look, state in zip(watcher["looks"], watcher["states"]):
        t = look["t"] + watcher["origin"]
        k = bisect.bisect_right(times, t + 0.25) - 1
        if k < 0 or t - times[k] > 1.0 or state["opponent"]["active"] is None:
            continue
        seen, own_state, own_look = state["opponent"], owner["states"][k], owner["looks"][k]
        theirs, me = seen["pokemon"][seen["active"]], own_state["me"]["pokemon"][own_state["me"]["active"]]
        row = {"who is out": theirs["species"] == me["species"]}
        if row["who is out"]:
            row["health within 3%"] = abs(theirs["hp_share"] - me["hp_share"]) <= 0.03
            row["health within 10%"] = abs(theirs["hp_share"] - me["hp_share"]) <= 0.10
            if "my_energy" in own_look:
                off = abs(theirs["energy"] - own_look["my_energy"]) / max(me["fast_move"]["energy_gain"], 1)
                row["energy within one fast move"], row["energy within two"] = off <= 1.25, off <= 2.25
        row["shields"] = seen["shields"] == own_state["me"]["shields"]
        row["Pokémon left"] = seen["left"] == own_state["me"]["left"]
        row["all of these but energy"] = all(row.get(f, False) for f in ("who is out", "health within 10%", "shields", "Pokémon left"))
        if "energy within two" in row:
            row["everything, energy within two"] = row["all of these but energy"] and row["energy within two"]
        yield row


if __name__ == "__main__":
    folders = [load(Path(a)) for a in sys.argv[1:]]
    rows = [r for a, b in zip(folders[::2], folders[1::2]) for watcher, owner in ((a, b), (b, a)) for r in moments(watcher, owner)]
    print(f"{len(rows)} moments from {len(folders) // 2} matches, each seen from both sides")
    for f in FIELDS:
        have = [r[f] for r in rows if f in r]
        print(f"  {f:32s} right in {100 * sum(have) / max(len(have), 1):5.1f}% of {len(have)}")
