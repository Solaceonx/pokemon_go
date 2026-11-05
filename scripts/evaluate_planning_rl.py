#!/usr/bin/env python3
"""Evaluate learned policies with independent public-world rollout search.

Validation selects search settings/weights. Lock and test reuse the original
paired, fresh-seed final protocol. bench uses training teams for timing only.
"""
from __future__ import annotations

import argparse
import functools
import hashlib
import json
import multiprocessing as mp
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import standalone_rl as base
from pogo.planning_rl import PlanningAgent

_source_hashes, _initialize, _prepare = base.source_hashes, base.initialize, base.prepare
_context = None


def sources():
    paths = [Path(__file__), ROOT / "pogo/planning_rl.py", ROOT / "pogo/battle.py", ROOT / "pogo/gamedata.py"]
    return {**_source_hashes(), **{p.relative_to(ROOT).as_posix():
            hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest() for p in paths}}


def configure(folder):
    base.source_hashes = sources
    base.initialize = functools.partial(initialize, config_path=str(folder / "experiment.json"))
    base.evaluate_job = play_job


def initialize(snapshot, deadline_unix=None, *, config_path):
    global _context
    _initialize(snapshot, deadline_unix)
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    opponent = Path(config_path).parent / "opponent.npz"
    if config["sources"] != sources() or base.digest(opponent) != config["opponent_policy_sha256"]:
        raise ValueError("planning implementation or opponent model changed")
    _context = {"config": config, "opponent_model": base.ActorCritic.load(opponent)[0]}


def play_job(task):
    checkpoint, case, greedy, opponent, samples = task
    if base._deadline_unix and time.time() >= base._deadline_unix:
        raise TimeoutError("authorized work budget exhausted")
    if checkpoint not in base._model_cache:
        base._model_cache.clear()
        base._model_cache[checkpoint] = base.ActorCritic.load(checkpoint)[0]
    model, rt = base._model_cache[checkpoint], base._runtime
    teams = [[rt.gd.default(sp) for sp in team] for team in case["teams"]]
    scores, winners, seconds, diagnostics = [], [], [], []
    for seat in (0, 1):
        battle_seed, agent_seed, foe_seed = case["seeds"][seat]
        me = PlanningAgent(model, _context["opponent_model"], rt.pool, seed=agent_seed,
                           **_context["config"]["planning"])
        foe = rt.opponent(opponent, foe_seed, samples)
        players = (me, foe) if seat == 0 else (foe, me)
        began = time.perf_counter()
        winner = rt.Battle(*teams, *players, seed=battle_seed).run()
        seconds.append(time.perf_counter() - began)
        winners.append(winner)
        scores.append(base.score(winner, seat))
        diagnostics.append({"searches": me.searches, "rollouts": me.rollouts,
                            "simulated_turns": me.simulated_turns})
    return {"index": case["index"], "scores": scores, "score": sum(scores) / 2,
            "seconds": seconds, "winners": winners, "planning_diagnostics": diagnostics}


def prepare(folder, args):
    existed = (folder / "experiment.json").exists()
    config = _prepare(folder, args)
    planning = {"samples": args.samples, "confidence": args.confidence,
                "stochastic_opponent": True}
    if existed:
        if config.get("planning") != planning or config["sources"] != sources() \
                or config["opponent_policy_sha256"] != base.digest(args.opponent_policy):
            raise ValueError("use a separate run for different planning settings/models")
    else:
        shutil.copyfile(args.opponent_policy, folder / "opponent.npz")
        config.update(planning=planning, opponent_policy_sha256=base.digest(folder / "opponent.npz"),
                      opponent_policy_origin=str(args.opponent_policy),
                      algorithm="RL policy with independent complete-battle public-world rollout improvement",
                      validation_modes=[True],
                      primary_endpoint="mixed field vs full frozen engine; fixed greedy rollout controller; two fresh final seed blocks")
        base.atomic_json(folder / "experiment.json", config)
        model, meta = base.ActorCritic.load(folder / "initial.npz")
        model.save(folder / "initial.npz", {**meta, "experiment": base.digest(folder / "experiment.json")})
        base.log_event(folder, "planning_registered", planning=planning,
                       opponent_policy_sha256=config["opponent_policy_sha256"])
    if base.digest(folder / "opponent.npz") != config["opponent_policy_sha256"]:
        raise ValueError("registered rollout opponent changed")
    rt = base.restore_snapshot(config)
    for name in ("pogo/battle.py", "pogo/gamedata.py"):
        normalize = lambda p: p.read_bytes().replace(b"\r\n", b"\n")
        if normalize(ROOT / name) != normalize(rt.path / name):
            raise ValueError("independent rules model differs from frozen battle rules")
    return config, rt


def validation(folder, config, runtime, args, *, bench=False):
    if (folder / "lock.json").exists():
        raise ValueError("planning run already locked; do not tune after testing")
    if bench:
        cases = base.schedule(runtime, "train", "mixed", base.stream_seed(args.seed, "planning_speed"), 2)
        base.atomic_json(folder / "bench_schedule.json", cases)
        label, split = "bench", "train"
    else:
        cases = json.loads((folder / "validation_schedule_mixed.json").read_text(encoding="utf-8"))
        label, split = "validation", "validation"
    checkpoint = folder / "initial.npz"
    model = base.ActorCritic.load(checkpoint)[0]
    with mp.get_context("spawn").Pool(args.workers, initializer=base.initialize,
                                     initargs=(str(ROOT / config["snapshot"]), config["budget_deadline_unix"])) as pool:
        result = base.evaluate(runtime, model, cases, folder / f"{label}_planning.jsonl", greedy=True,
                               metadata={"checkpoint_sha256": base.digest(checkpoint), "split": split,
                                         "experiment_sha256": base.digest(folder / "experiment.json")},
                               mapper=base.evaluation_mapper(pool, checkpoint, True))
    base.atomic_json(folder / f"{label}_summary.json", result)
    base.log_event(folder, label, **{k: result[k] for k in ("score", "ci95", "pairings", "seconds")})
    if not bench:
        state = {"phase": "validated", "best_round": 0, "best_greedy": True, "best_validation": result["score"]}
        model.save(folder / "best.npz", {"state": state, "selection": "validation_only"})
        base.atomic_json(folder / "state.json", state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "bench", "validate", "lock", "test"))
    parser.add_argument("--run", required=True)
    parser.add_argument("--start", type=Path, default=Path("runs/standalone-rl/ppo-v2/best.npz"))
    parser.add_argument("--opponent-policy", type=Path,
                        default=Path("runs/standalone-rl/engine-bc-v1/candidate_epoch_00016.npz"))
    parser.add_argument("--ref", default="59836c86f4c9ccf7e8d35ef7c94268e64c1a4ba9")
    parser.add_argument("--seed", type=int, default=37001)
    parser.add_argument("--workers", type=int, choices=(1, 2, 3), default=3)
    parser.add_argument("--samples", type=int, default=4)
    parser.add_argument("--confidence", type=float, default=.98)
    parser.add_argument("--validation-pairings", type=int, default=128)
    parser.add_argument("--pairings", type=int, default=1200)
    parser.add_argument("--budget-deadline", type=float, required=True)
    args = parser.parse_args()
    if Path(args.run).name != args.run or args.run in (".", ".."):
        parser.error("run must be one directory name")
    if args.samples < 0 or not 0 <= args.confidence <= 1 or min(args.validation_pairings, args.pairings) < 2:
        parser.error("invalid planning/evaluation settings")
    if args.seed < 0 or args.budget_deadline <= time.time():
        parser.error("invalid seed or expired work budget")
    args.network, args.hidden = "independent", 128
    folder = ROOT / "runs/standalone-rl" / args.run
    configure(folder)
    config, runtime = prepare(folder, args)
    if args.command in ("bench", "validate"):
        validation(folder, config, runtime, args, bench=args.command == "bench")
    elif args.command == "lock":
        base.lock(folder, config)
    elif args.command == "test":
        base.test(folder, config, args)


if __name__ == "__main__":
    mp.freeze_support()
    main()
