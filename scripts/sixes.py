#!/usr/bin/env python3
"""Six against six, open team sheets: which three to bring and who leads (pogo.sixes).

    python3 scripts/sixes.py melmetal altaria jellicent stunfisk quagsire_shadow umbreon \
        --vs tinkaton annihilape_shadow corviknight mandibuzz carbink thievul [--battles 40] [--workers 3]

Every one of our 60 choices (three of six, each leading) plays every one of theirs, --battles battles each with
both sides the trained bot with shifted habits (the same battles down each column, so our choices compare on equal
terms). The table is then solved as a simultaneous game. To keep the answer honest about luck, the battles of each
cell are split in two: the mix is found on one half and scored on the other.

Prints: our win chance when both sides choose well; our best mix of choices and theirs; the best single choice if
we do not mix (with its worst case); how often each of our six is brought and leads. Writes runs/sixes/<name>.json.
Our Pokémon use the owner's own builds where they have them (--no-owned for PvPoke's usual ones).
"""
from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import random
import sys
import time
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_v] = "1"
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pogo.agents import varied_settings  # noqa: E402
from pogo.battle import DRAW, Battle  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.learner import Learner, QNet  # noqa: E402
from pogo.roster import builds  # noqa: E402
from pogo.sixes import choices, gap, solve  # noqa: E402

_state: dict = {}


def setup(owned: bool) -> None:
    os.nice(10)
    gd = GameData()
    _state.update(gd=gd, pool=gd.meta(50), net=QNet.load(str(ROOT / "runs" / "general-decide" / "q.npz")),
                  owned=builds(gd) if owned else {})


def cell(job):
    i, j, mine, theirs, battles, seed = job
    s = _state
    gd, pool, net = s["gd"], s["pool"], s["net"]
    ours = [s["owned"].get(sp) or gd.default(sp) for sp in mine]
    foes = [gd.default(sp) for sp in theirs]
    rng = random.Random(seed)
    points = []
    for _ in range(battles):
        a = Learner(q=net, margin=rng.choice((0.02, 0.05)), **varied_settings(rng, pool))
        b = Learner(q=net, margin=rng.choice((0.02, 0.05)), **varied_settings(rng, pool))
        winner = Battle(ours, foes, a, b, seed=rng.getrandbits(32)).run()
        points.append(1.0 if winner == 0 else 0.5 if winner == DRAW else 0.0)
    return i, j, points


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mine", nargs=6, metavar="OURS")
    parser.add_argument("--vs", nargs=6, required=True, metavar="THEIRS")
    parser.add_argument("--battles", type=int, default=40, help="battles for each of our choices against each of theirs")
    parser.add_argument("--no-owned", action="store_true")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--seed", type=int, default=6)
    args = parser.parse_args()
    gd = GameData()
    for sp in args.mine + args.vs:
        if sp not in gd.species or not gd.supported(sp):
            raise SystemExit(f"unknown or unsupported Pokémon: {sp}")
    ours, theirs = choices(args.mine), choices(args.vs)
    name = lambda sp: gd.species[sp]["speciesName"]  # noqa: E731
    label = lambda c: f"{name(c[0])} leading, {name(c[1])} and {name(c[2])} behind"  # noqa: E731
    jobs = [(i, j, ours[i], theirs[j], args.battles, args.seed * 1_000_003 + j) for j in range(60) for i in range(60)]
    points = np.zeros((60, 60, args.battles))
    t0 = time.time()
    with multiprocessing.get_context("spawn").Pool(args.workers, initializer=setup, initargs=(not args.no_owned,)) as pool:
        for n, (i, j, pts) in enumerate(pool.imap_unordered(cell, jobs, chunksize=10), start=1):
            points[i, j] = pts
            if n % 600 == 0:
                print(f"  {n} of 3600 cells, {(time.time() - t0) / 60:.0f} min", flush=True)
    half = args.battles // 2
    full, first, second = points.mean(axis=2), points[:, :, :half].mean(axis=2), points[:, :, half:].mean(axis=2)
    value, p, q = solve(full)
    p1, q1 = solve(first)[1:]
    honest_vs_mix = float(p1 @ second @ solve(second)[2])   # mix found on one half, against their best mix on the other
    honest_worst = float((p1 @ second).min())               # ... and against their single best reply on the other half
    worst = full.min(axis=1)
    best_pure = int(np.argmax(worst))
    print(f"\n{' / '.join(map(name, args.mine))}\n  against {' / '.join(map(name, args.vs))}\n"
          f"  {args.battles} battles for each of 3,600 pairs of choices, {(time.time() - t0) / 60:.0f} min")
    print(f"\nour win chance when both sides choose well: {100 * value:.0f}% "
          f"(found and scored on separate battles: {100 * honest_vs_mix:.0f}%; against their best single reply {100 * honest_worst:.0f}%)")
    print("\nour best mix (choices above 3%):")
    for k in np.argsort(-p):
        if p[k] < 0.03:
            break
        print(f"  {100 * p[k]:3.0f}%  {label(ours[k])}   (worst case {100 * worst[k]:.0f}%)")
    print("\ntheir best mix:")
    for k in np.argsort(-q):
        if q[k] < 0.03:
            break
        print(f"  {100 * q[k]:3.0f}%  {label(theirs[k])}")
    print(f"\nbest single choice if we do not mix: {label(ours[best_pure])}: at worst {100 * worst[best_pure]:.0f}%, "
          f"{100 * float(full[best_pure] @ q):.0f}% against their mix")
    naive = int(np.argmax(full.mean(axis=1)))
    print(f"best choice against a random one of theirs: {label(ours[naive])}: {100 * full[naive].mean():.0f}% on average, "
          f"{100 * worst[naive]:.0f}% at worst, {100 * float(full[naive] @ q):.0f}% against their mix")
    brought = {sp: sum(p[k] for k, c in enumerate(ours) if sp in c) for sp in args.mine}
    leads = {sp: sum(p[k] for k, c in enumerate(ours) if c[0] == sp) for sp in args.mine}
    print("\nhow often each of ours is brought / leads in our mix: "
          + ", ".join(f"{name(sp)} {100 * brought[sp]:.0f}% / {100 * leads[sp]:.0f}%" for sp in args.mine))
    print(f"(solution check: either side could gain {100 * gap(full, p, q):.2f} points by deviating)")
    out = ROOT / "runs" / "sixes"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{'-'.join(args.mine)}--vs--{'-'.join(args.vs)}.json"
    path.write_text(json.dumps({"mine": args.mine, "theirs": args.vs, "battles": args.battles, "value": value,
                                "ours": ours, "theirs_choices": theirs, "table": full.round(4).tolist(),
                                "our_mix": p.round(4).tolist(), "their_mix": q.round(4).tolist()}) + "\n")
    print(f"table: {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
