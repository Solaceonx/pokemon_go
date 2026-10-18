#!/usr/bin/env python3
"""Build an opening book for one team: the best first plan against each opposing lead (pogo.openings).

    python3 scripts/openings.py melmetal altaria jellicent [--leads 50] [--battles 200] [--check 3000] [--workers 3]

For each of the top --leads Pokémon as the opposing lead (their back two drawn from listed teams that contain it, or at
random from the top 50), every candidate plan plays the same --battles battles: stay in; swap at once to either
team-mate; stay 2, 4 or 8 fast moves then swap; throw our first charged move then swap. Both sides are the trained bot
with shifted habits (as pogo.lineup). A plan goes into the book only if it beats staying in by more than its margin
(paired battles). Then the check: the bot with the book against the bot without it on --check fresh battles against
leads drawn from the good-team list, the same battles for both. Writes data/openings/<team>.json.
Our Pokémon use the owner's builds where they have them.
"""
from __future__ import annotations

import argparse
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
from pogo.agents import varied_settings  # noqa: E402
from pogo.arena import low_priority, mean_and_margin  # noqa: E402
from pogo.battle import DRAW, Battle  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.learner import Learner, QNet  # noqa: E402
from pogo.openings import Booked, describe  # noqa: E402
from pogo.roster import builds  # noqa: E402

_s: dict = {}


def setup(team) -> None:
    low_priority()
    gd = GameData()
    pool = gd.meta(50)
    owned = builds(gd)
    listed = json.loads((ROOT / "data" / "teams.json").read_text())["teams"]
    _s.update(gd=gd, pool=pool, net=QNet.load(str(ROOT / "runs" / "general-decide" / "q.npz")),
              mine=[owned.get(sp) or gd.default(sp) for sp in team], listed=[e["team"] for e in listed],
              weights=[max(e["score"] - 0.4, 0.02) for e in listed])


def their_team(lead: str, rng: random.Random):
    s = _s
    gd = s["gd"]
    fitting = [t for t in s["listed"] if t[0] == lead or lead in t]
    dex = lambda sp: gd.species[sp]["dex"]  # noqa: E731
    if fitting and rng.random() < 0.7:
        t = rng.choice(fitting)
        back = [sp for sp in t if sp != lead][:2]
    else:
        others = [b.species_id for b in s["pool"] if dex(b.species_id) != dex(lead)]
        while True:
            back = rng.sample(others, 2)
            if dex(back[0]) != dex(back[1]):
                break
    return [gd.default(sp) for sp in [lead, *back]]


def player(rng):
    s = _s
    return Learner(q=s["net"], margin=rng.choice((0.02, 0.05)), **varied_settings(rng, s["pool"]))


def points(winner) -> float:
    return 1.0 if winner == 0 else 0.5 if winner == DRAW else 0.0


def job(task):
    """One opposing lead, one plan: `battles` battles; the battle numbers fix their team, habits and dice."""
    lead, plan_index, plan, battles, seed = task
    out = []
    for n in range(battles):
        rng = random.Random(seed * 1_000_003 + n)
        theirs = their_team(lead, rng)
        ours, foes = player(rng), player(rng)
        book = {lead: plan}
        winner = Battle(_s["mine"], theirs, Booked(ours, book), foes, seed=rng.getrandbits(32)).run()
        out.append(points(winner))
    return lead, plan_index, out


def check(task):
    """The bot with the book against the bot without it, on the same battles; leads from the good-team list."""
    book, start, count, seed = task
    s = _s
    with_book, without = [], []
    for n in range(start, start + count):
        rng = random.Random(seed * 7_919 + n)
        lead = rng.choices(s["listed"], s["weights"])[0][0]
        theirs = their_team(lead, rng)
        state = rng.getstate()
        for use, out in ((True, with_book), (False, without)):
            rng.setstate(state)
            ours, foes = player(rng), player(rng)
            pilot = Booked(ours, book) if use else ours
            out.append(points(Battle(s["mine"], theirs, pilot, foes, seed=rng.getrandbits(32)).run()))
    return with_book, without


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("team", nargs=3)
    parser.add_argument("--leads", type=int, default=50)
    parser.add_argument("--battles", type=int, default=200)
    parser.add_argument("--check", type=int, default=3000)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--seed", type=int, default=41)
    args = parser.parse_args()
    gd = GameData()
    names = [gd.species[sp]["speciesName"] for sp in args.team]
    plans = [{"swap": None}]
    for slot in (1, 2):
        plans += [{"swap": slot, "after_fast": n} for n in (0, 2, 4, 8)] + [{"swap": slot, "after_charged": True}]
    leads = [b.species_id for b in gd.meta(args.leads)]
    tasks = [(lead, k, p, args.battles, args.seed + i) for i, lead in enumerate(leads) for k, p in enumerate(plans)]
    results: dict = {}
    with multiprocessing.get_context("spawn").Pool(args.workers, initializer=setup, initargs=(args.team,)) as pool:
        for lead, k, out in pool.imap_unordered(job, tasks, chunksize=2):
            results[(lead, k)] = out
        book, rows = {}, []
        for lead in leads:
            stay = results[(lead, 0)]
            best_k, best_gain, best_margin = 0, 0.0, 0.0
            for k in range(1, len(plans)):
                gain, margin = mean_and_margin([a - b for a, b in zip(results[(lead, k)], stay)])
                if gain - margin > best_gain - best_margin and gain > margin:
                    best_k, best_gain, best_margin = k, gain, margin
            if best_k:
                book[lead] = plans[best_k]
            rows.append((lead, sum(stay) / len(stay), best_k, best_gain, best_margin))
        per = -(-args.check // args.workers)
        parts = pool.map(check, [(book, w * per, min(per, args.check - w * per), args.seed + 999) for w in range(args.workers)])
    with_book = [x for p in parts for x in p[0]]
    without = [x for p in parts for x in p[1]]
    print(f"opening book for {' / '.join(names)} ({names[0]} leading); {args.battles} battles per lead and plan")
    for lead, stay, k, gain, margin in sorted(rows, key=lambda r: r[1]):
        plan = describe(plans[k], names) if k else "stay in"
        extra = f"  ({100 * gain:+.0f} ± {100 * margin:.0f} on staying in)" if k else ""
        print(f"  {gd.species[lead]['speciesName']:28s} staying in wins {100 * stay:3.0f}% -> {plan}{extra}")
    m1, h1 = mean_and_margin(with_book)
    m0, h0 = mean_and_margin(without)
    d, dh = mean_and_margin([a - b for a, b in zip(with_book, without)])
    print(f"\ncheck on {len(with_book)} fresh battles (leads from the good-team list): with the book {100 * m1:.1f}% ± {100 * h1:.1f}, "
          f"without {100 * m0:.1f}% ± {100 * h0:.1f}, difference {100 * d:+.1f} ± {100 * dh:.1f} points")
    out = ROOT / "data" / "openings" / f"{'-'.join(args.team)}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"team": args.team, "battles_per_plan": args.battles,
                               "book": {lead: {**plan, "plan": describe(plan, names)} for lead, plan in book.items()},
                               "check": {"battles": len(with_book), "with": m1, "without": m0, "difference": [d, dh]}},
                              indent=1) + "\n")
    print(f"written: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
