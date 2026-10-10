#!/usr/bin/env python3
"""Compare how two learned players play when they face each other.

    python3 scripts/habits.py runs/exploiter-2/q.npz runs/general-decide/q.npz

For each player: how it throws charged moves, when it shields, how it switches, and how
much energy it leaves on Pokémon that faint. Then one battle the first player won.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pogo.agents import fasts_to_wait  # noqa: E402
from pogo.battle import CHARGED, SWITCH, Battle, damage  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.learner import Learner, QNet  # noqa: E402


class Spy:
    """Passes everything through to a player and notes the circumstances of each choice."""

    def __init__(self, inner):
        self.inner, self.throws, self.shields, self.switches = inner, [], [], []

    def act(self, view):
        action = self.inner.act(view)
        mon, foe = view.me.mon, view.foe
        if action in CHARGED:
            moves = mon.build.charged
            move = moves[action - CHARGED[0]]
            dear = max(m.energy for m in moves)
            two_prices = len({m.energy for m in moves}) > 1
            self.throws.append(dict(
                energy=mon.energy, both_ready=mon.energy >= dear, dearer=two_prices and move.energy == dear,
                two_prices=two_prices, into_shields=view.foe_shields > 0,
                share=min(damage(mon, move, foe) / max(foe.hp, 1), 1.0),
                timed=fasts_to_wait(mon.build.fast.turns, foe.build.fast.turns, view.foe_busy) == 0))
        elif action in SWITCH:
            self.switches.append(view.turn)
        return action

    def shield(self, view, foe_energy):
        answer = bool(self.inner.shield(view, foe_energy))
        mon, foe = view.me.mon, view.foe
        threat = max((damage(foe, m, mon) for m in foe.build.charged if m.energy <= foe_energy), default=0)
        if view.me.left() > 1:  # with one Pokémon left, shielding is automatic
            self.shields.append((threat / mon.build.hp, answer))
        return answer

    def replace(self, view):
        return self.inner.replace(view)

    def saw_throw(self, *args):
        self.inner.saw_throw(*args)

    def saw_shield(self, *args):
        self.inner.saw_shield(*args)


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    gd = GameData()
    pool = gd.meta(50)
    models = [QNet.load(path) for path in sys.argv[1:]]
    rng = random.Random(0)
    battles = 1500
    notes = [dict(throws=[], shields=[], switches=0, early=0, stranded=0.0, wins=0.0) for _ in models]
    shown = None
    for _ in range(battles):
        spies = [Spy(Learner(q=q, margin=0.02)) for q in models]
        flip = rng.random() < 0.5
        order = spies[::-1] if flip else spies
        battle = Battle(rng.sample(pool, 3), rng.sample(pool, 3), *order, seed=rng.getrandbits(32), record=True)
        winner = battle.run()
        for k, spy in enumerate(spies):
            side = battle.sides[(1 - k) if flip else k]
            n = notes[k]
            n["throws"] += spy.throws
            n["shields"] += spy.shields
            n["switches"] += len(spy.switches)
            n["early"] += any(t < 20 for t in spy.switches)
            n["stranded"] += sum(m.energy for m in side.team if m.hp <= 0)
            n["wins"] += winner == ((1 - k) if flip else k)
        if shown is None and winner == (1 if flip else 0) and len(battle.log) < 26:
            shown = (battle, flip)

    def rate(items, test, among=lambda x: True):
        chosen = [x for x in items if among(x)]
        return 100 * sum(test(x) for x in chosen) / max(len(chosen), 1)

    names = [Path(p).parent.name for p in sys.argv[1:]]
    print(f"{battles} battles between them, random teams" + " " * 22 + "".join(f"{n:>18s}" for n in names))
    rows = [
        ("wins", lambda n: f"{100 * n['wins'] / battles:.1f}%"),
        ("charged moves thrown per battle", lambda n: f"{len(n['throws']) / battles:.1f}"),
        ("  energy held when throwing (mean)", lambda n: f"{sum(t['energy'] for t in n['throws']) / len(n['throws']):.0f}"),
        ("  thrown with energy for either move", lambda n: f"{rate(n['throws'], lambda t: t['both_ready'], lambda t: t['two_prices']):.0f}%"),
        ("  the dearer move, of those", lambda n: f"{rate(n['throws'], lambda t: t['dearer'], lambda t: t['two_prices'] and t['both_ready']):.0f}%"),
        ("  the dearer move, into shields", lambda n: f"{rate(n['throws'], lambda t: t['dearer'], lambda t: t['two_prices'] and t['into_shields']):.0f}%"),
        ("  thrown on the best-timed turn", lambda n: f"{rate(n['throws'], lambda t: t['timed']):.0f}%"),
        ("  share of target's health it would take", lambda n: f"{100 * sum(t['share'] for t in n['throws']) / len(n['throws']):.0f}%"),
        ("shields a hit worth over half its health", lambda n: f"{rate(n['shields'], lambda s: s[1], lambda s: s[0] >= 0.5):.0f}%"),
        ("shields a hit worth a quarter to a half", lambda n: f"{rate(n['shields'], lambda s: s[1], lambda s: 0.25 <= s[0] < 0.5):.0f}%"),
        ("shields a hit worth under a quarter", lambda n: f"{rate(n['shields'], lambda s: s[1], lambda s: s[0] < 0.25):.0f}%"),
        ("switches per battle", lambda n: f"{n['switches'] / battles:.2f}"),
        ("battles with a switch in the first 10 s", lambda n: f"{100 * n['early'] / battles:.0f}%"),
        ("energy left on its fainted Pokémon, per battle", lambda n: f"{n['stranded'] / battles:.0f}"),
    ]
    for label, cell in rows:
        print(f"  {label:48s}" + "".join(f"{cell(n):>18s}" for n in notes))

    if shown:
        battle, flip = shown
        who = (names[1], names[0]) if flip else (names[0], names[1])
        print(f"\none battle won by {names[0]}:")
        for i, side in enumerate(battle.sides):
            print(f"  {who[i]}: " + ", ".join(m.build.name for m in side.team))
        for turn, side, text in battle.log:
            print(f"  {turn * 0.5:6.1f}s  {who[side]:16s} {text}")


if __name__ == "__main__":
    main()
