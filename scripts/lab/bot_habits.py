#!/usr/bin/env python3
"""The same throw and shield measures as scripts/lab/creator_habits.py, for a player in the simulator.

    python -X utf8 scripts/lab/bot_habits.py [--player bot] [--opponent bot|crowd] [--battles 300] [--seed 1]

Plays --battles battles of the player (an engine_versus.py spec: "bot", "website", "website,temperature=0.02" ...)
against --opponent on the usual team draw (the good-team list and the top 50), logs every charged move with the
situation before it (thrower's energy and both costs, the defender's shields, health and Pokémon left, how much of
its health each move takes) and whether the defender shielded, and prints the tables creator_habits.py prints, so
the bot's rates and predictability sit next to the creators'. Rows from both sides are kept; "creator" in the
printout means the player, "opponent" its opponent. One process: keep --battles small for engines.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lab"))
import engine_versus as ev  # noqa: E402
from creator_habits import bait_bucket, hit_bucket, pct, predictability, repeats, shield_bucket  # noqa: E402
from pogo.agents import varied  # noqa: E402
from pogo.battle import CHARGED, CHARGED_TURNS, SWITCH, Battle, damage  # noqa: E402

SWITCHES: list = []  # (side, turn, turns of play since our own last charged move or None, battle)


class Logged:
    """Passes everything to `inner`, logging its throws, and its shield answers onto the opponent's last throw."""

    def __init__(self, inner, side: str, log: list, pending: dict, game: str):
        self.inner, self.side, self.log, self.pending, self.game = inner, side, log, pending, game
        self.faced = 0
        self.thrown_at = None  # the turn our last charged move ended
        for hook in ("saw_throw", "saw_shield"):
            if hasattr(inner, hook):
                setattr(self, hook, getattr(inner, hook))
        self.sees_move = getattr(inner, "sees_move", False)

    def act(self, view):
        action = self.inner.act(view)
        if action in SWITCH and view.turn > 0:
            since = None if self.thrown_at is None else view.turn - self.thrown_at
            SWITCHES.append((self.side, view.turn, since, self.game))
        if action in CHARGED:
            self.thrown_at = view.turn + 1 + CHARGED_TURNS
            me, foe = view.me.mon, view.foe
            moves = me.build.charged
            k = action - CHARGED[0]
            move = moves[k]
            costs = [m.energy for m in moves]
            hits = [damage(me, m, foe) for m in moves]
            other = [j for j in range(len(moves)) if j != k]
            row = {"game": self.game, "t": view.turn, "side": self.side, "thrower": me.build.species_id,
                   "defender": foe.build.species_id, "move": move.id, "cost": move.energy, "energy": me.energy,
                   "spare": me.energy - move.energy, "two_costs": len(set(costs)) > 1,
                   "both_ready": len(set(costs)) > 1 and me.energy >= max(costs),
                   "cheaper": bool(other) and move.energy < max(costs), "def_shields": view.foe_shields,
                   "thr_shields": view.me.shields, "shielded": False,
                   "def_hp_share": foe.hp / foe.build.hp, "hit": hits[k] / max(1, foe.hp), "ko": hits[k] >= foe.hp,
                   "alt_hit": max((hits[j] for j in other), default=None),
                   "def_left": view.foe_left, "thr_left": view.me.left(), "faced": None}
            if row["alt_hit"] is not None:
                row["alt_hit"] /= max(1, foe.hp)
            self.log.append(row)
            self.pending[self.side] = row
        return action

    def shield(self, view, energy, *move):
        answer = self.inner.shield(view, energy, *move) if move else self.inner.shield(view, energy)
        other = "opponent" if self.side == "creator" else "creator"
        row = self.pending.get(other)
        if row is not None:
            self.faced += 1
            row["shielded"] = bool(answer)
            row["faced"] = self.faced
            self.pending[other] = None
        return answer

    def replace(self, view):
        return self.inner.replace(view)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--player", default="bot")
    parser.add_argument("--opponent", default="bot", help="bot, crowd, or an engine_versus.py spec")
    parser.add_argument("--battles", type=int, default=300)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--save", help="write every throw to this JSON file")
    args = parser.parse_args()
    ev.setup()
    s = ev._state
    rows: list = []
    t0 = time.time()
    for n in range(args.battles):
        rng = random.Random(args.seed * 1_000_003 + n)
        a, b = s["draw"](rng), s["draw"](rng)
        pending: dict = {}
        me = Logged(ev.pilot(ev.parse(args.player), rng.getrandbits(32)), "creator", rows, pending, f"b{n}")
        if args.opponent == "crowd":
            foe_inner = varied(random.Random(rng.getrandbits(32)), s["pool"])
        else:
            foe_inner = ev.pilot(ev.parse(args.opponent), rng.getrandbits(32))
        foe = Logged(foe_inner, "opponent", rows, pending, f"b{n}")
        Battle(a, b, me, foe, seed=rng.getrandbits(32)).run()
    print(f"{args.battles} battles, {len(rows)} charged moves, {time.time() - t0:.0f} s; player {args.player!r} "
          f"against {args.opponent!r}")
    for name, side in (("the player", "opponent"), ("its opponent", "creator")):
        prompts = [r for r in rows if r["side"] == side and r["def_shields"] > 0 and r["faced"] is not None]
        not_last = [r for r in prompts if r["def_left"] > 1]
        print(f"\n  shields by {name}: {pct(sum(r['shielded'] for r in prompts), len(prompts))}; not the last Pokémon "
              f"{pct(sum(r['shielded'] for r in not_last), len(not_last))}")
        for label, cond in (("with 2 shields", lambda r: r["def_shields"] == 2),
                            ("with 1 shield", lambda r: r["def_shields"] == 1),
                            ("first charged move faced", lambda r: r["faced"] == 1),
                            ("hit < 30% of health", lambda r: hit_bucket(r) == "small"),
                            ("hit 30-60%", lambda r: hit_bucket(r) == "mid"),
                            ("hit 60%+, no knock-out", lambda r: hit_bucket(r) == "big"),
                            ("would knock out", lambda r: hit_bucket(r) == "ko"),
                            ("a bait (cheaper, dearer affordable)", lambda r: r["both_ready"] and r["cheaper"])):
            sub = [r for r in not_last if cond(r)]
            print(f"    {label:38} {pct(sum(r['shielded'] for r in sub), len(sub))}")
        print(f"    predictability: {predictability(not_last, shield_bucket, lambda r: r['shielded'])}")
        print(f"    repeated situations: {repeats(not_last, lambda r: r['shielded'])}")
    for name, side in (("the player", "creator"), ("its opponent", "opponent")):
        sub = [r for r in rows if r["side"] == side]
        spare = sorted(r["spare"] for r in sub)
        if not spare:
            continue
        q = lambda p: spare[min(len(spare) - 1, int(p * len(spare)))]  # noqa: E731
        print(f"\n  throws by {name}: {len(sub)}; spare energy median {q(0.5)}, quartiles {q(0.25)} to {q(0.75)}; "
              f"20+ spare {pct(sum(x >= 20 for x in spare), len(spare))}")
        bait = [r for r in sub if r["both_ready"] and r["def_shields"] > 0]
        print(f"    both moves affordable, defender has a shield: cheaper move "
              f"{pct(sum(r['cheaper'] for r in bait), len(bait))}")

        def hits(r):
            return (r["hit"], r["alt_hit"]) if r["cheaper"] else (r["alt_hit"], r["hit"])
        real = [r for r in bait if r["alt_hit"] is not None and hits(r)[1] >= 1.3 * hits(r)[0] and hits(r)[0] < 1]
        print(f"    of those where the dearer move hits 1.3x+ harder and the cheaper does not knock out: cheaper "
              f"{pct(sum(r['cheaper'] for r in real), len(real))}")
        print(f"    bait predictability: {predictability(bait, bait_bucket, lambda r: r['cheaper'])}")
    for name, side in (("the player", "creator"), ("its opponent", "opponent")):
        sw = [x for x in SWITCHES if x[0] == side]
        lead = len({x[3] for x in sw if x[1] <= 24})  # battles with a switch within 12 s of the start
        after = sum(1 for x in sw if x[2] is not None and 0 <= x[2] <= 4)
        print(f"\n  switches by {name} (after the lead, voluntary): {len(sw)} in {args.battles} battles; lead switched "
              f"in the first 12 s in {pct(lead, args.battles)} of battles; within 2 s of play after its own "
              f"charged move: {pct(after, len(sw))}")
    if args.save:
        Path(args.save).parent.mkdir(parents=True, exist_ok=True)
        with open(args.save, "w", encoding="utf-8", newline="\n") as f:
            json.dump(rows, f)
            f.write("\n")


if __name__ == "__main__":
    main()
