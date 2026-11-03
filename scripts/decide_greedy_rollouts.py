#!/usr/bin/env python3
"""Apply the preregistered screen/confirmation rule without tuning a policy."""
import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.evaluate_greedy_rollouts_rl import sources
from pogo.rl_experiment import atomic_json, digest
from pogo.standalone_rl_v2 import ActorCritic
from scripts.select_capacity_candidate import paired_difference


def decide(plan_path, stage):
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    name = plan[stage + "_run"]
    if Path(name).name != name:
        raise ValueError("invalid run name")
    folder = ROOT / "runs/standalone-rl" / name
    config = json.loads((folder / "experiment.json").read_text())
    expected_seed = plan["seed"] if stage == "screen" else int(plan["confirmation_seed"])
    n = plan[stage + "_pairings"]
    if config["sources"] != sources() or config["seed"] != expected_seed \
            or config["commit"] != plan["frozen_commit"] \
            or config["initialization"]["sha256"] != plan["own_policy_sha256"] \
            or config["opponent_policy_sha256"] != plan["opponent_policy_sha256"] \
            or config["planning"] != plan["planning"]:
        raise ValueError("registered settings or sources differ")
    rows = [json.loads(s) for s in (folder / "validation_planning.jsonl").read_text().splitlines()]
    header, pairs = rows[0], rows[1:]
    model = ActorCritic.load(folder / "initial.npz")[0]
    fingerprint = hashlib.sha256(b"".join(model.params[k].tobytes() for k in sorted(model.params))).hexdigest()
    if len(pairs) != n or header["samples"] != 32 or header["weights_sha256"] != fingerprint:
        raise ValueError("incomplete or mismatched evaluation")
    summary = json.loads((folder / "validation_summary.json").read_text())
    if summary["pairings"] != n or not math.isclose(summary["score"], sum(r["score"] for r in pairs)/n):
        raise ValueError("summary differs from the paired outcomes")
    report = {"stage": stage, "run": name, "score": summary["score"], "ci95": summary["ci95"],
              "pairings": n, "sources_match": True, "initial_sha256": digest(folder / "initial.npz"),
              "scope": "Exploratory validation; substantive final test data unopened."}
    if stage == "screen":
        control = ROOT / plan["control_log"]
        reference = [json.loads(s) for s in control.read_text().splitlines()]
        cases = json.loads((folder / "validation_schedule_mixed.json").read_text())
        original_cases = json.loads((control.parent / "validation_schedule_mixed.json").read_text())[:n]
        if cases != original_cases or header["weights_sha256"] != reference[0]["weights_sha256"] \
                or header["frozen_commit"] != reference[0]["frozen_commit"]:
            raise ValueError("screen and neural control are not matched")
        matched = reference[1:n+1]
        report.update(control_score=sum(r["score"] for r in matched)/n,
                      paired_difference=paired_difference(matched, pairs))
        report["advance"] = report["score"] > report["control_score"]
    else:
        report["eligible_for_final_test"] = summary["ci95"][0] > .5
    atomic_json(folder / "decision.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--stage", choices=("screen", "confirmation"), required=True)
    args = parser.parse_args()
    print(json.dumps(decide(args.plan, args.stage)))
