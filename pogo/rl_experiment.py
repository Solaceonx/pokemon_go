"""Frozen-source opponents, team splits and reproducible paired RL evaluation.

This module is experiment infrastructure; standalone_rl has no dependency on it.
"""
from __future__ import annotations

import hashlib
import importlib
import importlib.util
import io
import json
import math
import random
import subprocess
import sys
import tarfile
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
FROZEN_PATHS = ("pogo", "data", "runs/general-decide/q.npz", "runs/eval/eval.npz")
SPLIT_SALT = "standalone-rl-v1-team-split-2026-11-01"
BASELINE = {"samples": 32, "horizon": 20, "edge": .03, "margin": .02, "rollout": "bot"}


def digest(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def stream_seed(seed: int, *labels) -> int:
    return int.from_bytes(hashlib.sha256(json.dumps([seed, *labels], separators=(",", ":")).encode()).digest()[:8], "big")


def freeze(ref: str = "origin/main", cache: Path | None = None) -> Path:
    """Archive a Git commit, never working files; verify every byte on reuse."""
    sha = subprocess.check_output(["git", "rev-parse", ref + "^{commit}"], cwd=ROOT, text=True).strip()
    dest = Path(cache or ROOT / ".rl-cache/frozen") / sha
    manifest = dest / "manifest.json"
    if not manifest.exists():
        if dest.exists():
            raise ValueError(f"incomplete frozen snapshot at {dest}; use a new cache directory")
        archive = subprocess.check_output(["git", "archive", sha, *FROZEN_PATHS], cwd=ROOT)
        dest.mkdir(parents=True)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tf:
            tf.extractall(dest, filter="data")
        files = {p.relative_to(dest).as_posix(): digest(p) for p in sorted(dest.rglob("*")) if p.is_file()}
        atomic_json(manifest, {"commit": sha, "files": files, "baseline": BASELINE,
                               "note": "full 32 samples, no wall-clock cuts; per-battle evaluator cache"})
    verify_snapshot(dest)
    return dest


def verify_snapshot(dest: Path):
    manifest = json.loads((dest / "manifest.json").read_text(encoding="utf-8"))
    for name, expected in manifest["files"].items():
        if digest(dest / name) != expected:
            raise ValueError(f"frozen opponent modified: {name}")
    if manifest["baseline"] != BASELINE:
        raise ValueError("frozen baseline settings changed")
    return manifest


class FrozenRuntime:
    """Load the frozen package in its own namespace, including its simulator."""
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.manifest = verify_snapshot(self.path)
        namespace = "_rl_frozen_" + self.manifest["commit"]
        if namespace not in sys.modules:
            spec = importlib.util.spec_from_file_location(namespace, self.path / "pogo/__init__.py",
                                                        submodule_search_locations=[str(self.path / "pogo")])
            package = importlib.util.module_from_spec(spec)
            sys.modules[namespace] = package
            spec.loader.exec_module(package)
        self.modules = {name: importlib.import_module(namespace + "." + name)
                        for name in ("battle", "gamedata", "engine", "learner", "evaluation", "teamshape", "teamlist", "agents", "pvpoke_ai")}
        self.gd = self.modules["gamedata"].GameData()
        self.pool, mixed = self.modules["teamshape"].mixed_field(self.gd)
        self.draws = {"mixed": mixed, "standard": self.modules["teamlist"].drawer(self.gd, self.gd.meta(50))}
        self.net = self.modules["learner"].QNet.load(self.path / "runs/general-decide/q.npz")
        self.ev = self.modules["evaluation"].Evaluator.load(self.path / "runs/eval/eval.npz").model
        self.Battle = self.modules["battle"].Battle

    def engine(self, seed: int, samples: int = 32):
        settings = {**BASELINE, "samples": samples}
        # Never share an evaluator's matchup cache with another player/game.
        return self.modules["engine"].Engine(self.modules["evaluation"].Evaluator(self.ev), self.pool,
                                               q=self.net, seed=seed, **settings)

    def teacher(self, seed: int):
        return self.modules["learner"].Learner(q=self.net, margin=.02, seed=seed)

    def opponent(self, kind: str, seed: int, samples=32):
        if kind == "engine":
            return self.engine(seed, samples)
        if kind == "learner":
            return self.teacher(seed)
        if kind == "pvpoke":
            return self.modules["pvpoke_ai"].PvpokeAI()
        if kind == "crowd":
            return self.modules["agents"].varied(random.Random(seed), self.pool)
        raise ValueError(f"unknown opponent {kind}")

    def draw(self, rng: random.Random, split: str, field="mixed"):
        if split not in ("train", "validation", "test"):
            raise ValueError("invalid team split")
        for _ in range(100000):
            team = self.draws[field](rng)
            if team_split(team) == split:
                return team
        raise RuntimeError("could not draw a team in requested split")


def team_key(team) -> tuple[str, ...]:
    """Lead and bench permutations of a trio stay in the same partition."""
    return tuple(sorted(m if isinstance(m, str) else (m.home or m.species_id) for m in team))


def team_split(team) -> str:
    key = json.dumps([SPLIT_SALT, team_key(team)], separators=(",", ":")).encode()
    bucket = int.from_bytes(hashlib.sha256(key).digest()[:8], "big") % 100
    return "train" if bucket < 70 else "validation" if bucket < 85 else "test"


def schedule(runtime, split: str, field: str, seed: int, pairings: int) -> list[dict]:
    """All seeds fixed before battles, independent of policy/episode length.

    Both team allocation AND player seat are reversed in the second battle.
    Draw with replacement to preserve the registered field distribution. Each
    pairing is an independent draw with fresh policy and battle randomness.
    """
    rng, out = random.Random(stream_seed(seed, split, field, "teams")), []
    for index in range(pairings):
        teams = []
        for _ in range(2):
            team = runtime.draw(rng, split, field)
            teams.append([m.species_id for m in team])
        out.append({"index": index, "teams": teams,
                    "seeds": [[stream_seed(seed, split, field, index, orientation, kind)
                               for kind in ("battle", "agent", "opponent")] for orientation in range(2)]})
    return out


def score(winner, seat):
    return .5 if winner == -1 else float(winner == seat)


def intervals(values, seed=0, replicates=10000):
    """Pairing-cluster bootstrap and a conservative finite-sample bound.

    A bootstrap CI describes uncertainty; the distribution-free Hoeffding lower
    bound gates the claim of reliability (one-sided 97.5%, bounded [0,1]).
    """
    values = np.asarray(values, dtype=float)
    n = len(values)
    if n < 2:
        raise ValueError("at least two independent team pairings required")
    rng = np.random.default_rng(seed)
    boot = np.empty(replicates)
    for start in range(0, replicates, 100):
        count = min(100, replicates - start)
        boot[start:start + count] = values[rng.integers(n, size=(count, n))].mean(axis=1)
    lo, hi = np.quantile(boot, [.025, .975])
    mean = float(values.mean())
    return {"score": mean, "ci95": [float(lo), float(hi)], "pairings": n, "battles": 2 * n,
            "normal_margin95": float(1.96 * values.std(ddof=1) / math.sqrt(n)),
            "hoeffding_lower97_5": max(0., mean - math.sqrt(math.log(40) / (2 * n)))}


def play_case(runtime, model, case, *, greedy=False, opponent="engine", samples=32):
    from .standalone_rl import StandaloneAgent
    pair, times, winners = [], [], []
    a, b = [[runtime.gd.default(sp) for sp in team] for team in case["teams"]]
    for orientation in range(2):
        battle_seed, agent_seed, foe_seed = case["seeds"][orientation]
        me = StandaloneAgent(model, seed=agent_seed, greedy=greedy)
        foe = runtime.opponent(opponent, foe_seed, samples)
        # Battle 0: agent A vs engine B. Battle 1: engine A vs agent B.
        agents = (me, foe) if orientation == 0 else (foe, me)
        start = time.perf_counter()
        winner = runtime.Battle(a, b, *agents, seed=battle_seed).run()
        pair.append(score(winner, orientation))
        times.append(time.perf_counter() - start)
        winners.append(winner)
    return {"index": case["index"], "scores": pair, "score": sum(pair) / 2,
            "seconds": times, "winners": winners}


def evaluate(runtime, model, cases, path, *, greedy=False, opponent="engine", samples=32, metadata=None, mapper=None):
    """Append each completed independent pairing; crash/resume loses at most one.

    Headers bind the cache to weights, opponent snapshot, cases and settings.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    weights_hash = hashlib.sha256(b"".join(model.params[k].tobytes() for k in sorted(model.params))).hexdigest()
    header = {"schema": 1, "metadata": metadata or {}, "opponent": opponent, "samples": samples,
              "greedy": greedy, "frozen_commit": runtime.manifest["commit"],
              "weights_sha256": weights_hash,
              "schedule_sha256": hashlib.sha256(json.dumps(cases, sort_keys=True).encode()).hexdigest()}
    rows = []
    if path.exists():
        raw = path.read_bytes()
        if not raw.endswith(b"\n"):
            # A killed writer can leave one incomplete final row. Only complete
            # newline-terminated records are committed and used on resumption.
            raw = raw[:raw.rfind(b"\n") + 1]
            path.write_bytes(raw)
        lines = raw.decode("utf-8").splitlines()
        if not lines:
            raise ValueError(f"incomplete evaluation header: {path}")
        if json.loads(lines[0]) != header:
            raise ValueError(f"evaluation cache provenance mismatch: {path}")
        for line in lines[1:]:
            rows.append(json.loads(line))
        if [r["index"] for r in rows] != [c["index"] for c in cases[:len(rows)]]:
            raise ValueError("evaluation cache has duplicate or unordered pairings")
    else:
        path.write_text(json.dumps(header, sort_keys=True) + "\n", encoding="utf-8")
    pending = cases[len(rows):]
    played = mapper(pending) if mapper else (play_case(runtime, model, case, greedy=greedy, opponent=opponent, samples=samples) for case in pending)
    for case, row in zip(pending, played, strict=True):
        if row["index"] != case["index"]:
            raise ValueError("evaluation mapper changed pairing order")
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, sort_keys=True) + "\n")
        rows.append(row)
        if len(rows) % 25 == 0:
            print(f"{path.stem}: {len(rows)}/{len(cases)} pairings, score={np.mean([r['score'] for r in rows]):.3f}", flush=True)
    result = intervals([r["score"] for r in rows], seed=stream_seed(0, header["schedule_sha256"]))
    result.update(header=header, wins=sum(s == 1 for r in rows for s in r["scores"]),
                  draws=sum(s == .5 for r in rows for s in r["scores"]),
                  losses=sum(s == 0 for r in rows for s in r["scores"]),
                  seconds=sum(sum(r["seconds"]) for r in rows))
    return result
