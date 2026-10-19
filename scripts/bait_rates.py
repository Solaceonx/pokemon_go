#!/usr/bin/env python3
"""How often players bait, and in which situations, measured from simulated games (the owner: "if I can afford
both, shouldn't it start on some predetermined rate based off of training?").

    python3 scripts/bait_rates.py [--battles 4000] [--workers 3] [--seed 7]

Battles on the mixed field (pogo.teamshape.mixed_field): half the trained bot against the crowd, half the bot
against itself. Every charged move thrown while the defender had a shield and the thrower could pay for both its
charged moves (and the two hit differently) is a bait chance: did it throw the softer one? Each is noted with the
situation: who threw, shields on both sides, health, whether the softer move would knock out, whether the harder
one would, the thrower's one-on-one outlook. Also the defender's call: shield or not, and whether that was the right
read (shield the harder move, let the softer one through).

The bot starts each battle believing a player baits half the time (expect_bait 0.5, worth about two throws) and
updates that from what this opponent does; this measures what the rate is in each situation, as a candidate
starting point. The rates are of players like ours (the bot and its crowd), not of people.
"""
from __future__ import annotations

import argparse
import collections
import json
import multiprocessing
import os
import random
import sys
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_v] = "1"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pogo.agents import duel, varied  # noqa: E402
from pogo.arena import low_priority, mean_and_margin  # noqa: E402
from pogo.battle import Battle, damage  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.learner import Learner, QNet  # noqa: E402
from pogo.teamshape import mixed_field  # noqa: E402

_s: dict = {}


class Watch:
    """Plays as `inner`; notes every charged move thrown at it that was a bait chance, and its own shield call."""

    def __init__(self, inner, rows: list, thrower: str):
        self.inner, self.rows, self.thrower, self.last_shield = inner, rows, thrower, None
        self.sees_move = getattr(inner, "sees_move", False)

    def act(self, view):
        return self.inner.act(view)

    def replace(self, view):
        return self.inner.replace(view)

    def shield(self, view, energy, *move):
        self.last_shield = bool(self.inner.shield(view, energy, *move))
        return self.last_shield

    def saw_shield(self, view, shielded):
        if hasattr(self.inner, "saw_shield"):
            self.inner.saw_shield(view, shielded)

    def saw_throw(self, view, move, foe_energy, could_shield):
        if hasattr(self.inner, "saw_throw"):
            self.inner.saw_throw(view, move, foe_energy, could_shield)
        me, mon, foe = view.me, view.me.mon, view.foe
        threats = [m for m in foe.build.charged if m.energy <= foe_energy]
        called, self.last_shield = self.last_shield, None
        if not could_shield or len(threats) < 2:
            return
        soft = min(threats, key=lambda m: damage(foe, m, mon))
        hard = max(threats, key=lambda m: damage(foe, m, mon))
        if soft is hard or damage(foe, soft, mon) == damage(foe, hard, mon):
            return
        hp = mon.hp  # the defender's health before this hit (the shield call came first, the hit comes after)
        self.rows.append({
            "thrower": self.thrower, "soft": move is soft, "called": called,
            "their_shields": me.shields, "thrower_shields": view.foe_shields,
            "thrower_hp": foe.hp / foe.build.hp, "defender_hp": hp / mon.build.hp,
            "soft_kills": damage(foe, soft, mon) >= hp, "hard_kills": damage(foe, hard, mon) >= hp,
            "thrower_ahead": duel(foe, mon, view.foe_shields, me.shields) > 0,
            "left": [view.foe_left, me.left()], "energy": foe_energy,
        })


def setup():
    low_priority()
    gd = GameData()
    pool, draw = mixed_field(gd)
    _s.update(pool=pool, draw=draw, net=QNet.load(str(ROOT / "runs" / "general-decide" / "q.npz")))


def job(task):
    start, count, seed = task
    s, rows = _s, []
    for n in range(start, start + count):
        rng = random.Random(seed * 1_000_003 + n)
        a, b = s["draw"](rng), s["draw"](rng)
        bot = Learner(q=s["net"], margin=0.02, seed=rng.getrandbits(32))
        other_is_bot = n % 2 == 1
        other = Learner(q=s["net"], margin=0.02, seed=rng.getrandbits(32)) if other_is_bot else varied(rng, s["pool"])
        # each Watch notes the throws made at it, so it is told who throws at it
        Battle(a, b, Watch(bot, rows, "bot" if other_is_bot else "crowd"), Watch(other, rows, "bot"),
               seed=rng.getrandbits(32)).run()
    return rows


def rate(rows, label):
    if not rows:
        return f"  {label:46s} none"
    m, h = mean_and_margin([float(r["soft"]) for r in rows])
    calls = [r for r in rows if r["called"] is not None]
    right = [float(r["called"] != r["soft"]) for r in calls]  # shield the harder move, let the softer through
    rm, rh = mean_and_margin(right) if right else (0, 0)
    return f"  {label:46s} softer move {100 * m:4.1f}% ± {100 * h:3.1f}   defender read it right {100 * rm:4.1f}% ± {100 * rh:3.1f}   ({len(rows)})"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--battles", type=int, default=4000)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    per = -(-args.battles // (4 * args.workers))
    tasks = [(k, min(per, args.battles - k), args.seed) for k in range(0, args.battles, per)]
    with multiprocessing.get_context("spawn").Pool(args.workers, initializer=setup) as pool:
        rows = [r for part in pool.map(job, tasks) for r in part]
    print(f"{args.battles} battles on the mixed field; {len(rows)} throws where the defender had a shield and the thrower "
          f"could pay for both moves\n")
    groups = [
        ("everyone", lambda r: True),
        ("the trained bot throwing", lambda r: r["thrower"] == "bot"),
        ("the crowd throwing", lambda r: r["thrower"] == "crowd"),
        ("defender has 2 shields", lambda r: r["their_shields"] == 2),
        ("defender has 1 shield", lambda r: r["their_shields"] == 1),
        ("thrower has no shields left", lambda r: r["thrower_shields"] == 0),
        ("thrower has shields left", lambda r: r["thrower_shields"] > 0),
        ("the softer move would knock out", lambda r: r["soft_kills"]),
        ("only the harder move would knock out", lambda r: r["hard_kills"] and not r["soft_kills"]),
        ("neither would knock out", lambda r: not r["hard_kills"]),
        ("thrower under half health", lambda r: r["thrower_hp"] < 0.5),
        ("thrower over half health", lambda r: r["thrower_hp"] >= 0.5),
        ("thrower winning the one-on-one", lambda r: r["thrower_ahead"]),
        ("thrower losing the one-on-one", lambda r: not r["thrower_ahead"]),
        ("last Pokémon throwing", lambda r: r["left"][0] == 1),
        ("defender on its last Pokémon", lambda r: r["left"][1] == 1),
    ]
    for label, keep in groups:
        print(rate([r for r in rows if keep(r)], label))
    by_combo = collections.defaultdict(list)
    for r in rows:
        if not r["hard_kills"]:
            by_combo[(r["their_shields"], r["thrower_ahead"], r["thrower_hp"] >= 0.5)].append(r)
    print("\nneither move would knock out, by defender's shields / thrower winning the one-on-one / thrower over half health:")
    for key in sorted(by_combo, reverse=True):
        print(rate(by_combo[key], f"{key[0]} shields, {'winning' if key[1] else 'losing'}, {'over' if key[2] else 'under'} half"))
    out = ROOT / "runs" / "bait_rates.json"
    out.write_text(json.dumps(rows) + "\n")
    print(f"\nrows: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
