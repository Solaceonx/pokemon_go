#!/usr/bin/env python3
"""Independent learned-policy rollouts with a fixed greedy opponent model.

Keeps the earlier stochastic-rollout implementation and experiments reproducible.
This entry point adds its own source hash and changes only the rollout setting.
"""
from __future__ import annotations

import hashlib
import multiprocessing as mp
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import evaluate_planning_rl as parent

_sources, _prepare, _initialize = parent.sources, parent.prepare, parent.initialize


def sources():
    path = Path(__file__)
    return {**_sources(), path.relative_to(ROOT).as_posix():
            hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()}


def configure(folder):
    parent.sources, parent.prepare, parent.initialize = sources, prepare, initialize
    parent.configure(folder)


def initialize(snapshot, deadline_unix=None, *, config_path):
    configure(Path(config_path).parent)
    _initialize(snapshot, deadline_unix, config_path=config_path)


def prepare(folder, args):
    existed = (folder / "experiment.json").exists()
    if existed:
        config = parent._prepare(folder, args)
        runtime = parent.base.restore_snapshot(config)
    else:
        config, runtime = _prepare(folder, args)
        config["planning"]["stochastic_opponent"] = False
        config["algorithm"] = "RL policy with independent full-battle rollouts against a greedy learned opponent"
        parent.base.atomic_json(folder / "experiment.json", config)
        model, meta = parent.base.ActorCritic.load(folder / "initial.npz")
        model.save(folder / "initial.npz", {**meta, "experiment": parent.base.digest(folder / "experiment.json")})
        parent.base.log_event(folder, "greedy_rollouts_registered", planning=config["planning"], sources=config["sources"])
    expected = {"samples": args.samples, "confidence": args.confidence, "stochastic_opponent": False}
    if config.get("planning") != expected or config["sources"] != sources():
        raise ValueError("use a separate run for greedy opponent rollouts")
    checkpoint = folder / "opponent.npz"
    if config["opponent_policy_sha256"] != parent.base.digest(checkpoint) \
            or config["opponent_policy_sha256"] != parent.base.digest(args.opponent_policy):
        raise ValueError("registered greedy rollout opponent changed")
    for name in ("pogo/battle.py", "pogo/gamedata.py"):
        normalize = lambda p: p.read_bytes().replace(b"\r\n", b"\n")
        if normalize(ROOT / name) != normalize(runtime.path / name):
            raise ValueError("independent rules model differs from frozen rules")
    return config, runtime


if __name__ == "__main__":
    mp.freeze_support()
    configure(ROOT / "runs/standalone-rl")  # main rebinds the actual run folder.
    parent.main()
