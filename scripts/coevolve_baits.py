#!/usr/bin/env python3
"""Evolve throwing and shielding the "readable bait" against each other (pogo.coevo; the owner, task 34).

    python3 scripts/coevolve_baits.py --run coevo-1 [--rounds 3] [--generations 15] [--population 12] [--pairings 300]
                                      [--workers 6] [--seed 3401]

The trained bot throws the cheaper move into a shield before the dearer one is affordable more than the owner thinks
right, and simulated defenders shield such throws a third of the time, which may be what makes them pay. So both
sides evolve, in turns (CMA-ES, as scripts/evolve_rules.py): the thrower's genes against the current shielder, then
the shielder's against the new thrower, `--rounds` times. A candidate plays the current pair (`CoevoBot` with the best
genes so far; none at first, which is the trained bot itself) on `--pairings` pairs of teams from the mixed field,
each pair both ways, the same pairs for the whole generation. After each phase the CMA-ES mean becomes the current
genes (the mean, not the luckiest candidate). The state is saved after every generation and the run resumes from it.

At the end the final pair is tested on fresh battles against the trained bot as it is: head to head, against the
crowd and against PvPoke's AI, the same battles for both (`--final-pairings`, `--final-crowd`, `--final-pvpoke`).
Results go to runs/evolve/<run>/ (state.json, final.json) and the printout.
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
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
from evolve_rules import CMAES  # noqa: E402
from pogo.agents import varied  # noqa: E402
from pogo.arena import compare, field_results, low_priority, mean_and_margin  # noqa: E402
from pogo.battle import DRAW, Battle  # noqa: E402
from pogo.coevo import CoevoBot  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.learner import Learner, QNet  # noqa: E402
from pogo.pvpoke_ai import PvpokeAI  # noqa: E402
from pogo.teamshape import mixed_field  # noqa: E402

N_GENES = 5
_s: dict = {}


def setup():
    low_priority()
    gd = GameData()
    pool, draw = mixed_field(gd)
    _s.update(pool=pool, draw=draw, net=QNet.load(str(ROOT / "runs" / "general-decide" / "q.npz")))


def bot(r, throw=None, shield=None):
    if throw is None and shield is None:
        return Learner(q=_s["net"], margin=0.02, seed=r.getrandbits(30))
    return CoevoBot(throw, shield, q=_s["net"], margin=0.02, seed=r.getrandbits(30))


def fitness(task):
    """One candidate against the current pair, head to head on the generation's pairs."""
    index, cand, current, pairings, seed = task
    r = random.Random(seed + 17)
    res = compare(lambda: bot(r, *cand), lambda: bot(r, *current), _s["pool"], pairings=pairings, seed=seed, draw=_s["draw"])
    return index, res.score


def final_chunk(task):
    kind, genes, n, seed = task
    r = random.Random(seed)
    if kind == "h2h":
        return kind, [compare(lambda: bot(r, *genes), lambda: bot(r), _s["pool"], pairings=n, seed=seed, draw=_s["draw"]).score]
    out = []
    for make in (lambda rr: bot(rr, *genes), lambda rr: bot(rr)):
        rr = random.Random(seed + 1)
        if kind == "crowd":
            out.append(field_results(None, _s["pool"], lambda: make(rr), lambda rng: varied(rng, _s["pool"]), n, seed, draw=_s["draw"]))
        else:
            rng = random.Random(seed)
            pts = []
            for _ in range(n):
                a, b = _s["draw"](rng), _s["draw"](rng)
                w = Battle(a, b, make(rr), PvpokeAI(), seed=rng.getrandbits(32)).run()
                pts.append(1.0 if w == 0 else 0.5 if w == DRAW else 0.0)
            out.append(pts)
    return kind, out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", required=True)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--generations", type=int, default=15)
    parser.add_argument("--population", type=int, default=12)
    parser.add_argument("--pairings", type=int, default=300)
    parser.add_argument("--sigma", type=float, default=1.0)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--seed", type=int, default=3401)
    parser.add_argument("--final-pairings", type=int, default=3000)
    parser.add_argument("--final-crowd", type=int, default=3000)
    parser.add_argument("--final-pvpoke", type=int, default=1500)
    args = parser.parse_args()
    folder = ROOT / "runs" / "evolve" / args.run
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "state.json"
    state = json.loads(path.read_text()) if path.exists() else {
        "round": 0, "phase": "throw", "throw": None, "shield": None, "cma": None, "history": [], "arguments": vars(args)}
    rng = np.random.default_rng(args.seed)
    t0 = time.time()
    with multiprocessing.get_context("spawn").Pool(args.workers, initializer=setup) as pool:
        while state["round"] < args.rounds:
            phase = state["phase"]
            start = np.array(state[phase] if state[phase] is not None else [0.0] * N_GENES)
            cma = CMAES(start, args.sigma, args.population, state["cma"])
            while cma.gen < args.generations:
                xs = cma.ask(rng)
                seed = args.seed * 1000 + 100 * state["round"] + 50 * (phase == "shield") + cma.gen
                current = (state["throw"], state["shield"])
                cands = [(list(map(float, x)), state["shield"]) if phase == "throw" else (state["throw"], list(map(float, x)))
                         for x in xs]
                scores = np.zeros(len(xs))
                for i, s in pool.imap_unordered(fitness, [(i, c, current, args.pairings, seed) for i, c in enumerate(cands)]):
                    scores[i] = s
                cma.tell(xs, scores)
                state["cma"] = {"mean": cma.mean.tolist(), "sigma": cma.sigma, "C": cma.C.tolist(), "pc": cma.pc.tolist(),
                                "ps": cma.ps.tolist(), "gen": cma.gen}
                state["history"].append({"round": state["round"], "phase": phase, "gen": cma.gen, "best": float(scores.max()),
                                         "median": float(np.median(scores)), "mean": [round(float(v), 3) for v in cma.mean]})
                path.write_text(json.dumps(state, indent=1))
                print(f"round {state['round'] + 1} {phase:6s} generation {cma.gen:2d}: best {100 * scores.max():.1f}%, "
                      f"median {100 * np.median(scores):.1f}% against the current pair; mean genes "
                      f"{[round(float(v), 2) for v in cma.mean]} ({(time.time() - t0) / 60:.0f} min)", flush=True)
            state[phase] = [float(v) for v in cma.mean]
            state["cma"] = None
            if phase == "throw":
                state["phase"] = "shield"
            else:
                state["phase"], state["round"] = "throw", state["round"] + 1
            path.write_text(json.dumps(state, indent=1))
        genes = (state["throw"], state["shield"])
        print(f"\nfinal genes: thrower {genes[0]}, shielder {genes[1]}", flush=True)
        chunk = 50
        tasks = ([("h2h", genes, chunk, args.seed * 7 + k) for k in range(args.final_pairings // chunk)]
                 + [("crowd", genes, chunk, args.seed * 11 + k) for k in range(args.final_crowd // chunk)]
                 + [("pvpoke", genes, chunk, args.seed * 13 + k) for k in range(args.final_pvpoke // chunk)])
        got = {"h2h": [], "crowd": [], "pvpoke": []}
        for kind, out in pool.imap_unordered(final_chunk, tasks):
            got[kind].append(out)
    m, h = mean_and_margin([x[0] for x in got["h2h"]])
    lines = [f"evolved pair against the trained bot as it is, mixed field, fresh battles:",
             f"  head to head ({args.final_pairings} pairings both ways): {100 * m:.1f}% ± {100 * h:.1f}"]
    final = {"genes": {"throw": genes[0], "shield": genes[1]}, "h2h": [m, h]}
    for kind in ("crowd", "pvpoke"):
        a = [x for o in got[kind] for x in o[0]]
        b = [x for o in got[kind] for x in o[1]]
        d, dh = mean_and_margin([x - y for x, y in zip(a, b)])
        lines.append(f"  against the {kind} ({len(a)} battles, the same for both): evolved {100 * sum(a) / len(a):.1f}%, "
                     f"as it is {100 * sum(b) / len(b):.1f}%, difference {100 * d:+.1f} ± {100 * dh:.1f} points")
        final[kind] = [d, dh]
    print("\n".join(lines))
    (folder / "final.json").write_text(json.dumps(final, indent=1) + "\n")


if __name__ == "__main__":
    main()
