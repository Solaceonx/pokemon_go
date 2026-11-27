#!/usr/bin/env python3
"""Does giving the engine a cup's field help in that cup? Today's live engine (pogo.realtime.WEBSITE with the live
settings, without the phone's time cap) plays our team against the real teams met in the cup, three ways:

    open   their unseen Pokémon imagined from the open Great League top 50 (as until 2026-11-26)
    pool   imagined from the cup's field (scripts/live/cup_field.py: species met twice or more)
    teams  the cup's field and its real teams (the bench imagined from teams that hold the ones seen)

    python3 scripts/cup_versus.py --field FIELD.json --accounts third --team data/team_third.json --seeds 12 \
        --workers 3 --seed 4911 --tag mcc-1

The opponents are the teams of the battles not used to build FIELD (--accounts: whose battles; lead first, the moves
the tracker knew), played by the trained bot with habits varied in each battle (as pogo.lineup.win_chance). Every arm
meets each opponent on the same seeds (same dice, same opponent habits), so the arms' differences are paired.
Battles are saved as they finish to runs/cup-field/TAG.jsonl and a rerun skips them; the table goes to TAG.json.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
from multiprocessing import get_context
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "1")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts" / "live"))

ARMS = ("open", "pool", "teams")
_w: dict = {}


def load_team(gd, path: Path) -> list:
    by_name = {m.name: m.id for m in gd.moves.values()}
    out = []
    for e in json.loads(path.read_text(encoding="utf-8"))["pokemon"]:
        sid = next(k for k, v in gd.species.items() if v["speciesName"] == e["species"])
        exact = {"level": e["level"], "ivs": tuple(e["ivs"])} if "level" in e and "ivs" in e else {}
        out.append(gd.build(sid, [by_name[e["fast"]], *(by_name[m] for m in e["charged"])], **exact))
    return out


def field_parts(gd, path: Path):
    """(pool, teams, builds) as the live player builds them (play_android.cup_field), without importing it."""
    data = json.loads(path.read_text(encoding="utf-8"))
    moves, builds = data.get("moves", {}), {}
    for sp, _ in data["species"]:
        if sp not in gd.species or not gd.supported(sp):
            continue
        m = moves.get(sp)
        try:
            builds[sp] = gd.build(sp, [m["fast"], *m["charged"]]) if m else gd.default(sp)
        except (KeyError, ValueError):
            continue
    pool = [builds[sp] for sp, k in data["species"] if k >= data.get("min_seen", 2) and sp in builds]
    teams = [(float(e["weight"]), list(e["team"])) for e in data.get("teams", []) if all(sp in builds for sp in e["team"])]
    return pool, teams, builds


def init(field: str, team: str) -> None:
    from pogo.evaluation import Evaluator
    from pogo.gamedata import GameData
    from pogo.learner import QNet
    gd = GameData()
    pool, teams, builds = field_parts(gd, Path(field))
    _w.update(gd=gd, open=gd.meta(50), pool=pool, teams=teams, builds=builds, mine=load_team(gd, Path(team)),
              ev=Evaluator.load(ROOT / "runs" / "eval" / "eval.npz"), q=QNet.load(str(ROOT / "runs" / "general-decide" / "q.npz")))


def play(job: dict) -> dict:
    from play_android import LIVE_ENGINE, engine_settings  # noqa: F401  (cv2 stubbed below)
    from pogo.agents import varied_settings
    from pogo.battle import DRAW, Battle
    from pogo.engine import Engine
    from pogo.evaluation import Evaluator
    from pogo.learner import Learner
    from pogo.realtime import WEBSITE
    gd, arm = _w["gd"], job["arm"]
    theirs = []
    for sp in job["foes"]:
        m = job["moves"].get(sp)
        try:
            theirs.append(gd.build(sp, [m[0], *m[1]]) if m else gd.default(sp))
        except (KeyError, ValueError):
            theirs.append(_w["builds"][sp])
    rng = random.Random(job["seed"])
    foe = Learner(q=_w["q"], margin=rng.choice((0.02, 0.05)), **varied_settings(rng, _w["open"]))
    battle_seed = rng.getrandbits(32)
    pool = _w["open"] if arm == "open" else _w["pool"]
    me = Engine(Evaluator(_w["ev"].model), pool, q=_w["q"], seed=job["seed"] % 100000,
                **{**WEBSITE, **engine_settings(LIVE_ENGINE)})
    if arm == "teams" and _w["teams"]:
        me._teams, me._team_builds = _w["teams"], _w["builds"]
    winner = Battle(_w["mine"], theirs, me, foe, seed=battle_seed).run()
    return {**{k: job[k] for k in ("key", "arm", "stamp", "seed")}, "foes": job["foes"],
            "points": 1.0 if winner == 0 else 0.5 if winner == DRAW else 0.0}


def mean_margin(xs: list) -> tuple[float, float]:
    n = len(xs)
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / max(1, n - 1))
    return m, 1.96 * sd / math.sqrt(n)


def main() -> None:
    import importlib.util, types
    ap = argparse.ArgumentParser()
    ap.add_argument("--field", required=True)
    ap.add_argument("--accounts", nargs="+", required=True, help="the battles to meet (not used to build --field)")
    ap.add_argument("--season", default="catch")
    ap.add_argument("--league", default="Great League Edition")
    ap.add_argument("--team", default=str(ROOT / "data" / "team_third.json"))
    ap.add_argument("--seeds", type=int, default=12)
    ap.add_argument("--seed", type=int, default=4911)
    ap.add_argument("--arms", nargs="+", default=list(ARMS))
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--tag", required=True)
    a = ap.parse_args()
    from cup_field import battles
    met = [(stamp, foes, {sp: (f, list(c)) for sp, (f, c) in moves.items()})
           for stamp, _, foes, moves in battles((ROOT / "runs" / "live").glob("2*.jsonl"), a.season, a.league, a.accounts)
           if len(foes) == 3]
    out = ROOT / "runs" / "cup-field" / f"{a.tag}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    done = {json.loads(l)["key"] + "|" + json.loads(l)["arm"] for l in open(out)} if out.exists() else set()
    jobs = []
    for i, (stamp, foes, moves) in enumerate(met):
        for j in range(a.seeds):
            key = f"{stamp}|{j}"
            for arm in a.arms:
                if f"{key}|{arm}" not in done:
                    jobs.append({"key": key, "arm": arm, "stamp": stamp, "foes": foes, "moves": moves,
                                 "seed": a.seed * 1_000_003 + i * 1009 + j})
    print(f"{len(met)} opponents x {a.seeds} seeds x {len(a.arms)} arms: {len(jobs)} battles to play", flush=True)
    if importlib.util.find_spec("cv2") is None:
        sys.modules["cv2"] = types.ModuleType("cv2")
    if jobs:
        with get_context("spawn").Pool(a.workers, initializer=_init_worker, initargs=(a.field, a.team)) as p, \
                open(out, "a", encoding="utf-8") as f:
            for k, r in enumerate(p.imap_unordered(play, jobs), 1):
                f.write(json.dumps(r) + "\n"); f.flush()
                if k % 50 == 0:
                    print(f"{k}/{len(jobs)}", flush=True)
    rows = [json.loads(l) for l in open(out)]
    by = {}
    for r in rows:
        by.setdefault(r["key"], {})[r["arm"]] = r["points"]
    full = [v for v in by.values() if all(arm in v for arm in a.arms)]
    table = {"battles": len(full), "field": a.field, "accounts": a.accounts, "seed": a.seed, "arms": {}}
    for arm in a.arms:
        m, e = mean_margin([v[arm] for v in full])
        table["arms"][arm] = {"win": round(m, 4), "margin": round(e, 4)}
        line = f"{arm:6} {100 * m:5.1f}% ± {100 * e:.1f}"
        if arm != "open" and "open" in a.arms:
            d, de = mean_margin([v[arm] - v["open"] for v in full])
            table["arms"][arm].update(vs_open=round(d, 4), vs_open_margin=round(de, 4))
            line += f"   paired vs open {100 * d:+.1f} ± {100 * de:.1f}"
        print(line)
    print(f"({len(full)} paired opponent-seeds)")
    out.with_suffix(".json").write_text(json.dumps(table, indent=1) + "\n", encoding="utf-8")


def _init_worker(field: str, team: str) -> None:
    import importlib.util, types
    if importlib.util.find_spec("cv2") is None:
        sys.modules["cv2"] = types.ModuleType("cv2")
    try:
        os.nice(10)
    except (AttributeError, OSError):
        pass
    init(field, team)


if __name__ == "__main__":
    main()
