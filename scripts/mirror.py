#!/usr/bin/env python3
"""One Pokémon against one, solved as a game: every plan against every plan, then the best mix for each side
(the owner: "try a 1 on 1 Melmetal vs Melmetal game and see how that works").

    python3 scripts/mirror.py [--mine melmetal] [--theirs melmetal] [--shields 2-2 2-1 1-2 1-1] [--swap] [--seed 0]

A plan is what to throw with each of the first three charged moves while the other side still has a shield: the
cheaper move as soon as it is affordable ("C", the bait), or wait for the dearer one ("D"); and how to answer each
of the first two charged moves thrown at it while it has a shield: shield ("S"), take it ("N"), or shield only if the
dearer move was affordable ("?", since the move is not known until it lands, only the thrower's energy). Beyond that
every plan throws the dearer move when it can, takes a knockout with the cheapest move that does it, and shields
only a hit that would knock it out. Fast moves otherwise. 8 throw plans x 9 shield plans = 72 plans a side, every
pair played once (the battle is deterministic but for who throws first in a tie of attack, which a stronger attack
wins). The table of our win chances is solved for both sides' best mixes (pogo.sixes.solve, regret matching).

Our Pokémon uses the owner's build where there is one; theirs PvPoke's default (--swap: the other way round).
Shields are given as ours-theirs. Also, as a yardstick, the trained bot
against itself on the same pair, 400 battles.
"""
from __future__ import annotations

import argparse
import itertools
import random
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pogo.arena import mean_and_margin  # noqa: E402
from pogo.battle import CHARGED, DRAW, FAST, Battle, damage  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.learner import Learner, QNet  # noqa: E402
from pogo.roster import builds  # noqa: E402
from pogo.sixes import gap, solve  # noqa: E402

THROWS = ["".join(p) for p in itertools.product("CD", repeat=3)]
SHIELDS = ["".join(p) for p in itertools.product("SN?", repeat=2)]
PLANS = [(t, s) for t in THROWS for s in SHIELDS]


class Plan:
    def __init__(self, throws: str, shields: str):
        self.throws, self.shields, self.thrown, self.faced = throws, shields, 0, 0

    def act(self, view):
        mon, foe = view.me.mon, view.foe
        moves = mon.build.charged
        cheap = min(range(len(moves)), key=lambda k: moves[k].energy)
        dear = max(range(len(moves)), key=lambda k: moves[k].energy)
        ready = [k for k in range(len(moves)) if mon.energy >= moves[k].energy]
        if view.foe_shields == 0:
            lethal = [k for k in ready if damage(mon, moves[k], foe) >= foe.hp]
            if lethal:
                return self._throw(min(lethal, key=lambda k: moves[k].energy))
            return self._throw(dear) if dear in ready else FAST
        want = self.throws[self.thrown] if self.thrown < len(self.throws) else "D"
        k = cheap if want == "C" else dear
        return self._throw(k) if k in ready else FAST

    def _throw(self, k):
        self.thrown += 1
        return CHARGED[k]

    def shield(self, view, energy, *move):
        mon, foe = view.me.mon, view.foe
        j, self.faced = self.faced, self.faced + 1
        rule = self.shields[j] if j < len(self.shields) else "K"
        dear = max(foe.build.charged, key=lambda m: m.energy)
        if rule == "S":
            return True
        if rule == "N":
            return False
        if rule == "?":
            return energy >= dear.energy
        return any(damage(foe, m, mon) >= mon.hp for m in foe.build.charged if m.energy <= energy)

    def replace(self, view):
        return view.me.bench()[0]

    def clone(self):
        twin = Plan(self.throws, self.shields)
        twin.thrown, twin.faced = self.thrown, self.faced
        return twin


def points(winner):
    return 1.0 if winner == 0 else 0.5 if winner == DRAW else 0.0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mine", default="melmetal")
    parser.add_argument("--theirs", default="melmetal")
    parser.add_argument("--shields", nargs="+", default=["2-2", "2-1", "1-2", "1-1"])
    parser.add_argument("--swap", action="store_true", help="the owner's build on their side, PvPoke's default on ours")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    gd = GameData()
    mine = builds(gd).get(args.mine) or gd.default(args.mine)
    theirs = gd.default(args.theirs)
    if args.swap:
        mine, theirs = gd.default(args.mine), builds(gd).get(args.theirs) or gd.default(args.theirs)
    net = QNet.load(str(ROOT / "runs" / "general-decide" / "q.npz"))
    print(f"ours: {mine.name} (attack {mine.atk:.1f}, defence {mine.defense:.1f}, {mine.hp} HP); theirs: {theirs.name} "
          f"(attack {theirs.atk:.1f}, defence {theirs.defense:.1f}, {theirs.hp} HP); moves {mine.fast.name}, "
          + ", ".join(f"{m.name} {m.energy}" for m in mine.charged)
          + f". Ties in throwing first go to the stronger attack: {'ours' if mine.atk > theirs.atk else 'theirs'}.")
    for pair in args.shields:
        s = tuple(int(x) for x in pair.split("-"))
        table = np.zeros((len(PLANS), len(PLANS)))
        for i, (t1, s1) in enumerate(PLANS):
            for j, (t2, s2) in enumerate(PLANS):
                table[i, j] = points(Battle([mine], [theirs], Plan(t1, s1), Plan(t2, s2), shields=s, seed=args.seed).run())
        value, p, q = solve(table)
        rng = random.Random(args.seed)
        bot = [points(Battle([mine], [theirs], Learner(q=net, margin=0.02, seed=rng.getrandbits(30)),
                             Learner(q=net, margin=0.02, seed=rng.getrandbits(30)), shields=s, seed=rng.getrandbits(32)).run())
               for _ in range(400)]
        bm, bh = mean_and_margin(bot)
        print(f"\nshields {s[0]} (ours) - {s[1]} (theirs): with best play we win {100 * value:.1f}% (gap {gap(table, p, q):.3f}); "
              f"the trained bot against itself: ours wins {100 * bm:.0f}% ± {100 * bh:.0f}")
        for label, mix in (("our best mix", p), ("their best mix", q)):
            parts = sorted(((w, PLANS[k]) for k, w in enumerate(mix) if w > 0.02), reverse=True)
            print(f"  {label}: " + "; ".join(f"{100 * w:.0f}% throw {t} / shield {sh}" for w, (t, sh) in parts))
        # in words: how often the first throw is the bait, and how the first throw faced is answered
        for label, mix in (("ours", p), ("theirs", q)):
            first_bait = sum(w for k, w in enumerate(mix) if PLANS[k][0][0] == "C")
            answer = {c: sum(w for k, w in enumerate(mix) if PLANS[k][1][0] == c) for c in "SN?"}
            print(f"  {label}: first throw is the bait {100 * first_bait:.0f}%; first throw faced: shield {100 * answer['S']:.0f}%, "
                  f"take it {100 * answer['N']:.0f}%, shield only if the dearer move was affordable {100 * answer['?']:.0f}%")
        best = sorted(range(len(PLANS)), key=lambda k: -(table[k] @ q))[:3]
        print("  our best single plans against their mix: " + "; ".join(
            f"throw {PLANS[k][0]} / shield {PLANS[k][1]} {100 * (table[k] @ q):.0f}%" for k in best))


if __name__ == "__main__":
    main()
