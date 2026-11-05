"""Teams top players use (the owner, 2026-11-04, Great League with megas allowed) as the opponents.

    python3 scripts/top_player_teams.py [--battles 25] [--field 600] [--workers 3] [--seed 5]

Every team, the players' nine and our search's best, plays each players' team (PvPoke's default moves and IVs) with
every pair of leads, --battles battles each, and --field battles against the mixed field. With teams fixed the bots
play nearly the same game every time, so the nine lead pairs, not the battle count, are what make a pairing's score. Both sides are the
trained bot reading the wide one-on-ones of scripts/wide_teams.py, extended here to the Pokémon it lacked (Mega Sableye
among them). Each pairing uses the same dice for every team. Writes runs/wide-teams/top_players_leads.out and .json.
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

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from wide_teams import OUT, species_pool  # noqa: E402

PLAYERS = [["mimikyu", "morpeko_full_belly", "jumpluff"], ["sableye_mega", "mantine", "ninetales_shadow"],
           ["cramorant", "clodsire", "mimikyu"], ["sableye_mega", "dunsparce", "corviknight"],
           ["melmetal", "altaria", "florges"], ["electrode_hisuian", "cramorant", "mimikyu"],
           ["corsola_galarian", "tinkaton", "vigoroth"], ["snorlax", "jumpluff", "quagsire_shadow"],
           ["feraligatr", "electrode_hisuian", "mimikyu"]]
OURS = [["diggersby", "mimikyu", "charjabug_shadow"], ["mimikyu", "stunfisk", "marowak_shadow"],
        ["carbink", "mimikyu", "charjabug_shadow"], ["charjabug_shadow", "thievul", "marowak_shadow"],
        ["carbink", "charjabug_shadow", "marowak_shadow"], ["quagsire", "sableye_shadow", "corviknight_shadow"],
        ["jellicent", "clodsire", "mandibuzz"], ["jellicent", "clodsire", "araquanid"]]

_w: dict = {}


def builds(gd) -> list:
    """The search's pool plus every Pokémon of the teams above; Mega Sableye is not in PvPoke's Great League
    rankings, so it gets Sableye's moves at the IVs PvPoke lists for it."""
    pool = species_pool(gd, 300)
    have = {b.species_id for b in pool}
    for sp in sorted({s for t in PLAYERS + OURS for s in t} - have):
        if sp == "sableye_mega":
            lvl, a, d, h = gd.species[sp]["defaultIVs"]["cp1500"]
            plain = gd.default("sableye")
            pool.append(gd.build(sp, [plain.fast.id] + [m.id for m in plain.charged], level=lvl, ivs=(a, d, h)))
        else:
            pool.append(gd.default(sp))
    return pool


def _init(table_path: str | None) -> None:
    from pogo.arena import low_priority
    from pogo.gamedata import GameData
    low_priority()
    gd = GameData()
    _w.update(gd=gd, pool=builds(gd))
    if table_path:
        import pogo.agents as agents
        import pogo.learner as learner
        from pogo.learner import QNet
        from pogo.teamshape import mixed_field
        wide = json.loads(Path(table_path).read_text())
        agents._matchup_table = learner._matchup_table = lambda: wide
        _w["net"] = QNet.load(str(ROOT / "runs" / "general-decide" / "q.npz"))
        _w["draw"] = mixed_field(gd)[1]


def _pair(job) -> tuple:
    from teams import one_on_one
    i, j = job
    a, b = _w["pool"][i], _w["pool"][j]
    return i, j, round(sum(one_on_one(a, b, s) for s in (0, 1, 2)) / 3, 4)


def _battles(job) -> tuple:
    from pogo.battle import DRAW, Battle
    from pogo.learner import Learner
    key, team, foe_team, seed, start, count = job
    by_id = {b.species_id: b for b in _w["pool"]}
    ours = [by_id[s] for s in team]
    points = []
    for k in range(start, start + count):
        rng = random.Random(seed * 1_000_003 + k)
        foe = [by_id[s] for s in foe_team] if foe_team else _w["draw"](rng)
        dice = rng.getrandbits(32)
        winner = Battle(ours, foe, Learner(q=_w["net"], margin=0.02, seed=dice % 99991),
                        Learner(q=_w["net"], margin=0.02, seed=dice % 99989), seed=dice).run()
        points.append(1.0 if winner == 0 else 0.5 if winner == DRAW else 0.0)
    return key, points


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--battles", type=int, default=25)
    parser.add_argument("--field", type=int, default=600)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--seed", type=int, default=5)
    args = parser.parse_args()
    from pogo.arena import low_priority
    from pogo.gamedata import GameData
    low_priority()
    gd = GameData()
    pool = builds(gd)
    ids = [b.species_id for b in pool]
    path = OUT / "matchups.json"
    wide = json.loads(path.read_text())
    new = [i for i, s in enumerate(ids) if s not in wide]
    todo = [(i, j) for i in new for j in range(len(ids)) if j != i and not (j in new and j < i)]
    t0 = time.time()
    print(f"one-on-ones for {[ids[i] for i in new]}: {len(todo)}", flush=True)
    with Pool(args.workers, _init, (None,)) as runner:
        for i, j, m in runner.imap_unordered(_pair, todo, chunksize=100):
            wide.setdefault(ids[i], {})[ids[j]] = m
            wide.setdefault(ids[j], {}).setdefault(ids[i], -m)
    path.write_text(json.dumps(wide))
    print(f"one-on-ones ready ({time.time() - t0:.0f}s)", flush=True)

    teams = {"/".join(t): t for t in PLAYERS + OURS}
    jobs = []
    for key, team in teams.items():
        for n, foe in enumerate(PLAYERS):
            if foe != team:
                for a in team:
                    for b in foe:
                        jobs.append(((key, n), [a] + [x for x in team if x != a], [b] + [x for x in foe if x != b],
                                     args.seed + n, 0, args.battles))
        jobs += [((key, "field"), team, None, args.seed + 99, s, min(25, args.field - s)) for s in range(0, args.field, 25)]
    got: dict = {}
    with Pool(args.workers, _init, (str(path),)) as runner:
        for key, points in runner.imap_unordered(_battles, jobs):
            got.setdefault(key, []).extend(points)
    print(f"battles played ({time.time() - t0:.0f}s)\n", flush=True)

    def pm(pts) -> tuple:
        p = sum(pts) / len(pts)
        return p, 1.96 * math.sqrt(max(p * (1 - p), 1e-9) / len(pts))

    rows = []
    for key, team in teams.items():
        vs = {n: pm(got[(key, n)])[0] for n in range(len(PLAYERS)) if (key, n) in got}
        allp = [x for n in vs for x in got[(key, n)]]
        rows.append({"team": team, "players": pm(allp), "field": pm(got[(key, "field")]), "vs": vs,
                     "theirs": team in PLAYERS})
    rows.sort(key=lambda r: -r["players"][0])
    lines = [f"{'v players':>12} {'v mixed field':>14}   team (players' teams marked *)   then v each players' team 1-9"]
    for r in rows:
        lines.append(f"{100 * r['players'][0]:5.1f}% ± {100 * r['players'][1]:.1f} {100 * r['field'][0]:6.1f}% ± {100 * r['field'][1]:.1f}   "
                     f"{'*' if r['theirs'] else ' '} {' / '.join(r['team']):48s} "
                     + " ".join(f"{100 * r['vs'][n]:3.0f}" if n in r["vs"] else "  -" for n in range(len(PLAYERS))))
    text = "\n".join(lines)
    print(text)
    (OUT / "top_players_leads.out").write_text(text + "\n")
    (OUT / "top_players_leads.json").write_text(json.dumps({"args": vars(args), "rows": rows}, indent=1))


if __name__ == "__main__":
    main()
