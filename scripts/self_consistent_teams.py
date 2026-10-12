#!/usr/bin/env python3
"""Build an opposing team mixture that can answer its own counters (task 21).

    python3 scripts/self_consistent_teams.py --help
    python3 scripts/self_consistent_teams.py --workers 3 --out data/teams_v2.json

Both sides use runs/general-decide/q.npz, margin 0.02. Start with the old list,
measure a side-balanced payoff matrix, solve its zero-sum game with fictitious
play, search for counters, add them, and solve again without discarding old teams.
Search includes random legal threes, every lead, and all one-member changes to
the strongest parents. No one-on-one coverage filter excludes candidates.

The default is a substantial search, not enumeration of all top-100 line-ups.
--exhaustive screens every legal line-up each round (much slower). --rounds,
--random, --parents, --stages and --matrix-pairs allow a smaller, labelled run.
Stage sizes and --finals count independent pairings, each played BOTH ways.
Only the final untouched battles are printed as scores. Search and stopping
battles never enter those scores; the final test cannot update the mixture.

--observed accepts additional {"teams": [{"team": [...], "seen": N}]} files,
with the lead first. Counts are preserved (maximum on duplicate records), and
these teams join the search population. Explicit fitted weights are authoritative;
seen counts do not distort them again at draw time. Unsupported/out-of-pool
observations fail clearly. No real sightings are inferred from simulation.

The output is a NEW list plus a small .report.json with provenance and held-out
checks. The old list is never overwritten. Rerun roster_teams.py with
--compare-teams NEW_LIST to rank the owner's roster against both fields.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing
import os
import random
import shlex
import sys
import time
from pathlib import Path
from statistics import NormalDist

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_v] = "1"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
from pogo.arena import mean_and_margin  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.teamlist import TEAMS, weights_for  # noqa: E402
from pogo.teamsearch import (all_lineups, canonical, equilibrium, estimate, evaluate, leads,
                             legal, play, schedule, seed_for, setup)  # noqa: E402

MODEL = ROOT / "runs" / "general-decide" / "q.npz"


def stages_arg(text):
    try:
        stages = [tuple(map(int, s.split(":"))) for s in text.split(",")]
        if not stages or any(len(s) != 2 or min(s) < 2 for s in stages):
            raise ValueError
        return stages
    except ValueError as exc:
        raise argparse.ArgumentTypeError("use pairs:keep,pairs:keep, with values at least 2") from exc


def candidates(ids, dex, population, parents, count, seed, exhaustive=False):
    if exhaustive:
        return all_lineups(ids, dex)
    rng = random.Random(seed)
    found = {canonical(t) for t in population}
    # Rejection of illegal forms preserves a uniform distribution over legal threes.
    for _ in range(count):
        while True:
            three = rng.sample(ids, 3)
            if legal(three, dex):
                found.update(leads(three))
                break
    for parent in parents:
        for slot in range(3):
            for sid in ids:
                child = list(parent)
                child[slot] = sid
                if legal(child, dex):
                    found.update(leads(child))
    return sorted(found)


def matrix_job(job):
    i, j, a, b, pairs, seed = job
    rows = schedule([b], [1], [], {}, pairs, seed)
    _, points = play((a, rows, False))
    return i, j, sum(points) / len(points) - 0.5


def extend_matrix(workers, teams, previous, pairs, seed):
    old = len(previous)
    out = np.zeros((len(teams), len(teams)))
    out[:old, :old] = previous
    jobs = [(i, j, teams[i], teams[j], pairs, seed_for(seed, "matrix", teams[i], teams[j]))
            for j in range(old, len(teams)) for i in range(j)]
    for i, j, score in workers.imap_unordered(matrix_job, jobs, chunksize=8):
        out[i, j], out[j, i] = score, -score
    return out


def search(workers, choices, teams, weights, ids, dex, stages, seed, label):
    alive, total, played = list(choices), {t: 0.0 for t in choices}, 0
    for number, (pairs, keep) in enumerate(stages):
        rows = schedule(teams, weights, ids, dex, pairs, seed_for(seed, "stage", number))
        for team, points in evaluate(workers, alive, rows).items():
            total[team] += sum(points)
        played += pairs
        alive = sorted(alive, key=lambda t: (-total[t], t))[:keep]
        print(f"{label}, stage {number + 1}: {len(choices) if number == 0 else before} line-ups, "
              f"{played} search pairs each; kept {len(alive)}", flush=True)
        before = len(alive)
    return alive


def fingerprint(paths):
    return {str(p.relative_to(ROOT) if p.is_relative_to(ROOT) else p): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in paths}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--teams", type=Path, default=TEAMS, help="initial list, preserved")
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "teams_v2.json")
    parser.add_argument("--observed", type=Path, nargs="*", default=[])
    parser.add_argument("--model", type=Path, default=MODEL)
    parser.add_argument("--pool", type=int, default=100)
    parser.add_argument("--rounds", type=int, default=10, help="maximum counter-search rounds")
    parser.add_argument("--random", type=int, default=2048, help="random threes per search, all three leads")
    parser.add_argument("--parents", type=int, default=4, help="parents whose every one-member change is screened")
    parser.add_argument("--stages", type=stages_arg, default=stages_arg("24:96,160:16"))
    parser.add_argument("--add", type=int, default=12, help="new counters retained each round")
    parser.add_argument("--matrix-pairs", type=int, default=24)
    parser.add_argument("--stop-pairs", type=int, default=400, help="development pairs for the stopping decision")
    parser.add_argument("--audit-random", type=int, default=4096, help="new random threes in the frozen-list counter search")
    parser.add_argument("--audit-keep", type=int, default=16, help="counter finalists for untouched testing")
    parser.add_argument("--finals", type=int, default=3000, help="untouched pairs per finalist, 2 battles per pair")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--seed", type=int, default=21021)
    parser.add_argument("--exhaustive", action="store_true", help="screen ALL legal top-pool line-ups in each search")
    args = parser.parse_args()
    if args.out.resolve() in {args.teams.resolve(), TEAMS.resolve(), *(p.resolve() for p in args.observed)}:
        parser.error("--out must be a new list, not an input list or data/teams.json")
    if not args.model.is_file():
        parser.error("the trained model is required; no Planner fallback")
    if min(args.rounds, args.random, args.parents, args.add, args.workers, args.audit_keep) < 1 or args.pool < 3:
        parser.error("counts must be positive; --pool must be at least 3")
    if min(args.matrix_pairs, args.stop_pairs, args.finals) < 2 or args.audit_random < 1:
        parser.error("pair counts must be at least 2; --audit-random must be positive")
    if args.stages[-1][1] < max(args.add, args.audit_keep):
        parser.error("last stage must keep at least max(--add, --audit-keep)")
    gd = GameData()
    ids = [b.species_id for b in gd.meta(args.pool)]
    dex = {s: gd.species[s]["dex"] for s in ids}
    entries = json.loads(args.teams.read_text())["teams"]
    seen = {}
    for path, rows in [(args.teams, entries), *[(p, json.loads(p.read_text())["teams"]) for p in args.observed]]:
        for entry in rows:
            t = canonical(entry["team"])
            if not legal(t, dex):
                parser.error(f"{path}: team {t} is illegal, unsupported, or outside the top {args.pool}")
            n = entry.get("seen", 0)
            if not isinstance(n, int) or n < 0:
                parser.error(f"{path}: seen must be a nonnegative integer")
            seen[t] = max(seen.get(t, 0), n)
    population = sorted(seen)
    if not population:
        parser.error("initial population is empty")
    original_weights = weights_for(entries)
    initial_parents = [canonical(e["team"]) for _, e in sorted(zip(original_weights, entries), key=lambda x: -x[0])]
    parents = initial_parents[:args.parents]
    started = time.monotonic()
    histories, tried = [], set(population)
    payoff = np.zeros((0, 0))
    print(f"top {len(ids)} supported Pokémon; {len(population)} initial line-ups; {args.workers} workers; "
          f"{'exhaustive screening' if args.exhaustive else 'sampled search (not exhaustive)'}; "
          "same learned pilot on both sides", flush=True)
    with multiprocessing.get_context("spawn").Pool(args.workers, initializer=setup,
                                                    initargs=(str(args.model), args.pool)) as workers:
        for number in range(args.rounds):
            payoff = extend_matrix(workers, population, payoff, args.matrix_pairs, args.seed)
            weights = equilibrium(payoff)
            choices = candidates(ids, dex, population, parents, args.random,
                                 seed_for(args.seed, "candidates", number), args.exhaustive)
            tried.update(choices)
            print(f"round {number + 1}: matrix ready for {len(population)} line-ups; "
                  f"searching {len(choices)} counters; elapsed {(time.monotonic() - started) / 60:.1f} min", flush=True)
            leaders = search(workers, choices, population, weights, ids, dex, args.stages,
                             seed_for(args.seed, "search", number), f"round {number + 1}")
            rows = schedule(population, weights, ids, dex, args.stop_pairs, seed_for(args.seed, "stop", number))
            development = evaluate(workers, leaders, rows)
            leaders.sort(key=lambda t: (-sum(development[t]), t))
            # These battles are development data: using them to stop is tuning.
            settled = all(mean_and_margin(p)[0] - 0.5 <= mean_and_margin(p)[1] for p in development.values())
            newcomers = [t for t in leaders if t not in population][:args.add]
            histories.append({"round": number + 1, "population": len(population), "candidates": len(choices),
                              "added": len(newcomers), "development_stop": settled})
            population.extend(newcomers)
            parents = leaders[:args.parents]
            print(f"round {number + 1}: added {len(newcomers)} counters; development stop={settled}", flush=True)
            if settled:
                break
        payoff = extend_matrix(workers, population, payoff, args.matrix_pairs, args.seed)
        weights = equilibrium(payoff)
        provenance = fingerprint([args.model.resolve(), args.teams.resolve(), *(p.resolve() for p in args.observed),
                                  *[ROOT / p for p in ("pogo/battle.py", "pogo/agents.py", "pogo/learner.py",
                                                       "pogo/teamsearch.py", "pogo/teamlist.py", "pogo/gamedata.py",
                                                       "data/gamemaster.json", "data/rankings-1500.json", "data/cpm.json",
                                                       "scripts/self_consistent_teams.py")]])
        config = {k: str(v) if isinstance(v, Path) else [str(p) for p in v] if k == "observed" else v
                  for k, v in vars(args).items()}
        payload = {"about": "Approximate self-consistent mixture; explicit weights, trained bot both sides, "
                            "top supported pool, typical IVs/moves. Not a measured real ladder distribution.",
                   "pilot": "Learner(q=..., margin=0.02)", "pool": args.pool,
                   "method": "side-balanced empirical zero-sum game; fictitious play; accumulated best responses",
                   "command": shlex.join([sys.executable, *sys.argv]), "config": config,
                   "sha256": provenance, "rounds": histories, "searched_lineups": len(tried),
                   "teams": [{"team": list(t), "weight": float(w), "seen": seen.get(t, 0)}
                             for t, w in sorted(zip(population, weights), key=lambda tw: -tw[1])]}
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(payload, indent=1) + "\n")
        print(f"frozen list: {args.out}; starting independent counter search and held-out audit", flush=True)
        choices = candidates(ids, dex, population, parents, args.audit_random,
                             seed_for(args.seed, "audit-candidates"), args.exhaustive)
        audit_stages = [*args.stages[:-1], (args.stages[-1][0], args.audit_keep)]
        leaders = search(workers, choices, population, weights, ids, dex, audit_stages,
                         seed_for(args.seed, "audit-search"), "audit")
        # Test every member of the fitted population too; a support-only average of
        # 50% is a zero-sum identity, never evidence that outsiders cannot exploit it.
        finalists = sorted(set(leaders) | set(population))
        fresh_seed = seed_for(args.seed, "untouched-final")
        fresh = schedule(population, weights, ids, dex, args.finals, fresh_seed)
        results = evaluate(workers, finalists, fresh)
        ordered = sorted(finalists, key=lambda t: (-sum(results[t]), t))
        z = NormalDist().inv_cdf(1 - 0.05 / (2 * len(finalists)))
        tested = [{"team": list(t), **estimate(results[t]), "in_population": t in population} for t in ordered]
        for entry in tested:
            entry["simultaneous_margin"] = entry["margin"] * z / 1.96
        passed_point = tested[0]["score"] < 0.55
        passed_bound = all(e["score"] + e["simultaneous_margin"] < 0.55 for e in tested)
        # Same frozen candidates and dice against the old list quantify the change.
        old_rows = schedule([tuple(e["team"]) for e in entries], original_weights, ids, dex, args.finals, fresh_seed)
        # Choose these from search data, before looking at the final scores.
        old_checks = list(dict.fromkeys([*leaders, *[population[i] for i in np.argsort(-weights)[:args.audit_keep]]]))
        old_results = evaluate(workers, old_checks, old_rows)
        comparisons = []
        for t in old_checks:
            comparisons.append({"team": list(t), "old": estimate(old_results[t]), "new": estimate(results[t]),
                                "new_minus_old": estimate([a - b for a, b in zip(results[t], old_results[t])])})
        print(f"\nuntouched test: {args.finals} independent pairs = {2 * args.finals} battles per team; "
              f"{len(finalists)} teams; 95% pair-cluster margins")
        for entry in tested[:10]:
            print(f"  {' / '.join(entry['team']):56s} {100 * entry['score']:.1f}% ± {100 * entry['margin']:.1f}")
        print(f"Done-when counter check: {'PASS' if passed_point else 'FAIL'} (best found under 55%); "
              f"simultaneous 95% upper-bound check: {'PASS' if passed_bound else 'FAIL'}")
        print("Search scope: " + ("all legal line-ups screened; staged pruning can still miss counters" if args.exhaustive else
                                  f"sampled top-{args.pool} search; not proof about every possible team"))
        report = {"list_sha256": hashlib.sha256(args.out.read_bytes()).hexdigest(), "config": config,
                  "sha256": provenance, "audit_candidates": len(choices), "tested_teams": len(finalists),
                  "seed": fresh_seed, "results": tested, "old_new": comparisons,
                  "under_55_point_estimate": passed_point, "under_55_simultaneous_upper_bound": passed_bound,
                  "exhaustive": args.exhaustive, "elapsed_seconds": time.monotonic() - started,
                  "caution": "Finite simulated search with typical moves and IVs, not the real ladder. "
                             "Marginal 95% intervals use independent mirrored pairs. Simultaneous margins "
                             "use a Bonferroni normal approximation across all tested teams. "
                             "No final-test battles used for fitting, stopping, or candidate selection."}
        report_path = args.out.with_suffix(".report.json")
        report_path.write_text(json.dumps(report, indent=1) + "\n")
        print(f"report: {report_path}; elapsed {report['elapsed_seconds'] / 60:.1f} min", flush=True)


if __name__ == "__main__":
    main()
