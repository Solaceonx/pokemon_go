#!/usr/bin/env python3
"""Refine a standalone RL initialization from logged full-engine actions.

This command performs actor-only behavior cloning on training episodes. It does
not select a checkpoint, run validation, or open the reserved final strength test.
Evaluate selected epoch candidates through the normal standalone RL protocol.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

for _name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_name] = "1"

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pogo.rl_experiment import atomic_json, digest, stream_seed, team_split
from pogo.standalone_rl import HEADS, N_FEATURES
from pogo.standalone_rl_v2 import ActorCritic
from scripts.standalone_rl import log_event, source_hashes


def sources():
    own = Path(__file__)
    return {**source_hashes(), own.relative_to(ROOT).as_posix():
            hashlib.sha256(own.read_bytes().replace(b"\r\n", b"\n")).hexdigest()}


def read_demonstrations(folder, first, last):
    """Require original source provenance, full-strength teachers and train trios."""
    cfg = json.loads((folder / "experiment.json").read_text(encoding="utf-8"))
    if cfg["sources"] != source_hashes():
        raise ValueError("demonstration source differs from the registered evaluator")
    if first < 1 or last < first:
        raise ValueError("invalid demonstration round interval")
    groups = {head: [] for head in HEADS}
    files, games, trios = {}, 0, set()
    for index in range(first, last + 1):
        episode_path = folder / f"training_games_{index:05d}.json"
        data_path = folder / f"demo_{index:05d}.npz"
        episodes = json.loads(episode_path.read_text(encoding="utf-8"))
        if not episodes or any(team_split(t) != "train" for g in episodes for t in g["teams"]):
            raise ValueError("demonstrations must come exclusively from training trios")
        if any(g["kind"] == "engine" and g["samples"] != 32 for g in episodes):
            raise ValueError("only full 32-sample engine demonstrations are allowed")
        expected = sum(g["public_teacher_decisions"] for g in episodes if g["kind"] == "engine")
        count = 0
        with np.load(data_path, allow_pickle=False) as data:
            for head, width in HEADS.items():
                if f"{head}:x" not in data:
                    continue
                row = {key: data[f"{head}:{key}"].copy() for key in ("x", "mask", "actions")}
                x, mask, actions = (row[k] for k in ("x", "mask", "actions"))
                n = len(actions)
                if not n or x.shape != (n, N_FEATURES) or mask.shape != (n, width) or actions.shape != (n,):
                    raise ValueError("invalid public demonstration schema")
                if mask.dtype != np.bool_ or actions.dtype.kind not in "iu" or not np.isfinite(x).all():
                    raise ValueError("invalid public demonstration values")
                if np.any(actions < 0) or np.any(actions >= width) or not mask[np.arange(n), actions].all():
                    raise ValueError("illegal demonstration action")
                groups[head].append(row)
                count += n
        if count != expected or not count:
            raise ValueError("demonstration rows do not match the episode audit")
        for file in (episode_path, data_path):
            files[file.name] = digest(file)
        games += len(episodes)
        trios.update(tuple(sorted(t)) for g in episodes for t in g["teams"])
    combined = {h: {k: np.concatenate([row[k] for row in rows]) for k in rows[0]}
                for h, rows in groups.items() if rows}
    audit = {"source_run": str(folder), "source_config_sha256": digest(folder / "experiment.json"),
             "frozen_commit": cfg["commit"], "first_round": first, "last_round": last,
             "files": files, "source_games": games, "distinct_training_trios": len(trios),
             "rows": {h: len(g["actions"]) for h, g in combined.items()}, "engine_samples": 32}
    return combined, audit


def imitate(model, head, x, mask, actions, rate):
    """Cross entropy updates this actor only; no artificial critic targets."""
    p, _, (actor, _) = model.forward(x, head, mask)
    n = len(x)
    loss = float(-np.log(np.maximum(p[np.arange(n), actions], 1e-12)).mean())
    gradient = p.copy()
    gradient[np.arange(n), actions] -= 1.
    norm = model._adam(model._backward(x, head, actor, gradient / n), rate)
    model.updates += 1
    return loss, norm


def fit_epoch(model, groups, *, seed, epoch, batch_size, rate, deadline):
    rng, result = np.random.default_rng(stream_seed(seed, "engine_behavior_cloning", epoch)), {}
    for head in HEADS:
        if head not in groups:
            continue
        group = groups[head]
        losses, norms = [], []
        order = rng.permutation(len(group["actions"]))
        for start in range(0, len(order), batch_size):
            if time.time() >= deadline:
                raise TimeoutError("authorized work budget exhausted")
            pick = order[start:start + batch_size]
            loss, norm = imitate(model, head, group["x"][pick], group["mask"][pick],
                                 group["actions"][pick], rate)
            losses.append(loss)
            norms.append(norm)
        correct, total_loss = 0, 0.
        for start in range(0, len(order), batch_size):
            pick = order[start:start + batch_size]
            probs = model.forward(group["x"][pick], head, group["mask"][pick])[0]
            correct += int(np.count_nonzero(probs.argmax(axis=1) == group["actions"][pick]))
            total_loss -= float(np.log(np.maximum(probs[np.arange(len(pick)), group["actions"][pick]], 1e-12)).sum())
        result[head] = {"rows": len(order), "training_agreement": correct / len(order),
                        "training_cross_entropy": total_loss / len(order),
                        "mean_update_loss": float(np.mean(losses)), "mean_gradient_norm": float(np.mean(norms))}
    return result


def train(folder, args):
    groups, audit = read_demonstrations(args.demo_folder, args.first_round, args.last_round)
    manifest = {"algorithm": "actor-only full-engine behavior cloning before further reinforcement learning",
                "start": str(args.start), "start_sha256": digest(args.start), "data": audit,
                "seed": args.seed, "batch_size": args.batch_size, "rate": args.rate,
                "budget_deadline_unix": args.budget_deadline, "sources": sources()}
    config_path = folder / "experiment.json"
    folder.mkdir(parents=True, exist_ok=True)
    if config_path.exists():
        registered = json.loads(config_path.read_text(encoding="utf-8"))
        if any(registered[k] != v for k, v in manifest.items()):
            raise ValueError("initialization, demonstrations, optimizer settings or source changed")
    else:
        manifest["implementation_git_head"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        atomic_json(config_path, manifest)
    state_path = folder / "state.json"
    if not state_path.exists():
        if any(p.name != "round_00000.npz" for p in folder.glob("round_*.npz")):
            raise ValueError("missing progress journal for existing trained checkpoints")
        model, metadata = ActorCritic.load(args.start)
        model.m = {k: np.zeros_like(v) for k, v in model.params.items()}
        model.v = {k: np.zeros_like(v) for k, v in model.params.items()}
        model.steps = {k: 0 for k in model.params}
        model.updates = 0
        model.save(folder / "round_00000.npz", {"initialization": metadata,
                   "optimizer_reset_for_method_change": True, "experiment": digest(config_path)})
        atomic_json(state_path, {"epoch": 0})
    state = json.loads(state_path.read_text(encoding="utf-8"))
    model = ActorCritic.load(folder / f"round_{state['epoch']:05d}.npz")[0]
    log_event(folder, "engine_bc_start", target_epochs=args.epochs, state=state, data=audit)
    for epoch in range(state["epoch"] + 1, args.epochs + 1):
        metrics = fit_epoch(model, groups, seed=args.seed, epoch=epoch, batch_size=args.batch_size,
                            rate=args.rate, deadline=args.budget_deadline)
        if not all(np.isfinite(v).all() for group in (model.params, model.m, model.v) for v in group.values()):
            raise ValueError("nonfinite pretrained weights or optimizer state")
        checkpoint = folder / f"round_{epoch:05d}.npz"
        model.save(checkpoint, {"stage": "engine_behavior_cloning", "epoch": epoch,
                   "experiment": digest(config_path), "selection_required": "validation only"})
        log_event(folder, "engine_bc_epoch", epoch=epoch, metrics=metrics, checkpoint_sha256=digest(checkpoint))
        atomic_json(state_path, {"epoch": epoch})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("train",))
    parser.add_argument("--run", required=True)
    parser.add_argument("--start", required=True, type=Path)
    parser.add_argument("--demo-folder", required=True, type=Path)
    parser.add_argument("--first-round", type=int, default=17)
    parser.add_argument("--last-round", type=int, default=24)
    parser.add_argument("--epochs", type=int, default=16)
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument("--rate", type=float, default=3e-4)
    parser.add_argument("--seed", type=int, default=41001)
    parser.add_argument("--budget-deadline", type=float, required=True)
    args = parser.parse_args()
    if Path(args.run).name != args.run or args.run in (".", ".."):
        parser.error("run must be one directory name")
    if min(args.epochs, args.batch_size) < 1 or args.rate <= 0 or args.seed < 0:
        parser.error("invalid optimizer settings")
    if args.budget_deadline <= time.time():
        parser.error("authorized work deadline has passed")
    train(ROOT / "runs/standalone-rl" / args.run, args)


if __name__ == "__main__":
    main()
