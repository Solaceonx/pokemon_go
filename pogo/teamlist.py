"""Draw teams for simulated opponents from the saved list of strong teams, not purely at random."""
from __future__ import annotations

import json
import math
import random
from pathlib import Path

from .gamedata import GameData

TEAMS = Path(__file__).resolve().parent.parent / "data" / "teams.json"


def weights_for(listed: list[dict]) -> list[float]:
    """Explicit mixture weights take precedence; old lists keep their original weighting.

    Explicit weights define the final mixture. Multiplying them by seen counts here
    would change the field that was tested for exploitability.
    """
    explicit = any("weight" in entry for entry in listed)
    if explicit and not all("weight" in entry for entry in listed):
        raise ValueError("every team must have a weight in an explicit mixture")
    weights = [float(entry["weight"]) if explicit else
               max(entry["score"] - 0.4, 0.02) * (1 + entry.get("seen", 0)) for entry in listed]
    if not weights or any(not math.isfinite(w) or w < 0 for w in weights) or sum(weights) <= 0:
        raise ValueError("team weights must be finite, nonnegative, and have a positive total")
    return weights


def drawer(gd: GameData, pool: list, path: Path = TEAMS, share: float = 0.5):
    """A function draw(rng) -> three Builds, lead first.

    With probability `share` it is a team from the list, weighted towards the better ones and
    towards those met more often in real games (the "seen" count), or with explicit mixture
    weights when supplied; otherwise a random legal three.
    """
    listed = json.loads(Path(path).read_text())["teams"]
    teams = [[gd.default(s) for s in entry["team"]] for entry in listed]
    weights = weights_for(listed)
    dex = {b.species_id: gd.species[b.species_id]["dex"] for b in pool}

    def draw(rng: random.Random) -> list:
        if rng.random() < share:
            return rng.choices(teams, weights)[0]
        while True:
            team = rng.sample(pool, 3)
            if len({dex[b.species_id] for b in team}) == 3:  # the game does not allow a species twice
                return team

    return draw
