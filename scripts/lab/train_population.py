#!/usr/bin/env python3
"""Train the trained bot's networks against a population instead of copies of itself (lab-learn; fictitious play).

    python scripts/lab/train_population.py --run lab-learn/population --generations 3 --minutes 180 --workers 12
    python scripts/lab/train_population.py --run lab-learn/smoke --generations 2 --minutes 2 --workers 2 --check 40

The diagnosis (engine lab, 2026-11-24): training and judging both use our own bots as opponents, so each new network
is a best response to a copy of ourselves (fictitious play without the averaging), which carries over neither to the
engine nor to people. This keeps scripts/decide.py's per-decision learning (at every decision every option is played
out with the same dice, and a network learns who won after each) and changes who the opponents are. Each example
battle's opponent is drawn from a weighted population (--weights):

  rulebook   the varied crowd (pogo.agents.varied): the rulebook with every habit shifted
  past       the trained bot on one of the earlier networks, uniformly: the shipped one and its versions q_v1-q_v5,
             task 39's two rounds, and every generation of this run so far (fictitious play: the next network answers
             the average of what came before, not only the newest), margin 0.02, 0.05 or 0.1
  people     a person-like guess: the trained bot on a past network with pogo.engine.human_settings and the creators'
             shield calls (pogo.people_shield, runs/people-shield/shield.npz)
  imitation  a policy fitted to someone's choices, drawn from (pogo.lab.policy, --imitation PATH; by default the
             owner's, scripts/lab/fit_policy.py owner). Off by default: a player trained against it cannot be judged
             against it (task 42's rule)
  engine     the website engine (pogo.engine.Engine, --engine-samples imagined battles, horizon 20) on the shipped
             networks. Off by default: every play-out of a decision continues against the engine, so it is slow

and decide.py's own --both-sides (the bot on the newest network against itself, both players' decisions kept) and
--pvpoke-share (one against one against PvPoke's AI) on top. Generation g collects minutes / generations of examples
with the newest network as our pilot (the first piloted by --start), fits a fresh network on ALL the examples so far
(decide.py's cumulative fit, which is fictitious play's average best response), saves it as gen_g/q.npz and adds it
to the population. The networks have no mid_swap head (tasks 43 and 48: it makes the engine search mid-matchup swaps,
which lose). The overrule margin stays 0.02, the shipped bot's.

After each generation, with --check N: the new network against the shipped one on N pairs of battles (each pair of
teams both ways), the bot alone on both sides, and against the varied crowd on N battles, both networks on the same
battles: paired, with 95% margins. These are quick screens on bots; judge the result with scripts/engine_versus.py
(the bot alone and inside the website engine) and scripts/lab/versus_people.py (person-like opponents).

Files in runs/<run>/: gen_N/q.npz, q.npz (the last generation's), population.json (the networks in the population),
training.json (counts, times, checks); examples.npz (large; not in git; lets a stopped run resume: run the same
command again).
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
    os.environ.setdefault(_v, "1")
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
import decide  # noqa: E402
from pogo.agents import Planner, varied, varied_settings  # noqa: E402
from pogo.arena import low_priority, mean_and_margin  # noqa: E402
from pogo.battle import DRAW, Battle  # noqa: E402
from pogo.engine import human_settings  # noqa: E402
from pogo.learner import N_FEATURES, Q_HEADS, Learner, QNet  # noqa: E402

SHIPPED = "runs/general-decide/q.npz"
PAST = [SHIPPED] + [f"runs/general-decide/q_v{k}.npz" for k in range(1, 6)] + \
       [f"runs/engine-loop/round_{k}/q.npz" for k in (1, 2)]
PEOPLE_SHIELD = "runs/people-shield/shield.npz"
OWNER_POLICY = "runs/lab-learn/owner-policy/policy.npz"
KINDS = ("rulebook", "past", "people", "imitation", "engine")
HEADS = [h for h in Q_HEADS if h != "mid_swap"]
_cache: dict = {}


def weights_from(text: str) -> dict:
    out = dict.fromkeys(KINDS, 0.0)
    for part in filter(None, text.split(",")):
        name, value = part.split("=")
        if name not in KINDS:
            raise SystemExit(f"unknown kind {name!r}; kinds: {', '.join(KINDS)}")
        out[name] = float(value)
    if sum(out.values()) <= 0:
        raise SystemExit("--weights: give at least one kind a weight")
    return out


def net(path: str) -> QNet:
    if path not in _cache:
        _cache[path] = QNet.load(str(ROOT / path))
    return _cache[path]


def population_crowd(config: dict, pool: list):
    """An opponent for one example battle, drawn from the population (see the notes above)."""
    weights = config["weights"]
    kinds = [k for k in KINDS if weights[k] > 0]
    shares = [weights[k] for k in kinds]
    nets = [net(p) for p in config["population"]]
    imitation = None
    if weights["imitation"] > 0:
        from pogo.lab.policy import cached
        imitation = cached(config["imitation"])
    engine_model = None
    if weights["engine"] > 0:
        from pogo.evaluation import Evaluator
        engine_model = Evaluator.load(ROOT / "runs" / "eval" / "eval.npz").model

    def crowd(rng: random.Random):
        kind = rng.choices(kinds, shares)[0]
        if kind == "rulebook":
            return Planner(**varied_settings(rng, pool))
        if kind == "past":
            return Learner(q=rng.choice(nets), margin=rng.choice((0.02, 0.05, 0.1)), seed=rng.getrandbits(32))
        if kind == "people":
            return Learner(q=rng.choice(nets), margin=rng.choice((0.02, 0.05)), people_shield=PEOPLE_SHIELD,
                           **human_settings(rng, pool))
        if kind == "imitation":
            from pogo.lab.policy import PolicyPlayer
            return PolicyPlayer(pnet=imitation, q=net(SHIPPED), margin=0.02, sample=True, seed=rng.getrandbits(32))
        from pogo.engine import Engine
        from pogo.evaluation import Evaluator
        return Engine(Evaluator(engine_model), pool, rollout="bot", samples=config["engine_samples"], horizon=20,
                      edge=0.03, q=net(SHIPPED), margin=0.02, seed=rng.getrandbits(32))

    return crowd


def collect_job(job):
    """One worker's share of a generation's examples."""
    config, q_params, seconds, seed = job
    low_priority()
    _, pool, team, draw, _ = decide.world(config)
    q = QNet(q_params) if q_params else None
    return decide.collect(team, pool, q, config["margin"], population_crowd(config, pool), seconds, seed, draw,
                          pvpoke_share=config["pvpoke_share"], mid_swap=False, score=config["score"],
                          horizon=config["horizon"], both_sides=config["both_sides"])


def check_job(job):
    """Battles for the screens: (kind, start, count, seed, new q, base q, config) -> points by battle number.
    h2h: the new network against the base one, each pair of teams both ways; crowd: each network against the same
    varied opponent on the same battle."""
    kind, start, count, seed, new_params, base_params, config = job
    low_priority()
    _, pool, _, draw, _ = decide.world(config)
    new, base = QNet(new_params), QNet(base_params)
    out = {}
    for n in range(start, start + count):
        rng = random.Random(seed * 1_000_003 + n)
        a, b = draw(rng), draw(rng)
        dice, seeds = rng.getrandbits(32), [rng.getrandbits(32) for _ in range(4)]
        if kind == "h2h":
            pair = []
            for ours, theirs in ((a, b), (b, a)):
                winner = Battle(ours, theirs, Learner(q=new, margin=config["margin"], seed=seeds[0]),
                                Learner(q=base, margin=0.02, seed=seeds[1]), seed=dice).run()
                pair.append(1.0 if winner == 0 else 0.5 if winner == DRAW else 0.0)
            out[n] = sum(pair) / 2
        else:
            got = []
            for q, margin in ((new, config["margin"]), (base, 0.02)):
                opponent = varied(random.Random(seeds[2]), pool)
                winner = Battle(a, b, Learner(q=q, margin=margin, seed=seeds[0]), opponent, seed=dice).run()
                got.append(1.0 if winner == 0 else 0.5 if winner == DRAW else 0.0)
            out[n] = (got[0], got[1])
    return kind, out


def run_checks(pool, new: QNet, base: QNet, count: int, seed: int, config: dict, workers: int) -> dict:
    chunk = max(1, count // (4 * workers))
    jobs = [(kind, s, min(chunk, count - s), seed, new.params, base.params, config)
            for kind in ("h2h", "crowd") for s in range(0, count, chunk)]
    got = {"h2h": {}, "crowd": {}}
    for kind, out in pool.imap_unordered(check_job, jobs):
        got[kind].update(out)
    h2h = [got["h2h"][n] for n in sorted(got["h2h"])]
    crowd = [got["crowd"][n] for n in sorted(got["crowd"])]
    result = {"pairings": len(h2h), "head_to_head": list(mean_and_margin(h2h)),
              "crowd_new": list(mean_and_margin([a for a, _ in crowd])),
              "crowd_base": list(mean_and_margin([b for _, b in crowd])),
              "crowd_change": list(mean_and_margin([a - b for a, b in crowd]))}
    h, hm = result["head_to_head"]
    c, cm = result["crowd_change"]
    print(f"  check, seed {seed}: head to head against the shipped bot {100 * h:.1f}% ± {100 * hm:.1f} ({len(h2h)} pairs both "
          f"ways); against the crowd {100 * result['crowd_new'][0]:.1f}% against {100 * result['crowd_base'][0]:.1f}%, "
          f"{100 * c:+.1f} ± {100 * cm:.1f} points (same {len(crowd)} battles)", flush=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", required=True, help="folder under runs/, e.g. lab-learn/population")
    parser.add_argument("--generations", type=int, default=3)
    parser.add_argument("--minutes", type=float, default=60, help="minutes of collecting, over all generations")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--weights", default="rulebook=0.3,past=0.45,people=0.25",
                        help="opponent kinds and their weights: " + ", ".join(KINDS))
    parser.add_argument("--past", nargs="*", default=None, help="networks in the population at the start (default: the "
                        "shipped one, q_v1-q_v5 and task 39's rounds, those present)")
    parser.add_argument("--imitation", default=OWNER_POLICY, help="the policy the 'imitation' kind plays")
    parser.add_argument("--engine-samples", type=int, default=4, help="imagined battles of the 'engine' kind")
    parser.add_argument("--both-sides", type=float, default=0.2)
    parser.add_argument("--pvpoke-share", type=float, default=0.05)
    parser.add_argument("--start", default=SHIPPED, help="the network piloting the first generation ('' for the rulebook)")
    parser.add_argument("--field", choices=("usual", "mixed"), default="mixed")
    parser.add_argument("--teams", help="with --field usual: draw half the teams from this list (data/teams.json)")
    parser.add_argument("--score", choices=("result", "margin"), default="result")
    parser.add_argument("--horizon", type=int, default=0, help="play-outs stop after this many turns, judged by the "
                        "evaluation (decide.py --horizon); 0 plays to the end")
    parser.add_argument("--hidden", type=int, default=48)
    parser.add_argument("--margin", type=float, default=0.02)
    parser.add_argument("--check", type=int, default=0, help="after each generation, this many pairs head to head "
                        "against the shipped bot and battles against the crowd")
    parser.add_argument("--seed", type=int, default=4242)
    args = parser.parse_args()
    if args.generations <= 0 or args.minutes <= 0 or args.workers <= 0:
        parser.error("--generations, --minutes and --workers must be positive")
    low_priority()
    weights = weights_from(args.weights)
    folder = ROOT / "runs" / args.run
    folder.mkdir(parents=True, exist_ok=True)
    past = args.past if args.past is not None else [p for p in PAST if (ROOT / p).exists()]
    receipt_path = folder / "training.json"
    receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else {"arguments": vars(args), "generations": []}
    done = [g["generation"] for g in receipt["generations"] if (folder / f"gen_{g['generation']}" / "q.npz").exists()]
    population = list(past) + [f"runs/{args.run}/gen_{g}/q.npz" for g in done]
    stored = {head: (np.zeros((0, N_FEATURES)), np.zeros((0, n))) for head, n in Q_HEADS.items()}
    if done and (folder / "examples.npz").exists():
        saved = np.load(folder / "examples.npz")
        stored.update({h: (saved[f"{h}_x"], saved[f"{h}_y"]) for h in Q_HEADS if f"{h}_x" in saved})
    q = net(population[-1]) if done else (net(args.start) if args.start else None)
    config = {"team": None, "teams": args.teams, "opponents": [], "exploit": None, "pool": 50, "forms": False,
              "field": args.field, "weights": weights, "population": population, "imitation": args.imitation,
              "engine_samples": args.engine_samples, "both_sides": args.both_sides, "pvpoke_share": args.pvpoke_share,
              "score": args.score, "horizon": args.horizon, "margin": args.margin}
    print(f"run: runs/{args.run}; field {args.field}; opponents " + ", ".join(f"{k} {v:g}" for k, v in weights.items() if v)
          + f"; both sides {args.both_sides:g}, PvPoke 1v1 {args.pvpoke_share:g}; {args.workers} workers", flush=True)
    print(f"population at the start: {', '.join(population)}", flush=True)
    if done:
        print(f"resuming after generation {done[-1]} with {sum(len(x) for x, _ in stored.values())} examples", flush=True)
    seconds = 60 * args.minutes / args.generations
    ctx = multiprocessing.get_context("spawn")
    with ctx.Pool(args.workers) as workers:
        for g in range(len(done) + 1, args.generations + 1):
            t0 = time.time()
            config["population"] = population
            jobs = [(config, q.params if q else None, seconds, args.seed + 100 * g + w) for w in range(args.workers)]
            parts = workers.map(collect_job, jobs)
            fresh = {h: (np.vstack([p[0][h][0] for p in parts]), np.vstack([p[0][h][1] for p in parts])) for h in Q_HEADS}
            battles, pvpoke_battles = sum(p[1] for p in parts), sum(p[2] for p in parts)
            for h in Q_HEADS:
                stored[h] = (np.vstack([stored[h][0], fresh[h][0]]), np.vstack([stored[h][1], fresh[h][1]]))
            collected = {h: len(fresh[h][0]) for h in HEADS}
            print(f"\ngeneration {g}: {battles} battles ({pvpoke_battles} 1v1 against PvPoke) in {(time.time() - t0) / 60:.1f} min; "
                  "new examples " + ", ".join(f"{n} {h}" for h, n in collected.items()) + "; all so far "
                  + ", ".join(f"{len(stored[h][0])} {h}" for h in HEADS), flush=True)
            new = QNet(seed=args.seed + g, hidden=args.hidden)
            new.params = {h: ps for h, ps in new.params.items() if h in HEADS and len(stored[h][0])}
            for h in new.params:
                x, y = stored[h]
                print(f"  {h}: average result by option " + " ".join(f"{100 * r:.1f}%" for r in np.nanmean(y, axis=0)), flush=True)
                new.fit(h, x, y, seed=args.seed + g)
            path = f"runs/{args.run}/gen_{g}/q.npz"
            new.save(ROOT / path)
            entry = {"generation": g, "battles": battles, "pvpoke_battles": pvpoke_battles, "new_examples": collected,
                     "all_examples": {h: len(stored[h][0]) for h in HEADS}, "population": list(population),
                     "minutes": round((time.time() - t0) / 60, 1)}
            if args.check:
                entry["check"] = run_checks(workers, new, net(SHIPPED), args.check, args.seed + 7 + g, config, args.workers)
            population = population + [path]
            q = new
            _cache[path] = new
            receipt["generations"] = [e for e in receipt["generations"] if e["generation"] != g] + [entry]
            # saved with the generation, so a stopped run resumes with exactly the examples of the generations it kept
            np.savez_compressed(folder / "examples.npz", **{f"{h}_{k}": a for h, xy in stored.items() for k, a in zip("xy", xy)})
            receipt_path.write_bytes((json.dumps(receipt, indent=1) + "\n").encode("utf-8"))
    q.save(folder / "q.npz")
    (folder / "population.json").write_bytes((json.dumps({"population": population, "weights": weights}, indent=1) + "\n").encode("utf-8"))
    print(f"\nfiles: runs/{args.run}/q.npz (generation {args.generations}), gen_N/q.npz, population.json, training.json; "
          f"examples.npz is large and stays out of git", flush=True)


if __name__ == "__main__":
    main()
