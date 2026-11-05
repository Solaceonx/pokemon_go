#!/usr/bin/env python3
"""Allocate training using complete paired validation, never final-test data."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import select_capacity_candidate as selector
from scripts.student_correction_rl import sources as student_sources
from pogo.rl_experiment import atomic_json


def choose(baseline_name, candidate_name):
    baseline, rows = selector.load_selection(baseline_name)
    original = selector.sources
    try:
        selector.sources = student_sources
        candidate, other = selector.load_selection(candidate_name)
    finally:
        selector.sources = original
    if any(candidate[k] != baseline[k] for k in ("schedule_sha256", "frozen_commit")):
        raise ValueError("candidate has a different frozen opponent or validation schedule")
    difference = selector.paired_difference(rows, other)
    promoted = candidate["score"] > baseline["score"] and difference["ci95"][0] > 0
    selected = candidate if promoted else baseline
    return dict(baseline=baseline, candidate=candidate, paired_difference=difference,
                promoted=bool(promoted), selected=selected,
                entry="scripts/student_correction_rl.py" if promoted else "scripts/monte_carlo_rl.py",
                batch_games=128 if promoted else 256,
                scope="Exploratory training allocation only; final-test data unopened.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", default="mc-ppo-v3")
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = choose(args.baseline, args.candidate)
    atomic_json(args.output, result)
    print(json.dumps(result))
