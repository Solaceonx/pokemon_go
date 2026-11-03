#!/usr/bin/env python3
"""Bounded offline terminal-return trial; separate from every locked PPO run."""
from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing as mp
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import monte_carlo_rl as mc
from scripts.select_capacity_candidate import paired_difference
from pogo.offline_returns import initialize_q, update
from pogo.standalone_rl_v2 import ActorCritic
import numpy as np

base = mc.base
_configured = False
FROZEN = "59836c86f4c9ccf7e8d35ef7c94268e64c1a4ba9"


def sources():
    paths = [Path(__file__), ROOT / "pogo/offline_returns.py"]
    return {**mc.sources(), **{p.relative_to(ROOT).as_posix():
            hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest() for p in paths}}


def configure():
    global _configured
    if not _configured:
        mc.configure()
        base.source_hashes, base.initialize, base.ActorCritic = sources, initialize, ActorCritic
        _configured = True


def initialize(snapshot, deadline_unix=None):
    configure()
    mc._initialize(snapshot, deadline_unix)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def parameters(args):
    return dict(alpha=args.alpha, epochs=args.epochs, max_train_minutes=args.max_train_minutes,
                batch_size=args.batch_size, rate=args.rate, head_scale=args.head_scale,
                final_reserve_hours=args.test_reserve_hours)


def prepare(folder, args):
    if (folder / "experiment.json").exists():
        config = read(folder / "experiment.json")
        if config.get("offline_returns") != parameters(args) or config["sources"] != sources():
            raise ValueError("registered offline method/settings changed; use a new run")
        base.restore_snapshot(config)
        return config
    args.network, args.hidden = "independent", 128
    config = mc._prepare(folder, args)
    parent = ROOT / "runs/standalone-rl/mc-ppo-v3"
    audit_path = parent.parent / "mc3_final_training_audit.json"
    audit = read(audit_path)
    if audit["rounds"] != 120 or audit["training_games"] != 30720:
        raise ValueError("expected the registered 120-round training dataset")
    shards = []
    for row in audit["checkpoints"]:
        path = parent / f"replay_{row['round']:05d}.npz"
        if base.digest(path) != row["replay_sha256"]:
            raise ValueError("offline training shard changed")
        shards.append(dict(path=path.relative_to(ROOT).as_posix(), sha256=row["replay_sha256"]))
    manifest = dict(shards=shards, source_games=30720, source_rows=audit["counts"]["replay"],
                    training_audit=audit_path.relative_to(ROOT).as_posix(), training_audit_sha256=base.digest(audit_path))
    base.atomic_json(folder / "offline_data.json", manifest)
    config.update(algorithm="conservative Monte-Carlo action-return regression; no Bellman bootstrap",
                  offline_returns=parameters(args), validation_modes=[True],
                  offline_data_sha256=base.digest(folder / "offline_data.json"),
                  parent_validation="mc-ppo-v3/validation_00104_greedy.jsonl",
                  reference="https://arxiv.org/abs/2006.04779", inference_mode="greedy only")
    base.atomic_json(folder / "experiment.json", config)
    model, meta = ActorCritic.load(folder / "initial.npz")
    initialize_q(model, args.head_scale)
    model.save(folder / "initial.npz", dict(initialization=meta, experiment=base.digest(folder / "experiment.json"),
                                            optimizer_reset_for_method_change=True, head_scale=args.head_scale))
    base.atomic_json(folder / "offline_cursor.json", dict(epoch=0, position=0, shards=0, rows_seen=0,
                                                          seconds=0., done=False, checkpoint="initial.npz"))
    base.log_event(folder, "offline_registered", settings=parameters(args), data_sha256=config["offline_data_sha256"],
                   source_rows=manifest["source_rows"], sources=config["sources"])
    return config


def check_config(folder, config):
    if config["sources"] != sources() or base.digest(folder / "offline_data.json") != config["offline_data_sha256"]:
        raise ValueError("offline sources or data manifest changed")


def train(folder, config, args):
    if (folder / "lock.json").exists():
        raise ValueError("locked offline run cannot train")
    check_config(folder, config)
    if (folder / "decision.json").exists():
        return read(folder / "decision.json")
    settings, manifest = config["offline_returns"], read(folder / "offline_data.json")
    cursor = read(folder / "offline_cursor.json")
    model, _ = ActorCritic.load(folder / cursor["checkpoint"])
    initial_seconds, started = cursor["seconds"], time.monotonic()
    allowance = min(settings["max_train_minutes"] * 60 - initial_seconds,
                    config["budget_deadline_unix"] - settings["final_reserve_hours"] * 3600 - time.time())
    stop = started + max(0., allowance)

    def commit():
        cursor["seconds"] = initial_seconds + time.monotonic() - started
        name = f"offline_step_{cursor['shards']:05d}.npz"
        model.save(folder / name, dict(offline_cursor={**cursor, "checkpoint": name}, stage="offline_training"))
        cursor["checkpoint"] = name
        base.atomic_json(folder / "offline_cursor.json", cursor)

    while not cursor["done"] and cursor["epoch"] < settings["epochs"] and time.monotonic() < stop:
        epoch = cursor["epoch"]
        order = np.random.default_rng(base.stream_seed(config["seed"], "offline_epoch", epoch)).permutation(len(manifest["shards"]))
        row = manifest["shards"][int(order[cursor["position"]])]
        path = ROOT / row["path"]
        if base.digest(path) != row["sha256"]:
            raise ValueError("training shard no longer matches registration")
        metrics = {}
        with np.load(path, allow_pickle=False) as data:
            for head in base.HEADS:
                x, mask, actions, returns = (data[head + ":" + k] for k in ("x", "mask", "actions", "returns"))
                if not np.isin(returns, [-1., 0., 1.]).all() or not np.isfinite(x).all():
                    raise ValueError("expected finite public inputs and exact terminal labels")
                rng = np.random.default_rng(base.stream_seed(config["seed"], "offline_batch", epoch, int(order[cursor["position"]]), head))
                permutation = rng.permutation(len(x))
                for begin in range(0, len(x), settings["batch_size"]):
                    ids = permutation[begin:begin + settings["batch_size"]]
                    metrics[head] = update(model, head, x[ids], mask[ids], actions[ids], returns[ids],
                                           alpha=settings["alpha"], rate=settings["rate"])
                    cursor["rows_seen"] += len(ids)
        cursor["position"] += 1
        cursor["shards"] += 1
        if cursor["position"] == len(order):
            cursor["epoch"], cursor["position"] = epoch + 1, 0
        if cursor["shards"] % 8 == 0 or cursor["position"] == 0:
            commit()
            base.log_event(folder, "offline_progress", cursor=cursor, diagnostics=metrics)
    if not cursor["done"]:
        cursor["done"] = True
        commit()
    candidate = folder / "candidate.npz"
    round_index = max(1, cursor["epoch"] + int(cursor["position"] > 0))
    state = dict(phase="offline_closed", round=round_index, bootstrap_games=0, training_games=0,
                 offline_rows_seen=cursor["rows_seen"], training_seconds=cursor["seconds"], best_greedy=True)
    if not candidate.exists():
        model.save(candidate, dict(state=state, stage="offline_candidate"))
    else:
        model, _ = ActorCritic.load(candidate)
    runtime = base.restore_snapshot(config)
    with mp.get_context("spawn").Pool(args.workers, initializer=initialize,
                                      initargs=(str(ROOT / config["snapshot"]), config["budget_deadline_unix"])) as pool:
        result = base.validation(folder, runtime, model, candidate, round_index, pool, config, True)
    parent = ROOT / "runs/standalone-rl/mc-ppo-v3"
    if read(folder / "validation_schedule_mixed.json") != read(parent / "validation_schedule_mixed.json"):
        raise ValueError("paired validation schedules differ")
    baseline = [json.loads(s) for s in (parent / "validation_00104_greedy.jsonl").read_text().splitlines()]
    records = [json.loads(s) for s in (folder / f"validation_{round_index:05d}_greedy.jsonl").read_text().splitlines()]
    parent_path = Path(config["initialization"]["checkpoint"])
    parent_path = parent_path if parent_path.is_absolute() else ROOT / parent_path
    if base.digest(parent_path) != config["initialization"]["sha256"]:
        raise ValueError("parent initialization artifact changed")
    parent_model, _ = ActorCritic.load(parent_path)
    parent_fp = hashlib.sha256(b"".join(parent_model.params[k].tobytes() for k in sorted(parent_model.params))).hexdigest()
    if (baseline[0]["weights_sha256"] != parent_fp or baseline[0]["samples"] != 32
            or baseline[0]["frozen_commit"] != config["commit"] or not baseline[0]["greedy"]):
        raise ValueError("parent is not bound to full-engine greedy validation")
    if baseline[0]["schedule_sha256"] != records[0]["schedule_sha256"] or len(records) != 129:
        raise ValueError("complete 128-pair matched validation required")
    difference = paired_difference(baseline[1:], records[1:])
    qualified = result["ci95"][0] > .5 and difference["ci95"][0] > 0
    enough_time = config["budget_deadline_unix"] - time.time() >= settings["final_reserve_hours"] * 3600
    state.update(best_validation=result["score"], best_round=round_index)
    model.save(folder / "best.npz", dict(state=state, selection="validation_only", offline_returns=True))
    base.atomic_json(folder / "state.json", state)
    decision = dict(scope="Separate adaptive training follow-up; no held-out outcomes used for fitting or selection",
                    score=result["score"], ci95=result["ci95"], paired_difference=difference,
                    validation_qualified=bool(qualified), enough_final_time=bool(enough_time),
                    enter_final=bool(qualified and enough_time), checkpoint_sha256=base.digest(folder / "best.npz"),
                    rows_seen=cursor["rows_seen"], cursor=cursor)
    base.atomic_json(folder / "decision.json", decision)
    base.log_event(folder, "offline_trial_closed", **decision)
    return decision


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "train", "lock", "test", "run"))
    parser.add_argument("--run", required=True)
    parser.add_argument("--ref", default=FROZEN)
    parser.add_argument("--start", type=Path, default=ROOT / "runs/standalone-rl/mc-ppo-v3/selected_round_00104.npz")
    parser.add_argument("--seed", type=int, default=37001)
    parser.add_argument("--workers", type=int, choices=(1, 2, 3), default=1)
    parser.add_argument("--budget-deadline", type=float, default=1793756530.)
    parser.add_argument("--pairings", type=int, default=1200)
    parser.add_argument("--validation-pairings", type=int, default=128)
    parser.add_argument("--alpha", type=float, default=.1)
    parser.add_argument("--epochs", type=int, default=4)
    parser.add_argument("--max-train-minutes", type=float, default=15.)
    parser.add_argument("--batch-size", type=int, default=1024)
    parser.add_argument("--rate", type=float, default=.0002)
    parser.add_argument("--head-scale", type=float, default=.1)
    parser.add_argument("--test-reserve-hours", type=float, default=5.5)
    args = parser.parse_args()
    if Path(args.run).name != args.run or args.run in (".", ".."):
        parser.error("run must be one directory name")
    if (min(args.epochs, args.batch_size, args.max_train_minutes, args.rate, args.head_scale) <= 0
            or args.alpha < 0 or args.test_reserve_hours < 0
            or not all(np.isfinite(x) for x in (args.alpha, args.max_train_minutes, args.rate,
                                                args.head_scale, args.test_reserve_hours, args.budget_deadline))):
        parser.error("invalid offline settings")
    if args.validation_pairings != 128 or args.pairings != 1200 or args.ref != FROZEN:
        parser.error("this registered trial requires E0, 128 validation pairs and 1,200 final pairs per seed/field")
    configure()
    folder = ROOT / "runs/standalone-rl" / args.run
    config = prepare(folder, args)
    if args.command == "prepare":
        return
    check_config(folder, config)
    if args.command in ("train", "run") and not (folder / "lock.json").exists():
        decision = train(folder, config, args)
        if args.command == "train" or not decision["enter_final"]:
            return
    if args.command in ("lock", "run") and not (folder / "lock.json").exists():
        if not read(folder / "decision.json")["enter_final"]:
            raise ValueError("validation/budget promotion gate did not pass")
        base.lock(folder, config)
    if args.command in ("test", "run"):
        base.test(folder, config, args)


if __name__ == "__main__":
    mp.freeze_support()
    main()
