#!/usr/bin/env python3
"""Prepare/validate/lock/test a six-view ensemble of an existing RL checkpoint.

Use prepare first, then validate. This entry point never performs training;
the frozen opponent, pairing schedules, lock and fresh final seeds are reused.
"""
from __future__ import annotations

import argparse
import functools
import hashlib
import json
import multiprocessing as mp
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import standalone_rl as base
from pogo.slot_ensemble import SlotEnsembleAgent

_source_hashes, _initialize, _prepare = base.source_hashes, base.initialize, base.prepare
METHOD = {"permutations": 6, "aggregation": "mean masked probabilities in physical action coordinates"}


def sources():
    paths = (Path(__file__), ROOT / "pogo/slot_ensemble.py")
    return {**_source_hashes(), **{p.relative_to(ROOT).as_posix():
            hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest() for p in paths}}


def configure(folder):
    base.source_hashes, base.prepare, base.StandaloneAgent = sources, prepare, SlotEnsembleAgent
    base.initialize = functools.partial(initialize, config_path=str(folder / "experiment.json"))
    base.evaluate_job = play_job


def play_job(task):
    if base._deadline_unix and time.time() >= base._deadline_unix:
        raise TimeoutError("authorized experiment time budget exhausted")
    checkpoint, case, greedy, opponent, samples = task
    if checkpoint not in base._model_cache:
        base._model_cache.clear()
        base._model_cache[checkpoint] = base.ActorCritic.load(checkpoint)[0]
    model, rt = base._model_cache[checkpoint], base._runtime
    teams = [[rt.gd.default(sp) for sp in team] for team in case["teams"]]
    scores, winners, seconds, decisions = [], [], [], []
    for seat in (0, 1):
        battle_seed, agent_seed, foe_seed = case["seeds"][seat]
        me = SlotEnsembleAgent(model, seed=agent_seed, greedy=greedy)
        foe = rt.opponent(opponent, foe_seed, samples)
        players = (me, foe) if seat == 0 else (foe, me)
        began = time.perf_counter()
        winner = rt.Battle(*teams, *players, seed=battle_seed).run()
        seconds.append(time.perf_counter() - began)
        winners.append(winner)
        scores.append(base.score(winner, seat))
        decisions.append(me.ensemble_decisions)
    return {"index": case["index"], "scores": scores, "score": sum(scores) / 2,
            "seconds": seconds, "winners": winners, "ensemble_decisions": decisions}


def initialize(snapshot, deadline_unix=None, *, config_path):
    folder = Path(config_path).parent
    configure(folder)
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    if config["sources"] != sources() or config.get("slot_ensemble") != METHOD:
        raise ValueError("registered slot-ensemble implementation changed")
    _initialize(snapshot, deadline_unix)


def prepare(folder, args):
    existed = (folder / "experiment.json").exists()
    config = _prepare(folder, args)
    if existed:
        if config.get("slot_ensemble") != METHOD or config["sources"] != sources():
            raise ValueError("use a separate run for the slot ensemble")
    else:
        config.update(slot_ensemble=METHOD, validation_modes=[True],
                      algorithm="inference-only six-view slot ensemble of a frozen RL policy")
        base.atomic_json(folder / "experiment.json", config)
        model, meta = base.ActorCritic.load(folder / "initial.npz")
        model.save(folder / "initial.npz", {**meta, "experiment": base.digest(folder / "experiment.json")})
        base.log_event(folder, "slot_ensemble_registered", method=METHOD, sources=config["sources"])
    return config


if __name__ == "__main__":
    mp.freeze_support()
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--run", required=True)
    parser.add_argument("--bootstrap-games", type=int, default=0)
    parser.add_argument("--max-rounds", type=int, default=0)
    known, _ = parser.parse_known_args()
    if Path(known.run).name != known.run or known.run in (".", ".."):
        parser.error("run must be one directory name")
    if known.bootstrap_games or known.max_rounds:
        parser.error("the ensemble is inference-only; bootstrap games and max rounds must be zero")
    if len(sys.argv) < 2 or sys.argv[1] not in ("prepare", "validate", "train", "lock", "test"):
        parser.error("use prepare, validate, lock or test")
    if sys.argv[1] == "validate":
        sys.argv[1] = "train"
    sys.argv += ["--bootstrap-games", "0", "--max-rounds", "0"]
    configure(ROOT / "runs/standalone-rl" / known.run)
    base.main()
