"""Does the trained bot's edge over the rulebook hold on teams it never trained with? (the owner, 2026-11-05)

    python3 scripts/any_team_test.py [--teams 20] [--battles 200] [--workers 3] [--seed 7] [--net runs/general-decide/q.npz]

Needs runs/wide-teams/matchups.json (not in git; `python3 scripts/wide_teams.py --table-only` builds it in under a minute).

Three groups of --teams random legal teams: PvPoke's top 50 (what the network trained on), ranks 51-300 (none in the
top 50), and teams with a form-changer (Mimikyu, Morpeko, Cramorant or Aegislash) beside two of the top 50. Each team
plays --battles battles against the mixed field twice, piloted once by the trained bot and once by the rulebook
(Planner), with the same opponents and dice; the opponents are the trained bot on the website's network, whichever
--net pilots our side. Both read the wide one-on-ones of
scripts/wide_teams.py (Aegislash added), so the table's coverage is not what is measured. The 51-300 group is played a
third way too: the trained bot with the shipped 50-Pokémon table, as the website has it. Writes
runs/wide-teams/any_team.out and .json.
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

FORMS = ["mimikyu", "morpeko_full_belly", "cramorant", "aegislash_shield"]
_w: dict = {}


def builds(gd) -> list:
    pool = species_pool(gd, 300)
    have = {b.species_id for b in pool}
    return pool + [gd.default(s) for s in FORMS if s not in have]


def _init(table_path: str | None, net: str = "runs/general-decide/q.npz") -> None:
    from pogo.arena import low_priority
    from pogo.gamedata import GameData
    from pogo.learner import QNet
    from pogo.teamshape import mixed_field
    low_priority()
    gd = GameData()
    _w.update(gd=gd, pool=builds(gd))
    if table_path:
        import pogo.agents as agents
        import pogo.learner as learner
        wide = json.loads(Path(table_path).read_text())
        agents._matchup_table = learner._matchup_table = lambda: wide
    _w["net"] = QNet.load(str(ROOT / "runs" / "general-decide" / "q.npz"))
    _w["ours"] = QNet.load(str(ROOT / net))
    _w["draw"] = mixed_field(gd)[1]


def _pair(job) -> tuple:
    from teams import one_on_one
    i, j = job
    a, b = _w["pool"][i], _w["pool"][j]
    return i, j, round(sum(one_on_one(a, b, s) for s in (0, 1, 2)) / 3, 4)


def _battles(job) -> tuple:
    from pogo.agents import Planner
    from pogo.battle import DRAW, Battle
    from pogo.learner import Learner
    key, team, pilot, seed, start, count = job
    by_id = {b.species_id: b for b in _w["pool"]}
    ours = [by_id[s] for s in team]
    points = []
    for k in range(start, start + count):
        rng = random.Random(seed * 1_000_003 + k)
        foe = _w["draw"](rng)
        dice = rng.getrandbits(32)
        me = Learner(q=_w["ours"], margin=0.02, seed=dice % 99991) if pilot == "trained" else Planner(seed=dice % 99991)
        winner = Battle(ours, foe, me, Learner(q=_w["net"], margin=0.02, seed=dice % 99989), seed=dice).run()
        points.append(1.0 if winner == 0 else 0.5 if winner == DRAW else 0.0)
    return key, pilot, start, points


def draw_teams(gd, species: list, n: int, rng: random.Random, must: list | None = None) -> list:
    dex = lambda s: gd.species[s]["dex"]
    teams = []
    while len(teams) < n:
        team = ([rng.choice(must)] if must else []) + rng.sample(species, 3)
        team = list(dict.fromkeys(team))[:3]
        if len(team) == 3 and len({dex(s) for s in team}) == 3 and sorted(team) not in [sorted(t) for t in teams]:
            teams.append(team)
    return teams


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--teams", type=int, default=20)
    parser.add_argument("--battles", type=int, default=200)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--net", default="runs/general-decide/q.npz", help="the network piloting our side (path from the repo root)")
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
    if todo:
        with Pool(args.workers, _init, (None,)) as runner:
            for i, j, m in runner.imap_unordered(_pair, todo, chunksize=100):
                wide.setdefault(ids[i], {})[ids[j]] = m
                wide.setdefault(ids[j], {}).setdefault(ids[i], -m)
        path.write_text(json.dumps(wide))
    print(f"one-on-ones added for {[ids[i] for i in new]} ({time.time() - t0:.0f}s)", flush=True)

    rng = random.Random(args.seed)
    top50 = [b.species_id for b in gd.meta(50)]
    rank = {e["speciesId"]: r + 1 for r, e in enumerate(gd.rankings())}
    rest = [s for s in ids if s not in top50 and s not in FORMS and 50 < rank.get(s, 999) <= 300]
    groups = {"top 50 (trained on)": draw_teams(gd, top50, args.teams, rng),
              "ranks 51-300": draw_teams(gd, rest, args.teams, rng),
              "with a form-changer": draw_teams(gd, top50, args.teams, rng, must=FORMS)}
    for g in groups:
        rng.shuffle(groups[g])

    def jobs(group_names, pilots):
        out = []
        for g in group_names:
            for n, team in enumerate(groups[g]):
                for pilot in pilots:
                    out += [((g, n), team, pilot, args.seed * 100 + n, s, min(25, args.battles - s))
                            for s in range(0, args.battles, 25)]
        return out

    got: dict = {}

    def collect(runner, job_list, tag=""):
        for key, pilot, start, points in runner.imap_unordered(_battles, job_list):
            got.setdefault((key, pilot + tag), {})[start] = points

    # same dice: battle k of a team draws the same opponent and seed whoever pilots it (jobs are chunked identically)
    with Pool(args.workers, _init, (str(path), args.net)) as runner:
        collect(runner, jobs(list(groups), ["trained", "rulebook"]))
    with Pool(args.workers, _init, (None, args.net)) as runner:
        collect(runner, jobs(["ranks 51-300"], ["trained"]), " (shipped table)")
    print(f"battles played ({time.time() - t0:.0f}s)\n", flush=True)

    def paired(a_pts: list, b_pts: list) -> tuple:
        d = [x - y for x, y in zip(a_pts, b_pts)]
        mean = sum(d) / len(d)
        var = sum((x - mean) ** 2 for x in d) / (len(d) - 1)
        return mean, 1.96 * math.sqrt(var / len(d))

    lines, rows = [], {}
    for g, teams in groups.items():
        tr = [x for n in range(len(teams)) for x in sorted_points(got, (g, n), "trained")]
        rb = [x for n in range(len(teams)) for x in sorted_points(got, (g, n), "rulebook")]
        edge, m = paired(tr, rb)
        mean = lambda xs: sum(xs) / len(xs)
        per_team = [mean(sorted_points(got, (g, n), "trained")) - mean(sorted_points(got, (g, n), "rulebook"))
                    for n in range(len(teams))]
        better = sum(e > 0 for e in per_team)
        rows[g] = {"trained": sum(tr) / len(tr), "rulebook": sum(rb) / len(rb), "edge": [edge, m],
                   "teams": [{"team": t, "edge": round(e, 3)} for t, e in zip(teams, per_team)]}
        lines.append(f"{g:22s} trained {100 * sum(tr) / len(tr):5.1f}%  rulebook {100 * sum(rb) / len(rb):5.1f}%  "
                     f"edge {100 * edge:+5.1f} ± {100 * m:.1f} points; trained better on {better} of {len(teams)} teams")
    g = "ranks 51-300"
    sh = [x for n in range(len(groups[g])) for x in sorted_points(got, (g, n), "trained (shipped table)")]
    tr = [x for n in range(len(groups[g])) for x in sorted_points(got, (g, n), "trained")]
    d, m = paired(sh, tr)
    rows["shipped table"] = {"trained": sum(sh) / len(sh), "vs_wide": [d, m]}
    lines.append(f"{'ranks 51-300, website':22s} trained {100 * sum(sh) / len(sh):5.1f}% with the shipped 50-Pokémon table: "
                 f"{100 * d:+.1f} ± {100 * m:.1f} points against the wide table")
    lines.append("\nworst and best teams per group (trained minus rulebook, points):")
    for g in groups:
        ts = sorted(rows[g]["teams"], key=lambda r: r["edge"])
        lines.append(f"  {g}: " + "; ".join(f"{'/'.join(r['team'])} {100 * r['edge']:+.0f}" for r in ts[:3] + ts[-2:]))
    text = "\n".join(lines)
    print(text)
    (OUT / "any_team.out").write_text(text + "\n")
    (OUT / "any_team.json").write_text(json.dumps({"args": vars(args), "groups": rows}, indent=1))


def sorted_points(got: dict, key, pilot: str) -> list:
    """A team's points in battle order, so the two pilots' battles pair up one to one."""
    chunks = got[(key, pilot)]
    return [x for start in sorted(chunks) for x in chunks[start]]


if __name__ == "__main__":
    main()
