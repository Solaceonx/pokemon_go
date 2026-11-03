#!/usr/bin/env python3
"""Engine settings scored on the exam (docs/benchmarking.md): each variant's pick at the exam's positions against the players' answers.

    python3 scripts/exam_variants.py ANSWERS.json [ANSWERS.json ...] [--variants switch_edge=0.05 ...] [--workers 3]

Replays every game the exam's positions come from, as scripts/exam_positions.py does, with the rulebook, the trained bot, the
website's engine and each variant (engine settings as `key=value,...`) asking at every decision, the variants with the engine's dice.
The engine's picks must come out as the exam's key has them. Each variant is scored where each person answered and where all of them
agree. A screen only: the positions were chosen where versions disagree and these answers are already known, so a variant that does
well here is tested on fresh positions before anything changes.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
import exam_positions as E  # noqa: E402
from pogo.battle import Battle  # noqa: E402
from pogo.engine import Engine  # noqa: E402
from pogo.evaluation import Evaluator  # noqa: E402
from pogo.review import Logged, Replay  # noqa: E402

_variants: list = []


def parse(spec: str) -> dict:
    out = {}
    for part in filter(None, spec.split(",")):
        k, v = part.split("=")
        out[k] = v in ("1", "true", "True") if k == "stay_after_replace" else float(v)
    return out


def setup(variants: list) -> None:
    _variants[:] = variants
    E.setup()


def builds(seed: int) -> dict:
    net, pool = E.L._state["net"], E.L._state["pool"]
    out = {k: v for k, v in E.versions(seed).items() if k != "matching"}
    for spec in _variants:
        out[spec] = Engine(Evaluator(E._s["ev"].model), pool, rollout="bot", samples=32, edge=0.03, q=net, margin=0.02,
                           seed=seed + 2, **parse(spec))
    return out


def family(kind: str) -> str:
    return "act" if kind in ("throw", "switch") else kind


def job(task):
    game, wanted = task
    saved, teams = E.load_game(ROOT / "games" / "played" / f"{game}.json")
    seed = saved["seed"] % 100_000
    shadows = [E.Shadow(Replay(saved["my_choices"]), builds(seed), 0, game), E.Shadow(Logged(saved["log"]), builds(seed + 10), 1, game)]
    battle = Battle(teams[0], teams[1], shadows[0], shadows[1], seed=saved["seed"], record=True)
    while battle.winner is None:
        shadows[0].step = shadows[1].step = battle.turn
        battle.step()
    same = [list(e) for e in battle.log] == [list(e) for e in saved["log"]]
    found = {}
    for r in shadows[0].rows + shadows[1].rows:
        at = (r["side"], r["turn"], family(r["kind"]))
        if at in wanted and at not in found:
            found[at] = r["picks"]
    return game, same, {f"{s}|{t}|{f}": p for (s, t, f), p in found.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("answers", nargs="+")
    parser.add_argument("--tag", default="exam-1")
    parser.add_argument("--variants", nargs="+", default=["switch_edge=0.02", "switch_edge=0.05", "switch_edge=0.1",
                                                           "switch_edge=0.05,stay_after_replace=1"])
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    key = [k for k in json.loads((ROOT / "runs" / "exam" / f"{args.tag}-key.json").read_text()) if k["group"] != "repeat"]
    people = []
    for path in args.answers:
        saved = json.loads(Path(path).read_text())
        people.append((Path(path).stem, {i: a["choice"] for i, a in saved.get("answers", saved).items() if a.get("choice")}))
    by_game: dict = {}
    for k in key:
        by_game.setdefault(k["game"], set()).add((k["side"], k["turn"], family(k["kind"])))
    with multiprocessing.get_context("spawn").Pool(args.workers, initializer=setup, initargs=(args.variants,)) as pool:
        out = pool.map(job, sorted(by_game.items()), chunksize=1)
    picks, broken = {}, [g for g, same, _ in out if not same]
    for game, _, found in out:
        for at, p in found.items():
            picks[(game, at)] = p
    rows = []
    for k in key:
        p = picks.get((k["game"], f"{k['side']}|{k['turn']}|{family(k['kind'])}"))
        if p is None:
            print(f"  {k['id']}: not found in the replay")
            continue
        if p["engine"] != k["picks"]["engine"]:
            print(f"  {k['id']}: the engine picks {p['engine']} here, the key has {k['picks']['engine']}")
        rows.append((k, p))
    if broken:
        print(f"  games that did not replay exactly: {broken}")
    names = ["engine", "trained", "rulebook"] + args.variants
    agree = [k["id"] for k, _ in rows if len({a.get(k["id"]) for _, a in people}) == 1 and people[0][1].get(k["id"])]
    sets = [(name, set(a)) for name, a in people] + [(f"all {len(people)} agree", set(agree))]
    print(f"\n{len(rows)} positions replayed. How often each plays the answer:")
    print(f"  {'':42s}" + "".join(f"{n:>22s}" for n, _ in sets))
    for v in names:
        cells = []
        for (name, ids), (_, answers) in zip(sets, people + [people[0]]):
            got = [(answers[k["id"]] == p[v]) for k, p in rows if k["id"] in ids]
            cells.append(f"{sum(got)}/{len(got)} ({100 * sum(got) / max(1, len(got)):.0f}%)")
        changed = sum(p[v] != p["engine"] for _, p in rows)
        print(f"  {v:34s} {changed:3d} new" + "".join(f"{c:>22s}" for c in cells))
    print("\n  (\"new\": positions where it picks other than the website's engine)")


if __name__ == "__main__":
    main()
