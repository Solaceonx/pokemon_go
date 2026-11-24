#!/usr/bin/env python3
"""The engine lab's league (runs/lab-league/REPORT.md): engines compared on more than win rate against one bot.

    python scripts/lab/league.py website bot "website,temperature=0.02" "website,mix=1" --preset smoke --tag smoke-1
    python scripts/lab/league.py --reference website "website,mix=1" --preset screen --workers 14 --tag mix-screen
    python scripts/lab/league.py ... --preset confirm --seed 2611901 --tag mix-confirm      (a fresh seed is required)

A spec is a scripts/engine_versus.py setting ("website", "bot", "website,mix=1", or any key another branch adds to
engine_versus.parse() and pilot()); specs pass through unchanged. The reference is --reference (default website),
then the specs in the order given. For each spec, on the same battles for all (paired dice):

  h2h      head to head against the reference, every pair of teams both ways round (engine_versus's h2h)
  round    a round robin among all specs: the matrix of head-to-head scores, and any rock-paper-scissors cycles
  crowd    against the varied crowd, and pvpoke: PvPoke's AI (engine_versus's own jobs), each paired on the reference
  reader   exploitability: points a probe that predicts the spec's next throw (pogo.reader) takes from it, over the
           same probe not reading, on the same battles and dice. Lower is better; mixing should show here
  predict  predictability: positions from the spec's own battles against the crowd (throws with a charged move ready,
           switches at a new matchup, shield calls, replacements); at each the spec, cloned as it stood, is asked again
           with fresh dice (every random.Random it holds reseeded; an engine can define reseed(seed)). The share of
           the most common answer: 100% means fully predictable from the position
  timing   live search time with the website's deadlines (pogo.realtime's default pauses, CPU clock) against the crowd:
           median, 99th percentile, share cut short, share with no complete round; also the score in those battles
  endgame  points lost against exact play on scripts/bench.py's frozen endgames (runs/bench/endgame-1.jsonl.gz)
  creator  the creators' decision exam, if scripts/lab/creator_exam.py exists and has
           league_scores(specs, workers=, seed=) -> {spec: {"score": share, "margin": share, "n": int}}

Verdict (Luke's adoption rule): above 50% head to head beyond the 95% margin, and no loss beyond the margin against the
crowd or PvPoke's AI. A screen's pass is a candidate for the confirm preset on a fresh seed, not an adoption. The
owner's field rule (docs/status.md, "Rules for proposing a change"): the default --field is mixed; also check that it
does not lose on --field standard.

Presets (--preset; any count can be overridden): smoke (5 minutes for 4 specs on 2 workers), screen (13 CPU hours for
the 4 specs above: about 1 to 1.5 hours on 14 workers), confirm (41 CPU hours: about 3 hours on 14 workers; 2,000
pairings against the reference, and a fresh --seed is required). Results are saved as they come to
runs/lab-league/<tag>/league.json; the same command again resumes, skipping what is done, and a larger preset extends.
While the pause file (default runs/lab-league/<tag>/pause) exists, workers finish their job and wait. The summary goes
to table.md and summary.json beside it, with the CPU seconds each measure took and projected times for each preset.
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import math
import os
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_v] = "1"
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
import bench  # noqa: E402
import engine_versus as EV  # noqa: E402
from pogo.agents import varied  # noqa: E402
from pogo.battle import CHARGED, SWITCH, Battle  # noqa: E402
from pogo.reader import Reader  # noqa: E402
from pogo.realtime import RealTime  # noqa: E402

OUT = ROOT / "runs" / "lab-league"
MEASURES = ("h2h", "round", "crowd", "pvpoke", "reader", "predict", "timing", "endgame", "creator")
# pairings: head to head against the reference; rr_pairings: the other pairs of the round robin; reader: pairs of
# battles, each both ways, read and not read; predict: battles against the crowd, `positions` asked `asks` times
# each; timing: battles against the crowd under live deadlines; endgame: frozen positions (None: all 318, a few
# seconds a spec; the first smoke's 30 missed all 10 positions where the website engine and the trained bot differ).
PRESETS = {
    "smoke": dict(pairings=4, rr_pairings=4, crowd=10, pvpoke=6, reader=3, predict=4, positions=3, asks=4,
                  timing=3, endgame=None),
    "screen": dict(pairings=500, rr_pairings=200, crowd=1000, pvpoke=500, reader=250, predict=60, positions=3,
                   asks=8, timing=100, endgame=None),
    "confirm": dict(pairings=2000, rr_pairings=500, crowd=2000, pvpoke=1000, reader=1000, predict=150, positions=3,
                    asks=8, timing=200, endgame=None),
}
CHUNK = {"h2h": 5, "crowd": 10, "pvpoke": 10, "reader": 2, "predict": 2, "timing": 5, "endgame": 20}
DEFAULT_SEED = 2611
# The website's release check (docs/benchmarking.md): 99th percentile, share cut short, share with no complete round.
RELEASE = {"p99_ms": 800, "cut": 0.20, "fallback": 0.005}
KINDS = ("throw", "switch", "shield", "replace")
LAYOUT = 1  # how results are keyed in league.json


# ---------------------------------------------------------------- players

class Live(RealTime):
    """The real-time engine with the game's own pauses: engine_versus.pilot() lifts every limit for RealTime itself."""


class Timer:
    """Time per decision for a player with no deadlines of its own (the trained bot, an engine that is not RealTime):
    searched decisions only when it counts them (`looks`), otherwise every decision. Wall clock (perf_counter):
    Windows' CPU clock ticks in steps of about 16 ms, too coarse for the trained bot's few milliseconds."""

    def __init__(self, inner):
        self.inner, self.rows = inner, []

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def _timed(self, decide, *args):
        looks = getattr(self.inner, "looks", None)
        start = time.perf_counter()
        answer = decide(*args)
        spent = 1000 * (time.perf_counter() - start)
        if looks is None or getattr(self.inner, "looks", 0) > looks:
            self.rows.append([round(spent, 1), 0, 0])
        return answer

    def act(self, view):
        return self._timed(self.inner.act, view)

    def shield(self, view, energy, *move):
        return self._timed(self.inner.shield, view, energy, *move)

    def replace(self, view):
        return self._timed(self.inner.replace, view)


def copy_agent(agent):
    return agent.clone() if callable(getattr(agent, "clone", None)) else copy.deepcopy(agent)


def reseed(agent, seed: int) -> None:
    """Fresh dice for every random number generator the player holds directly (random.Random, numpy Generator). An
    engine that keeps its dice elsewhere can define reseed(seed). Replaced, not reseeded in place, so a generator
    shared with the original player is left alone."""
    if callable(getattr(agent, "reseed", None)):
        agent.reseed(seed)
        return
    dice = random.Random(seed)
    for name in sorted(vars(agent)):
        value = vars(agent)[name]
        if isinstance(value, random.Random):
            setattr(agent, name, random.Random(dice.getrandbits(64)))
        elif isinstance(value, np.random.Generator):
            setattr(agent, name, np.random.default_rng(dice.getrandbits(64)))


class Snap:
    """One decision as it stood: the battle, the side, a copy of the player before it decided, and the call's args."""

    def __init__(self, kind, battle, side, agent, args=()):
        self.kind, self.battle, self.side, self.agent, self.args = kind, battle, side, agent, args

    def ask(self, seed: int):
        agent = copy_agent(self.agent)
        reseed(agent, seed)
        battle = self.battle.clone(None, None)
        view = battle.views[self.side]
        if self.kind == "shield":
            return bool(agent.shield(view, *self.args))
        if self.kind == "replace":
            return agent.replace(view)
        return agent.act(view)


class Recorder:
    """Plays as the player it wraps, keeping a Snap of each decision that is a real choice (as scripts/bench.py's
    people judge counts them): a throw with a charged move ready, a switch at a new matchup, a shield call, a
    replacement from two or more."""

    def __init__(self, inner):
        self.inner, self.snaps, self._matchup = inner, [], None

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def _snap(self, kind, view, *args):
        battle = view._battle
        self.snaps.append(Snap(kind, battle.clone(None, None), battle.views.index(view), copy_agent(self.inner), args))

    def act(self, view):
        kind = act_kind(view, self._matchup)
        self._matchup = (view.me.active, id(view.foe))
        if kind:
            self._snap(kind, view)
        return self.inner.act(view)

    def shield(self, view, energy, *move):
        if view.me.shields > 0:
            self._snap("shield", view, energy, *move)
        return self.inner.shield(view, energy, *move)

    def replace(self, view):
        if len(view.me.bench()) > 1:
            self._snap("replace", view)
        return self.inner.replace(view)


def act_kind(view, last_matchup) -> str | None:
    legal = view.legal()
    if any(a in CHARGED for a in legal):
        return "throw"
    if (view.me.active, id(view.foe)) != last_matchup and any(a in SWITCH for a in legal):
        return "switch"
    return None


def pick(snaps: list, cap: int, rng: random.Random) -> list:
    """At most `cap` snaps, taking the kinds in turn so rarer kinds (shields, replacements) are represented."""
    by = {kind: [s for s in snaps if s.kind == kind] for kind in KINDS}
    for group in by.values():
        rng.shuffle(group)
    out = []
    while len(out) < cap and any(by.values()):
        for kind in KINDS:
            if by[kind] and len(out) < cap:
                out.append(by[kind].pop())
    return out


def modal(answers: list) -> tuple[int, int, int]:
    """(how many gave the most common answer, how many were asked, how many different answers)."""
    counts = Counter(answers)
    return max(counts.values()), len(answers), len(counts)


# ---------------------------------------------------------------- jobs (run in the workers)

def setup(field: str = "mixed", pause: str | None = None, team_pool: int | None = None) -> None:
    EV.setup(field, pause, team_pool)
    bench._s["gd"] = EV._state["gd"]  # bench.restore() builds the frozen endgames from it


_endgames: list = []


def endgame_rows() -> list:
    if not _endgames:
        import gzip
        with gzip.open(bench.ENDGAMES, "rt") as f:
            _endgames.extend(json.loads(line) for line in f)
    return _endgames


def job(task):
    try:
        return _job(task)
    except StopIteration as e:  # in a worker it would end the result loop quietly, as if every job were done
        raise RuntimeError(f"StopIteration in league job {task[:2]}") from e


def _job(task):
    kind, key, numbers, opt = task
    EV.wait_while_paused(EV._state.get("pause"))
    start = time.process_time()
    if kind == "h2h":
        spec, base = key
        out = EV._job(("h2h", spec, spec, base, numbers[0], len(numbers), opt["seed"]))[2]
    elif kind in ("crowd", "pvpoke"):
        out = EV._job((kind, key, key, "", numbers[0], len(numbers), opt["seed"]))[2]
    else:
        out = {"reader": reader_battles, "predict": predict_battles, "timing": timing_battles,
               "endgame": endgame_positions}[kind](key, numbers, opt)
    return kind, key, out, time.process_time() - start, len(numbers)


def reader_battles(spec: str, numbers: list, opt: dict) -> dict:
    """[score against the probe not reading, score against it reading] per pair of battles. The reading half is
    engine_versus's reader job draw for draw, so its numbers match engine_versus --reader on the same seed and field."""
    s, out = EV._state, {}
    for n in numbers:
        rng = random.Random(opt["seed"] * 1_000_003 + n)
        a, b = s["our_draw"](rng), s["our_draw"](rng)
        dice = rng.getrandbits(32)
        plain, read = [], []
        for ours, theirs in ((a, b), (b, a)):
            target_seed, probe_seed = rng.getrandbits(32), rng.getrandbits(32)
            for reading, got in ((False, plain), (True, read)):
                target = EV.pilot(EV.parse(spec), target_seed)
                probe = EV.pilot(EV.parse(opt["probe"]), probe_seed, cls=Reader)
                if reading:
                    probe.target, probe.target_side = target, 1
                got.append(EV.points(Battle(theirs, ours, probe, target, seed=dice).run(), 1))
        out[n] = [sum(plain) / 2, sum(read) / 2]
    return out


def timing_battles(spec: str, numbers: list, opt: dict) -> dict:
    s, out = EV._state, {}
    for n in numbers:
        rng = random.Random(opt["seed"] * 1_000_003 + n)
        a, b = s["our_draw"](rng), s["draw"](rng)
        dice = rng.getrandbits(32)
        agent = EV.pilot(EV.parse(spec), dice, cls=Live)
        live = isinstance(agent, RealTime) and getattr(agent, "turn_ms", 1e9) < 1e9  # deadlines, not NO_LIMIT
        me = agent if live else Timer(agent)
        won = Battle(a, b, me, varied(random.Random(dice), s["pool"]), seed=dice).run()
        rows = [[round(r[3], 1), int(bool(r[5])), int(bool(r[6]))] for r in agent.rows] if live else me.rows
        out[n] = {"points": EV.points(won, 0), "live": live, "rows": rows}
    return out


def predict_battles(spec: str, numbers: list, opt: dict) -> dict:
    s, out = EV._state, {}
    for n in numbers:
        rng = random.Random(opt["seed"] * 1_000_003 + n)
        a, b = s["our_draw"](rng), s["draw"](rng)
        dice = rng.getrandbits(32)
        me = Recorder(EV.pilot(EV.parse(spec), dice))
        Battle(a, b, me, varied(random.Random(dice), s["pool"]), seed=dice).run()
        rows = []
        for k, snap in enumerate(pick(me.snaps, opt["positions"], random.Random(dice))):
            answers = [snap.ask(dice * 1009 + 101 * k + i) for i in range(opt["asks"])]
            rows.append([snap.kind, *modal(answers)])
        out[n] = rows
    return out


def endgame_positions(spec: str, numbers: list, opt: dict) -> dict:
    """Points given away against exact play, as scripts/bench.py's endgame judge, with engine_versus's pilot."""
    rows, out = endgame_rows(), {}
    for i in numbers:
        row = rows[i]
        battle = bench.restore(row["state"])
        agent = EV.pilot(EV.parse(spec), opt["seed"] * 1000 + i)
        view = battle.views[row["side"]]
        if row["kind"] == "shield":
            worth = row["worth"]["yes" if agent.shield(view, row["foe_energy"]) else "no"]
        else:
            worth = row["worth"].get(str(agent.act(view)))
        loss = row["value"] - (worth if worth is not None else min(row["worth"].values()))
        out[i] = [row["source"], round(max(float(loss), 0.0), 4), row["kind"]]
    return out


# ---------------------------------------------------------------- planning and saving

def runs_of(missing: list, size: int) -> list:
    """Contiguous runs of the missing numbers, at most `size` long."""
    out = []
    for n in missing:
        if out and n == out[-1][-1] + 1 and len(out[-1]) < size:
            out[-1].append(n)
        else:
            out.append([n])
    return out


def endgame_selection(total: int, wanted: int | None) -> list:
    """All positions, or `wanted` spread evenly through the frozen file (it is sorted by source)."""
    if wanted is None or wanted >= total:
        return list(range(total))
    return sorted({i * total // wanted for i in range(wanted)})


def pair_key(a: str, b: str) -> str:
    return f"{a} | {b}"


def plan_jobs(saved: dict, specs: list, sizes: dict, measures: set, seeds: dict, probe: str,
              endgame_total: int) -> list:
    """Every chunk still missing, interleaved across measures so a stopped run has some of everything."""
    results = saved.setdefault("results", {})
    streams = []

    def add(kind, key, numbers, opt):
        have = results.get(kind, {})
        if kind == "h2h":
            have = have.get(key[0], {}).get(key[1], {})
        else:
            have = have.get(key, {})
        missing = [n for n in numbers if str(n) not in have]
        if kind == "endgame":
            chunks = [missing[i:i + CHUNK[kind]] for i in range(0, len(missing), CHUNK[kind])]
        else:
            chunks = runs_of(missing, CHUNK[kind])
        streams.append([(kind, key, c, opt) for c in chunks])

    ref = specs[0]
    for j, spec in enumerate(specs):
        for i in range(j):
            base = specs[i]
            count = sizes["pairings"] if base == ref else sizes["rr_pairings"]
            if (base == ref and "h2h" in measures) or (base != ref and "round" in measures):
                # keep the way round an earlier run (with the specs in another order) used
                key = (base, spec) if spec in results.get("h2h", {}).get(base, {}) else (spec, base)
                add("h2h", key, range(count), {"seed": seeds["battles"]})
    for spec in specs:
        for kind in ("crowd", "pvpoke"):
            if kind in measures:
                add(kind, spec, range(sizes[kind]), {"seed": seeds["battles"]})
        if "reader" in measures:
            add("reader", spec, range(sizes["reader"]), {"seed": seeds["battles"], "probe": probe})
        if "timing" in measures:
            add("timing", spec, range(sizes["timing"]), {"seed": seeds["timing"]})
        if "predict" in measures:
            add("predict", spec, range(sizes["predict"]),
                {"seed": seeds["predict"], "positions": sizes["positions"], "asks": sizes["asks"]})
        if "endgame" in measures:
            add("endgame", spec, endgame_selection(endgame_total, sizes["endgame"]), {"seed": seeds["endgame"]})
    plan = []
    for k in range(max((len(s) for s in streams), default=0)):
        plan += [s[k] for s in streams if k < len(s)]
    return plan


def collect(saved: dict, result) -> None:
    kind, key, out, seconds, units = result
    results = saved.setdefault("results", {}).setdefault(kind, {})
    if kind == "h2h":  # results["h2h"][spec][base]: spec's points against base
        target = results.setdefault(key[0], {}).setdefault(key[1], {})
    else:
        target = results.setdefault(key, {})
    target.update({str(n): v for n, v in out.items()})
    cost = saved.setdefault("cost", {}).setdefault(kind, {})
    name = pair_key(*key) if kind == "h2h" else key
    spent, count = cost.get(name, [0.0, 0])
    cost[name] = [round(spent + seconds, 2), count + units]


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, separators=(",", ":"))
    os.replace(tmp, path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


# ---------------------------------------------------------------- summary

def mean_margin(values) -> tuple[float, float]:
    values = list(values)
    if not values:
        return float("nan"), float("nan")
    if len(values) == 1:
        return float(values[0]), float("nan")
    return EV.mean_and_margin(values)


def series(saved: dict, kind: str, key: str) -> dict:
    return {int(n): v for n, v in saved.get("results", {}).get(kind, {}).get(key, {}).items()}


def pair_scores(saved: dict, a: str, b: str) -> dict:
    """a's points against b by pairing, whichever way round the pair was run."""
    h2h = saved.get("results", {}).get("h2h", {})
    if b in h2h.get(a, {}):
        return {int(n): v for n, v in h2h[a][b].items()}
    if a in h2h.get(b, {}):
        return {int(n): 1.0 - v for n, v in h2h[b][a].items()}
    return {}


def paired(x: dict, y: dict) -> tuple[float, float, int]:
    common = sorted(set(x) & set(y))
    m, h = mean_margin([x[n] - y[n] for n in common])
    return m, h, len(common)


def cycles(names: list, score) -> list:
    """Rock-paper-scissors triples: a beats b, b beats c, c beats a on the point estimates. score(a, b) gives
    (mean, margin) of a's share against b, or None. Each cycle once, with whether every edge clears its margin."""
    out = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            for k in range(j + 1, len(names)):
                for a, b, c in ((names[i], names[j], names[k]), (names[i], names[k], names[j])):
                    edges = [score(a, b), score(b, c), score(c, a)]
                    if any(e is None or math.isnan(e[0]) for e in edges):
                        continue
                    if all(m > 0.5 for m, _ in edges):
                        out.append({"cycle": [a, b, c], "scores": [m for m, _ in edges],
                                    "beyond_margin": all(m - h > 0.5 for m, h in edges)})
    return out


def verdict(h2h, crowd, pvpoke, confirm: bool = False) -> str:
    """Luke's adoption rule: above 50% head to head beyond the margin, no loss beyond the margin against the crowd
    or PvPoke's AI. Each argument is (mean, margin) as fractions (h2h a share, the others paired differences on the
    reference), or None when not measured."""
    if h2h is None or math.isnan(h2h[0]):
        return "no head to head"
    m, h = h2h
    if math.isnan(h):
        return "too few battles"
    losses, missing = [], []
    for name, d in (("crowd", crowd), ("PvPoke", pvpoke)):
        if d is None or math.isnan(d[0]) or math.isnan(d[1]):
            missing.append(f"{name} not measured")
        elif d[0] + d[1] < 0:
            losses.append(f"loses points to {name}")
    if m + h < 0.5:
        return "; ".join(["fail: worse head to head", *losses])
    if m - h <= 0.5:
        return "; ".join(["no gain shown: head to head within margin", *losses])
    if losses:
        return "fail: wins head to head but " + "; ".join(losses)
    if missing:
        return "incomplete: wins head to head; " + "; ".join(missing)
    return "PASS" if confirm else "pass: confirm on a fresh seed"


def cluster_margin(rows: list) -> tuple[float, float]:
    """Mean of (cluster, value) rows with each cluster (a battle, a game) as one sample (scripts/bench.py)."""
    return bench.cluster(rows)


def bootstrap(games: list, measure, seed: int = 0, draws: int = 400) -> tuple[float, float]:
    """95% interval of measure(rows) resampling whole battles."""
    games = [g for g in games if g]
    if len(games) < 2:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    values = [measure([r for i in rng.integers(len(games), size=len(games)) for r in games[i]]) for _ in range(draws)]
    lo, hi = np.percentile(values, [2.5, 97.5])
    return float(lo), float(hi)


def summarize(saved: dict, specs: list) -> dict:
    ref = specs[0]
    out = {"reference": ref, "specs": {}, "matrix": {}, "cycles": []}
    for a in specs:
        out["matrix"][a] = {}
        for b in specs:
            if a != b:
                got = pair_scores(saved, a, b)
                m, h = mean_margin(got.values())
                out["matrix"][a][b] = {"score": m, "margin": h, "n": len(got)}

    def score(a, b):
        cell = out["matrix"][a].get(b)
        return None if cell is None or not cell["n"] else (cell["score"], cell["margin"])

    out["cycles"] = cycles(specs, score)
    for spec in specs:
        r = {}
        if spec != ref:
            got = pair_scores(saved, spec, ref)
            if got:
                m, h = mean_margin(got.values())
                r["h2h"] = {"score": m, "margin": h, "n": len(got)}
        others = [pair_scores(saved, spec, b) for b in specs if b != spec]
        if others and all(others):
            common = set.intersection(*(set(o) for o in others))
            m, h = mean_margin([sum(o[n] for o in others) / len(others) for n in sorted(common)])
            r["round_robin"] = {"score": m, "margin": h, "n": len(common), "opponents": len(others)}
        for kind in ("crowd", "pvpoke"):
            got = series(saved, kind, spec)
            if got:
                m, h = mean_margin(got.values())
                r[kind] = {"score": m, "margin": h, "n": len(got)}
                if spec != ref and series(saved, kind, ref):
                    d, dh, n = paired(got, series(saved, kind, ref))
                    r[kind].update(diff=d, diff_margin=dh, diff_n=n)
        got = series(saved, "reader", spec)
        if got:
            gain = {n: v[0] - v[1] for n, v in got.items()}
            m, h = mean_margin(gain.values())
            r["reader"] = {"gain": m, "margin": h, "n": len(got),
                           "plain": mean_margin(v[0] for v in got.values())[0],
                           "read": mean_margin(v[1] for v in got.values())[0]}
            base = series(saved, "reader", ref)
            if spec != ref and base:
                d, dh, n = paired(gain, {k: v[0] - v[1] for k, v in base.items()})
                r["reader"].update(diff=d, diff_margin=dh, diff_n=n)
        got = series(saved, "predict", spec)
        if got:
            p = {}
            for kind in (None, *KINDS):
                rows = [(n, row) for n, battle in got.items() for row in battle if kind is None or row[0] == kind]
                if not rows:
                    continue
                share = cluster_margin([(n, row[1] / row[2]) for n, row in rows])
                varies = cluster_margin([(n, float(row[3] > 1)) for n, row in rows])
                p[kind or "all"] = {"modal": share[0], "margin": share[1], "varies": varies[0], "positions": len(rows)}
            p["asks"] = max(row[2] for battle in got.values() for row in battle) if any(got.values()) else 0
            p["battles"] = len(got)
            r["predict"] = p
        got = series(saved, "timing", spec)
        if got:
            games = [g["rows"] for g in got.values()]
            rows = [row for g in games for row in g]
            live = all(g["live"] for g in got.values())
            t = {"battles": len(got), "decisions": len(rows), "live": live}
            pts = mean_margin(g["points"] for g in got.values())
            t["crowd_live"] = {"score": pts[0], "margin": pts[1]}
            if rows:
                spent = np.array([row[0] for row in rows])
                t.update(median_ms=float(np.median(spent)), p99_ms=float(np.percentile(spent, 99)),
                         worst_ms=float(spent.max()), cut=float(np.mean([row[1] for row in rows])),
                         fallback=float(np.mean([row[2] for row in rows])))
                t["p99_interval"] = bootstrap(games, lambda rs: np.percentile([x[0] for x in rs], 99))
                t["cut_interval"] = bootstrap(games, lambda rs: np.mean([x[1] for x in rs]))
                t["release_ok"] = (live and t["p99_ms"] <= RELEASE["p99_ms"] and t["cut"] <= RELEASE["cut"]
                                   and t["fallback"] <= RELEASE["fallback"])
            r["timing"] = t
        got = series(saved, "endgame", spec)
        if got:
            rows = [(v[0], v[1]) for v in got.values()]
            m, h = cluster_margin(rows)
            e = {"points": 100 * m, "margin": 100 * h, "n": len(rows),
                 "blunders": 100 * float(np.mean([v[1] >= 0.1 for v in got.values()]))}
            for kind in ("act", "shield"):
                these = [(v[0], v[1]) for v in got.values() if v[2] == kind]
                if these:
                    e[kind] = 100 * cluster_margin(these)[0]
            base = series(saved, "endgame", ref)
            if spec != ref and base:
                common = sorted(set(got) & set(base))
                if common:
                    d, dh = cluster_margin([(got[i][0], got[i][1] - base[i][1]) for i in common])
                    e.update(diff=100 * d, diff_margin=100 * dh, diff_n=len(common))
            r["endgame"] = e
        creator = saved.get("creator", {}).get(spec)
        if creator:
            r["creator"] = creator
        r["verdict"] = ("reference" if spec == ref else verdict(
            (r["h2h"]["score"], r["h2h"]["margin"]) if "h2h" in r else None,
            (r["crowd"]["diff"], r["crowd"]["diff_margin"]) if "diff" in r.get("crowd", {}) else None,
            (r["pvpoke"]["diff"], r["pvpoke"]["diff_margin"]) if "diff" in r.get("pvpoke", {}) else None,
            confirm=saved.get("preset") == "confirm"))
        out["specs"][spec] = r
    return out


def pct(m, h=None, sign=False) -> str:
    if m is None or (isinstance(m, float) and math.isnan(m)):
        return "—"
    text = f"{100 * m:+.1f}" if sign else f"{100 * m:.1f}"
    if h is not None:
        text += " (one)" if math.isnan(h) else f" ± {100 * h:.1f}"
    return text


def pts(m, h=None, sign=False) -> str:
    """Already in points (endgame)."""
    if m is None or math.isnan(m):
        return "—"
    text = f"{m:+.2f}" if sign else f"{m:.2f}"
    if h is not None:
        text += " (one)" if math.isnan(h) else f" ± {h:.2f}"
    return text


def table(summary: dict, specs: list, saved: dict) -> str:
    ref = specs[0]
    sizes = saved.get("sizes", {})
    lines = [f"# League {saved.get('tag', '')}: {saved.get('preset', '')} preset, seed {saved.get('seed')}, "
             f"field {saved.get('field')}" + (f", team pool {saved['team_pool']}" if saved.get("team_pool") else ""),
             "",
             f"Reference: `{ref}`. Shares and points are in percent with 95% margins; Δ is paired on the reference "
             "(same battles). Verdict: Luke's rule (above 50% head to head beyond the margin, no loss beyond the "
             "margin against the crowd or PvPoke's AI). ↓ lower is better.",
             "",
             "| # | spec | verdict | head to head vs ref | crowd, Δ ref | PvPoke, Δ ref | round robin | "
             "reader's gain ↓, Δ ref | predictable (modal share) | live ms median / p99, cut | "
             "endgame points lost ↓, Δ ref | creator exam |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, spec in enumerate(specs):
        r = summary["specs"][spec]
        cells = [str(k), f"`{spec}`", r["verdict"]]
        h = r.get("h2h")
        cells.append("—" if spec == ref else pct(h["score"], h["margin"]) + f" ({h['n']})" if h else "—")
        for kind in ("crowd", "pvpoke"):
            c = r.get(kind)
            if not c:
                cells.append("—")
            elif "diff" in c:
                cells.append(f"{pct(c['score'])}, {pct(c['diff'], c['diff_margin'], sign=True)}")
            else:
                cells.append(pct(c["score"], c["margin"]))
        rr = r.get("round_robin")
        cells.append(pct(rr["score"], rr["margin"]) if rr else "—")
        rd = r.get("reader")
        if rd:
            text = pct(rd["gain"], rd["margin"], sign=True)
            if "diff" in rd:
                text += f", {pct(rd['diff'], rd['diff_margin'], sign=True)}"
            cells.append(text)
        else:
            cells.append("—")
        p = r.get("predict", {}).get("all")
        cells.append(f"{pct(p['modal'], p['margin'])}, varies {pct(p['varies'])} ({p['positions']})" if p else "—")
        t = r.get("timing")
        if t and "median_ms" in t:
            text = f"{t['median_ms']:.0f} / {t['p99_ms']:.0f}, cut {pct(t['cut'])}"
            cells.append(text if t["live"] else text.split(",")[0] + " (no deadline)")
        else:
            cells.append("—")
        e = r.get("endgame")
        if e:
            text = pts(e["points"], e["margin"])
            if "diff" in e:
                text += f", {pts(e['diff'], e['diff_margin'], sign=True)}"
            cells.append(text)
        else:
            cells.append("—")
        c = r.get("creator")
        cells.append(pct(c.get("score"), c.get("margin")) if c and "score" in c else "—")
        lines.append("| " + " | ".join(cells) + " |")

    lines += ["", "## Round robin (row's score against the column, %)", "",
              "| | " + " | ".join(f"{k}" for k in range(len(specs))) + " |",
              "|---|" + "---|" * len(specs)]
    for k, a in enumerate(specs):
        cells = []
        for b in specs:
            cell = summary["matrix"][a].get(b)
            cells.append("·" if a == b else (pct(cell["score"], cell["margin"]) if cell and cell["n"] else "—"))
        lines.append(f"| {k} | " + " | ".join(cells) + " |")
    names = {s: str(k) for k, s in enumerate(specs)}
    if summary["cycles"]:
        for c in summary["cycles"]:
            lines.append("")
            lines.append("Cycle: " + " beats ".join(names[s] for s in c["cycle"]) + f" beats {names[c['cycle'][0]]} ("
                         + ", ".join(f"{100 * s:.1f}%" for s in c["scores"]) + "), "
                         + ("every edge beyond its margin" if c["beyond_margin"] else "within the margins"))
    else:
        lines += ["", "No rock-paper-scissors cycle on the point estimates."]

    lines += ["", "## Predictability by kind of decision (modal share; varies = positions with more than one answer)",
              "", "| # | throw | switch | shield | replace | asks | battles |", "|---|---|---|---|---|---|---|"]
    for k, spec in enumerate(specs):
        p = summary["specs"][spec].get("predict")
        if not p:
            continue
        cells = [f"{pct(p[kind]['modal'])} (varies {pct(p[kind]['varies'])}, {p[kind]['positions']})"
                 if kind in p else "—" for kind in KINDS]
        lines.append(f"| {k} | " + " | ".join(cells) + f" | {p['asks']} | {p['battles']} |")

    lines += ["", "## Live timing (searched decisions, CPU clock, the website's deadlines; † no deadline: CPU time per "
              "searched decision, or per decision if it does not count searches)", "",
              "| # | battles | decisions | median ms | p99 ms (95%) | worst | cut short (95%) | no round | "
              "release limits | crowd under deadlines |", "|---|---|---|---|---|---|---|---|---|---|"]
    for k, spec in enumerate(specs):
        t = summary["specs"][spec].get("timing")
        if not t or "median_ms" not in t:
            continue
        lo, hi = t["p99_interval"]
        clo, chi = t["cut_interval"]
        p99 = f"{t['p99_ms']:.0f}" + ("" if math.isnan(lo) else f" ({lo:.0f}–{hi:.0f})")
        cut = pct(t["cut"]) + ("" if math.isnan(clo) else f" ({pct(clo)}–{pct(chi)})")
        lines.append(
            f"| {k}{'' if t['live'] else ' †'} | {t['battles']} | {t['decisions']} | {t['median_ms']:.0f} | "
            f"{p99} | {t['worst_ms']:.0f} | {cut} | {pct(t['fallback'])} | "
            f"{('ok' if t['release_ok'] else 'over') if t['live'] else 'n/a'} | "
            f"{pct(t['crowd_live']['score'], t['crowd_live']['margin'])} |")

    lines += ["", "## Exact endgames (points lost a decision ×100, clustered by game)", "",
              "| # | all | moves | shields | blunders ≥ 0.1 | positions |", "|---|---|---|---|---|---|"]
    for k, spec in enumerate(specs):
        e = summary["specs"][spec].get("endgame")
        if e:
            lines.append(f"| {k} | {pts(e['points'], e['margin'])} | {pts(e.get('act'))} | {pts(e.get('shield'))} | "
                         f"{e['blunders']:.1f}% | {e['n']} |")

    lines += ["", "## Exploitability detail (score against the probe, not reading / reading)", "",
              "| # | not read | read | gain ↓ | pairs |", "|---|---|---|---|---|"]
    for k, spec in enumerate(specs):
        rd = summary["specs"][spec].get("reader")
        if rd:
            lines.append(f"| {k} | {pct(rd['plain'])} | {pct(rd['read'])} | {pct(rd['gain'], rd['margin'], sign=True)}"
                         f" | {rd['n']} |")
    creator = saved.get("creator_note")
    if creator:
        lines += ["", f"Creator exam: {creator}"]
    if sizes:
        lines += ["", "Sizes: " + ", ".join(f"{k} {v}" for k, v in sizes.items())]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- costs

def unit_costs(saved: dict) -> dict:
    """CPU seconds per unit (a pairing, a battle, a reader pair, a position) by kind and spec or pair."""
    return {kind: {key: s / n for key, (s, n) in by.items() if n} for kind, by in saved.get("cost", {}).items()}


def projected(saved: dict, specs: list, sizes: dict, measures: set, endgame_total: int) -> tuple[float, list]:
    """CPU seconds a run of these sizes would take, from the measured unit costs; and what had no measured cost."""
    costs, total, unknown = unit_costs(saved), 0.0, []
    ref = specs[0]
    measured = saved.get("sizes", sizes)
    asks = (sizes["positions"] * sizes["asks"]) / max(1, measured["positions"] * measured["asks"])

    def add(kind, key, units):
        nonlocal total
        c = costs.get(kind, {}).get(key)
        if c is None and kind == "h2h":
            a, b = key.split(" | ")
            c = costs.get(kind, {}).get(pair_key(b, a))
        if c is None:
            unknown.append(f"{kind} {key}")
        else:
            total += c * units

    for j, spec in enumerate(specs):
        for i in range(j):
            base = specs[i]
            if (base == ref and "h2h" in measures) or (base != ref and "round" in measures):
                add("h2h", pair_key(spec, base), sizes["pairings"] if base == ref else sizes["rr_pairings"])
    for spec in specs:
        for kind in ("crowd", "pvpoke", "reader", "timing", "predict"):
            if kind in measures:
                # a predict battle's cost is mostly its questions: scaled from the sizes it was measured at
                add(kind, spec, sizes[kind] * (asks if kind == "predict" else 1))
        if "endgame" in measures:
            add("endgame", spec, len(endgame_selection(endgame_total, sizes["endgame"])))
    return total, unknown


# ---------------------------------------------------------------- creator exam (optional)

def creator_exam(specs: list, workers: int, seed: int) -> tuple[dict, str]:
    path = ROOT / "scripts" / "lab" / "creator_exam.py"
    if not path.exists():
        return {}, "skipped: scripts/lab/creator_exam.py not found"
    loader = importlib.util.spec_from_file_location("creator_exam", path)
    module = importlib.util.module_from_spec(loader)
    try:
        loader.loader.exec_module(module)
    except Exception as e:  # another agent's script: report, do not stop the league
        return {}, f"failed to import creator_exam.py: {e!r}"
    scores = getattr(module, "league_scores", None)
    if not callable(scores):
        return {}, "skipped: creator_exam.py has no league_scores(specs, workers=, seed=)"
    try:
        got = scores(list(specs), workers=workers, seed=seed)
    except Exception as e:
        return {}, f"creator_exam.league_scores failed: {e!r}"
    return {spec: dict(v) for spec, v in got.items() if spec in specs}, "from scripts/lab/creator_exam.py"


# ---------------------------------------------------------------- main

def main(argv=None) -> dict:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("specs", nargs="*", help="engine_versus.py settings; the reference first unless --reference")
    parser.add_argument("--reference", default="website", help="the reference spec (default website)")
    parser.add_argument("--preset", choices=tuple(PRESETS), default="smoke")
    parser.add_argument("--tag", required=True, help="results in runs/lab-league/<tag>/")
    parser.add_argument("--seed", type=int, help=f"default {DEFAULT_SEED}; the confirm preset needs a fresh one")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--field", choices=("standard", "pvpoke", "mixed"), default="mixed",
                        help="opposing teams (engine_versus --field); the owner's rule measures on mixed")
    parser.add_argument("--team-pool", type=int, choices=(50,), help="as engine_versus --team-pool")
    parser.add_argument("--measures", default=",".join(MEASURES), help="comma-separated subset of " + ",".join(MEASURES))
    parser.add_argument("--probe", default="", help="the reading probe's engine settings (default: engine_versus's "
                                                    "confirmed engine, 4 imagined battles, as its --reader)")
    parser.add_argument("--pause-file", help="default runs/lab-league/<tag>/pause")
    parser.add_argument("--out", type=Path, default=OUT, help=argparse.SUPPRESS)  # tests write elsewhere
    parser.add_argument("--estimate-workers", type=int, default=14, help="workers assumed for projected times")
    for name in PRESETS["smoke"]:
        parser.add_argument("--" + name.replace("_", "-"), type=int, help=f"override the preset's {name}")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(newline="\n")  # the .out logs stay LF on Windows, as the repository's text files are
    except (AttributeError, ValueError):
        pass

    specs = list(dict.fromkeys([args.reference, *args.specs]))
    for spec in specs:
        EV.parse(spec)  # a mistyped setting fails here, before any worker starts
    probe = EV.parse(args.probe)
    if probe is None or probe.get("_bot"):
        parser.error("--probe must describe an engine, not the trained bot")
    measures = set(args.measures.split(","))
    if measures - set(MEASURES):
        parser.error(f"unknown measures {sorted(measures - set(MEASURES))}")
    sizes = dict(PRESETS[args.preset])
    for name in sizes:
        value = getattr(args, name)
        if value is not None:
            sizes[name] = value
    tag_dir = args.out / args.tag
    path = tag_dir / "league.json"
    saved = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if args.preset == "confirm":
        if args.seed is None:
            parser.error("the confirm preset needs --seed, a fresh one")
        for other in args.out.glob("*/league.json"):
            if other != path and json.loads(other.read_text(encoding="utf-8")).get("seed") == args.seed:
                parser.error(f"seed {args.seed} was used by {other.parent.name}; confirm needs a fresh seed")
    seed = args.seed if args.seed is not None else saved.get("seed", DEFAULT_SEED)
    for name, value in (("seed", seed), ("field", args.field), ("team_pool", args.team_pool), ("layout", LAYOUT)):
        if saved and saved.get(name) != value:
            raise SystemExit(f"{path} was made with {name} {saved.get(name)!r}; use that or another tag")
    seeds = {"battles": seed, "timing": seed + 1, "predict": seed + 2, "endgame": seed + 3}
    saved.update(tag=args.tag, seed=seed, field=args.field, team_pool=args.team_pool, layout=LAYOUT,
                 preset=args.preset, sizes=sizes, probe=args.probe, reference=specs[0],
                 specs=list(dict.fromkeys([*saved.get("specs", []), *specs])))
    pause = args.pause_file or str(tag_dir / "pause")
    endgame_total = len(endgame_rows()) if "endgame" in measures else 0
    plan = plan_jobs(saved, specs, sizes, measures, seeds, args.probe, endgame_total)
    print(f"league {args.tag}: {len(specs)} specs, preset {args.preset}, seed {seed}, field {args.field}; "
          f"{len(plan)} jobs on {args.workers} workers (pause file: {pause})", flush=True)
    for k, spec in enumerate(specs):
        print(f"  {k}: {spec}" + ("  (reference)" if k == 0 else ""), flush=True)
    t0 = last = time.time()
    before = saved.get("elapsed_seconds", 0.0)
    if plan:
        for result in EV.run_jobs(job, plan, args.workers, setup, (args.field, pause, args.team_pool), spawn=True):
            collect(saved, result)
            if time.time() - last > 30:
                saved["elapsed_seconds"] = round(before + time.time() - t0, 1)
                write_json(path, saved)
                last = time.time()
                done = sum(c[1] for by in saved["cost"].values() for c in by.values())
                print(f"  {(time.time() - t0) / 60:.1f} min, {done} units done", flush=True)
    if "creator" in measures:
        missing = [s for s in specs if s not in saved.get("creator", {})]
        if missing:
            got, note = creator_exam(missing, args.workers, seed)
            saved.setdefault("creator", {}).update(got)
            saved["creator_note"] = note
    saved["elapsed_seconds"] = round(before + time.time() - t0, 1)
    write_json(path, saved)
    summary = summarize(saved, specs)
    summary["elapsed_seconds"] = saved["elapsed_seconds"]
    summary["unit_cpu_seconds"] = unit_costs(saved)
    summary["projected"] = {}
    for name, preset in PRESETS.items():
        cpu, unknown = projected(saved, specs, preset, measures, endgame_total or len(endgame_rows()))
        summary["projected"][name] = {"cpu_hours": cpu / 3600, "unknown": unknown,
                                      "wall_hours_at": {str(args.estimate_workers): cpu / 3600 / args.estimate_workers,
                                                        "2": cpu / 3600 / 2}}
    text = table(summary, specs, saved)
    text += "\n## Cost (CPU seconds per unit, this machine) and projected times\n\n"
    for kind, by in summary["unit_cpu_seconds"].items():
        text += f"- {kind}: " + "; ".join(f"`{key}` {v:.2f}" for key, v in by.items()) + "\n"
    for name, p in summary["projected"].items():
        text += (f"- {name}: {p['cpu_hours']:.2f} CPU hours, about {p['wall_hours_at'][str(args.estimate_workers)]:.2f}"
                 f" h on {args.estimate_workers} workers, {p['wall_hours_at']['2']:.2f} h on 2"
                 + (f" (no cost measured for {len(p['unknown'])} parts)" if p["unknown"] else "") + "\n")
    text += (f"\nElapsed: {summary['elapsed_seconds'] / 60:.1f} min in all; this invocation "
             f"{(time.time() - t0) / 60:.1f} min on {args.workers} workers.\n")
    write_text(tag_dir / "table.md", text)
    with open(tag_dir / "summary.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(summary, f, indent=1, default=float)
        f.write("\n")
    print("\n" + text, flush=True)
    print(f"results: {tag_dir}", flush=True)
    return summary


if __name__ == "__main__":
    main()
