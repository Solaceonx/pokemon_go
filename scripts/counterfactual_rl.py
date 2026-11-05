#!/usr/bin/env python3
"""Terminal-return policy improvement for actions, PPO for shield/replacement heads.

    python scripts/counterfactual_rl.py train --run cf-pilot --start PATH --hours 4

Validation and final testing reuse the standalone experiment's frozen-opponent
protocol. train never opens the final test. run trains, locks, then tests.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing as mp
import os
import random
import sys
import time
from pathlib import Path

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_var] = "1"

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import standalone_rl as experiment
from pogo.arena import low_priority
from pogo.counterfactual_rl import CounterfactualModel, action_returns, branch, capture
from pogo.rl_experiment import atomic_json, digest, score, stream_seed, team_key
from pogo.standalone_rl import StandaloneAgent

ALGORITHM = "all-action terminal-return improvement with on-policy auxiliary heads"
_models = {}


class CollectionAgent(StandaloneAgent):
    """Greedy physical actions; sampled shield/replacement decisions for PPO."""
    def choose(self, view, head, energy=None):
        previous = self.greedy
        if head == "act":
            self.greedy = True
        try:
            return super().choose(view, head, energy)
        finally:
            self.greedy = previous


def training_sources():
    paths = [Path(__file__), ROOT / "pogo/counterfactual_rl.py"]
    return {**experiment.source_hashes(), **{
        p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        for p in paths}}


def verify_training_sources(config):
    if config["sources"] != experiment.source_hashes() or config["training_sources"] != training_sources():
        raise ValueError("registered training/evaluation source changed; create a new run")


def prepare(folder, args):
    config_path = folder / "experiment.json"
    if config_path.exists():
        config = json.loads(config_path.read_text(encoding="utf-8"))
        if config.get("algorithm") != ALGORITHM:
            raise ValueError("use a new run name for the counterfactual method")
        experiment.restore_snapshot(config)
        return config
    config = experiment.prepare(folder, args)
    config.update(algorithm=ALGORITHM, training_sources=training_sources(),
                  behavior="greedy act; sampled shield/replace; counterfactual continuations fully greedy",
                  label_scope="true training simulator state for terminal labels; public View only for policy features")
    model, old_meta = CounterfactualModel.load(folder / "initial.npz")
    # This is a new optimization method. Transfer the policy, not old Adam momentum.
    model.m = {k: np.zeros_like(v) for k, v in model.params.items()}
    model.v = {k: np.zeros_like(v) for k, v in model.params.items()}
    model.steps = {k: 0 for k in model.params}
    model.updates = 0
    atomic_json(config_path, config)
    model.save(folder / "initial.npz", {"initialization": old_meta, "optimizer_reset_for_method_change": True,
                                        "experiment": digest(config_path)})
    atomic_json(folder / "state.json", {"phase": "initial_validation", "round": 0, "training_games": 0,
                                         "training_seconds": 0., "best_validation": -1., "best_greedy": True})
    experiment.log_event(folder, "counterfactual_registered", algorithm=ALGORITHM, sources=config["training_sources"])
    return config


def collect_job(task):
    checkpoint, seed, start, count, samples, playouts, deadline = task
    runtime = experiment._runtime
    if checkpoint not in _models:
        _models.clear()
        _models[checkpoint] = CounterfactualModel.load(checkpoint)[0]
    model = _models[checkpoint]
    auxiliary, demonstrations, positions, games = [], [], [], []
    for index in range(start, start + count):
        if time.time() >= deadline:
            raise TimeoutError("authorized experiment time budget exhausted")
        team_rng = random.Random(stream_seed(seed, "counterfactual", index, "teams"))
        reservoir = random.Random(stream_seed(seed, "counterfactual", index, "position"))
        teams = [runtime.draw(team_rng, "train") for _ in range(2)]
        dice = [stream_seed(seed, "counterfactual", index, name) for name in ("battle", "agent", "opponent", "returns")]
        log, demo_log = [], []
        me = CollectionAgent(model, seed=dice[1], greedy=False, log=log)
        foe = experiment.TeacherRecorder(runtime.engine(dice[2], samples), demo_log)
        seat = index % 2
        players = (me, foe) if seat == 0 else (foe, me)
        battle = runtime.Battle(*teams, *players, seed=dice[0])
        chosen, seen = None, 0
        began = time.perf_counter()
        while battle.winner is None:
            view = battle.views[seat]
            if not view.me.busy and view.me.mon.hp > 0 and len(view.legal()) > 1:
                seen += 1
                if reservoir.randrange(seen) == 0:
                    chosen = capture(battle, seat)
            battle.step()
        reward = 2 * score(battle.winner, seat) - 1
        # No policy-gradient labels from greedy act choices. Monte Carlo returns
        # on the sampled auxiliary heads avoid bootstrapping through untrained
        # values at deterministic act decisions.
        aux = [row for row in log if row[0] != "act"]
        auxiliary.extend(experiment.advantages(aux, reward, lam=1.))
        demonstrations.extend((*row, 0., 0.) for row in demo_log if row[0] != "act")
        if chosen is None:
            raise RuntimeError("a three-Pokemon game supplied no ambiguous action")
        utilities = action_returns(chosen, playouts=playouts, seed=dice[3])
        positions.append((chosen.features, chosen.mask, utilities))
        known = utilities[chosen.mask]
        games.append({"index": index, "teams": [team_key(t) for t in teams], "seeds": dice,
                      "score": score(battle.winner, seat), "engine_samples": samples, "playouts": playouts,
                      "sampled_turn": chosen.battle.turn, "eligible_positions": seen,
                      "utility_spread": float(known.max() - known.min()),
                      "utilities": {str(k): float(utilities[k]) for k in np.flatnonzero(chosen.mask)},
                      "auxiliary_decisions": len(aux), "public_teacher_decisions": len(demo_log),
                      "seconds": time.perf_counter() - began})
    return positions, auxiliary, demonstrations, games


def fit_actions(model, data, *, epochs, rate, seed):
    x, mask, targets = data["x"], data["mask"], data["returns"]
    reference = model.forward(x, "act", mask)[0]
    rng, metrics = np.random.default_rng(seed), []
    for epoch in range(epochs):
        order = rng.permutation(len(x))
        for start in range(0, len(order), 128):
            pick = order[start:start + 128]
            metrics.append(model.improve_actions(x[pick], mask[pick], targets[pick], rate=rate,
                                                  reference=reference[pick], anchor=.01))
        p = model.forward(x, "act", mask)[0]
        kl = float((reference * (np.log(np.maximum(reference, 1e-12)) - np.log(np.maximum(p, 1e-12)))).sum(axis=1).mean())
        if kl > .03:
            break
    return {"positions": len(x), "epochs": epoch + 1, "kl": kl,
            **{key: float(np.mean([m[key] for m in metrics])) for key in metrics[0]}}


def load_recent(folder, round_index, keep):
    groups = []
    for index in range(max(1, round_index - keep + 1), round_index + 1):
        with np.load(folder / f"counterfactual_{index:05d}.npz", allow_pickle=False) as data:
            groups.append({k: data[k].copy() for k in ("x", "mask", "returns")})
    return {k: np.concatenate([g[k] for g in groups]) for k in groups[0]}


def train(folder, config, args):
    if (folder / "lock.json").exists():
        raise ValueError("run locked for final testing")
    verify_training_sources(config)
    runtime = experiment.restore_snapshot(config)
    state_path = folder / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    checkpoint = folder / f"round_{state['round']:05d}.npz" if state["phase"] == "counterfactual" else folder / "initial.npz"
    model = CounterfactualModel.load(checkpoint)[0]
    anchor = CounterfactualModel.load(folder / "initial.npz")[0]
    began = time.monotonic()
    end = began + max(0., min(args.hours * 3600 - state["training_seconds"],
                              config["budget_deadline_unix"] - args.test_reserve_hours * 3600 - time.time()))
    experiment.log_event(folder, "counterfactual_train_start", arguments={k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()}, state=state)
    with mp.get_context("spawn").Pool(args.workers, initializer=experiment.initialize,
                                     initargs=(str(ROOT / config["snapshot"]), config["budget_deadline_unix"])) as pool:
        if state["phase"] == "initial_validation":
            result, greedy = experiment.validate_modes(folder, runtime, model, folder / "initial.npz", 0, pool, config)
            state.update(phase="counterfactual", best_round=0, best_validation=result["score"], best_greedy=greedy)
            state["training_seconds"] += time.monotonic() - began
            began = time.monotonic()
            model.save(folder / "round_00000.npz", {"state": state, "stage": "counterfactual"})
            model.save(folder / "best.npz", {"state": state, "selection": "validation_only"})
            atomic_json(state_path, state)
        while state["round"] < args.max_rounds and time.monotonic() < end:
            next_round = state["round"] + 1
            behavior = folder / f"round_{state['round']:05d}.npz"
            tasks = [(str(behavior), config["seed"], start, min(4, state["training_games"] + args.batch_games - start),
                      args.train_samples, args.playouts, config["budget_deadline_unix"])
                     for start in range(state["training_games"], state["training_games"] + args.batch_games, 4)]
            positions, auxiliary, demonstrations, games = [], [], [], []
            for pos, aux, demo, summary in pool.imap(collect_job, tasks):
                positions.extend(pos)
                auxiliary.extend(aux)
                demonstrations.extend(demo)
                games.extend(summary)
            current = {"x": np.stack([p[0] for p in positions]), "mask": np.stack([p[1] for p in positions]),
                       "returns": np.stack([p[2] for p in positions])}
            path = folder / f"counterfactual_{next_round:05d}.npz"
            with path.with_suffix(".tmp").open("wb") as f:
                np.savez_compressed(f, **current)
            path.with_suffix(".tmp").replace(path)
            atomic_json(folder / f"training_games_{next_round:05d}.json", games)
            replay = load_recent(folder, next_round, args.replay_rounds)
            action_metrics = fit_actions(model, replay, epochs=args.action_epochs, rate=args.rate,
                                         seed=stream_seed(config["seed"], "cf_fit", next_round))
            aux_data, demos = experiment.grouped(auxiliary), experiment.grouped(demonstrations)
            experiment.save_batch(folder / f"replay_{next_round:05d}.npz", aux_data)
            aux_metrics = dict(experiment.fit(model, aux_data, stream_seed(config["seed"], "cf_aux_fit", next_round),
                                              epochs=args.ppo_epochs, rate=args.rate, anchor_model=anchor,
                                              anchor=.01, demos=demos, demo_weight=args.demo_weight))
            state.update(round=next_round, training_games=state["training_games"] + len(games))
            checkpoint = folder / f"round_{next_round:05d}.npz"
            model.save(checkpoint, {"state": state, "stage": "counterfactual"})
            model.save(folder / "latest.npz", {"state": state, "stage": "counterfactual"})
            experiment.log_event(folder, "counterfactual_update", round=next_round, total_games=state["training_games"],
                                 engine_samples=args.train_samples, playouts=args.playouts,
                                 action_metrics=action_metrics, auxiliary_metrics=aux_metrics,
                                 action_positions=len(positions), score=float(np.mean([g["score"] for g in games])),
                                 discriminative_positions=sum(g["utility_spread"] > 0 for g in games),
                                 seconds=sum(g["seconds"] for g in games), checkpoint_sha256=digest(checkpoint))
            if next_round % args.validation_every == 0:
                result, greedy = experiment.validate_modes(folder, runtime, model, checkpoint, next_round, pool, config)
                if result["score"] > state["best_validation"]:
                    state.update(best_round=next_round, best_validation=result["score"], best_greedy=greedy)
                    model.save(folder / "best.npz", {"state": state, "selection": "validation_only"})
                    experiment.log_event(folder, "best", round=next_round, validation_score=result["score"])
            state["training_seconds"] += time.monotonic() - began
            began = time.monotonic()
            atomic_json(state_path, state)
    experiment.log_event(folder, "counterfactual_stopped", state=state, reason="round or time budget")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("prepare", "train", "run", "lock", "test"))
    parser.add_argument("--run", required=True)
    parser.add_argument("--start", type=Path)
    parser.add_argument("--ref", default="59836c86f4c9ccf7e8d35ef7c94268e64c1a4ba9")
    parser.add_argument("--seed", type=int, default=37001)
    parser.add_argument("--network", choices=("independent",), default="independent")
    parser.add_argument("--hidden", type=int, default=128)
    parser.add_argument("--workers", type=int, choices=(1, 2, 3), default=3)
    parser.add_argument("--hours", type=float, default=4)
    parser.add_argument("--budget-deadline", type=float)
    parser.add_argument("--test-reserve-hours", type=float, default=10)
    parser.add_argument("--batch-games", type=int, default=64)
    parser.add_argument("--max-rounds", type=int, default=10000)
    parser.add_argument("--train-samples", type=int, default=32)
    parser.add_argument("--playouts", type=int, default=2)
    parser.add_argument("--action-epochs", type=int, default=8)
    parser.add_argument("--ppo-epochs", type=int, default=4)
    parser.add_argument("--replay-rounds", type=int, default=8)
    parser.add_argument("--validation-every", type=int, default=4)
    parser.add_argument("--validation-pairings", type=int, default=128)
    parser.add_argument("--pairings", type=int, default=1200)
    parser.add_argument("--rate", type=float, default=3e-4)
    parser.add_argument("--demo-weight", type=float, default=.05)
    args = parser.parse_args()
    if Path(args.run).name != args.run or args.run in (".", ".."):
        parser.error("run must be one directory name")
    if min(args.batch_games, args.max_rounds, args.train_samples, args.playouts, args.action_epochs,
           args.ppo_epochs, args.replay_rounds, args.validation_every) < 1 or min(args.pairings, args.validation_pairings) < 2:
        parser.error("positive training sizes and at least two evaluation pairings required")
    if args.hours <= 0 or args.rate <= 0 or args.demo_weight < 0 or args.test_reserve_hours < 0 or args.seed < 0:
        parser.error("invalid learning parameter or budget")
    low_priority()
    folder = ROOT / "runs/standalone-rl" / args.run
    config = prepare(folder, args)
    if args.command == "prepare":
        return
    if args.command in ("train", "run"):
        if not (folder / "lock.json").exists():
            train(folder, config, args)
        elif args.command == "train":
            raise ValueError("run locked for final testing")
        if args.command == "train":
            return
    if args.command in ("lock", "run"):
        verify_training_sources(config)
        experiment.lock(folder, config)
    if args.command in ("test", "run"):
        verify_training_sources(config)
        experiment.test(folder, config, args)


if __name__ == "__main__":
    mp.freeze_support()
    main()
