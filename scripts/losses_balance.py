#!/usr/bin/env python3
"""Does a change that would have won some losses help on balance, counting the battles it would have lost?

    python3 scripts/losses_balance.py --kinds "fast->switch,no shield->shield" [--battles 300] [--workers 3]

scripts/losses.py looks only at lost battles, so a kind of change it finds there ("we used a fast move where a
switch would have won") may just as well throw away wins. This plays fresh battles of the bot against itself,
won and lost alike, and at every decision where the change was possible (we chose the first kind and an option
of the second kind was legal) compares the two: the alternative of that kind that looks best on `--screen`
play-outs, against the bot's own choice, both on the same `--confirm` fresh play-outs (the opponent becomes a
different variation of the bot after the decision, as in losses.py). At most `--per-battle` such moments are
sampled from each battle for each kind.

Prints, for each kind, the mean change in win chance over all those moments with its 95% margin (all battles,
then won and lost separately), and the same split by situation, to show where the change helps.
Rows go to runs/losses/balance.jsonl.
"""
from __future__ import annotations

import argparse
import json
import math
import multiprocessing
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import losses  # noqa: E402
from pogo.battle import DRAW  # noqa: E402

TESTS = {
    "losing the matchup": lambda x: x["matchup"] < 0,
    "they had a charged move ready": lambda x: x["theirs_ready"],
    "we had a charged move ready": lambda x: x["mine_ready"],
    "all three each": lambda x: x["left"] == [3, 3],
    "last Pokémon each": lambda x: x["left"] == [1, 1],
    "fewer shields": lambda x: x["shields"][0] < x["shields"][1],
    "more shields": lambda x: x["shields"][0] > x["shields"][1],
    "their switch locked": lambda x: x["switch_wait"][1] > 0,
    "first minute": lambda x: x["turn"] < 120,
    "our health under a third": lambda x: x["hp"][0] < 1 / 3,
}


def detailed(kind, choice) -> str:
    """Like losses.kind_of, but shields read 'shield' / 'no shield' so a change of mind has a direction."""
    if kind == "shield":
        return "shield" if choice else "no shield"
    return losses.kind_of(kind, choice)


def run(job):
    number, seed, wanted, screen, confirm, per_battle = job
    battle, steps = losses.record(seed)
    won = 1.0 if battle.winner == 0 else 0.5 if battle.winner == DRAW else 0.0
    rng = random.Random(seed + 1)
    moments = {k: [] for k in wanted}
    for index, (snap, calls) in enumerate(steps):
        seen = set()
        for kind, chosen, options in calls:
            if kind in seen:
                continue
            seen.add(kind)
            mine = detailed(kind, chosen)
            for key in wanted:
                a, b = key.split("->")
                if a != mine:
                    continue
                alts = [o for o in options if o != chosen and detailed(kind, o) == b]
                if alts:
                    moments[key].append((index, kind, chosen, alts))
    rows = []
    for key, found in moments.items():
        for index, kind, chosen, alts in rng.sample(found, min(per_battle, len(found))):
            snap = steps[index][0]
            base = seed * 100003 + index * 31
            if len(alts) > 1:
                alt = max(alts, key=lambda o: losses.win_chance(snap, kind, o, screen, base))
            else:
                alt = alts[0]
            ours = losses.win_chance(snap, kind, chosen, confirm, base + 17)
            theirs = losses.win_chance(snap, kind, alt, confirm, base + 17)
            view = snap[0].views[0]
            rows.append({"battle": number, "won": won, "kind": key, "step": index, "chosen": losses.label(view, kind, chosen),
                         "alternative": losses.label(view, kind, alt), "ours": ours, "theirs": theirs,
                         "situation": losses.situation(view)})
    return rows


def mean_margin(values):
    n = len(values)
    if n < 2:
        return (values[0] if values else float("nan")), float("nan")
    m = sum(values) / n
    sd = math.sqrt(sum((v - m) ** 2 for v in values) / (n - 1))
    return m, 1.96 * sd / math.sqrt(n)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--kinds", required=True, help='comma-separated "ours->alternative", e.g. "fast->switch,no shield->shield"')
    parser.add_argument("--battles", type=int, default=300)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--screen", type=int, default=8)
    parser.add_argument("--confirm", type=int, default=24)
    parser.add_argument("--per-battle", type=int, default=3)
    parser.add_argument("--seed", type=int, default=11)
    args = parser.parse_args()
    wanted = [k.strip() for k in args.kinds.split(",") if k.strip()]
    for k in wanted:
        if "->" not in k:
            parser.error(f"kind {k!r} needs the form ours->alternative")
    losses.OUT.mkdir(parents=True, exist_ok=True)
    jobs = [(n, args.seed * 1_000_003 + n, wanted, args.screen, args.confirm, args.per_battle) for n in range(args.battles)]
    rows = []
    with multiprocessing.get_context("spawn").Pool(args.workers, initializer=losses.setup) as workers:
        for done, part in enumerate(workers.imap_unordered(run, jobs, chunksize=2), 1):
            rows.extend(part)
            if done % 50 == 0:
                print(f"  {done} battles done", flush=True)
    with (losses.OUT / "balance.jsonl").open("w") as out:
        for r in rows:
            out.write(json.dumps(r) + "\n")

    def line(name, sel):
        m, e = mean_margin([r["theirs"] - r["ours"] for r in sel])
        return f"  {name:34s} {len(sel):5d} moments  {100 * m:+5.1f} ± {100 * e:4.1f} points"

    print(f"\n{args.battles} fresh battles (seed {args.seed}); change in win chance from making the change, "
          f"same {args.confirm} play-outs for both")
    for key in wanted:
        sel = [r for r in rows if r["kind"] == key]
        if not sel:
            print(f"\n{key}: no moments found")
            continue
        print(f"\n{key}")
        print(line("all battles", sel))
        print(line("battles we won", [r for r in sel if r["won"] == 1.0]))
        print(line("battles we lost", [r for r in sel if r["won"] == 0.0]))
        for name, test in TESTS.items():
            yes = [r for r in sel if test(r["situation"])]
            if len(yes) >= 20:
                print(line("when " + name, yes))
    print(f"\nrows: {(losses.OUT / 'balance.jsonl').relative_to(ROOT)}")


if __name__ == "__main__":
    main()
