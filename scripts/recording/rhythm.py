"""Energy counted from the rhythm of fast moves alone: a fast move lands every so many turns for as long as
its user is on the field and the fight is running. No health bars are used.

    python3 scripts/recording/rhythm.py games/<name>

Needs timeline.json (written by assemble.py) and state.json (written by track.py, for the fast moves).
For every charged move thrown it prints the energy this count gives just before, next to the move's cost.
"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pogo.gamedata import GameData

game = Path(sys.argv[1])
START = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0  # the first fast moves begin this long after the bars appear
CHARGED = 10.0  # seconds from the cue of a charged move to fighting again
SLACK = 0.2  # seconds of timing error allowed when counting whole fast moves
tl, state, gd = json.loads((game / "timeline.json").read_text()), json.loads((game / "state.json").read_text()), GameData()
by_name = {m.name: m for m in gd.moves.values()}
fast = {("mine", q["name"].split(" (")[0]): gd.moves[q["fast_move"]["id"]] for q in state["me"]["pokemon"]}
fast.update({("theirs", q["name"].split(" (")[0]): gd.moves[q["fast_move"]["id"]] for q in state["opponent"]["pokemon"]})

# Times when nobody can attack: a charged move playing, or a side waiting for a replacement after a faint.
stops = [(c["t"], c["t"] + CHARGED, c) for c in tl["charged"]]
for side, entries in tl["field"].items():
    for f in entries:
        if f["faint"]:
            fell = [when for when, _ in tl["left"][side][1:] if when <= f["t"]]
            stops.append((fell[-1] if fell else f["t"] - 2.0, f["t"] + 0.3, None))
stops.sort(key=lambda x: x[0])

def on_field(side, t):
    out = None
    for f in tl["field"][side]:
        if f["t"] + (0.0 if f["faint"] or out is None else 0.5) <= t: out = f["name"]  # a switch costs its turn
    return out

energy, rows, clock = {}, [], START
for a, b, thrown in stops + [(tl["end"], tl["end"], None)]:
    if a > clock:  # a stretch of fighting from clock to a
        for side in ("mine", "theirs"):
            changes = [clock] + [f["t"] + 0.5 for f in tl["field"][side] if clock < f["t"] + 0.5 < a and not f["faint"]] + [a]
            for u, v in zip(changes, changes[1:]):
                name = on_field(side, (u + v) / 2)
                if (side, name) not in fast: continue
                move = fast[side, name]; period = 0.5 * move.turns
                hits = int((v - u + SLACK) // period)
                # A fast move still in the air when the other side throws a charged move lands after it.
                if thrown and v == a and thrown["side"] != side and (v - u) - hits * period > SLACK: hits += 1
                energy[side, name] = min(100, energy.get((side, name), 0) + hits * move.energy_gain)
    if thrown and thrown["move"] in by_name:
        key = (thrown["side"], on_field(thrown["side"], a - 0.1)); cost = by_name[thrown["move"]].energy
        have = energy.get(key, 0)
        rows.append((a, key, thrown["move"], cost, have, fast[key].energy_gain if key in fast else 0))
        energy[key] = max(0, have - cost)
    clock = max(clock, b)
for side in ("mine", "theirs"):
    mine = [r for r in rows if r[1][0] == side]
    print("ours" if side == "mine" else "theirs")
    for t, key, move, cost, have, gain in mine:
        print(f"  {t:6.1f}s {key[1]:11s} {move:17s} cost {cost:3d}  counted {have:3d}  {'SHORT by' if have < cost else 'spare'} {abs(have - cost):3d}"
              + (f" ({abs(have - cost) / gain:.1f} fast moves)" if gain else ""))
    ok = sum(1 for r in mine if r[4] >= r[3])
    spare = sorted((r[4] - r[3]) / r[5] for r in mine if r[5])
    if mine: print(f"  could pay {ok} of {len(mine)}; spare energy in fast moves: median {spare[len(spare) // 2]:.1f}, from {spare[0]:.1f} to {spare[-1]:.1f}")
