#!/usr/bin/env python3
"""Standalone PPO with complete terminal-return advantages (gamma=1, lambda=1).

Reuses the frozen-opponent controller without changing historical experiment
sources. This entry point is included in every training/evaluation source hash.
The network and deployment format remain the ordinary standalone policy.
"""
from __future__ import annotations

import hashlib
import multiprocessing as mp
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import standalone_rl as base

_source_hashes = base.source_hashes
_advantages = base.advantages
_initialize = base.initialize
_prepare = base.prepare
_configured = False


def sources():
    path = Path(__file__)
    return {**_source_hashes(), path.relative_to(ROOT).as_posix():
            hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()}


def terminal_advantages(log, reward, lam=1.):
    # With gamma=1 and lambda=1 the TD terms telescope to R - V(s).
    # Ignore the historical collector's explicit lambda=.98 argument.
    return _advantages(log, reward, lam=1.)


def prepare(folder, args):
    existed = (folder / "experiment.json").exists()
    config = _prepare(folder, args)
    if existed:
        if config.get("gae_lambda") != 1. or config["sources"] != sources():
            raise ValueError("use a separate run for terminal-return PPO")
        return config
    config.update(gae_lambda=1., gamma=1., algorithm=
                  "masked actor-critic PPO with complete terminal returns; optional public opponent demonstrations")
    path = folder / "experiment.json"
    base.atomic_json(path, config)
    model, meta = base.ActorCritic.load(folder / "initial.npz")
    model.save(folder / "initial.npz", {**meta, "experiment": base.digest(path)})
    base.log_event(folder, "terminal_returns_registered", gae_lambda=1., sources=config["sources"])
    return config


def initialize(snapshot, deadline_unix=None):
    # Spawned workers configure their own module globals before collecting games.
    configure()
    _initialize(snapshot, deadline_unix)


def configure():
    global _configured
    if not _configured:
        base.source_hashes = sources
        base.advantages = terminal_advantages
        base.prepare = prepare
        base.initialize = initialize
        _configured = True


if __name__ == "__main__":
    mp.freeze_support()
    configure()
    base.main()
