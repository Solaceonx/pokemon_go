#!/usr/bin/env python3
"""Test the Tracker against simulated battles, before any image recognition exists.

    python3 scripts/check_tracker.py            accuracy and playing strength under three camera qualities
    python3 scripts/check_tracker.py --game     also write one game's event file to games/example.jsonl

A simulated camera turns the true state of each battle into what a look at the
screen would give, optionally blurred: looks missed, health bars read in steps,
energy read with error, the opponent's charged move not named. The Tracker sees
only that. We then measure how close its picture is to the truth, and whether
the Planner plays as well from the Tracker's picture as from the truth.
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pogo.agents import Planner  # noqa: E402
from pogo.battle import DRAW, FAST, Battle  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.tracker import Observation, Tracker, describe  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CAMERAS = {
    "perfect": dict(miss=0.0, bar_steps=0, energy_error=0.0, names=True),
    "move not named": dict(miss=0.0, bar_steps=0, energy_error=0.0, names=False),
    "rough": dict(miss=0.2, bar_steps=200, energy_error=3.0, names=False),
}
PARTS = {  # one flaw at a time, to see which matters
    "only: one look in five missed": dict(miss=0.2, bar_steps=0, energy_error=0.0, names=True),
    "only: health bars read in 0.5% steps": dict(miss=0.0, bar_steps=200, energy_error=0.0, names=True),
    "only: my energy read with error of 3": dict(miss=0.0, bar_steps=0, energy_error=3.0, names=True),
}


ENERGY = "hits" if "--hits" in sys.argv else "rhythm"  # how the tracker counts energy


class Camera:
    """What one player's screen would show after each turn of a simulated battle."""

    def __init__(self, battle: Battle, side: int, rng: random.Random, miss: float, bar_steps: int,
                 energy_error: float, names: bool):
        self.battle, self.side, self.rng = battle, side, rng
        self.miss, self.bar_steps, self.energy_error, self.names = miss, bar_steps, energy_error, names
        self.seen = 0
        self.my_charged, self.foe_charged, self.foe_move = None, False, None

    def _bar(self, mon) -> float:
        share = max(mon.hp, 0) / mon.build.hp
        return round(share * self.bar_steps) / self.bar_steps if self.bar_steps else share

    def look(self, certain: bool = False) -> Observation | None:
        b = self.battle
        me, them = b.sides[self.side], b.sides[1 - self.side]
        for side, move_id, _ in b.hits[self.seen:]:
            team = b.sides[side].team
            if any(move_id == m.id for mon in team for m in mon.build.charged):
                if side == self.side:
                    ids = [m.id for m in me.mon.build.charged]
                    self.my_charged = ids.index(move_id) if move_id in ids else 0
                else:
                    self.foe_charged, self.foe_move = True, move_id
        self.seen = len(b.hits)
        if not certain and self.rng.random() < self.miss:
            return None  # this look was lost; a charged move is long enough to be caught by the next one
        energy = me.mon.energy + self.rng.gauss(0, self.energy_error) if self.energy_error else me.mon.energy
        obs = Observation(
            t=b.turn * 0.5, my_species=me.mon.build.species_id, my_hp=self._bar(me.mon),
            foe_species=them.mon.build.species_id, foe_hp=self._bar(them.mon),
            my_shields=me.shields, foe_shields=them.shields, my_left=me.left(), foe_left=them.left(),
            my_energy=min(100.0, max(0.0, energy)), my_switch=me.switch_wait * 0.5,
            my_charged=self.my_charged, foe_charged=self.foe_charged, foe_move=self.foe_move if self.names else None)
        self.my_charged, self.foe_charged, self.foe_move = None, False, None
        return obs


class ViaTracker:
    """A player that decides from the Tracker's picture, never from the true state."""

    def __init__(self, inner):
        self.inner = inner
        self.tracker: Tracker | None = None

    def act(self, view):
        action = self.inner.act(self.tracker.view())
        return action if action in view.legal() else FAST  # a tap on a move that is not ready does nothing

    def shield(self, view, foe_energy):
        return self.inner.shield(self.tracker.view(), self.tracker.foe.hi)

    def replace(self, view):
        slot = self.inner.replace(self.tracker.view())
        return slot if slot in view.me.bench() else view.me.bench()[0]

    def saw_throw(self, view, move, energy, could_shield):
        self.inner.saw_throw(self.tracker.view(), move, self.tracker.foe.hi, could_shield)

    def saw_shield(self, view, shielded):
        self.inner.saw_shield(self.tracker.view(), shielded)


class Tally:
    def __init__(self):
        self.n = self.exact = self.inside = self.wrong_active = self.busy_right = 0
        self.energy = self.my_energy = self.my_hp = self.switch = 0.0

    def add(self, battle: Battle, side: int, tracker: Tracker) -> None:
        me, them = battle.sides[side], battle.sides[1 - side]
        if tracker.foe is None or tracker.foe.mon.build.species_id != them.mon.build.species_id:
            self.wrong_active += 1
            return
        view, foe = tracker.view(), tracker.foe
        self.n += 1
        self.exact += foe.lo == foe.hi == them.mon.energy
        self.inside += foe.lo <= them.mon.energy <= foe.hi
        self.energy += abs(foe.mon.energy - them.mon.energy)
        self.busy_right += view.foe_busy == them.busy
        self.switch += abs(view.foe_switch_wait - them.switch_wait) * 0.5
        if tracker.me.active == me.active:
            self.my_energy += abs(tracker.me.mon.energy - me.mon.energy)
            self.my_hp += abs(tracker.me.mon.hp - max(me.mon.hp, 0))

    def report(self) -> str:
        n = max(self.n, 1)
        return (f"their energy exact {100 * self.exact / n:.0f}%, inside the range {100 * self.inside / n:.0f}%, "
                f"off by {self.energy / n:.1f} on average | their fast-move position right {100 * self.busy_right / n:.0f}% | "
                f"their switch timer off by {self.switch / n:.2f}s | my energy off by {self.my_energy / n:.1f}, "
                f"my health by {self.my_hp / n:.1f} | wrong Pokémon in view {100 * self.wrong_active / (self.n + self.wrong_active):.1f}% of turns")


def play(gd, teams, agents, seed, camera: dict, tally: Tally | None, rng, path=None, looks: list | None = None) -> int:
    battle = Battle(*teams, *agents, seed=seed, record=True)
    watched = []
    for i, agent in enumerate(agents):
        if isinstance(agent, ViaTracker):
            agent.tracker = Tracker(gd, teams[i], path=path, energy=ENERGY)
            cam = Camera(battle, i, rng, **camera)
            first = cam.look(certain=True)
            agent.tracker.update(first)
            if looks is not None:
                looks.append(describe(first))
            watched.append((i, agent.tracker, cam))
    while battle.winner is None:
        battle.step()
        for i, tracker, cam in watched:
            obs = cam.look()
            if obs is not None and looks is not None:
                looks.append(describe(obs))
            if obs is not None:
                tracker.update(obs)
            else:
                tracker.tick(battle.turn * 0.5)
            if tally is not None and battle.winner is None:
                tally.add(battle, i, tracker)
    for i, tracker, _ in watched:
        tracker.close("draw" if battle.winner == DRAW else "win" if battle.winner == i else "loss")
    return battle.winner


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pairings", type=int, default=400)
    parser.add_argument("--hits", action="store_true", help="count energy from the steps in the health bars, not from the rhythm of fast moves")
    parser.add_argument("--game", action="store_true", help="write one game's event file to games/example.jsonl")
    parser.add_argument("--parts", action="store_true", help="test one camera flaw at a time")
    args = parser.parse_args()

    gd = GameData()
    pool = [gd.default(b.species_id) for b in gd.meta(50)]
    for name, camera in (PARTS if args.parts else CAMERAS).items():
        rng = random.Random(0)
        tally, points = Tally(), 0.0
        for _ in range(args.pairings):
            a, b = rng.sample(pool, 3), rng.sample(pool, 3)
            for mine, theirs in ((a, b), (b, a)):
                winner = play(gd, (mine, theirs), (ViaTracker(Planner()), Planner()), rng.getrandbits(32), camera, tally, rng)
                points += 1.0 if winner == 0 else 0.5 if winner == DRAW else 0.0
        games = 2 * args.pairings
        share = points / games
        print(f"camera: {name}")
        print(f"  {tally.report()}")
        print(f"  Planner playing from the Tracker's picture, against the Planner playing from the truth: "
              f"{100 * share:.1f}% ± {100 * 1.96 * (share * (1 - share) / games) ** 0.5:.1f} over {games} battles\n")

    if args.game:
        import json
        rng = random.Random(4)
        folder = ROOT / "games" / "example"
        folder.mkdir(parents=True, exist_ok=True)
        teams = rng.sample(pool, 3), rng.sample(pool, 3)
        looks: list = []
        play(gd, teams, (ViaTracker(Planner()), Planner()), 4, CAMERAS["move not named"], None, rng, looks=looks)
        sheet = {"pokemon": [{"species": b.species_id, "fast": b.fast.id, "charged": [m.id for m in b.charged]} for b in teams[0]]}
        (folder / "team.json").write_text(json.dumps(sheet, indent=2) + "\n")
        (folder / "observations.jsonl").write_text("".join(json.dumps(look) + "\n" for look in looks))
        print(f"wrote {folder.relative_to(ROOT)}/team.json and observations.jsonl ({len(looks)} looks); now run scripts/track.py on that folder")


if __name__ == "__main__":
    main()
