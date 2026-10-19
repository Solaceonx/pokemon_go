#!/usr/bin/env python3
"""Build a book of answers for one team: what to do when each opposing Pokémon comes in against each of ours
(pogo.openings.Answers; the opening book is the special case of their lead against ours).

    python3 scripts/answers.py melmetal altaria jellicent [--field mixed] [--battles 500] [--check 4000] [--workers 3]

For each of our Pokémon and each opposing Pokémon (the 30 most used in PvPoke's data and the usual top 50), --battles
battles against teams holding it (drawn from --field) are played by the bot as it is; those in which it came in while
ours was in are played again with each plan from that moment: swap to either team-mate at once or after 1, 2 or 4
fast moves, or throw our first charged move and then swap. The battles are the same up to that moment, so the
differences are the plan's alone. A plan goes into the book if it beats the bot's own play by more than its margin.
Then the check, on fresh battles on the mixed field and on the usual one (the owner's rule against overfitting): the
bot with this book, with the opening book alone (data/openings/<team>-mixed.json, if there), and with neither.
Writes data/openings/<team>-answers.json.
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
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
import openings as op  # noqa: E402
from pogo.arena import mean_and_margin  # noqa: E402
from pogo.battle import Battle  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.openings import Answers, Booked  # noqa: E402


def setup(team, field):
    op.setup(team, field)
    pool = op._s["pool"]
    op._s["holding_draw"] = op._s.get("field_draw") or (lambda rng: rng.sample(pool, 3))
    op._s["field"] = field


def holding(species: str, rng: random.Random):
    """A team from the field that holds `species`, in its drawn order (it need not lead)."""
    s = op._s
    for _ in range(5000):
        team = s["holding_draw"](rng)
        if any(b.species_id == species for b in team):
            return team
    gd = s["gd"]
    others = [b for b in s["pool"] if gd.species[b.species_id]["dex"] != gd.species[species]["dex"]]
    return [gd.default(species), *rng.sample(others, 2)]


def describe(plan: dict) -> str:
    if plan.get("to") is None:
        return "the bot decides"
    to = op._s["gd"].species[plan["to"]]["speciesName"] if op._s else plan["to"]
    if plan.get("after_charged"):
        return f"throw first, then swap to {to}"
    n = plan.get("after_fast", 0)
    return f"swap to {to} at once" if n == 0 else f"{n} fast move{'s' if n > 1 else ''}, then swap to {to}"


def job(task):
    """One of ours, one of theirs: the bot's own score and each plan's, on the battles where theirs came in."""
    ours_sp, theirs_sp, plans, battles, seed = task
    s = op._s
    rows = []
    for n in range(battles):
        rng = random.Random(seed * 1_000_003 + n)
        theirs = holding(theirs_sp, rng)
        state = rng.getstate()
        ours, foes = op.player(rng), op.player(rng)
        probe = Answers(ours, {ours_sp: {theirs_sp: {}}})
        dice = rng.getrandbits(32)
        base = op.points(Battle(s["mine"], theirs, probe, foes, seed=dice).run())
        if not probe.fired:
            continue
        row = [base]
        for plan in plans:
            rng.setstate(state)
            ours, foes = op.player(rng), op.player(rng)
            row.append(op.points(Battle(s["mine"], theirs, Answers(ours, {ours_sp: {theirs_sp: plan}}), foes,
                                        seed=rng.getrandbits(32)).run()))
        rows.append(row)
    return ours_sp, theirs_sp, rows


def check(task):
    """Fresh battles: the bot with the answers book, with the opening book alone, and with neither."""
    answers, opening, start, count, seed = task
    s = op._s
    out = ([], [], [])
    for n in range(start, start + count):
        rng = random.Random(seed * 7_919 + n)
        theirs = s["field_draw"](rng) if s["field"] != "standard" else op.their_team(
            rng.choices(s["listed"], s["weights"])[0][0], rng)
        state = rng.getstate()
        for k, wrap in enumerate((lambda p: Answers(p, answers), lambda p: Booked(p, opening), lambda p: p)):
            rng.setstate(state)
            ours, foes = op.player(rng), op.player(rng)
            out[k].append(op.points(Battle(s["mine"], theirs, wrap(ours), foes, seed=rng.getrandbits(32)).run()))
    return out


def run_check(team, field, answers, opening, battles, workers, seed):
    per = -(-battles // workers)
    with multiprocessing.get_context("spawn").Pool(workers, initializer=setup, initargs=(team, field)) as pool:
        parts = pool.map(check, [(answers, opening, w * per, min(per, battles - w * per), seed) for w in range(workers)])
    a, b, c = ([x for p in parts for x in p[k]] for k in range(3))
    (d1, h1), (d2, h2), (d3, h3) = (mean_and_margin([x - y for x, y in zip(u, v)]) for u, v in ((a, c), (b, c), (a, b)))
    m, h = mean_and_margin(c)
    return (f"  {field} field, {len(a)} fresh battles: neither {100 * m:.1f}% ± {100 * h:.1f}; answers book "
            f"{100 * d1:+.1f} ± {100 * h1:.1f} points, opening book alone {100 * d2:+.1f} ± {100 * h2:.1f}, "
            f"answers on the opening book {100 * d3:+.1f} ± {100 * h3:.1f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("team", nargs=3)
    parser.add_argument("--field", choices=("mixed", "pvpoke", "standard"), default="mixed")
    parser.add_argument("--theirs", type=int, default=30, help="most-used Pokémon in PvPoke's data (plus the usual top 50)")
    parser.add_argument("--battles", type=int, default=500)
    parser.add_argument("--check", type=int, default=4000)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--seed", type=int, default=43)
    args = parser.parse_args()
    gd = GameData()
    from pogo.teamshape import pvpoke_field, pvpoke_usage
    usage, field = pvpoke_usage(), {b.species_id for b in pvpoke_field(gd)[0]}
    theirs = [sp for sp in sorted(usage, key=lambda x: -usage[x]) if sp in field][:args.theirs]
    theirs += [b.species_id for b in gd.meta(50) if b.species_id not in theirs]
    tasks = []
    for i, ours_sp in enumerate(args.team):
        mates = [sp for sp in args.team if sp != ours_sp]
        plans = [{"to": to, "after_fast": k} for to in mates for k in (0, 1, 2, 4)] + [{"to": to, "after_charged": True} for to in mates]
        for j, theirs_sp in enumerate(theirs):
            tasks.append((ours_sp, theirs_sp, plans, args.battles, args.seed + 1000 * i + j))
    book, lines = {}, []
    with multiprocessing.get_context("spawn").Pool(args.workers, initializer=setup, initargs=(args.team, args.field)) as pool:
        for ours_sp, theirs_sp, rows in pool.imap_unordered(job, tasks, chunksize=1):
            plans = next(t[2] for t in tasks if t[0] == ours_sp and t[1] == theirs_sp)
            if len(rows) < 30:
                lines.append((ours_sp, theirs_sp, len(rows), None, 0.0, 0.0, None))
                continue
            base = [r[0] for r in rows]
            best = (None, 0.0, 0.0)
            for k, plan in enumerate(plans):
                gain, margin = mean_and_margin([r[k + 1] - r[0] for r in rows])
                if gain > margin and gain - margin > best[1] - best[2]:
                    best = (plan, gain, margin)
            if best[0]:
                book.setdefault(ours_sp, {})[theirs_sp] = best[0]
            lines.append((ours_sp, theirs_sp, len(rows), best[0], best[1], best[2], sum(base) / len(base)))
    name = lambda sp: gd.species[sp]["speciesName"]  # noqa: E731
    op._s["gd"] = gd
    print(f"answers for {' / '.join(map(name, args.team))} on the {args.field} field; up to {args.battles} battles per pair, "
          f"counted where theirs came in while ours was in")
    for ours_sp in args.team:
        print(f"\nwhen {name(ours_sp)} is in and this comes in:")
        for o, t, n, plan, gain, margin, score in sorted((x for x in lines if x[0] == ours_sp), key=lambda x: x[1]):
            if score is None:
                print(f"  {name(t):26s} came in {n} times: too few to judge")
                continue
            what = describe(plan) if plan else "the bot decides"
            extra = f"  ({100 * gain:+.0f} ± {100 * margin:.0f} on the bot's own play)" if plan else ""
            print(f"  {name(t):26s} {n:4d} times, bot wins {100 * score:3.0f}% -> {what}{extra}")
    opening_path = ROOT / "data" / "openings" / f"{'-'.join(args.team)}-mixed.json"
    opening = {}
    if opening_path.exists():
        opening = {k: {x: y for x, y in v.items() if x != "plan"} for k, v in json.loads(opening_path.read_text())["book"].items()}
    print("\ncheck (the bot with each book against the bot with none, the same fresh battles):")
    checks = [run_check(args.team, f, book, opening, args.check, args.workers, args.seed + 999) for f in ("mixed", "standard")]
    print("\n".join(checks))
    out = ROOT / "data" / "openings" / f"{'-'.join(args.team)}-answers.json"
    out.write_text(json.dumps({"team": args.team, "field": args.field, "battles_per_pair": args.battles,
                               "book": {o: {t: {**p, "plan": describe(p)} for t, p in v.items()} for o, v in book.items()},
                               "check": checks}, indent=1) + "\n")
    print(f"written: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
