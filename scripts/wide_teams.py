"""Teams from the top 300, not only PvPoke's top 50 (the owner, 2026-11-04: good teams often use Pokémon ranked 100-300).

    python3 scripts/wide_teams.py [--pool 300] [--shortlist 120] [--battles 150] [--finalists 12] [--finals 600] [--workers 3]

1. One-on-ones among the top --pool (form-changers left out) and every Pokémon of the mixed field, averaged over 0, 1
   and 2 shields, saved to runs/wide-teams/matchups.json. Pairs already in data/matchups.json keep their saved value;
   new pairs are played once and the reverse taken as the negative. data/matchups.json, which the shipped bot reads, is
   not touched.
2. A quick score for every legal team: against each opponent its best two answers, weighted like the mixed field
   (PvPoke's Elite/Champion usage three parts, the top 50 evenly one part).
3. The best --shortlist by quick score, plus reference teams, play three-on-three battles against the mixed field
   (pogo.teamshape.mixed_field), both sides the trained bot, which reads the wide table, so a Pokémon outside the top 50
   is not played blind. Every team meets the same opponents with the same dice. The best --finalists play again on
   fresh battles with each member leading; only that round is reported, best lead first.
"""
from __future__ import annotations

import os

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import argparse  # noqa: E402

import json  # noqa: E402
import math  # noqa: E402
import random  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from multiprocessing import Pool  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
OUT = ROOT / "runs" / "wide-teams"
REFERENCE = [["quagsire", "sableye_shadow", "corviknight_shadow"], ["jellicent", "clodsire", "araquanid"],
             ["jellicent", "clodsire", "mandibuzz"]]

_w: dict = {}


def species_pool(gd, n: int) -> list:
    from pogo.teamshape import mixed_field
    pool = gd.meta(n)
    have = {b.species_id for b in pool}
    field_pool, _ = mixed_field(gd)
    extra = [b for b in field_pool if b.species_id not in have]
    for team in REFERENCE:
        for sp in team:
            if sp not in have and sp not in {b.species_id for b in extra}:
                extra.append(gd.default(sp))
    return pool + extra


def _init(n: int, table_path: str | None) -> None:
    from pogo.arena import low_priority
    from pogo.gamedata import GameData
    low_priority()
    gd = GameData()
    _w.update(gd=gd, pool=species_pool(gd, n))
    if table_path:
        import pogo.agents as agents
        import pogo.learner as learner
        from pogo.learner import QNet
        wide = json.loads(Path(table_path).read_text())
        agents._matchup_table = learner._matchup_table = lambda: wide  # the bot reads the wide one-on-ones
        _w["net"] = QNet.load(str(ROOT / "runs" / "general-decide" / "q.npz"))
        from pogo.teamshape import mixed_field
        _w["draw"] = mixed_field(gd)[1]


def _pair(job) -> tuple:
    from teams import one_on_one
    i, j = job
    a, b = _w["pool"][i], _w["pool"][j]
    return i, j, round(sum(one_on_one(a, b, s) for s in (0, 1, 2)) / 3, 4)


def _battles(job) -> tuple:
    """Our team (species ids, lead first) against the mixed field's battles start..start+count of this seed."""
    from pogo.battle import DRAW, Battle
    from pogo.learner import Learner
    key, team, seed, start, count = job
    gd, net = _w["gd"], _w["net"]
    by_id = {b.species_id: b for b in _w["pool"]}
    ours = [by_id[s] for s in team]
    points = []
    for k in range(start, start + count):
        rng = random.Random(seed * 1_000_003 + k)
        foe = _w["draw"](rng)
        dice = rng.getrandbits(32)
        winner = Battle(ours, foe, Learner(q=net, margin=0.02, seed=dice % 99991),
                        Learner(q=net, margin=0.02, seed=dice % 99989), seed=dice).run()
        points.append(1.0 if winner == 0 else 0.5 if winner == DRAW else 0.0)
    return key, points


def score(pool_runner, teams: dict, battles: int, seed: int, chunk: int = 25) -> dict:
    jobs = [(key, team, seed, s, min(chunk, battles - s)) for key, team in teams.items() for s in range(0, battles, chunk)]
    got: dict = {key: [] for key in teams}
    for key, points in pool_runner.imap_unordered(_battles, jobs):
        got[key] += points
    out = {}
    for key, pts in got.items():
        p = sum(pts) / len(pts)
        out[key] = (p, 1.96 * math.sqrt(max(p * (1 - p), 1e-9) / len(pts)))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pool", type=int, default=300)
    parser.add_argument("--shortlist", type=int, default=120)
    parser.add_argument("--battles", type=int, default=150)
    parser.add_argument("--finalists", type=int, default=12)
    parser.add_argument("--finals", type=int, default=600)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    from pogo.arena import low_priority
    from pogo.gamedata import GameData
    from pogo.teamshape import pvpoke_usage
    low_priority()
    OUT.mkdir(parents=True, exist_ok=True)
    gd = GameData()
    pool = species_pool(gd, args.pool)
    ids = [b.species_id for b in pool]
    n = len(pool)
    rank = {e["speciesId"]: r + 1 for r, e in enumerate(gd.rankings())}
    t0 = time.time()

    # 1. one-on-ones
    path = OUT / "matchups.json"
    wide = json.loads(path.read_text()) if path.exists() else {}
    saved = json.loads((ROOT / "data" / "matchups.json").read_text())
    for a, row in saved.items():
        wide.setdefault(a, {}).update(row)
    todo = [(i, j) for i in range(n) for j in range(i + 1, n)
            if ids[j] not in wide.get(ids[i], {}) and ids[i] not in wide.get(ids[j], {})]
    print(f"{n} Pokémon; {len(todo)} new one-on-ones to play", flush=True)
    with Pool(args.workers, _init, (args.pool, None)) as runner:
        for done, (i, j, m) in enumerate(runner.imap_unordered(_pair, todo, chunksize=200), 1):
            wide.setdefault(ids[i], {})[ids[j]] = m
            wide.setdefault(ids[j], {}).setdefault(ids[i], -m)
            if done % 10000 == 0:
                print(f"  {done} of {len(todo)} ({time.time() - t0:.0f}s)", flush=True)
                path.write_text(json.dumps(wide))
    path.write_text(json.dumps(wide))
    table = np.array([[wide[a].get(b, -wide[b].get(a, 0.0)) if a != b else 0.0 for b in ids] for a in ids])
    print(f"one-on-ones ready ({time.time() - t0:.0f}s)", flush=True)

    # 2. quick score against the field's weights
    usage = pvpoke_usage()
    top50 = {b.species_id for b in gd.meta(50)}
    weight = np.array([0.75 * usage.get(s, 0.0) / sum(usage.values()) + (0.25 / 50 if s in top50 else 0.0) for s in ids])
    weight /= weight.sum()
    dex = [gd.species[s]["dex"] for s in ids]
    dex = np.array(dex)
    scores, legal = [], 0
    for i in range(n):
        for j in range(i + 1, n):
            if dex[j] == dex[i]:
                continue
            ks = np.arange(j + 1, n)
            ks = ks[(dex[ks] != dex[i]) & (dex[ks] != dex[j])]
            if not len(ks):
                continue
            legal += len(ks)
            a, b, c = table[i], table[j], table[ks]
            quick = ((a + b + c - np.minimum(np.minimum(a, b), c)) / 2) @ weight  # its best two answers to each opponent
            for k in np.argsort(-quick)[:5]:
                scores.append((float(quick[k]), (i, j, int(ks[k]))))
        scores.sort(reverse=True)
        del scores[args.shortlist * 4:]
    scores.sort(reverse=True)
    print(f"quick score: {legal} legal teams ({time.time() - t0:.0f}s)", flush=True)

    def lead_first(team) -> list:
        return [ids[k] for k in sorted(team, key=lambda k: -float(table[k] @ weight))]

    teams = {}
    for q, team in scores[:args.shortlist]:
        teams["/".join(sorted(ids[k] for k in team))] = lead_first(team)
    for team in REFERENCE:
        idx = [ids.index(s) for s in team]
        teams.setdefault("/".join(sorted(team)), lead_first(idx))

    # 3. battles, then finals with each lead on fresh battles
    with Pool(args.workers, _init, (args.pool, str(path))) as runner:
        first = score(runner, teams, args.battles, args.seed)
        print(f"shortlist played: {len(teams)} teams x {args.battles} battles ({time.time() - t0:.0f}s)", flush=True)
        ranked = sorted(first, key=lambda k: -first[k][0])
        finalists = ranked[:args.finalists] + [k for k in ("/".join(sorted(t)) for t in REFERENCE) if k not in ranked[:args.finalists]]
        orders = {}
        for key in finalists:
            team = teams[key]
            for lead in team:
                orders[f"{key}|{lead}"] = [lead] + [s for s in team if s != lead]
        final = score(runner, orders, args.finals, args.seed + 1)
    print(f"finals played: {len(orders)} line-ups x {args.finals} fresh battles ({time.time() - t0:.0f}s)\n", flush=True)
    rows = []
    for key in finalists:
        leads = sorted(((final[f"{key}|{lead}"], lead) for lead in teams[key]), key=lambda x: -x[0][0])
        (p, m), lead = leads[0]
        rows.append({"team": [lead] + [s for s in teams[key] if s != lead], "best_lead": [round(p, 3), round(m, 3)],
                     "leads": {ld: round(v[0], 3) for v, ld in leads}, "shortlist": [round(x, 3) for x in first[key]],
                     "ranks": {s: rank.get(s) for s in teams[key]}})
    rows.sort(key=lambda r: -r["best_lead"][0])
    for r in rows:
        names = " / ".join(f"{s} (#{r['ranks'][s]})" for s in r["team"])
        print(f"{100 * r['best_lead'][0]:5.1f}% ± {100 * r['best_lead'][1]:.1f}  {names}   other leads "
              + ", ".join(f"{s} {100 * v:.0f}%" for s, v in list(r["leads"].items())[1:]))
    (OUT / "result.json").write_text(json.dumps({"args": vars(args), "pool": n, "teams": rows,
                                                 "shortlist": {k: [round(x, 3) for x in v] for k, v in first.items()}}, indent=1))


if __name__ == "__main__":
    main()
