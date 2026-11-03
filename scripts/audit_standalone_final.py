#!/usr/bin/env python3
"""Read-only verification of completed, locked MC-PPO evaluation blocks.

The evaluator and policy are not modified. Raw pairing logs and lineage caches
are retained locally. Use --require-complete for the final four-block verdict.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pogo.rl_experiment import (FrozenRuntime, atomic_json, canonical_json_digest,
                                digest, intervals, schedule, stream_seed, team_key, team_split)
from pogo.standalone_rl_v2 import ActorCritic
from scripts.monte_carlo_rl import sources
import numpy as np


def require(condition, message):
    if not condition:
        raise ValueError(message)


def pairing_values(rows, pairings):
    """Check each seat's winner-to-score mapping before computing statistics."""
    require(len(rows) == pairings, "incomplete pairing records")
    require([r["index"] for r in rows] == list(range(pairings)), "unordered or duplicate indices")
    values, counts = [], dict(wins=0, draws=0, losses=0)
    for row in rows:
        require(len(row["scores"]) == len(row["winners"]) == 2, "two seats required")
        expected = []
        for seat, winner in enumerate(row["winners"]):
            require(winner in (-1, 0, 1), "invalid winner")
            expected.append(.5 if winner == -1 else float(winner == seat))
        require(row["scores"] == expected, "winner/seat score mismatch")
        require(row["score"] == sum(expected) / 2, "pairing score mismatch")
        counts["wins"] += expected.count(1)
        counts["draws"] += expected.count(.5)
        counts["losses"] += expected.count(0)
        values.append(row["score"])
    return values, counts


def check_statistics(values, result, schedule_sha256):
    # evaluate() fixes this seed from the schedule, rather than intervals()'s
    # standalone default. It is independent of observed scores and policy.
    seed = stream_seed(0, schedule_sha256)
    computed = intervals(values, seed=seed)
    for key in ("score", "normal_margin95", "hoeffding_lower97_5"):
        require(np.isclose(result[key], computed[key], rtol=0, atol=1e-14),
                f"recomputed {key} differs")
    require(np.allclose(result["ci95"], computed["ci95"], rtol=0, atol=1e-14),
            "recomputed bootstrap interval differs")
    lower = max(0, float(np.mean(values)) - math.sqrt(math.log(40) / (2 * len(values))))
    require(np.isclose(result["hoeffding_lower97_5"], lower, rtol=0, atol=1e-14),
            "bounded-score lower limit differs")
    return str(seed)


def audit(run, lineage_report, require_complete=False):
    require(Path(run).name == run and run not in (".", ".."), "run must be one directory name")
    folder = ROOT / "runs/standalone-rl" / run
    read = lambda name: json.loads((folder / name).read_text(encoding="utf-8-sig"))
    locked, plan, config, saved = (read(name) for name in
                                  ("lock.json", "test_plan.json", "experiment.json", "test_results.json"))
    expected_sources = sources()
    if config.get("offline_returns"):
        from scripts.offline_returns_rl import sources as offline_sources
        expected_sources = offline_sources()
    require(locked["sources"] == expected_sources == config["sources"], "registered sources changed")
    require(digest(folder / "locked.npz") == locked["checkpoint_sha256"], "locked model changed")
    require(digest(folder / "experiment.json") == locked["experiment_sha256"], "configuration changed")
    require(saved["lock"] == locked and saved["plan"] == plan, "result provenance differs")
    require(plan["fields"] == ["mixed", "standard"] and len(set(plan["seeds"])) == 2,
            "registered fields/seeds differ")
    require(plan["seeds"] == locked["test_seeds"] and plan["pairings_per_seed_and_field"] == 1200,
            "registered seed/sample plan differs")
    require(plan["checkpoint_sha256"] == locked["checkpoint_sha256"] and plan["greedy"] == locked["greedy"],
            "plan model/mode differs")
    require(config["commit"] == locked["frozen_commit"], "frozen opponent differs")
    expected = [f"{field}_{block}" for field in plan["fields"] for block in range(2)]
    require(bool(saved["results"]) and set(saved["results"]) <= set(expected), "unexpected test blocks")
    complete = set(saved["results"]) == set(expected) and "reliably_beats_frozen_engine" in saved
    require(not require_complete or complete, "final evaluation is incomplete")

    lineage_meta = json.loads(Path(lineage_report).read_text(encoding="utf-8-sig"))
    cache = ROOT / lineage_meta["lineage_cache"]
    require(digest(cache) == lineage_meta["lineage_cache_sha256"], "lineage cache changed")
    lineage = json.loads(cache.read_text(encoding="utf-8"))
    train_teams = {tuple(t) for t in lineage["training_trios"]}
    val_teams = {tuple(t) for t in lineage["validation_trios"]}
    train_seeds, val_seeds = set(lineage["training_seeds"]), set(lineage["validation_seeds"])
    model, _ = ActorCritic.load(folder / "locked.npz")
    fingerprint = hashlib.sha256(b"".join(model.params[k].tobytes() for k in sorted(model.params))).hexdigest()
    runtime = FrozenRuntime(ROOT / config["snapshot"])
    blocks = {}
    for key in expected:
        if key not in saved["results"]:
            continue
        result = saved["results"][key]
        field, block_string = key.rsplit("_", 1)
        seed = plan["seeds"][int(block_string)]
        log = folder / f"test_{key}.jsonl"
        records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        header, rows = records[0], records[1:]
        require(header == result["header"], "pairing header differs from summary")
        require(header["opponent"] == "engine" and header["samples"] == 32, "opponent settings differ")
        require(header["greedy"] == locked["greedy"] and header["weights_sha256"] == fingerprint,
                "evaluated policy differs")
        require(header["frozen_commit"] == locked["frozen_commit"], "pairing opponent differs")
        require(header["metadata"] == dict(checkpoint_sha256=locked["checkpoint_sha256"], split="test", seed=seed),
                "pairing metadata differs")
        values, counts = pairing_values(rows, 1200)
        require(result["pairings"] == 1200 and result["battles"] == 2400, "sample count differs")
        require(all(result[k] == v for k, v in counts.items()), "win/draw/loss counts differ")
        bootstrap_seed = check_statistics(values, result, header["schedule_sha256"])
        cases = read(f"test_schedule_{key}.json")
        # Evaluation cache headers retain the original JSON spacing convention.
        schedule_hash = hashlib.sha256(json.dumps(cases, sort_keys=True).encode()).hexdigest()
        require(schedule_hash == header["schedule_sha256"], "schedule fingerprint differs")
        require(cases == schedule(runtime, "test", field, seed, 1200), "regenerated schedule differs")
        teams = {team_key(t) for case in cases for t in case["teams"]}
        seeds = {s for case in cases for group in case["seeds"] for s in group}
        require(all(team_split(t) == "test" for t in teams), "team outside test partition")
        require(not teams & train_teams and not teams & val_teams, "training/validation trio overlap")
        require(not seeds & train_seeds and not seeds & val_seeds, "training/validation seed overlap")
        gate = result["ci95"][0] > .5 and (field != "mixed" or result["hoeffding_lower97_5"] > .5)
        blocks[key] = dict(result=result, test_seed_string=str(seed), bootstrap_seed_string=bootstrap_seed,
                           gate_pass=bool(gate), unique_test_trios=len(teams), trio_overlap=0, seed_overlap=0,
                           score_mapping_checked=True, statistics_recomputed=True, schedule_regenerated_exactly=True,
                           pairing_log_sha256=digest(log))
    verdict = all(block["gate_pass"] for block in blocks.values()) if complete else None
    if complete:
        require(saved["reliably_beats_frozen_engine"] == verdict, "final reliability verdict differs")
    return dict(scope="Read-only audit of completed preregistered final blocks", run=run,
                complete=complete, completed_blocks=blocks, total_battles=sum(b["result"]["battles"] for b in blocks.values()),
                reliably_beats_frozen_engine=verdict, source_guards_match=True, lineage_cache_verified=True,
                locked_checkpoint_sha256=locked["checkpoint_sha256"], weights_sha256=fingerprint,
                lock_canonical_sha256=canonical_json_digest(locked), plan_canonical_sha256=canonical_json_digest(plan))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", default="mc-ppo-v3")
    parser.add_argument("--lineage-report", type=Path, default=ROOT / "runs/standalone-rl/mc3_final_training_audit.json")
    parser.add_argument("--require-complete", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.run, args.lineage_report, args.require_complete)
    atomic_json(args.output, report)
    print(json.dumps(dict(complete=report["complete"], total_battles=report["total_battles"],
                         reliably_beats_frozen_engine=report["reliably_beats_frozen_engine"],
                         blocks={key: dict(score=block["result"]["score"], ci95=block["result"]["ci95"],
                                           gate_pass=block["gate_pass"]) for key, block in report["completed_blocks"].items()})))


if __name__ == "__main__":
    main()
