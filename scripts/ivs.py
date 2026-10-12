#!/usr/bin/env python3
"""How much do IVs matter, and how far can an opponent's IVs be worked out?

    python3 scripts/ivs.py melmetal jellicent altaria

For the three Pokémon named: their best, default, most-attack and worst IV spreads; how
each spread fares one-on-one against the top 50; how the team fares three-on-three with
each spread, piloted by the best bot on the same battles; where fast moves gain or lose a
point of damage (breakpoints); and how many IV combinations fit what an opponent shows.
"""
from __future__ import annotations

import os
import random
import sys
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pogo.agents import Planner, varied  # noqa: E402
from pogo.arena import field_results, mean_and_margin  # noqa: E402
from pogo.battle import Battle, Mon, damage  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.learner import Learner, QNet  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def one_on_one(a, b, shields: int) -> bool:
    x, y = Mon(a), Mon(b)
    winner = Battle([x], [y], Planner(switches=False, seed=0), Planner(switches=False, seed=0), seed=0, shields=(shields, shields)).run()
    return winner == 0


def main() -> None:
    names = sys.argv[1:4]
    if len(names) != 3:
        sys.exit(__doc__)
    gd = GameData()
    pool = gd.meta(50)
    team = [gd.default(s) for s in names]
    rng = random.Random(0)

    kinds = {}
    print("IV spreads (attack/defence/HP IVs, level, stats, rank by stat product out of 4,096)")
    for b in team:
        sp = gd.spreads(b.species_id)
        chosen = {"best (rank 1)": sp[0], "default": next(e for e in sp if e["ivs"] == b.ivs),
                  "15/15/15": next(e for e in sp if e["ivs"] == (15, 15, 15)),
                  "most attack": max(sp, key=lambda e: e["atk"]), "worst": sp[-1]}
        kinds[b.species_id] = chosen
        print(f"  {b.name}")
        for label, e in chosen.items():
            print(f"    {label:14s} {'/'.join(map(str, e['ivs'])):>8s}  level {e['level']:<5g} attack {e['atk']:6.1f}  defence {e['def']:6.1f}  HP {e['hp']:3d}  "
                  f"rank {e['rank']:4d}  product {100 * e['product'] / sp[0]['product']:.1f}% of best")
    labels = list(next(iter(kinds.values())))

    print("\none-on-one against the top 50 (default IVs): wins out of 147 (49 opponents at 0, 1 and 2 shields each)")
    print(f"  {'':12s}" + "".join(f"{label:>16s}" for label in labels))
    for b in team:
        others = [o for o in pool if o.species_id != b.species_id]
        results = {}
        for label in labels:
            mine = gd.with_ivs(b, kinds[b.species_id][label]["ivs"])
            results[label] = [one_on_one(mine, o, s) for o in others for s in (0, 1, 2)]
        base = results["default"]
        cells = [f"{sum(r):3d} ({sum(x != y for x, y in zip(r, base))} differ)" for r in results.values()]
        print(f"  {b.name:12s}" + "".join(f"{c:>16s}" for c in cells))

    q = QNet.load(ROOT / "runs" / "general-decide" / "q.npz")
    pilot = lambda: Learner(q=q, margin=0.02)  # noqa: E731
    crowd = lambda r: varied(r, pool)  # noqa: E731
    battles = 3000
    print(f"\nthree-on-three, the whole team on one kind of spread, best bot piloting, {battles} battles (same battles for every row)")
    rows = {label: field_results([gd.with_ivs(b, kinds[b.species_id][label]["ivs"]) for b in team], pool, pilot, crowd, battles, 31)
            for label in labels}
    base = rows["default"]
    for label, pts in rows.items():
        mean, margin = mean_and_margin(pts)
        gain, spread = mean_and_margin([a - b for a, b in zip(pts, base)])
        print(f"  {label:14s} {100 * mean:.1f}% ± {100 * margin:.1f}" + ("" if label == "default" else f"   {100 * gain:+.1f} ± {100 * spread:.1f} points against default"))
    draws = []
    for k in range(10):
        random_team = [gd.with_ivs(b, tuple(rng.randrange(16) for _ in range(3))) for b in team]
        pts = field_results(random_team, pool, pilot, crowd, 600, 31)
        draws += [a - b for a, b in zip(pts, base[:600])]
    gain, spread = mean_and_margin(draws)
    print(f"  {'random IVs':14s} {100 * gain:+.1f} ± {100 * spread:.1f} points against default (ten random teams, 600 battles each)")

    print("\nbreakpoints: against the 49 other top-50 Pokémon, how many take a different amount from our fast move, and hit us for a different amount with theirs")
    for b in team:
        others = [o for o in pool if o.species_id != b.species_id]
        base_mon = Mon(b)
        for label in ("best (rank 1)", "most attack"):
            alt = Mon(gd.with_ivs(b, kinds[b.species_id][label]["ivs"]))
            more = sum(damage(alt, alt.build.fast, Mon(o)) > damage(base_mon, b.fast, Mon(o)) for o in others)
            less = sum(damage(alt, alt.build.fast, Mon(o)) < damage(base_mon, b.fast, Mon(o)) for o in others)
            hurt = sum(damage(Mon(o), o.fast, alt) > damage(Mon(o), o.fast, base_mon) for o in others)
            safer = sum(damage(Mon(o), o.fast, alt) < damage(Mon(o), o.fast, base_mon) for o in others)
            print(f"  {b.name:10s} {label:14s} vs default: our fast move does +1 to {more}, -1 to {less}; their fast move does +1 to us from {hurt}, -1 from {safer}")

    print("\nworking out an opponent's IVs: combinations that fit, as clues are added (opponent has default IVs; our Pokémon is the first one named)")
    ours = Mon(team[0])
    for sid in ("azumarill", "altaria", "tinkaton", "corviknight", "annihilape_shadow"):
        true = gd.default(sid)
        fits = [(level / 2, (a, d, s)) for a in range(16) for d in range(16) for s in range(16)
                for level in range(2, 103) if gd.cp_at(sid, level / 2, (a, d, s)) == true.cp]
        builds = [gd.build(sid, [true.fast.id, *(m.id for m in true.charged)], level=lv, ivs=ivs) for lv, ivs in fits]
        hit = damage(Mon(true), true.fast, ours)
        by_hit = [b for b in builds if damage(Mon(b), b.fast, ours) == hit]
        share = damage(ours, ours.build.fast, Mon(true)) / true.hp
        by_bar = [b for b in by_hit if abs(damage(ours, ours.build.fast, Mon(b)) / b.hp - share) < 0.5 / 138]
        first = (true.cmp_atk > ours.build.cmp_atk)
        by_cmp = [b for b in by_bar if (b.cmp_atk > ours.build.cmp_atk) == first]
        atk = lambda bs: f"attack {min(b.cmp_atk for b in bs):.1f}-{max(b.cmp_atk for b in bs):.1f}"  # noqa: E731
        print(f"  {true.name:20s} CP {true.cp}: {len(builds):5d} fit the CP ({atk(builds)}) -> {len(by_hit):5d} also fit their fast move's damage on us "
              f"-> {len(by_bar):5d} also fit our fast move's share of their bar -> {len(by_cmp):5d} also fit who throws first ({atk(by_cmp)})")


if __name__ == "__main__":
    main()
