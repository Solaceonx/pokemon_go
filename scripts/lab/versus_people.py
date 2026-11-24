#!/usr/bin/env python3
"""Players against person-like opponents, every player on the same battles (lab-learn).

    python scripts/lab/versus_people.py --tag NAME --specs "bot" "bot,q=runs/lab-learn/population/q.npz" \
        [--battles 1000] [--opponents human owner] [--workers 2] [--seed 6001] [--field mixed]

Specs are scripts/engine_versus.py's ("bot", "website", "website,opp_policy=PATH", "bot,anchor=PATH,lam=0.02", ...);
the first is the baseline. Every spec plays the same battles: the same teams, opponent and dice. Opponents, taking turns
battle by battle:

  human   the trained bot with pogo.engine.human_settings (people keep fast-moving where the bot would throw, many use
          a fast move before swapping) and the creators' shield calls (pogo.people_shield): the engine's own guess at
          a person, with real shield habits
  owner   the owner, imitated: a policy fitted to the owner's website games (scripts/lab/fit_policy.py owner), drawn
          from at every decision, the trained bot for the rest
  owner_top  the same policy, its likeliest option taken (it departs from the trained bot only where the owner is
          more likely than not to depart)

Both are guesses at people, not people: a player trained or imagining against one of them is not judged by it (task
42's rule; for example the 'imitation' kind of train_population.py and the 'owner' opponent, or an engine with
opp_policy=the owner's policy and the 'owner' opponent). Prints each spec's score against each kind with a 95% margin,
and its change on the baseline on the same battles. Results in runs/lab-learn/versus_people/<tag>.json; a run started
again with the same tag carries on.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_v] = "1"

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
import engine_versus as V  # noqa: E402
from pogo.arena import mean_and_margin  # noqa: E402
from pogo.battle import Battle  # noqa: E402
from pogo.engine import human_settings  # noqa: E402
from pogo.learner import Learner  # noqa: E402
from scripts.wide_teams import run_jobs  # noqa: E402

PEOPLE_SHIELD = "runs/people-shield/shield.npz"
OWNER_POLICY = "runs/lab-learn/owner-policy/policy.npz"
KINDS = ("human", "owner", "owner_top")


def opponent(kind: str, rng: random.Random, owner_policy: str):
    s = V._state
    if kind == "human":
        return Learner(q=s["net"], margin=rng.choice((0.02, 0.05)), people_shield=PEOPLE_SHIELD, **human_settings(rng, s["pool"]))
    from pogo.lab.policy import PolicyPlayer, cached
    return PolicyPlayer(pnet=cached(owner_policy), q=s["net"], margin=0.02, sample=kind == "owner", seed=rng.getrandbits(32))


def job(task):
    spec, start, count, seed, kinds, owner_policy = task
    out = {}
    for n in range(start, start + count):
        rng = random.Random(seed * 1_000_003 + n)
        kind = kinds[n % len(kinds)]
        a, b = V._state["our_draw"](rng), V._state["draw"](rng)
        dice, ours, theirs = rng.getrandbits(32), rng.getrandbits(32), rng.getrandbits(32)
        me = V.pilot(V.parse(spec), ours)
        out[n] = (kind, V.points(Battle(a, b, me, opponent(kind, random.Random(theirs), owner_policy), seed=dice).run(), 0))
    return spec, out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--specs", nargs="+", required=True, help="the first is the baseline")
    parser.add_argument("--battles", type=int, default=1000)
    parser.add_argument("--opponents", nargs="+", choices=KINDS, default=list(KINDS))
    parser.add_argument("--owner-policy", default=OWNER_POLICY)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--chunk", type=int, default=10)
    parser.add_argument("--seed", type=int, default=6001)
    parser.add_argument("--field", choices=("standard", "pvpoke", "mixed"), default="mixed")
    args = parser.parse_args()
    for spec in args.specs:
        V.parse(spec)
    path = ROOT / "runs" / "lab-learn" / "versus_people" / f"{args.tag}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    saved = json.loads(path.read_text()) if path.exists() else {}
    fixed = {"seed": args.seed, "field": args.field, "opponents": args.opponents, "owner_policy": args.owner_policy}
    if saved and any(saved.get(k) != v for k, v in fixed.items()):
        raise SystemExit(f"{path} was made with other settings; use them or another tag")
    saved.update(fixed)
    results = saved.setdefault("results", {})
    plan = []
    for spec in args.specs:
        have = results.get(spec, {})
        missing = [n for n in range(args.battles) if str(n) not in have]
        while missing:  # contiguous jobs, as engine_versus.py makes them
            start, length = missing[0], 1
            while length < min(args.chunk, len(missing)) and missing[length] == start + length:
                length += 1
            plan.append((spec, start, length, args.seed, args.opponents, args.owner_policy))
            missing = missing[length:]
    print(f"{len(plan)} jobs on {args.workers} workers", flush=True)
    t0, last = time.time(), time.time()
    for spec, out in run_jobs(job, plan, args.workers, V.setup, (args.field, None, None), spawn=True):
        results.setdefault(spec, {}).update({str(n): v for n, v in out.items()})
        if time.time() - last > 60:
            path.write_text(json.dumps(saved))
            last = time.time()
    path.write_text(json.dumps(saved))
    base = args.specs[0]
    print(f"\nperson-like opponents, {args.battles} battles, seed {args.seed}, field {args.field}; baseline: {base}")
    for spec in args.specs:
        got = results[spec]
        line = [f"  {spec}"]
        for kind in args.opponents:
            ns = sorted((int(n) for n, (k, _) in got.items() if k == kind and int(n) < args.battles))
            if len(ns) < 2:
                continue
            mine = [got[str(n)][1] for n in ns]
            m, h = mean_and_margin(mine)
            text = f"{kind} {100 * m:.1f}% ± {100 * h:.1f} ({len(ns)})"
            if spec != base:
                theirs = [results[base][str(n)][1] for n in ns]
                d, dh = mean_and_margin([x - y for x, y in zip(mine, theirs)])
                text += f", {100 * d:+.1f} ± {100 * dh:.1f} on the baseline"
            line.append(text)
        print("\n    ".join(line), flush=True)
    print(f"\nelapsed {time.time() - t0:.0f} s; results: {path.relative_to(ROOT).as_posix()}")


if __name__ == "__main__":
    main()
