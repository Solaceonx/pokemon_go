#!/usr/bin/env python3
"""Given a game state, say what to do now and how the rest of the game is likely to go.

    python3 scripts/advise.py games/example             the last state (state.json)
    python3 scripts/advise.py games/example --look 60   the state after the 60th look (states.jsonl)

The state is the one the tracker writes. The advice comes from playing the position on
many times: our side by the Planner, their side by varied versions of it, their unseen
Pokémon drawn from the top 50, and their energy drawn from the range the tracker gives.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pogo.agents import Planner, varied  # noqa: E402
from pogo.battle import CHARGED, DRAW, FAST, SWITCH, Battle, Mon  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402


class Watched:
    """Passes everything through to a player, remembering its first action and first shield answer."""

    def __init__(self, inner):
        self.inner, self.first, self.shielded = inner, None, None

    def act(self, view):
        action = self.inner.act(view)
        if self.first is None:
            self.first = action
        return action

    def shield(self, view, foe_energy):
        answer = self.inner.shield(view, foe_energy)
        if self.shielded is None:
            self.shielded = answer
        return answer

    def replace(self, view):
        return self.inner.replace(view)

    def saw_throw(self, *args):
        self.inner.saw_throw(*args)

    def saw_shield(self, *args):
        self.inner.saw_shield(*args)


def mon_from(gd: GameData, p: dict, energy: int | None = None) -> Mon:
    moves = [p["fast_move"]["id"], *(m["id"] for m in p["charged_moves"])]
    mon = Mon(gd.build(p["species"], moves, level=p["level"], ivs=tuple(p["ivs"])), hp=p["hp"],
              energy=p["energy"] if energy is None else energy)
    mon.atk_stage, mon.def_stage = p["attack_stage"], p["defense_stage"]
    return mon


def rebuild(gd: GameData, state: dict, pool, rng: random.Random, me_agent, foe_agent) -> Battle:
    """A battle standing at this state, with what we cannot know filled in at random."""
    me, foe = state["me"], state["opponent"]
    mine = [mon_from(gd, p) for p in me["pokemon"]]
    theirs = [mon_from(gd, p, rng.randint(*p["energy_range"])) for p in foe["pokemon"]]
    taken = {m.build.species_id for m in theirs}
    theirs += [Mon(b) for b in rng.sample([b for b in pool if b.species_id not in taken], foe["unseen"])]
    battle = Battle(mine, theirs, me_agent, foe_agent, seed=rng.getrandbits(32), shields=(me["shields"], foe["shields"]),
                    switch_wait=(round(me["switch_ready_in"] * 2), round(foe["switch_ready_in"] * 2)), record=True)
    battle.sides[0].active, battle.sides[1].active = me["active"], foe["active"]
    battle.sides[1].busy = foe.get("fast_move_turns_left") or 0
    battle.turn = round(state["t"] * 2)
    return battle


def name_action(action: int, mon: Mon, team: list[Mon]) -> str:
    if action == FAST:
        return f"fast move ({mon.build.fast.name})"
    if action in CHARGED:
        return f"throw {mon.build.charged[action - CHARGED[0]].name}"
    return f"switch to {team[action - SWITCH[0]].build.name}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder")
    parser.add_argument("--look", type=int, help="use the state after this many looks, from states.jsonl")
    parser.add_argument("--games", type=int, default=300, help="simulated continuations")
    parser.add_argument("--q", metavar="FILE", help="pilot with decisions learned by scripts/decide.py, e.g. runs/<team>-decide/q.npz")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    if args.q:
        from pogo.learner import Learner, QNet
        learned = QNet.load(args.q)
        make_pilot = lambda seed: Learner(q=learned, margin=0.02, seed=seed, hold=True, hold_cost=0.5)  # noqa: E731
    else:
        make_pilot = lambda seed: Planner(seed=seed)  # noqa: E731

    folder = Path(args.folder)
    if args.look:
        state = json.loads((folder / "states.jsonl").read_text().splitlines()[args.look - 1])
    else:
        state = json.loads((folder / "state.json").read_text())
    gd = GameData()
    pool = gd.meta(50)
    rng = random.Random(args.seed)
    me, foe = state["me"], state["opponent"]
    if foe["active"] is None or me["pokemon"][me["active"]]["fainted"] or foe["pokemon"][foe["active"]]["fainted"]:
        sys.exit("nothing to advise: this state has no live matchup (the battle is over or a Pokémon is being chosen)")
    ours, theirs = me["pokemon"][me["active"]], foe["pokemon"][foe["active"]]
    print(f"at {state['t']:.1f}s: our {ours['name']} {ours['hp']}/{ours['hp_max']} hp, {ours['energy']} energy"
          f"  against  their {theirs['name']} about {theirs['hp']}/{theirs['hp_max']} hp, energy {theirs['energy_range'][0]}-{theirs['energy_range'][1]}")
    print(f"shields {me['shields']} v {foe['shields']}; Pokémon left {me['left']} v {foe['left']} ({foe['unseen']} of theirs unseen); "
          f"our switch ready in {me['switch_ready_in']:.0f}s")

    firsts, shields, results, stories = Counter(), Counter(), [], []
    for _ in range(args.games):
        pilot = Watched(make_pilot(rng.getrandbits(32)))
        battle = rebuild(gd, state, pool, rng, pilot, varied(rng, pool))
        start = battle.turn
        winner = battle.run()
        results.append(1.0 if winner == 0 else 0.5 if winner == DRAW else 0.0)
        firsts[pilot.first] += 1
        if pilot.shielded is not None:
            shields[pilot.shielded] += 1
        stories.append((results[-1], [((turn - start) * 0.5, side, text) for turn, side, text in battle.log]))

    mine = rebuild(gd, state, pool, rng, None, None).sides[0]
    action, votes = firsts.most_common(1)[0]
    print(f"\ndo now:         {name_action(action, mine.mon, mine.team)}  ({100 * votes / args.games:.0f}% of continuations start this way)")
    if shields:
        yes = shields[True] / sum(shields.values())
        print(f"next shield:    {'use it' if yes >= 0.5 else 'hold it'} on their next charged move ({100 * max(yes, 1 - yes):.0f}% of continuations)")
    share = sum(results) / len(results)
    print(f"chance to win:  {100 * share:.0f}% ± {100 * 1.96 * (share * (1 - share) / len(results)) ** 0.5:.0f}")
    likely = 1.0 if share >= 0.5 else 0.0
    story = next(events for result, events in stories if result == likely)
    print(f"\none typical way it goes from here ({'a win' if likely else 'a loss'}):")
    for seconds, side, text in story[:10]:
        print(f"  +{seconds:5.1f}s  {'we  ' if side == 0 else 'they'}  {text}")
    if len(story) > 10:
        print(f"  ... {len(story) - 10} more events")


if __name__ == "__main__":
    main()
