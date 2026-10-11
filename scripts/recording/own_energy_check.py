"""How far is the fast-move count from a player's own energy, as read off their buttons?

    python3 scripts/recording/own_energy_check.py GAME_FOLDER [GAME_FOLDER ...]

Tracks each game again without letting the buttons correct the count (track.py --blind, into a copy), then
compares the two at the end of every stretch of fighting, while the energy is under both move costs (where the
buttons are at their most reliable). Differences are in fast moves of the Pokémon that is out.
"""
import json, shutil, subprocess, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]


def stretch_ends(game: Path) -> list[int]:
    with tempfile.TemporaryDirectory() as tmp:
        for name in ("team.json", "observations.jsonl", "foes.json"):
            if (game / name).exists():
                shutil.copy(game / name, Path(tmp) / name)
        subprocess.run([sys.executable, ROOT / "scripts/track.py", tmp, "--blind"], capture_output=True, cwd=ROOT)
        looks = [json.loads(l) for l in open(Path(tmp) / "observations.jsonl")]
        states = [json.loads(l) for l in open(Path(tmp) / "states.jsonl")]
    ends, previous = [], None
    for look, state in zip(looks, states):
        mon = state["me"]["pokemon"][state["me"]["active"]]
        current = (look["my_energy"], mon) if "my_energy" in look else None
        if current is None and previous is not None:
            energy, was = previous
            if energy < min(m["energy"] for m in was["charged_moves"]) - 2:
                ends.append(round((energy - was["energy"]) / was["fast_move"]["energy_gain"]))
        previous = current
    return ends


if __name__ == "__main__":
    everything = [d for folder in sys.argv[1:] for d in stretch_ends(Path(folder))]
    n = max(len(everything), 1)
    print(f"{len(everything)} stretch ends in {len(sys.argv) - 1} games: exact {100 * sum(d == 0 for d in everything) / n:.0f}%, "
          f"within one fast move {100 * sum(abs(d) <= 1 for d in everything) / n:.0f}%, within two {100 * sum(abs(d) <= 2 for d in everything) / n:.0f}%, "
          f"average size {sum(abs(d) for d in everything) / n:.2f}, buttons minus count {sum(everything) / n:+.2f}")
