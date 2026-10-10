#!/usr/bin/env python3
"""Check that a speed-up changed nothing, and measure it.

    python3 scripts/speedcheck.py          compare with the saved baseline
    python3 scripts/speedcheck.py save     save a new baseline (after an intended change in behaviour)

Plays three fixed-seed workloads, times each in CPU seconds, and fingerprints every
result. "results identical: True" means every battle ended exactly as in the baseline.
"""
import hashlib, json, os, random, sys, time
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_v] = "1"  # numpy's idle threads otherwise burn CPU and spoil the timing
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pogo.agents import Masher, Planner, varied
from pogo.battle import Battle
from pogo.gamedata import GameData
from pogo.learner import Learner, QNet
import pogo.agents as agents

gd = GameData(); pool = gd.meta(50)
q = QNet.load(ROOT / "runs" / "general-decide" / "q_v3.npz")
work = {
    "engine only (Masher v Masher)": (2000, Masher, lambda rng: Masher()),
    "Planner v the crowd": (400, lambda: Planner(seed=1), lambda rng: varied(rng, pool)),
    "learned bot v learned bot": (250, lambda: Learner(q=q, margin=0.02, seed=1), lambda rng: Learner(q=q, margin=0.02, seed=2)),
}
out = {}
for name, (n, mine, theirs) in work.items():
    agents._seeds.seed(20261009)
    rng = random.Random(7); h = hashlib.sha256(); t0 = time.process_time()
    for _ in range(n):
        b = Battle(rng.sample(pool, 3), rng.sample(pool, 3), mine(), theirs(rng), seed=rng.getrandbits(32))
        w = b.run()
        h.update(repr((w, b.turn, [(m.hp, m.energy) for s in b.sides for m in s.team], [s.shields for s in b.sides])).encode())
    cpu = time.process_time() - t0
    out[name] = {"battles_per_cpu_second": round(n / cpu, 1), "fingerprint": h.hexdigest()[:16]}
path = ROOT / "tests" / "data" / "speed_baseline.json"
if len(sys.argv) > 1 and sys.argv[1] == "save":
    json.dump(out, open(path, "w"), indent=1); print("baseline saved")
    for k, v in out.items(): print(f"  {k:32s} {v['battles_per_cpu_second']:8.1f} battles per CPU second")
else:
    base = json.load(open(path))
    for k, v in out.items():
        same = v["fingerprint"] == base[k]["fingerprint"]
        print(f"  {k:32s} {base[k]['battles_per_cpu_second']:8.1f} -> {v['battles_per_cpu_second']:8.1f} battles per CPU second "
              f"({v['battles_per_cpu_second'] / base[k]['battles_per_cpu_second']:.2f}x)  results identical: {same}")
