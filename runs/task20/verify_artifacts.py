"""Verify the saved task 20 models and their equal training-example budgets."""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from pogo.learner import N_FEATURES, Q_HEADS, QNet

settings = []
for name, has_mid in (("task20-with", True), ("task20-without", False)):
    folder = ROOT / "runs" / name
    receipt = json.loads((folder / "training.json").read_text())
    args = receipt["arguments"]
    assert args["no_mid_swap"] is not has_mid
    settings.append({k: v for k, v in args.items() if k not in ("run", "no_mid_swap")})
    assert len(receipt["rounds"]) == 3
    assert all(sum(r["retained"].values()) == 60000 for r in receipt["rounds"])
    counts = receipt["rounds"][-1]["cumulative"]
    with np.load(folder / "examples.npz") as examples:
        for head, n in Q_HEADS.items():
            x, y = examples[f"{head}_x"], examples[f"{head}_y"]
            assert x.shape == (counts[head], N_FEATURES)
            assert y.shape == (counts[head], n)
            assert np.isfinite(x).all()
            assert ((y >= 0) & (y <= 1) | np.isnan(y)).all()
            assert np.isfinite(y).any(axis=1).all()
    model = QNet.load(folder / "q.npz")
    assert ("mid_swap" in model.params) == has_mid
    assert set(model.params) == {head for head, count in counts.items() if count}
    assert all(np.isfinite(p).all() for params in model.params.values() for p in params)
    assert sum(counts.values()) == 180000
    generated = sum(sum(r["collected"].values()) for r in receipt["rounds"])
    minutes = sum(r["collection_seconds"] for r in receipt["rounds"]) / 60
    print(f"{name}: {generated} collected; {sum(counts.values())} retained; {minutes:.2f} collection minutes")
    print("  " + ", ".join(f"{head}={count}" for head, count in counts.items()))
assert settings[0] == settings[1]
print("PASS: same training settings and 60,000 retained examples per round; only the with model has mid_swap")
