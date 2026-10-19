"""Team shapes, as players describe them (the owner: balanced teams, ABC or ABB, are common; BAB or AAA are not).

Each Pokémon gets a letter by what beats it: two Pokémon share a letter when their one-on-one records against the
top Pokémon (data/matchups.json: mean health margin over 0, 1 and 2 shields) correlate at `threshold` or more, so they
tend to beat and lose to the same things. (Sharing most of their counters outright is too strict: nearly every team
is then ABC.) At 0.3, random threes from the top 50 are 68% ABC, 9% ABB, 22% AAB and 1% AAA; the 81 strongest teams
the team search found are 81 / 6 / 12 / 0, and their top 15 87 / 7 / 7 / 0: strong teams avoid AAB and AAA.
Real teams agree (PvPoke's training data, data/pvpoke_training_1500.json, scripts/pvpoke_teams.py): its 47 best-scoring
teams are 94 / 6 / 0 / 0 (98 / 2 / 0 / 0 by games played) and its bots' 37 teams 92 / 3 / 5 / 0, where random threes
drawn by usage are 73 / 8 / 19 / 0; so ABB is rarer than the owner's guess, AAB about as rare. PVPOKE_WEIGHTS is that.
A team, lead first, is then:

- ABC: no two share a letter (balanced);
- ABB: the two in the back share one, the lead does not (the lead covers what beats the back);
- AAB: the lead shares a letter with one in the back (the owner's BAB);
- AAA: all three share one.

`shaped_drawer` draws opposing teams with each shape weighted, and Pokémon weighted by how high they rank, as a
stand-in for what people bring until there is real data.
"""
from __future__ import annotations

import json
import math
import random
from pathlib import Path

MATCHUPS = Path(__file__).resolve().parent.parent / "data" / "matchups.json"
SHAPES = ("ABC", "ABB", "AAB", "AAA")
WEIGHTS = {"ABC": 1.0, "ABB": 0.8, "AAB": 0.15, "AAA": 0.03}  # the owner's rule of thumb, as weights
PVPOKE_WEIGHTS = {"ABC": 1.0, "ABB": 0.2, "AAB": 0.05, "AAA": 0.01}  # listed teams / random threes, from PvPoke's data
USAGE = Path(__file__).resolve().parent.parent / "data" / "pvpoke_training_1500.json"
WIDE = Path(__file__).resolve().parent.parent / "data" / "matchups_wide.json"  # scripts/pvpoke_teams.py writes it


def pvpoke_usage(path: Path = USAGE) -> dict:
    """{species: share of team slots} in PvPoke's training battles (the Pokémon it lists; about 80% of slots)."""
    data = json.loads(Path(path).read_text())["usage"]
    out: dict = {}
    for p in data["performers"]:
        out[p["pokemon"]] = out.get(p["pokemon"], 0.0) + p["games"] / data["totalPerformers"]
    return out


class Shapes:
    def __init__(self, threshold: float = 0.3, path: Path = MATCHUPS):
        import numpy as np
        table = json.loads(Path(path).read_text())
        ids = list(table)
        self.records = {p: np.array([table[p].get(q, 0.0) for q in ids]) for p in ids}
        self.counters = self.records  # the Pokémon this knows about
        self.threshold = threshold
        self._same: dict = {}

    def alike(self, a: str, b: str) -> float:
        import numpy as np
        if a not in self.records or b not in self.records:
            return 0.0
        return float(np.corrcoef(self.records[a], self.records[b])[0, 1])

    def same(self, a: str, b: str) -> bool:
        key = (a, b) if a < b else (b, a)
        if key not in self._same:
            self._same[key] = self.alike(a, b) >= self.threshold
        return self._same[key]

    def shape(self, team: list[str]) -> str:
        lead, b1, b2 = team
        l1, l2, bb = self.same(lead, b1), self.same(lead, b2), self.same(b1, b2)
        if l1 and l2 and bb:
            return "AAA"
        if bb and not (l1 or l2):
            return "ABB"
        if l1 or l2:
            return "AAB"
        return "ABC"


def shaped_drawer(gd, pool: list, weights: dict = WEIGHTS, popularity: float = 25.0, shapes: Shapes | None = None,
                  seed_checks: int = 2000, usage: dict | None = None):
    """A function draw(rng) -> three Builds, lead first: Pokémon weighted by rank (exp(-rank / popularity)), or by
    `usage` ({species: share}, e.g. pvpoke_usage(); half the smallest share for the unlisted), teams kept with the
    chance their shape's weight gives (rejection sampling); no species twice."""
    shapes = shapes or Shapes()
    ranked = [b for b in pool if b.species_id in shapes.counters]
    if usage:
        floor = min(usage.values()) / 2
        rank_weights = [usage.get(b.species_id, floor) for b in ranked]
    else:
        rank_weights = [math.exp(-k / popularity) for k in range(len(ranked))]
    dex = {b.species_id: gd.species[b.species_id]["dex"] for b in ranked}
    top = max(weights.values())

    def draw(rng: random.Random) -> list:
        for _ in range(seed_checks):
            team = rng.choices(ranked, rank_weights, k=3)
            if len({dex[b.species_id] for b in team}) < 3:
                continue
            if rng.random() < weights[shapes.shape([b.species_id for b in team])] / top:
                return team
        return rng.sample(ranked, 3)

    return draw


def pvpoke_field(gd):
    """(pool, draw): the opposing field as PvPoke's data has it: our top 50 with the form-changers (Cramorant, Mimikyu)
    plus the other Pokémon PvPoke lists (Morpeko, Jumpluff, Lickilicky), teams drawn by usage and PVPOKE_WEIGHTS."""
    usage = pvpoke_usage()
    pool = gd.meta(50, forms=True)
    have = {b.species_id for b in pool}
    known = {e["speciesId"] for e in gd.rankings(1500)}
    pool += [gd.default(sp) for sp in sorted(usage, key=lambda x: -usage[x]) if sp in known and sp not in have]
    return pool, shaped_drawer(gd, pool, PVPOKE_WEIGHTS, shapes=Shapes(path=WIDE), usage=usage)


def mixed_field(gd, usual: float = 0.25):
    """(pool, draw): pvpoke_field most of the time, the usual broad draw (pogo.teamlist.drawer over the top 50) with
    chance `usual`, so the field is realistic without fitting one snapshot of PvPoke's training data: rarer
    Pokémon and odd teams still come up. The default field for team choice, opening books and new measurements."""
    from .teamlist import drawer
    pool, pvpoke = pvpoke_field(gd)
    plain = gd.meta(50)
    broad = drawer(gd, plain)
    have = {b.species_id for b in pool}
    pool = pool + [b for b in plain if b.species_id not in have]

    def draw(rng):
        return broad(rng) if rng.random() < usual else pvpoke(rng)

    return pool, draw
