#!/usr/bin/env python3
"""Measure what ships, before it ships (docs/benchmarking.md; a bug once reached the website because it was not).

    python3 scripts/release_check.py [--crowd 200] [--workers 3]

With the website's own settings (pogo.realtime.WEBSITE) and time limits: the unit tests, the PvPoke reference battles, how
long decisions take, and the score against the crowd next to the trained bot's. Writes runs/bench/release.json, tied to the
code that was tested; scripts/build_pvpbot_site.py refuses to build code without a passing record. The time limits sit between
the fixed build and the nesting bug (99th percentile 475 against 1,292 ms; cut short 11% against 30%). Browser speed is not
covered: check it by hand when the settings change.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
RECORD = ROOT / "runs" / "bench" / "release.json"
SHIPPED = ["pogo", "scripts/pvpbot_site", "scripts/play", "scripts/build_pvpbot_site.py", "runs/general-decide/q.npz", "runs/eval/eval.npz"]
LIMITS = {"p99_ms": 800.0, "cut_percent": 20.0, "fallback_percent": 0.5}


def code_id() -> str | None:
    """A name for the shipped files as committed; None if any differ from the commit."""
    if subprocess.run(["git", "status", "--porcelain", "--", *SHIPPED], cwd=ROOT, capture_output=True, text=True).stdout.strip():
        return None
    return " ".join(subprocess.run(["git", "rev-parse", f"HEAD:{p}"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip() for p in SHIPPED)


def timing_problems(summary: dict) -> list:
    got = {k: summary["intervals"][k]["estimate"] for k in LIMITS}
    return [f"{k} {got[k]:.1f} is over the limit of {LIMITS[k]:g}" for k in LIMITS if got[k] > LIMITS[k]]


def run(*command) -> subprocess.CompletedProcess:
    if os.name == "nt" and command[0] == "nice":
        command = command[1:]  # realtime_trial's workers already lower their priority on Windows
    print("  $", " ".join(command), flush=True)
    return subprocess.run(command, cwd=ROOT, capture_output=True, text=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--crowd", type=int, default=200)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--seed", type=int, default=3553)
    args = parser.parse_args()
    from pogo.realtime import WEBSITE
    settings = f"samples={WEBSITE['samples']}"
    code = code_id()
    if code is None:
        raise SystemExit("commit the shipped files first: the record is tied to the commit")
    problems, record = [], {"commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip(),
                            "code": code, "settings": WEBSITE, "date": time.strftime("%Y-%m-%d %H:%M")}
    tests = run(sys.executable, "-m", "unittest", "discover", "tests")
    record["tests"] = tests.stderr.strip().splitlines()[-1] if tests.stderr.strip() else "no output"
    if tests.returncode:
        problems.append("unit tests failed")
    pvpoke = run(sys.executable, "scripts/check_pvpoke.py")
    record["pvpoke"] = pvpoke.stdout.strip().splitlines()[-1] if pvpoke.stdout.strip() else "no output"
    if pvpoke.returncode or not record["pvpoke"].startswith("108 of 108"):
        problems.append("PvPoke reference battles failed")
    saved = ROOT / "runs" / "bench" / "release_timing.json"
    timing = run("nice", sys.executable, "scripts/realtime_trial.py", "--timing", "30", "--workers", "1", "--seed", str(args.seed), "--settings", settings, "--save", str(saved))
    if timing.returncode:
        problems.append("timing run failed: " + timing.stderr.strip()[-200:])
    else:
        summary = json.loads(saved.read_text())
        record["timing"] = {k: round(v["estimate"], 1) for k, v in summary["intervals"].items()}
        problems += timing_problems(summary)
    if args.crowd:
        strength = run("nice", sys.executable, "scripts/realtime_trial.py", "--crowd", str(args.crowd), "--workers", str(args.workers), "--seed", str(args.seed), "--settings", settings)
        lines = [line for line in strength.stdout.splitlines() if re.search(r"crowd|trained bot|real-time", line)]
        record["crowd"] = lines[-4:]
        if strength.returncode:
            problems.append("crowd run failed: " + strength.stderr.strip()[-200:])
    record["problems"], record["passed"] = problems, not problems
    RECORD.parent.mkdir(parents=True, exist_ok=True)
    RECORD.write_text(json.dumps(record, indent=1))
    print(json.dumps(record, indent=1))
    print("PASSED" if not problems else "FAILED: " + "; ".join(problems))
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
