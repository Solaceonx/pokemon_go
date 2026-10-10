"""Decide, without anyone looking, whether a tracked game can be trusted.

    python3 scripts/recording/verdict.py games/<name>

Reads what assemble.py and track.py wrote and applies checks that need no ground truth. Writes verdict.json
and prints one line. A game fails if any hard check fails; soft checks are only listed.

Hard checks
  looks        no look was rejected by the tracker
  teams        one to three Pokémon seen on each side, all recognised
  moves        every charged move was read by name
  shields      each side's shields used equal the charged moves tracked as blocked against it
  energy       whoever threw a charged move had at least its cost, by the tracker's count, on both sides
  ending       the result screen agrees with who had Pokémon left; with no result screen, exactly one side is out
Soft checks
  unexplained  changes in our health the rules could not explain, as a share of looks (listed above 15%)
  fast moves   opponent fast moves still only guessed
"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pogo.gamedata import GameData


def verdict(game: Path, gd: GameData) -> dict:
    load = lambda name: json.loads((game / name).read_text())
    rows = lambda name: [json.loads(l) for l in (game / name).read_text().splitlines() if l.strip()]
    track, final, timeline = load("track.json"), load("state.json"), load("timeline.json")
    obs, states, events = rows("observations.jsonl"), rows("states.jsonl"), rows("events.jsonl")
    failed, notes = [], []
    if track["rejected"] or track["looks"] != len(states):
        failed.append(f"looks: {track['rejected']} rejected")
    ours, theirs = final["me"]["pokemon"], final["opponent"]["pokemon"]
    if not 1 <= len(ours) <= 3 or not 1 <= len(theirs) <= 3:
        failed.append(f"teams: {len(ours)} of ours and {len(theirs)} of theirs seen")
    thrown = [e for e in events if e["event"] in ("my_charged", "foe_charged")]
    unnamed = sum(1 for e in thrown if not e.get("move")) + sum(1 for c in timeline["charged"] if not c["move"])
    if unnamed:
        failed.append(f"moves: {unnamed} charged move(s) without a name")
    if len(thrown) != len(timeline["charged"]):
        failed.append(f"moves: {len(timeline['charged'])} charged moves announced, {len(thrown)} tracked")
    # Each shield that went must have a charged move it blocked, and the other way round.
    for side, mine in (("me", True), ("opponent", False)):
        gone = 2 - final[side]["shields"]
        blocked = sum(1 for e in thrown if e.get("shielded") and (e["event"] == "foe_charged") == mine)
        if gone != blocked:
            failed.append(f"shields: {'we' if mine else 'they'} used {gone}, but {blocked} charged move(s) were tracked as blocked")
    short, spare = [], []
    for e in thrown:
        if not e.get("move"):
            continue
        cost = gd.moves[e["move"]].energy
        if e["event"] == "foe_charged":
            had = e["energy_before"][1]
        else:  # our energy just after the throw is in the state for that look
            k = next((i for i, o in enumerate(obs) if abs(o["t"] - e["t"]) < 0.01), None)
            mon = next((p for p in states[k]["me"]["pokemon"] if any(m["id"] == e["move"] for m in p["charged_moves"])), None) \
                if k is not None and k < len(states) else None
            if mon is None:
                continue
            had = mon["energy"] + cost
        spare.append(had - cost)
        if had < cost:
            short.append(f"{e['move'].lower()} at {e['t']}s had {had} of {cost}")
    if short:
        failed.append("energy: " + "; ".join(short))
    result, mine_left, their_left = timeline.get("result"), final["me"]["left"], final["opponent"]["left"]
    if result == "win" and not (their_left == 0 and mine_left >= 1):
        failed.append(f"ending: result says win, tracker has us on {mine_left} and them on {their_left}")
    elif result == "loss" and not (mine_left == 0 and their_left >= 1):
        failed.append(f"ending: result says loss, tracker has us on {mine_left} and them on {their_left}")
    elif result is None:
        # Without the result screen the ending still has to be decisive: exactly one side out of Pokémon.
        if (mine_left == 0) == (their_left == 0):
            failed.append(f"ending: no result screen, and the tracker has us on {mine_left} and them on {their_left}")
        else:
            result = "win" if their_left == 0 else "loss"
            notes.append("no result screen read; result taken from who had Pokémon left")
    share = track["unexplained"] / max(track["looks"], 1)
    if share > 0.15:
        notes.append(f"unexplained changes in {100 * share:.0f}% of looks")
    guessed = [p["species"] for p in theirs if p["fast_move"]["known_from"] == "guessed"]
    if guessed:
        notes.append("fast move only guessed for " + ", ".join(guessed))
    return {"game": game.name, "verdict": "fail" if failed else "pass", "failed": failed, "notes": notes,
            "result": result, "seconds": timeline["end"], "looks": track["looks"], "charged_moves": len(thrown),
            "ours": [p["species"] for p in ours], "theirs": [p["species"] for p in theirs],
            "their_fast_moves": {p["species"]: p["fast_move"]["id"] for p in theirs},
            "spare_energy_at_throws": spare}


if __name__ == "__main__":
    game = Path(sys.argv[1])
    v = verdict(game, GameData())
    (game / "verdict.json").write_text(json.dumps(v, indent=1) + "\n")
    print(f"{v['verdict'].upper():4s} {v['game']}: {v['result'] or 'no result'}, {v['looks']} looks, {v['charged_moves']} charged moves; "
          + ("; ".join(v["failed"] + v["notes"]) or "all checks clean"))
    sys.exit(0 if v["verdict"] == "pass" else 1)
