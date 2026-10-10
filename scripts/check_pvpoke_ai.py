#!/usr/bin/env python3
"""Acceptance test for a port of PvPoke's simulator AI.

    python3 scripts/check_pvpoke_ai.py                       tests pogo.pvpoke_ai:PvpokeAI
    python3 scripts/check_pvpoke_ai.py --agent pogo.agents:Masher   tests another player (as a baseline)
    python3 scripts/check_pvpoke_ai.py -v                    shows every battle that differs

tests/data/pvpoke_duels.txt records 108 one-on-one battles in which PvPoke's own AI
played both sides. A faithful port, playing both sides of the same matchups in this
engine, must choose the same moves in the same order, make the same shield choices,
and so end with the same health and energy.
"""
from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_pvpoke import load, runs  # noqa: E402
from pogo.battle import CHARGED, FAST, Battle, Mon  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402


class Recorder:
    """Passes everything through to a player and writes down what it chose."""

    def __init__(self, inner):
        self.inner, self.actions, self.shields = inner, [], []
        self.sees_move = getattr(inner, "sees_move", False)

    def act(self, view):
        action = self.inner.act(view)
        self.actions.append("f" if action == FAST else "AB"[action - CHARGED[0]] if action in CHARGED else "?")
        return action

    def shield(self, view, foe_energy, move=None):
        answer = bool(self.inner.shield(view, foe_energy, move) if self.sees_move else self.inner.shield(view, foe_energy))
        self.shields.append("1" if answer else "0")
        return answer

    def replace(self, view):
        return self.inner.replace(view)


def compact(actions: list[str]) -> str:
    out, i = [], 0
    while i < len(actions):
        j = i
        while j < len(actions) and actions[j] == actions[i]:
            j += 1
        out.append((str(j - i) if j - i > 1 else "") + actions[i])
        i = j
    return "".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--agent", default="pogo.pvpoke_ai:PvpokeAI", help="module:Class of the player to test")
    parser.add_argument("-v", action="store_true", help="show every battle that differs")
    args = parser.parse_args()
    module, name = args.agent.split(":")
    make = getattr(importlib.import_module(module), name)

    gd = GameData()
    ids, moves, lines = load()
    exact = same_winner = 0
    shown = 0
    for line in lines:
        head, seq_a, seq_b, sh_a, sh_b, final, hits_a, hits_b = line.split(":")
        pair, shields = head.split("/")
        a, b = (ids[int(k)] for k in pair.split(">"))
        mons = [Mon(gd.build(sid, moves[sid].split(","))) for sid in (a, b)]
        players = Recorder(make()), Recorder(make())
        battle = Battle([mons[0]], [mons[1]], *players, seed=0, shields=(int(shields), int(shields)), record=True)
        try:
            battle.run()
            error = None
        except Exception as err:  # a port that crashes should still get a full report
            error = f"{type(err).__name__}: {err}"
        mine = ",".join(str(v) for m in mons for v in (max(m.hp, 0), m.energy))
        got = [compact(p.actions) for p in players] + ["".join(p.shields) for p in players]
        my_hits = [runs([d for side, _, d in battle.hits if side == k]) for k in (0, 1)]
        want_winner = final.split(",")[0] == "0"
        same_winner += error is None and (mons[0].hp <= 0) == want_winner
        if error is None and (mine, my_hits[0], my_hits[1]) == (final, hits_a, hits_b):
            exact += 1
            continue
        if args.v or shown < 5:
            shown += 1
            print(f"{a} v {b}, {shields} shields each" + (f"  CRASHED: {error}" if error else ""))
            print(f"    PvPoke  A {seq_a:28s} B {seq_b:28s} shields {sh_a or '-'}/{sh_b or '-'}  end {final}")
            print(f"    yours   A {got[0]:28s} B {got[1]:28s} shields {got[2] or '-'}/{got[3] or '-'}  end {mine}")
    print(f"\n{exact} of {len(lines)} battles identical to PvPoke; same winner in {same_winner}")
    print("actions: f = fast move, A/B = first/second charged move, with a leading repeat count; a trailing f that "
          "never lands can differ harmlessly")
    return 0 if exact == len(lines) else 1


if __name__ == "__main__":
    sys.exit(main())
