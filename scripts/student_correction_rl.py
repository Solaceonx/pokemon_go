#!/usr/bin/env python3
"""On-policy terminal-return PPO plus expert corrections at student states.

Runtime/evaluation stays the ordinary standalone neural policy. Recent expert
labels from student and opponent states are aggregated in an eight-round window.
"""
from __future__ import annotations

import argparse
import hashlib
import multiprocessing as mp
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import monte_carlo_rl as mc
from pogo.student_correction import CorrectedStudent
import numpy as np

base = mc.base
_prepare, _fit, _initialize = mc._prepare, base.fit, mc._initialize
_configured, _folder = False, None


def sources():
    paths = [Path(__file__), ROOT / "pogo/student_correction.py", ROOT / "pogo/counterfactual_rl.py"]
    return {**mc.sources(), **{p.relative_to(ROOT).as_posix():
            hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest() for p in paths}}


def prepare(folder, args):
    existed = (folder / "experiment.json").exists()
    config = _prepare(folder, args)
    if existed:
        if not config.get("student_state_corrections") or config["sources"] != sources():
            raise ValueError("use a separate student-correction run")
        return config
    config.update(gae_lambda=1., gamma=1., student_state_corrections=True, expert_replay_rounds=8,
                  training_opponents="100% frozen engine; sample count logged per batch",
                  algorithm="on-policy PPO with public frozen-expert corrections on student-visited states")
    path = folder / "experiment.json"
    base.atomic_json(path, config)
    model, meta = base.ActorCritic.load(folder / "initial.npz")
    model.m = {k: np.zeros_like(v) for k, v in model.params.items()}
    model.v = {k: np.zeros_like(v) for k, v in model.params.items()}
    model.steps, model.updates = {k: 0 for k in model.params}, 0
    model.save(folder / "initial.npz", {"initialization": meta, "experiment": base.digest(path),
                                        "optimizer_reset_for_method_change": True})
    base.log_event(folder, "student_corrections_registered", sources=config["sources"], replay_rounds=8)
    return config


def collect_job(task):
    kind, checkpoint, seed, start, count, samples, round_index = task
    if kind != "ppo":
        raise ValueError("student corrections require a warm start and zero bootstrap games")
    if checkpoint not in base._model_cache:
        base._model_cache.clear()
        base._model_cache[checkpoint] = base.ActorCritic.load(checkpoint)[0]
    model, rt = base._model_cache[checkpoint], base._runtime
    rows, games, demonstrations = [], [], []
    for index in range(start, start + count):
        if base._deadline_unix and time.time() >= base._deadline_unix:
            raise TimeoutError("authorized work budget exhausted")
        rng = random.Random(base.stream_seed(seed, "student_corrections", index, "teams"))
        teams = [rt.draw(rng, "train") for _ in range(2)]
        dice = [base.stream_seed(seed, "student_corrections", index, name)
                for name in ("battle", "student", "opponent", "expert")]
        log, own_demo, foe_demo = [], [], []
        pilot = CorrectedStudent(model, rt.engine(dice[3], samples), seed=dice[1], log=log,
                                 demonstrations=own_demo)
        foe = base.TeacherRecorder(rt.engine(dice[2], samples), foe_demo)
        seat = index % 2
        players = (pilot, foe) if seat == 0 else (foe, pilot)
        began = time.perf_counter()
        winner = rt.Battle(*teams, *players, seed=dice[0]).run()
        reward = 2 * base.score(winner, seat) - 1
        rows.extend(mc.terminal_advantages(log, reward))
        demonstrations.extend((*row, 0., 0.) for row in (*own_demo, *foe_demo))
        games.append({"index": index, "kind": "engine", "samples": samples,
                      "score": base.score(winner, seat), "decisions": len(log),
                      "student_state_expert_decisions": len(own_demo),
                      "opponent_expert_decisions": len(foe_demo),
                      "public_teacher_decisions": len(own_demo) + len(foe_demo),
                      "teams": [base.team_key(t) for t in teams], "seeds": dice,
                      "seconds": time.perf_counter() - began})
    return rows, games, demonstrations


def fit(model, data, seed, **kwargs):
    if _folder is not None and kwargs.get("demos") and not kwargs.get("imitation"):
        shards = sorted(_folder.glob("demo_*.npz"))[-8:]
        groups = {}
        for path in shards:
            with np.load(path, allow_pickle=False) as values:
                for head in base.HEADS:
                    if f"{head}:x" in values:
                        groups.setdefault(head, []).append({key: values[f"{head}:{key}"].copy()
                                                          for key in ("x", "mask", "actions")})
        kwargs["demos"] = {head: {k: np.concatenate([g[k] for g in chunks]) for k in chunks[0]}
                           for head, chunks in groups.items()}
    return _fit(model, data, seed, **kwargs)


def initialize(snapshot, deadline_unix=None):
    configure()
    _initialize(snapshot, deadline_unix)


def configure(folder=None):
    global _configured, _folder
    if folder is not None:
        _folder = folder
    if not _configured:
        mc.configure()
        base.source_hashes, base.prepare = sources, prepare
        base.initialize, base.collect_job, base.fit = initialize, collect_job, fit
        _configured = True


if __name__ == "__main__":
    mp.freeze_support()
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--run", required=True)
    parser.add_argument("--bootstrap-games", type=int, default=0)
    known, _ = parser.parse_known_args()
    if Path(known.run).name != known.run or known.run in (".", "..") or known.bootstrap_games:
        parser.error("use a new single-name run and zero bootstrap games")
    if "--bootstrap-games" not in sys.argv:
        sys.argv += ["--bootstrap-games", "0"]
    if "--demo-weight" not in sys.argv:
        sys.argv += ["--demo-weight", "1.0"]
    if "--train-samples" not in sys.argv:
        sys.argv += ["--train-samples", "32"]
    if "--curriculum-rounds" not in sys.argv:
        sys.argv += ["--curriculum-rounds", "0"]
    configure(ROOT / "runs/standalone-rl" / known.run)
    base.main()
