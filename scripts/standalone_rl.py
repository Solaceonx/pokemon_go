#!/usr/bin/env python3
"""Standalone RL: freeze, train, lock, then evaluate once on untouched teams.

  python scripts/standalone_rl.py prepare --run first
  python scripts/standalone_rl.py train --run first --hours 36 --workers 3
  python scripts/standalone_rl.py lock --run first
  python scripts/standalone_rl.py test --run first --pairings 1200 --workers 3

All phases resume. Test is unavailable before lock; training is forbidden after
lock. Failed experiments need a new run and fresh final-test seeds.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import multiprocessing as mp
import os
import platform
import random
import secrets
import subprocess
import sys
import time
from pathlib import Path

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_var] = "1"

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pogo.arena import low_priority
from pogo.rl_experiment import (BASELINE, FrozenRuntime, SPLIT_SALT, atomic_json, canonical_json_digest, digest, evaluate,
                                freeze, intervals, play_case, schedule, score, stream_seed, team_key)
from pogo.standalone_rl import ActorCritic, HEADS, N_FEATURES, StandaloneAgent, encode, mask_for
from pogo.standalone_rl_v2 import ActorCritic as IndependentActorCritic

_runtime = None
_model_cache = {}
_deadline_unix = None


def log_event(folder, event, **values):
    row = {"event": event, "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **values}
    with (folder / "experiments.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")
    print(json.dumps(row, sort_keys=True), flush=True)


def source_hashes():
    paths = [ROOT / "pogo/standalone_rl.py", ROOT / "pogo/standalone_rl_v2.py",
             ROOT / "pogo/rl_experiment.py", Path(__file__)]
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest() for p in paths}


def restore_snapshot(config):
    snapshot = ROOT / config["snapshot"]
    if not (snapshot / "manifest.json").exists():
        freeze(config["commit"], cache=snapshot.parent)
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    expected = config.get("frozen_manifest_canonical_sha256")
    actual = canonical_json_digest(manifest) if expected else digest(snapshot / "manifest.json")
    if actual != (expected or config["frozen_manifest_sha256"]):
        raise ValueError("frozen snapshot manifest no longer matches experiment")
    return FrozenRuntime(snapshot)


def prepare(folder, args):
    path = folder / "experiment.json"
    if path.exists():
        config = json.loads(path.read_text(encoding="utf-8"))
        restore_snapshot(config)
        print(json.dumps(config, indent=2), flush=True)
        return config
    snapshot = freeze(args.ref)
    folder.mkdir(parents=True, exist_ok=True)
    runtime = FrozenRuntime(snapshot)
    config = {"schema": 1, "run": folder.name, "seed": args.seed, "created_unix": time.time(),
              "implementation_git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "budget_deadline_unix": args.budget_deadline or time.time() + 48 * 3600,
              "snapshot": snapshot.relative_to(ROOT).as_posix(), "commit": runtime.manifest["commit"],
              "frozen_manifest_sha256": digest(snapshot / "manifest.json"), "baseline": BASELINE,
              "frozen_manifest_canonical_sha256": canonical_json_digest(runtime.manifest),
              "split_salt": SPLIT_SALT, "split": "70% train / 15% validation / 15% test; unordered trios; same species allowed",
              "algorithm": "masked actor-critic PPO; terminal win=+1, draw=0, loss=-1; optional public opponent demonstrations",
              "network": args.network,
              "primary_endpoint": "mixed field vs full frozen engine; greedy/stochastic mode selected on validation only; two fresh seed blocks",
              "validation_modes": [False, True],
              "acceptance": "each mixed seed block: pairing bootstrap 95% lower > .5 AND Hoeffding one-sided 97.5% lower > .5; each standard seed block: bootstrap lower > .5",
              "test_seeds": "generated only after checkpoint lock; never used for selection",
              "numpy": np.__version__, "python": sys.version, "platform": platform.platform(),
              "sources": source_hashes(), "review_pr": "https://github.com/Solaceonx/pokemon_go/pull/10"}
    constructor = IndependentActorCritic if args.network == "independent" else ActorCritic
    if args.start:
        model, initial_meta = constructor.load(args.start)
        config["initialization"] = {"checkpoint": str(args.start), "sha256": digest(args.start), "metadata": initial_meta}
    else:
        model, initial_meta = constructor(args.seed, hidden=args.hidden), {"stage": "random"}
    atomic_json(path, config)
    atomic_json(folder / "frozen_manifest.json", runtime.manifest)
    for field in ("mixed", "standard"):
        cases = schedule(runtime, "validation", field, stream_seed(args.seed, "validation"), args.validation_pairings)
        atomic_json(folder / f"validation_schedule_{field}.json", cases)
    model.save(folder / "initial.npz", {"initialization": initial_meta, "experiment": digest(path)})
    atomic_json(folder / "state.json", {"phase": "bootstrap", "round": 0, "bootstrap_games": 0,
                                         "training_games": 0, "training_seconds": 0, "best_validation": -1.})
    log_event(folder, "prepared", commit=config["commit"], features=N_FEATURES, network=args.network,
              parameters=sum(p.size for p in model.params.values()))
    return config


def initialize(snapshot, deadline_unix=None):
    global _runtime, _deadline_unix
    low_priority()
    _runtime = FrozenRuntime(snapshot)
    _deadline_unix = deadline_unix


class TeacherRecorder:
    sees_move = False

    def __init__(self, teacher, log):
        self.teacher, self.log = teacher, log

    def call(self, view, head, energy=None):
        mask = mask_for(view, head)
        x = encode(view, energy) if mask.sum() > 1 else None
        if head == "act":
            action = self.teacher.act(view)
        elif head == "shield":
            action = int(self.teacher.shield(view, energy))
        else:
            action = self.teacher.replace(view)
        if x is not None:
            if not mask[action]:
                raise ValueError("illegal teacher choice")
            self.log.append((head, x, mask, action, 0., 0.))
        return action

    def act(self, view):
        return self.call(view, "act")

    def shield(self, view, energy):
        return self.call(view, "shield", energy)

    def replace(self, view):
        return self.call(view, "replace")

    def saw_throw(self, *args):
        self.teacher.saw_throw(*args)

    def saw_shield(self, *args):
        self.teacher.saw_shield(*args)


def advantages(log, reward, lam=.98):
    """GAE within ONE episode/side; gamma=1, terminal bootstrap=0."""
    out, gae, next_value = [], 0., 0.
    for row in reversed(log):
        value = row[5]
        delta = (reward if not out else 0.) + next_value - value
        gae = delta + lam * gae
        out.append((*row, gae, gae + value))
        next_value = value
    return out[::-1]


def collect_job(task):
    kind, checkpoint, seed, start, count, samples, round_index = task
    runtime = _runtime
    if checkpoint and checkpoint not in _model_cache:
        _model_cache.clear()
        _model_cache[checkpoint] = ActorCritic.load(checkpoint)[0]
    model = _model_cache.get(checkpoint)
    rows, summaries, demonstrations = [], [], []
    for index in range(start, start + count):
        if _deadline_unix and time.time() >= _deadline_unix:
            raise TimeoutError("authorized experiment time budget exhausted")
        domain = "bootstrap" if kind == "bootstrap" else "train"
        rng = random.Random(stream_seed(seed, domain, index, "teams"))
        teams = [runtime.draw(rng, "train") for _ in range(2)]
        seeds = [stream_seed(seed, domain, index, name) for name in ("battle", "agent", "opponent")]
        logs, demo_log = [[], []], []
        if kind == "bootstrap":
            players = [TeacherRecorder(runtime.teacher(seeds[i + 1]), logs[i]) for i in range(2)]
            opponent_name = "learner"
            seats = [0, 1]
        else:
            seat = index % 2
            pilot = StandaloneAgent(model, seeds[1], log=logs[seat])
            choice = random.Random(stream_seed(seed, "opponent_kind", index)).random()
            if choice < .8:
                opponent_name = "engine"
                foe = TeacherRecorder(runtime.engine(seeds[2], samples), demo_log)
            elif choice < .9:
                opponent_name = "learner"
                foe = runtime.teacher(seeds[2])
            else:
                opponent_name = "self"
                foe = StandaloneAgent(model, seeds[2])
            players = (pilot, foe) if seat == 0 else (foe, pilot)
            seats = [seat]
        before = time.perf_counter()
        winner = runtime.Battle(*teams, *players, seed=seeds[0]).run()
        for seat in seats:
            reward = 2 * score(winner, seat) - 1
            rows.extend(advantages(logs[seat], reward, lam=1. if kind == "bootstrap" else .98))
        demonstrations.extend((*row, 0., 0.) for row in demo_log)
        summaries.append({"index": index, "kind": opponent_name, "samples": samples,
                          "score": score(winner, seats[0]), "decisions": sum(map(len, logs)),
                          "public_teacher_decisions": len(demo_log),
                          "teams": [team_key(t) for t in teams], "seeds": seeds,
                          "seconds": time.perf_counter() - before})
    return rows, summaries, demonstrations


def grouped(rows):
    out = {}
    for head in HEADS:
        rs = [r for r in rows if r[0] == head]
        if not rs:
            continue
        out[head] = {"x": np.stack([r[1] for r in rs]), "mask": np.stack([r[2] for r in rs]),
                     "actions": np.array([r[3] for r in rs]), "logp": np.array([r[4] for r in rs], np.float32),
                     "advantages": np.array([r[6] for r in rs], np.float32),
                     "returns": np.array([r[7] for r in rs], np.float32)}
    return out


def save_batch(path, groups):
    # Large examples are local and ignored; atomic to avoid half-written resumes.
    tmp = path.with_suffix(".tmp")
    with tmp.open("wb") as f:
        np.savez_compressed(f, **{f"{h}:{k}": v for h, data in groups.items() for k, v in data.items()})
    tmp.replace(path)


def fit(model, data, seed, *, epochs, rate, imitation=False, anchor_model=None, anchor=0., demos=None, demo_weight=0.):
    rng, metrics = np.random.default_rng(seed), []
    for head, group in data.items():
        advantage = group["advantages"]
        advantage = (advantage - advantage.mean()) / max(float(advantage.std()), 1e-5)
        teacher = anchor_model.forward(group["x"], head, group["mask"])[0] if anchor_model else None
        stop = False
        for epoch in range(epochs):
            order = rng.permutation(len(advantage))
            kls = []
            for start in range(0, len(order), 512):
                pick = order[start:start + 512]
                extra = {}
                if isinstance(model, IndependentActorCritic) and demos and head in demos and demo_weight:
                    demo = demos[head]
                    dpick = rng.integers(len(demo["actions"]), size=len(pick))
                    extra = {"demo_x": demo["x"][dpick], "demo_mask": demo["mask"][dpick],
                             "demo_actions": demo["actions"][dpick], "demo_weight": demo_weight}
                result = model.update(head, group["x"][pick], group["mask"][pick], group["actions"][pick],
                                      group["returns"][pick], advantages=advantage[pick], old_logp=group["logp"][pick],
                                      imitation=imitation, rate=rate, teacher=teacher[pick] if teacher is not None else None,
                                      anchor=anchor, **extra)
                metrics.append({"head": head, "epoch": epoch, **result})
                kls.append(result["kl"])
            if not imitation and np.mean(kls) > .03:
                stop = True
                break
        p = model.forward(group["x"], head, group["mask"])[0]
        yield head, {"rows": len(advantage), "epochs": epoch + 1, "kl_stop": stop,
                     "agreement": float((p.argmax(axis=1) == group["actions"]).mean()),
                     **{k: float(np.mean([r[k] for r in metrics if r["head"] == head]))
                        for k in ("policy_loss", "value_mse", "entropy", "kl", "grad_norm")},
                     "demo_loss": float(np.mean([r.get("demo_loss", 0.) for r in metrics if r["head"] == head]))}


def collect(pool, kind, checkpoint, config, start, count, samples, round_index):
    tasks = [(kind, str(checkpoint) if checkpoint else None, config["seed"], i, min(16, start + count - i), samples, round_index)
             for i in range(start, start + count, 16)]
    rows, games, demos = [], [], []
    # Ordered map makes dataset order independent of worker scheduling.
    for part, summary, demonstrations in pool.imap(collect_job, tasks):
        rows.extend(part)
        games.extend(summary)
        demos.extend(demonstrations)
    return grouped(rows), games, grouped(demos)


def evaluate_job(task):
    if _deadline_unix and time.time() >= _deadline_unix:
        raise TimeoutError("authorized experiment time budget exhausted")
    checkpoint, case, greedy, opponent, samples = task
    if checkpoint not in _model_cache:
        _model_cache.clear()
        _model_cache[checkpoint] = ActorCritic.load(checkpoint)[0]
    return play_case(_runtime, _model_cache[checkpoint], case, greedy=greedy, opponent=opponent, samples=samples)


def evaluation_mapper(pool, checkpoint, greedy=False, opponent="engine", samples=32):
    return lambda pending: pool.imap(evaluate_job, [(str(checkpoint), case, greedy, opponent, samples) for case in pending])


def validation(folder, runtime, model, checkpoint, round_index, pool, greedy=False):
    cases = json.loads((folder / "validation_schedule_mixed.json").read_text(encoding="utf-8"))
    mode = "greedy" if greedy else "stochastic"
    result = evaluate(runtime, model, cases, folder / f"validation_{round_index:05d}_{mode}.jsonl", greedy=greedy,
                      metadata={"checkpoint_sha256": digest(checkpoint), "split": "validation"},
                      mapper=evaluation_mapper(pool, checkpoint, greedy))
    atomic_json(folder / f"validation_summary_{round_index:05d}_{mode}.json", result)
    log_event(folder, "validation", round=round_index, score=result["score"], ci95=result["ci95"],
              seconds=result["seconds"], checkpoint=checkpoint.name, greedy=greedy)
    return result


def validate_modes(folder, runtime, model, checkpoint, round_index, pool, config):
    measured = [(validation(folder, runtime, model, checkpoint, round_index, pool, greedy), greedy)
                for greedy in config.get("validation_modes", [False])]
    return max(measured, key=lambda item: item[0]["score"])


def train(folder, config, args):
    if (folder / "lock.json").exists():
        raise ValueError("run is locked for final evaluation; create a new run to train again")
    path = folder / "state.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    if config["sources"] != source_hashes():
        if state["training_games"] or state["bootstrap_games"]:
            raise ValueError("training source changed; create a new run rather than mix experiment versions")
        config["sources"] = source_hashes()
        atomic_json(folder / "experiment.json", config)
    runtime = restore_snapshot(config)
    started = time.monotonic()
    deadline = started + max(0, min(args.hours * 3600 - state["training_seconds"],
                                   config["budget_deadline_unix"] - args.test_reserve_hours * 3600 - time.time()))
    if state["phase"] == "ppo":
        committed = folder / f"round_{state['round']:05d}.npz"
        committed = committed if committed.exists() else folder / "bootstrap.npz"
    elif state["bootstrap_games"]:
        committed = folder / f"bootstrap_step_{state['bootstrap_games']:07d}.npz"
    else:
        committed = folder / "initial.npz"
    model, _ = ActorCritic.load(committed)
    args_record = {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()}
    log_event(folder, "train_start", arguments=args_record, resume=state)
    with mp.get_context("spawn").Pool(args.workers, initializer=initialize,
                                     initargs=(str(ROOT / config["snapshot"]), config["budget_deadline_unix"])) as pool:
        while state["bootstrap_games"] < args.bootstrap_games and time.monotonic() < deadline:
            count = min(args.batch_games, args.bootstrap_games - state["bootstrap_games"])
            data, games, _ = collect(pool, "bootstrap", None, config, state["bootstrap_games"], count, 0, 0)
            shard = folder / f"bootstrap_{state['bootstrap_games']:07d}.npz"
            save_batch(shard, data)
            metrics = dict(fit(model, data, stream_seed(config["seed"], "fit_bootstrap", state["bootstrap_games"]),
                               epochs=args.bootstrap_epochs, rate=1e-3, imitation=True))
            state["bootstrap_games"] += count
            state["training_seconds"] += time.monotonic() - started
            started = time.monotonic()
            model.save(folder / f"bootstrap_step_{state['bootstrap_games']:07d}.npz", {"state": state, "stage": "bootstrap"})
            model.save(folder / "latest.npz", {"state": state, "stage": "bootstrap"})
            atomic_json(path, state)
            log_event(folder, "bootstrap", games=state["bootstrap_games"], metrics=metrics,
                      seconds=sum(g["seconds"] for g in games), decisions=sum(g["decisions"] for g in games))
        if state["phase"] == "bootstrap" and state["bootstrap_games"] >= args.bootstrap_games:
            model.save(folder / "bootstrap.npz", {"state": state, "stage": "bootstrap_complete"})
            result, greedy = validate_modes(folder, runtime, model, folder / "bootstrap.npz", 0, pool, config)
            state.update(phase="ppo", best_validation=result["score"], best_round=0, best_greedy=greedy)
            model.save(folder / "best.npz", {"state": state, "selection": "validation_only"})
            state["training_seconds"] += time.monotonic() - started
            started = time.monotonic()
            atomic_json(path, state)
        anchor_model = ActorCritic.load(folder / "bootstrap.npz")[0] if (folder / "bootstrap.npz").exists() else None
        while state["phase"] == "ppo" and state["round"] < args.max_rounds and time.monotonic() < deadline:
            round_index = state["round"] + 1
            # Frozen search mechanics, fewer samples only for early curriculum.
            samples = args.train_samples if round_index <= args.curriculum_rounds else 32
            checkpoint = folder / f"round_{state['round']:05d}.npz"
            if not checkpoint.exists():
                model.save(checkpoint, {"state": state, "stage": "ppo_behavior"})
            data, games, demos = collect(pool, "ppo", checkpoint, config, state["training_games"], args.batch_games, samples, round_index)
            save_batch(folder / f"replay_{round_index:05d}.npz", data)
            save_batch(folder / f"demo_{round_index:05d}.npz", demos)
            atomic_json(folder / f"training_games_{round_index:05d}.json", games)
            metrics = dict(fit(model, data, stream_seed(config["seed"], "ppo_update", round_index),
                               epochs=args.ppo_epochs, rate=args.rate, anchor_model=anchor_model, anchor=args.anchor,
                               demos=demos, demo_weight=args.demo_weight))
            state["round"], state["training_games"] = round_index, state["training_games"] + len(games)
            model.save(folder / "latest.npz", {"state": state, "stage": "ppo"})
            checkpoint = folder / f"round_{round_index:05d}.npz"
            model.save(checkpoint, {"state": state, "stage": "ppo"})
            scores = {kind: float(np.mean([g["score"] for g in games if g["kind"] == kind]))
                      for kind in sorted({g["kind"] for g in games})}
            log_event(folder, "ppo", round=round_index, total_games=state["training_games"], scores=scores,
                      engine_samples=samples, metrics=metrics, seconds=sum(g["seconds"] for g in games),
                      decisions=sum(g["decisions"] for g in games), public_teacher_decisions=sum(g["public_teacher_decisions"] for g in games),
                      demo_weight=args.demo_weight, checkpoint_sha256=digest(checkpoint))
            if round_index % args.validation_every == 0:
                result, greedy = validate_modes(folder, runtime, model, checkpoint, round_index, pool, config)
                if result["score"] > state["best_validation"]:
                    state.update(best_validation=result["score"], best_round=round_index, best_greedy=greedy)
                    model.save(folder / "best.npz", {"state": state, "selection": "validation_only"})
                    log_event(folder, "best", round=round_index, validation_score=result["score"])
            state["training_seconds"] += time.monotonic() - started
            started = time.monotonic()
            atomic_json(path, state)
            if args.target_validation and state["best_validation"] >= args.target_validation:
                break
    log_event(folder, "training_stopped", state=state, reason="round or time budget")


def lock(folder, config):
    path = folder / "lock.json"
    if path.exists():
        print(path.read_text(encoding="utf-8"))
        return
    model, meta = ActorCritic.load(folder / "best.npz")
    model.save(folder / "locked.npz", {**meta, "locked": True})
    record = {"checkpoint_sha256": digest(folder / "locked.npz"), "frozen_commit": config["commit"],
              "experiment_sha256": digest(folder / "experiment.json"), "sources": source_hashes(),
              "selected_metadata": meta, "test_seeds": [secrets.randbits(63), secrets.randbits(63)],
              "selected_unix": time.time(), "greedy": bool(meta.get("state", {}).get("best_greedy", False))}
    atomic_json(path, record)
    log_event(folder, "locked", **record)


def test(folder, config, args):
    locked = json.loads((folder / "lock.json").read_text(encoding="utf-8"))
    checkpoint = folder / "locked.npz"
    if digest(checkpoint) != locked["checkpoint_sha256"] or source_hashes() != locked["sources"]:
        raise ValueError("locked checkpoint or evaluation implementation changed")
    if digest(folder / "experiment.json") != locked["experiment_sha256"]:
        raise ValueError("experiment changed after lock")
    model = ActorCritic.load(checkpoint)[0]
    runtime = restore_snapshot(config)
    plan_path = folder / "test_plan.json"
    plan = {"pairings_per_seed_and_field": args.pairings, "fields": ["mixed", "standard"], "opponent": "engine",
            "seeds": locked["test_seeds"], "checkpoint_sha256": digest(checkpoint), "greedy": locked["greedy"]}
    if plan_path.exists() and json.loads(plan_path.read_text(encoding="utf-8")) != plan:
        raise ValueError("final test sample size already committed; do not change it after seeing results")
    atomic_json(plan_path, plan)
    results = {}
    with mp.get_context("spawn").Pool(args.workers, initializer=initialize,
                                     initargs=(str(ROOT / config["snapshot"]), config["budget_deadline_unix"])) as pool:
        for field in plan["fields"]:
            for block, seed in enumerate(plan["seeds"]):
                cases_path = folder / f"test_schedule_{field}_{block}.json"
                cases = schedule(runtime, "test", field, seed, args.pairings)
                atomic_json(cases_path, cases)
                result = evaluate(runtime, model, cases, folder / f"test_{field}_{block}.jsonl", greedy=locked["greedy"],
                                  metadata={"checkpoint_sha256": digest(checkpoint), "split": "test", "seed": seed},
                                  mapper=evaluation_mapper(pool, checkpoint, locked["greedy"]))
                results[f"{field}_{block}"] = result
                atomic_json(folder / "test_results.json", {"lock": locked, "plan": plan, "results": results})
                log_event(folder, "test_block", field=field, block=block, **{k: result[k] for k in ("score", "ci95", "hoeffding_lower97_5", "pairings", "seconds")})
    primary = [results[f"mixed_{block}"] for block in range(2)]
    standard = [results[f"standard_{block}"] for block in range(2)]
    passed = all(r["ci95"][0] > .5 and r["hoeffding_lower97_5"] > .5 for r in primary) and all(r["ci95"][0] > .5 for r in standard)
    report = {"lock": locked, "plan": plan, "results": results, "reliably_beats_frozen_engine": passed,
              "scope": "simulated public exact state; unseen unordered team trios, familiar species; no camera/human claim"}
    atomic_json(folder / "test_results.json", report)
    log_event(folder, "final", reliably_beats_frozen_engine=passed)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("prepare", "train", "lock", "test", "run"))
    parser.add_argument("--run", required=True)
    parser.add_argument("--ref", default="origin/main")
    parser.add_argument("--seed", type=int, default=37001)
    parser.add_argument("--workers", type=int, choices=(1, 2, 3), default=3)
    parser.add_argument("--hours", type=float, default=36)
    parser.add_argument("--test-reserve-hours", type=float, default=10)
    parser.add_argument("--budget-deadline", type=float, help="absolute Unix deadline across all runs in the user's work budget")
    parser.add_argument("--network", choices=("shared", "independent"), default="independent")
    parser.add_argument("--start", type=Path, help="warm-start weights; schema-1 migration preserves policy and resets Adam")
    parser.add_argument("--hidden", type=int, default=128)
    parser.add_argument("--bootstrap-games", type=int, default=4096)
    parser.add_argument("--bootstrap-epochs", type=int, default=8)
    parser.add_argument("--batch-games", type=int, default=256)
    parser.add_argument("--max-rounds", type=int, default=10000)
    parser.add_argument("--ppo-epochs", type=int, default=4)
    parser.add_argument("--rate", type=float, default=2e-4)
    parser.add_argument("--anchor", type=float, default=.02)
    parser.add_argument("--demo-weight", type=float, default=.1)
    parser.add_argument("--target-validation", type=float, default=0., help="optional early-stop validation score, never a test score")
    parser.add_argument("--train-samples", type=int, default=8)
    parser.add_argument("--curriculum-rounds", type=int, default=8)
    parser.add_argument("--validation-every", type=int, default=4)
    parser.add_argument("--validation-pairings", type=int, default=128)
    parser.add_argument("--pairings", type=int, default=1200)
    args = parser.parse_args()
    if Path(args.run).name != args.run or args.run in (".", ".."):
        parser.error("--run must be one directory name")
    if min(args.batch_games, args.bootstrap_epochs, args.ppo_epochs, args.validation_every) < 1 or args.pairings < 2 or args.validation_pairings < 2:
        parser.error("positive training sizes and at least two evaluation pairings required")
    if (args.seed < 0 or args.bootstrap_games < 0 or args.max_rounds < 0 or args.curriculum_rounds < 0
            or args.train_samples < 1 or args.hours <= 0 or args.test_reserve_hours < 0
            or args.rate <= 0 or args.anchor < 0 or args.demo_weight < 0):
        parser.error("invalid seed, budget, training count or learning parameter")
    low_priority()
    folder = ROOT / "runs/standalone-rl" / args.run
    if args.command in ("prepare", "run"):
        config = prepare(folder, args)
        if args.command == "run":
            if not (folder / "lock.json").exists():
                train(folder, config, args)
                lock(folder, config)
            test(folder, config, args)
        return
    config = json.loads((folder / "experiment.json").read_text(encoding="utf-8"))
    if args.command == "train":
        train(folder, config, args)
    elif args.command == "lock":
        lock(folder, config)
    else:
        test(folder, config, args)


if __name__ == "__main__":
    mp.freeze_support()
    main()
