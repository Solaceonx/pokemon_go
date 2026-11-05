#!/usr/bin/env python3
"""Engine settings against each other, and each against the crowd, PvPoke's AI and a reader (docs/tasks.md, 27-31).

    python3 scripts/engine_versus.py --tag time-grid --baseline "samples=4,horizon=20" \
        --candidates "samples=16" "samples=16,horizon=40" [--pairings 1000] [--crowd 1000] [--pvpoke 500] \
        [--reader 0] [--workers 64] [--seed 2701]

A setting is "key=value,key=value" on top of the confirmed engine (samples 4, horizon 20, edge 0.03, the trained bot
inside the look-ahead, margin 0.02). Keys: samples, horizon, edge, margin, shield_margin (float), shield_toward (0 | 1),
heads (joined by "+", for example
"throw+swap+mid_swap+replace+shield"), opponents (bot | mix), profile (0 | 1), unseen (pool | teams), mix (0 | 1),
temperature, mix_shield (requires the shield head), mix_switch, random_hold (0 | 1), even_cost (first | best), judge (steps | turn | end), switch_edge, stay_after_replace (0 | 1), eval (path to an evaluation
.npz), q (path to the trained bot's networks, q.npz: used for the engine's own picks and inside its look-ahead; task 39),
team_file (listed unseen-team prior), and style_file (calibrated mixture with optional human_settings
overrides). Data-file paths are relative to the repository root unless absolute. The setting "bot" is the trained bot alone.

For each candidate, on the same battles for all: head to head against the baseline (every pair of teams both ways
round), against the crowd, against PvPoke's AI, and against a reader (pogo.reader: an engine that predicts its
opponent's next throw decision and plays the best reply), with margins; also the search time per decision. Teams are
drawn half from the good-team list and half at random from the top 50; with --field pvpoke, as PvPoke's usage data
has them (pogo.teamshape.pvpoke_field: Cramorant and Mimikyu included, balanced teams), and the pool the engine and
the crowd imagine from is that field too. Results go to runs/engine_versus/<tag>.json
as they come in; a run started again with the same tag skips what is done. Each player has a private evaluator
cache, so another battle or a different worker schedule cannot change its cached matchup outlooks.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import random
import sys
import time
from collections import Counter
from contextlib import nullcontext
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_v] = "1"
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pogo.agents import varied  # noqa: E402
from pogo.arena import low_priority, mean_and_margin  # noqa: E402
from pogo.battle import DRAW, Battle  # noqa: E402
from pogo.evaluation import Evaluator  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.learner import Learner, QNet  # noqa: E402
from pogo.pvpoke_ai import PvpokeAI  # noqa: E402
from pogo.reader import Reader  # noqa: E402
from pogo.realtime import RealTime  # noqa: E402
from pogo.teamlist import drawer  # noqa: E402

CONFIRMED = {"samples": 4, "horizon": 20, "edge": 0.03, "margin": 0.02}
CACHE_POLICY = "per-player"
SHIELD_COUNTS = "per-battle-v1"
NO_LIMIT = {k: 1e9 for k in ("turn_ms", "unforeseen_ms", "after_charged_ms", "after_faint_ms", "replace_ms", "start_ms")}
_state: dict = {}


def parse(spec: str) -> dict | None:
    """'samples=16,heads=throw+shield' -> settings on top of the confirmed engine; 'bot' -> None (the trained bot)."""
    if spec.strip() == "bot":
        return None
    out = dict(CONFIRMED)
    for part in filter(None, (p.strip() for p in spec.split(","))):
        key, value = part.split("=", 1)
        if key == "heads":
            out[key] = tuple(value.split("+"))
        elif key in ("samples", "horizon"):
            out[key] = int(value)
        elif key in ("edge", "margin", "shield_margin", "temperature", "switch_edge", "robust"):
            out[key] = float(value)
        elif key == "shield_toward":
            if value not in ("0", "1"):
                raise SystemExit("shield_toward must be 0 or 1")
            out[key] = bool(int(value))
        elif key in ("profile", "mix", "mix_shield", "mix_switch", "random_hold", "matching", "no_tell_bait",
                     "stay_after_replace"):
            out[key] = value not in ("0", "false", "False", "")
        elif key in ("opponents", "unseen", "eval", "q", "team_file", "style_file", "even_cost", "judge"):
            out[key] = value
        else:
            raise SystemExit(f"unknown setting {key!r} in {spec!r}")
    return out


def wait_while_paused(path: str | None) -> None:
    """Start no more work while the pause file exists (--pause-file; scripts/engine_loop.py runs while its owner says)."""
    while path and Path(path).exists():
        time.sleep(30)


def setup(field: str = "standard", pause: str | None = None) -> None:
    low_priority()
    gd = GameData()
    if field == "pvpoke":
        from pogo.teamshape import pvpoke_field
        pool, draw = pvpoke_field(gd)
    elif field == "mixed":
        from pogo.teamshape import mixed_field
        pool, draw = mixed_field(gd)
    else:
        pool = gd.meta(50)
        draw = drawer(gd, pool)
    _state.update(gd=gd, pool=pool, draw=draw, net=QNet.load(str(ROOT / "runs" / "general-decide" / "q.npz")),
                  evals={}, pause=pause)


def evaluator(path: str | None) -> Evaluator:
    path = path or str(ROOT / "runs" / "eval" / "eval.npz")
    if path not in _state["evals"]:
        _state["evals"][path] = Evaluator.load(ROOT / path).model
    # Share immutable weights only: the evaluator's outlook cache belongs to one player
    # in one battle, otherwise prior jobs and the opposing player's searches affect it.
    return Evaluator(_state["evals"][path])


def network(path: str | None) -> QNet:
    """The trained bot's networks: the website's, or those at a path (task 39's rounds)."""
    if path is None:
        return _state["net"]
    nets = _state.setdefault("nets", {})
    if path not in nets:
        nets[path] = QNet.load(str(ROOT / path))
    return nets[path]


def pilot(settings: dict | None, seed: int, cls=RealTime):
    s = _state
    if settings is None:
        return Learner(q=s["net"], margin=0.02, seed=seed)
    kw = dict(settings)
    # Share immutable model weights, not the evaluator's matchup cache across teams or opponents.
    ev = Evaluator(evaluator(kw.pop("eval", None)).model)
    q = network(kw.pop("q", None))
    margin = kw.pop("margin")
    extra = NO_LIMIT if cls is RealTime else {}
    return cls(ev, s["pool"], rollout="bot", q=q, margin=margin, seed=seed, **kw, **extra)


def points(winner: int, side: int) -> float:
    return 1.0 if winner == side else 0.5 if winner == DRAW else 0.0


class ShieldCalls:
    """Count only the real battle's prompts; imagined players and reader copies are unwrapped."""

    def __init__(self, inner):
        self.inner = inner
        self.shields, self.prompts = 0, 0

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def shield(self, view, energy, *move):
        answer = self.inner.shield(view, energy, *move)
        self.prompts += 1
        self.shields += bool(answer)
        return answer

    def counts(self):
        return {"shields": self.shields, "prompts": self.prompts}


def job(task):
    """kind is h2h (candidate against baseline, both ways), crowd, pvpoke or reader; returns points by battle number."""
    try:
        return _job(task)
    except StopIteration as e:  # raised in a worker it would end the result loop quietly, as if every job were done
        raise RuntimeError(f"StopIteration in job {task[:2]} from {task[4]}") from e


def _job(task):
    kind, name, spec, base, start, count, seed = task
    wait_while_paused(_state.get("pause"))
    s = _state
    out, searches, calls = {}, [], {}
    for n in range(start, start + count):
        rng = random.Random(seed * 1_000_003 + n)
        a, b = s["draw"](rng), s["draw"](rng)
        dice = rng.getrandbits(32)
        if kind == "h2h":
            pair = []
            ours_calls, base_calls = Counter(), Counter()
            for ours, theirs in ((a, b), (b, a)):
                me = ShieldCalls(pilot(parse(spec), rng.getrandbits(32)))
                them = ShieldCalls(pilot(parse(base), rng.getrandbits(32)))
                pair.append(points(Battle(ours, theirs, me, them, seed=dice).run(), 0))
                searches += [r[3] for r in getattr(me, "rows", [])]
                ours_calls.update(me.counts())
                base_calls.update(them.counts())
            out[n] = sum(pair) / 2
            calls[n] = {**ours_calls, "baseline": dict(base_calls)}
        elif kind == "reader":
            pair = []
            ours_calls = Counter()
            for ours, theirs in ((a, b), (b, a)):
                me = ShieldCalls(pilot(parse(spec), rng.getrandbits(32)))
                probe = pilot(dict(CONFIRMED), rng.getrandbits(32), cls=Reader)
                probe.target, probe.target_side = me, 1
                pair.append(points(Battle(theirs, ours, probe, me, seed=dice).run(), 1))
                ours_calls.update(me.counts())
            out[n] = sum(pair) / 2
            calls[n] = dict(ours_calls)
        else:
            me = ShieldCalls(pilot(parse(spec), dice))
            them = varied(random.Random(dice), s["pool"]) if kind == "crowd" else PvpokeAI()
            out[n] = points(Battle(a, b, me, them, seed=dice).run(), 0)
            searches += [r[3] for r in getattr(me, "rows", [])]
            calls[n] = me.counts()
    return kind, name, out, searches, calls


def record(saved: dict, result) -> None:
    """Merge a worker's scores and counts by battle number, so resuming cannot count a prompt twice."""
    kind, spec, out, searches, calls = result
    saved.setdefault("results", {}).setdefault(kind, {}).setdefault(spec, {}).update({str(n): v for n, v in out.items()})
    saved.setdefault("shield_calls", {}).setdefault(kind, {}).setdefault(spec, {}).update({str(n): v for n, v in calls.items()})
    hist = saved.setdefault("search_ms", {}).setdefault(spec, {})
    for ms in searches[:200]:
        key = str(round(ms, 1))
        hist[key] = hist.get(key, 0) + 1


def shield_rate(rows, baseline=False) -> str:
    counts = Counter()
    for row in rows:
        counts.update(row["baseline"] if baseline else {k: row[k] for k in ("shields", "prompts")})
    shields, prompts = counts["shields"], counts["prompts"]
    rate = f"{100 * shields / prompts:.1f}%" if prompts else "n/a"
    return f"{shields} / {prompts} ({rate})"


def estimate(values: list) -> tuple[float, float]:
    """A one-battle smoke has a score, but no estimated margin."""
    return (values[0], float("nan")) if len(values) == 1 else mean_and_margin(values)


def summary(values: list) -> str:
    m, h = estimate(values)
    return f"{100 * m:.1f}% ± {100 * h:.1f}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tag", required=True, help="name of this comparison; results in runs/engine_versus/<tag>.json")
    parser.add_argument("--baseline", default="")
    parser.add_argument("--candidates", nargs="+", required=True)
    parser.add_argument("--pairings", type=int, default=1000, help="head to head against the baseline, each pair both ways")
    parser.add_argument("--crowd", type=int, default=1000)
    parser.add_argument("--pvpoke", type=int, default=500)
    parser.add_argument("--reader", type=int, default=0, help="pairs of battles against the reader probe")
    parser.add_argument("--chunk", type=int, default=5, help="battles (or pairs) per job")
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 4)
    parser.add_argument("--seed", type=int, default=2701)
    parser.add_argument("--field", choices=("standard", "pvpoke", "mixed"), default="standard",
                        help="opposing teams: the usual draw, or as PvPoke's usage data has them")
    parser.add_argument("--pause-file", help="while this file exists, workers finish the job they are on and wait")
    args = parser.parse_args()
    for spec in [args.baseline, *args.candidates]:
        parse(spec)  # fail early on a mistyped setting
    path = ROOT / "runs" / "engine_versus" / f"{args.tag}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    saved = json.loads(path.read_text()) if path.exists() else {}
    if saved.get("results") and saved.get("shield_counting") != SHIELD_COUNTS:
        raise SystemExit(f"{path} has no shield prompt counts; use a new tag")
    if saved and saved.get("evaluator_cache") not in (CACHE_POLICY, "per_player"):  # task 29 wrote "per_player"
        raise SystemExit(f"{path} does not record isolated evaluator caches; use a new tag")
    if saved and saved.get("seed") != args.seed:
        raise SystemExit(f"{path} was made with seed {saved.get('seed')}; use that seed or another tag")
    if saved and saved.get("baseline") != args.baseline:
        raise SystemExit(f"{path} used a different baseline; use that baseline or another tag")
    if saved and saved.get("field", "standard") != args.field:
        raise SystemExit(f"{path} was made with --field {saved.get('field', 'standard')}; use that or another tag")
    saved.update(seed=args.seed, baseline=args.baseline, field=args.field,
                 evaluator_cache=saved.get("evaluator_cache", CACHE_POLICY), shield_counting=SHIELD_COUNTS)
    results = saved.setdefault("results", {})  # results[kind][spec] = {battle number: points}
    times = saved.setdefault("search_ms", {})
    # Exact frequencies of the rounded timings keep checkpoints small without dropping tail observations.
    for spec, recorded in times.items():
        if isinstance(recorded, list):  # resume checkpoints from before timing histograms
            times[spec] = dict(Counter(str(float(ms)) for ms in recorded))
    saved["timing_storage"] = "rounded_ms_counts"
    named = {"baseline": args.baseline, **{f"candidate {k + 1}": c for k, c in enumerate(args.candidates)}}
    plan = []
    for name, spec in named.items():
        for kind, count in (("h2h", args.pairings if name != "baseline" else 0), ("crowd", args.crowd),
                            ("pvpoke", args.pvpoke), ("reader", args.reader)):
            have = results.get(kind, {}).get(spec, {})
            start = 0
            while start < count:
                if str(start) in have:
                    start += 1
                    continue
                end = start + 1
                while end < min(start + args.chunk, count) and str(end) not in have:
                    end += 1
                plan.append((kind, spec, spec, args.baseline, start, end - start, args.seed))
                start = end
    print(f"{len(plan)} jobs to run on {args.workers} workers", flush=True)
    t0, last = time.time(), time.time()
    if plan:
        with (multiprocessing.get_context("spawn").Pool(args.workers, initializer=setup, initargs=(args.field, args.pause_file))
              if args.workers > 1 else nullcontext()) as pool:
            if pool is None:
                setup(args.field, args.pause_file)
            for result in (pool.imap_unordered(job, plan) if pool else map(job, plan)):
                record(saved, result)
                if time.time() - last > 60:
                    path.write_text(json.dumps(saved))
                    last = time.time()
                    print(f"  {sum(len(v) for r in results.values() for v in r.values())} results, "
                          f"{(time.time() - t0) / 60:.0f} min", flush=True)
    path.write_text(json.dumps(saved))

    def values(kind, spec):
        got = results.get(kind, {}).get(spec, {})
        return [got[k] for k in sorted(got, key=int)]

    def calls(kind, spec):
        return saved.get("shield_calls", {}).get(kind, {}).get(spec, {}).values()

    print(f"\nbaseline: {args.baseline or 'the confirmed engine'}")
    head_calls = [row for spec in args.candidates for row in calls("h2h", spec)]
    if head_calls:
        print(f"  head to head, all candidates: shields / shield prompts {shield_rate(head_calls, baseline=True)}")
    base = {kind: values(kind, args.baseline) for kind in ("crowd", "pvpoke", "reader")}
    for kind, v in base.items():
        if v:
            print(f"  against the {kind}: {summary(v)}; shields / shield prompts {shield_rate(calls(kind, args.baseline))}")
    for name, spec in named.items():
        if name == "baseline":
            continue
        print(f"\n{name}: {spec}")
        h2h = values("h2h", spec)
        if h2h:
            print(f"  head to head against the baseline, {len(h2h)} pairings both ways: {summary(h2h)}")
            print(f"    shields / shield prompts {shield_rate(calls('h2h', spec))}; "
                  f"baseline {shield_rate(calls('h2h', spec), baseline=True)}")
        for kind in ("crowd", "pvpoke", "reader"):
            v = values(kind, spec)
            if v and len(v) == len(base[kind]):
                diff = [x - y for x, y in zip(v, base[kind])]
                m, h = estimate(diff)
                print(f"  against the {kind}: {summary(v)}, {100 * m:+.1f} ± {100 * h:.1f} points on the baseline")
                print(f"    shields / shield prompts {shield_rate(calls(kind, spec))}")
        t = np.array([float(ms) for ms, count in times.get(spec, {}).items() for _ in range(count)])
        if len(t):
            print(f"  search time per searched decision: median {np.median(t):.0f} ms, 99th percentile "
                  f"{np.percentile(t, 99):.0f}, worst {t.max():.0f} (this machine)")
    print(f"\nresults: {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
