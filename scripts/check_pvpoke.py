#!/usr/bin/env python3
"""Replay battles from PvPoke's simulator in this engine and compare them hit for hit.

    python3 scripts/check_pvpoke.py          summary and the first mismatches
    python3 scripts/check_pvpoke.py -v       every mismatch
    python3 scripts/check_pvpoke.py --forms  the form-changing Pokémon's battles (tests/data/pvpoke_forms.txt)

tests/data/pvpoke_duels.txt holds each side's exact sequence of moves and shield
choices from PvPoke. Feeding the same sequences to this engine should give the
same hits, the same damage and the same final health and energy.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pogo.battle  # noqa: E402
from pogo.battle import CHARGED, FAST, Battle, Mon  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "tests" / "data" / "pvpoke_duels.txt"
FORMS = DATA.parent / "pvpoke_forms.txt"


class Replay:
    """Plays a fixed list of actions and shield choices; fast moves once the list runs out."""

    def __init__(self, actions: str, shields: str):
        self.actions = [c for n, c in re.findall(r"(\d*)([fAB])", actions) for _ in range(int(n or 1))]
        self.shields = [c == "1" for c in shields]

    def act(self, view):
        if not self.actions:
            return FAST
        return {"f": FAST, "A": CHARGED[0], "B": CHARGED[1]}[self.actions.pop(0)]

    def shield(self, view, foe_energy):
        return self.shields.pop(0) if self.shields else False

    def replace(self, view):
        return view.me.bench()[0]


def runs(values: list[int]) -> str:
    out, i = [], 0
    while i < len(values):
        j = i
        while j < len(values) and values[j] == values[i]:
            j += 1
        out.append(f"{j - i}x{values[i]}" if j - i > 1 else str(values[i]))
        i = j
    return ".".join(out)


def load(path: Path = DATA):
    lines = [line for line in path.read_text().splitlines() if line and not line.startswith("#")]
    moves = json.loads(lines[0][2:])
    return sorted(moves), moves, lines[1:]


def check(gd: GameData, ids, moves, line: str):
    """Returns None if this engine reproduces the PvPoke battle, else a description of the difference."""
    head, seq_a, seq_b, sh_a, sh_b, final, hits_a, hits_b = line.split(":")
    pair, shields = head.split("/")
    a, b = (ids[int(k)] for k in pair.split(">"))
    mons = [Mon(gd.build(sid, moves[sid].split(","), allow_forms=True)) for sid in (a, b)]
    battle = Battle([mons[0]], [mons[1]], Replay(seq_a, sh_a), Replay(seq_b, sh_b), seed=0,
                    shields=(int(shields), int(shields)), record=True)
    toggles, pogo.battle.MORPEKO_TOGGLES = pogo.battle.MORPEKO_TOGGLES, False  # PvPoke never turns Morpeko back
    try:
        battle.run()
    except ValueError as err:
        return f"{a} v {b}, {shields} shields: {err}"
    finally:
        pogo.battle.MORPEKO_TOGGLES = toggles
    mine = ",".join(str(v) for m in mons for v in (max(m.hp, 0), m.energy))
    my_hits = [runs([d for side, _, d in battle.hits if side == k]) for k in (0, 1)]
    if (mine, my_hits[0], my_hits[1]) == (final, hits_a, hits_b):
        return None
    return (f"{a} v {b}, {shields} shields:\n    PvPoke  end {final}  hits {hits_a} | {hits_b}\n"
            f"    engine  end {mine}  hits {my_hits[0]} | {my_hits[1]}")


def main() -> int:
    gd = GameData()
    ids, moves, lines = load(FORMS if "--forms" in sys.argv else DATA)
    problems = [p for p in (check(gd, ids, moves, line) for line in lines) if p]
    print(f"{len(lines) - len(problems)} of {len(lines)} PvPoke battles reproduced exactly")
    for p in problems if "-v" in sys.argv else problems[:6]:
        print("  " + p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
