#!/usr/bin/env python3
"""Evolve the rulebook's settings together with CMA-ES (docs/tasks.md, task 30; the owner's idea).

    python3 scripts/evolve_rules.py --run rules-1 [--generations 100] [--population 32] [--pairings 2000] [--workers 64]
    python3 scripts/evolve_rules.py --run rules-1 --final [--final-pairings 5000]       re-score the best on fresh battles
    python3 scripts/evolve_rules.py --run engine-1 --engine [--pairings 300]            evolve the engine's settings

Rules: every candidate is a set of `Planner` settings (GENES: numbers, on/off rules and the bait and shield styles,
encoded between 0 and 1) and plays the current standard `Planner` head to head, every pair of random teams both ways,
on the same pairings as the rest of its generation; its score is its fitness. With --pilot bot the trained bot plays on
top of each candidate's rules against the trained bot on the standard rules, which is what would be adopted.

Engine: the genes are the engine's settings (ENGINE_GENES) and each candidate plays the confirmed engine head to head
(scripts/engine_versus.py), much slower per battle.

The state is saved after every generation in runs/evolve/<run>/ and the run resumes from it. The best of thousands of
noisy scores is flattered by luck, so --final plays the five best candidates seen (by score) again on fresh pairings;
only those numbers count. Then confirm the winner with scripts/rule_trial.py on a new seed (it prints the command).
"""
from __future__ import annotations

import argparse
import json
import math
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
from pogo.agents import Planner  # noqa: E402
from pogo.arena import low_priority, mean_and_margin  # noqa: E402
from pogo.battle import DRAW, Battle  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402

# (name, kind, low, high or choices, current default). kind: "num", "bool" (on above 0.5) or "pick" (one of choices).
GENES = [
    ("shield_share", "num", 0.0, 1.0, 0.4), ("shield_worth", "num", 0.0, 1.0, 0.35),
    ("energy_worth", "num", 0.0, 0.5, 0.0), ("switch_margin", "num", 0.0, 0.8, 0.35),
    ("expect_shield", "num", 0.2, 1.0, 0.7), ("expect_bait", "num", 0.0, 1.0, 0.5),
    ("belief", "num", 0.5, 10.0, 2.0), ("safe_weight", "num", 0.0, 1.0, 0.0),
    ("bad_matchup", "num", -0.6, 0.2, -0.2), ("farm_cost", "num", 0.0, 1.0, 0.35),
    ("sac_margin", "num", 0.0, 0.4, 0.1), ("hold_cost", "num", 0.0, 1.5, 0.5),
    ("win_switch", "num", 0.0, 0.5, 0.1), ("matchup_weight", "num", 0.0, 1.0, 0.75),
    ("switch_worth", "num", 0.0, 0.5, 0.0), ("shield_matchup_hp", "num", 0.0, 0.6, 0.3),
    ("catch_gain", "num", 0.0, 0.5, 0.2), ("known_edge", "num", 0.0, 0.4, 0.15),
    ("sweeper", "num", 0.0, 1.0, 0.0), ("sweep_chance", "num", 0.05, 1.0, 0.75),
    ("fast_first", "num", 0.0, 1.0, 0.0),
    ("hold", "bool", 0, 1, True), ("last_gasp", "bool", 0, 1, True), ("timed_farm", "bool", 0, 1, True),
    ("good_matchup", "bool", 0, 1, True), ("sac", "bool", 0, 1, True), ("farm", "bool", 0, 1, True),
    ("punish", "bool", 0, 1, False), ("shield_matchups", "bool", 0, 1, False), ("catch", "bool", 0, 1, False),
    ("rush", "bool", 0, 1, False), ("known_team", "bool", 0, 1, False),
    ("bait", "pick", 0, ("mix", "read", "even", "farm", "cheap", "never"), "mix"),
    ("shields", "pick", 0, ("lookahead", "threshold"), "lookahead"),
]
ENGINE_GENES = [
    ("edge", "num", 0.0, 0.1, 0.03), ("samples", "int", 2, 32, 4), ("horizon", "int", 10, 60, 20),
    ("margin", "num", 0.0, 0.1, 0.02), ("temperature", "num", 0.0, 0.05, 0.0),
]


def encode(genes) -> np.ndarray:
    out = []
    for name, kind, low, high, default in genes:
        if kind in ("num", "int"):
            out.append((default - low) / (high - low))
        elif kind == "bool":
            out.append(0.75 if default else 0.25)
        else:
            out.append((high.index(default) + 0.5) / len(high))
    return np.array(out)


def decode(genes, x: np.ndarray) -> dict:
    out = {}
    for (name, kind, low, high, default), v in zip(genes, np.clip(x, 0.0, 1.0)):
        if kind == "num":
            out[name] = round(float(low + v * (high - low)), 4)
        elif kind == "int":
            out[name] = int(round(low + v * (high - low)))
        elif kind == "bool":
            out[name] = bool(v > 0.5)
        else:
            out[name] = high[min(int(v * len(high)), len(high) - 1)]
    return out


class CMAES:
    """Plain CMA-ES (Hansen's tutorial), maximising; state as plain lists so it saves as JSON."""

    def __init__(self, mean: np.ndarray, sigma: float, population: int, state: dict | None = None):
        n = len(mean)
        self.n, self.lam = n, population
        mu = population // 2
        w = np.log(mu + 0.5) - np.log(np.arange(1, mu + 1))
        self.w = w / w.sum()
        self.mueff = 1 / (self.w ** 2).sum()
        self.cs = (self.mueff + 2) / (n + self.mueff + 5)
        self.ds = 1 + 2 * max(0.0, math.sqrt((self.mueff - 1) / (n + 1)) - 1) + self.cs
        self.cc = (4 + self.mueff / n) / (n + 4 + 2 * self.mueff / n)
        self.c1 = 2 / ((n + 1.3) ** 2 + self.mueff)
        self.cmu = min(1 - self.c1, 2 * (self.mueff - 2 + 1 / self.mueff) / ((n + 2) ** 2 + self.mueff))
        self.chi = math.sqrt(n) * (1 - 1 / (4 * n) + 1 / (21 * n * n))
        if state:
            self.mean, self.sigma = np.array(state["mean"]), state["sigma"]
            self.C, self.pc, self.ps, self.gen = np.array(state["C"]), np.array(state["pc"]), np.array(state["ps"]), state["gen"]
        else:
            self.mean, self.sigma, self.C = mean.copy(), sigma, np.eye(n)
            self.pc, self.ps, self.gen = np.zeros(n), np.zeros(n), 0

    def ask(self, rng: np.random.Generator) -> np.ndarray:
        vals, vecs = np.linalg.eigh(self.C)
        self._B, self._D = vecs, np.sqrt(np.maximum(vals, 1e-20))
        z = rng.standard_normal((self.lam, self.n))
        return self.mean + self.sigma * (z * self._D) @ self._B.T

    def tell(self, xs: np.ndarray, scores: np.ndarray) -> None:
        order = np.argsort(-scores)[: len(self.w)]
        ys = (xs[order] - self.mean) / self.sigma
        yw = self.w @ ys
        self.mean = self.mean + self.sigma * yw
        inv_sqrt = self._B @ np.diag(1 / self._D) @ self._B.T
        self.ps = (1 - self.cs) * self.ps + math.sqrt(self.cs * (2 - self.cs) * self.mueff) * inv_sqrt @ yw
        self.gen += 1
        hs = np.linalg.norm(self.ps) / math.sqrt(1 - (1 - self.cs) ** (2 * self.gen)) < (1.4 + 2 / (self.n + 1)) * self.chi
        self.pc = (1 - self.cc) * self.pc + hs * math.sqrt(self.cc * (2 - self.cc) * self.mueff) * yw
        rank_mu = (ys.T * self.w) @ ys
        self.C = ((1 - self.c1 - self.cmu) * self.C
                  + self.c1 * (np.outer(self.pc, self.pc) + (1 - hs) * self.cc * (2 - self.cc) * self.C)
                  + self.cmu * rank_mu)
        self.C = (self.C + self.C.T) / 2
        self.sigma *= math.exp((self.cs / self.ds) * (np.linalg.norm(self.ps) / self.chi - 1))

    def state(self) -> dict:
        return {"mean": self.mean.tolist(), "sigma": self.sigma, "C": self.C.tolist(), "pc": self.pc.tolist(),
                "ps": self.ps.tolist(), "gen": self.gen}


_state: dict = {}


def setup(pilot: str) -> None:
    low_priority()
    gd = GameData()
    _state.update(pool=gd.meta(50), pilot=pilot)
    if pilot == "bot":
        from pogo.learner import QNet
        _state["net"] = QNet.load(str(ROOT / "runs" / "general-decide" / "q.npz"))


def player(settings: dict, seed: int):
    if _state["pilot"] == "bot":
        from pogo.learner import Learner
        return Learner(q=_state["net"], margin=0.02, seed=seed, **settings)
    return Planner(seed=seed, **settings)


def rules_job(task):
    """Candidate rules (or the bot on them) against the standard: `count` pairs of random teams, both ways round."""
    index, settings, start, count, seed = task
    pool = _state["pool"]
    total = 0.0
    for n in range(start, start + count):
        rng = random.Random(seed * 1_000_003 + n)
        a, b = rng.sample(pool, 3), rng.sample(pool, 3)
        dice = rng.getrandbits(32)
        for ours, theirs in ((a, b), (b, a)):
            winner = Battle(ours, theirs, player(settings, rng.getrandbits(32)), player({}, rng.getrandbits(32)), seed=dice).run()
            total += 0.5 * (1.0 if winner == 0 else 0.5 if winner == DRAW else 0.0)
    return index, total, count


def engine_job(task):
    import engine_versus
    index, settings, start, count, seed = task
    if not engine_versus._state:
        engine_versus.setup()
    spec = ",".join(f"{k}={v}" for k, v in settings.items())
    _, _, out, _ = engine_versus.job(("h2h", spec, spec, "", start, count, seed))
    return index, sum(out.values()), count


def score_all(pool, job, candidates, pairings, chunk, seed) -> np.ndarray:
    tasks = [(i, c, s, min(chunk, pairings - s), seed) for i, c in enumerate(candidates) for s in range(0, pairings, chunk)]
    totals, counts = np.zeros(len(candidates)), np.zeros(len(candidates))
    for i, total, count in pool.imap_unordered(job, tasks):
        totals[i] += total
        counts[i] += count
    return totals / counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", required=True)
    parser.add_argument("--engine", action="store_true", help="evolve the engine's settings instead of the rules")
    parser.add_argument("--pilot", choices=("rules", "bot"), default="rules", help="rules alone, or the trained bot on top")
    parser.add_argument("--generations", type=int, default=100)
    parser.add_argument("--population", type=int, default=32)
    parser.add_argument("--sigma", type=float, default=0.15)
    parser.add_argument("--pairings", type=int, default=2000, help="pairs of teams per candidate per generation")
    parser.add_argument("--chunk", type=int, default=50)
    parser.add_argument("--final", action="store_true")
    parser.add_argument("--final-pairings", type=int, default=5000)
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 4)
    parser.add_argument("--seed", type=int, default=3001)
    args = parser.parse_args()
    genes = ENGINE_GENES if args.engine else GENES
    job = engine_job if args.engine else rules_job
    folder = ROOT / "runs" / "evolve" / args.run
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "state.json"
    saved = json.loads(path.read_text()) if path.exists() else {"history": [], "seen": []}
    es = CMAES(encode(genes), args.sigma, args.population, saved.get("cma"))
    rng = np.random.default_rng(args.seed + es.gen)
    print(f"{'engine' if args.engine else 'rules'} evolution '{args.run}': {len(genes)} genes, population {args.population}, "
          f"{args.pairings} pairings each, generation {es.gen} of {args.generations}, {args.workers} workers", flush=True)
    with multiprocessing.get_context("spawn").Pool(args.workers, initializer=setup, initargs=(args.pilot,)) as pool:
        if args.final:
            best = sorted(saved["seen"], key=lambda e: -e["score"])
            picked, keys = [], set()
            for e in best:
                key = json.dumps(e["settings"], sort_keys=True)
                if key not in keys:
                    picked.append(e)
                    keys.add(key)
                if len(picked) == 5:
                    break
            scores = score_all(pool, job, [e["settings"] for e in picked], args.final_pairings, args.chunk, args.seed + 99_991)
            print(f"\nthe five best seen, on {args.final_pairings} fresh pairings each, against the standard:")
            for e, s in sorted(zip(picked, scores), key=lambda t: -t[1]):
                changed = {k: v for k, v in e["settings"].items() if v != next(g[4] for g in genes if g[0] == k)}
                print(f"  {100 * s:.1f}% (in the run {100 * e['score']:.1f}%, generation {e['gen']}): {changed}")
            winner = picked[int(np.argmax(scores))]
            (folder / "best.json").write_text(json.dumps({"settings": winner["settings"], "fresh_score": float(scores.max()),
                                                          "pairings": args.final_pairings}, indent=1) + "\n")
            if not args.engine:
                text = ",".join(f"{k}={v!r}" for k, v in winner["settings"].items())
                print(f"\nconfirm on a new seed:\n  python3 scripts/rule_trial.py \"{text}\" --battles 8000 --seed {args.seed + 7}")
            return
        while es.gen < args.generations:
            t0 = time.time()
            xs = es.ask(rng)
            candidates = [decode(genes, x) for x in xs]
            scores = score_all(pool, job, candidates, args.pairings, args.chunk, args.seed * 1000 + es.gen)
            for c, s in zip(candidates, scores):
                saved["seen"].append({"gen": es.gen, "score": float(s), "settings": c})
            saved["seen"] = sorted(saved["seen"], key=lambda e: -e["score"])[:200]
            es.tell(xs, scores)
            mean_settings = decode(genes, es.mean)
            saved["history"].append({"gen": es.gen, "best": float(scores.max()), "median": float(np.median(scores)),
                                     "sigma": es.sigma, "mean": mean_settings, "minutes": round((time.time() - t0) / 60, 1)})
            saved["cma"] = es.state()
            path.write_text(json.dumps(saved))
            print(f"generation {es.gen}: best {100 * scores.max():.1f}%, median {100 * np.median(scores):.1f}%, "
                  f"step {es.sigma:.3f}, {(time.time() - t0) / 60:.1f} min", flush=True)
    print(f"\ndone; now: python3 scripts/evolve_rules.py --run {args.run}{' --engine' if args.engine else ''} --final")


if __name__ == "__main__":
    main()
