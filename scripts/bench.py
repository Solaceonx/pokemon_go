#!/usr/bin/env python3
"""The benchmark (docs/benchmarking.md): judges that are not the bot, on frozen positions and battles.

    python3 scripts/bench.py freeze [--battles 300] [--workers 3]      once: exact endgames from real and simulated games
    python3 scripts/bench.py score BUILD [BUILD ...] [--rulers endgame,people,field,exploit] [--label NAME] [--workers 3]
    python3 scripts/bench.py check [--workers 3]                       does the benchmark itself work?

Judges:
    endgame   points given away per decision against exact play (pogo.endgame), on frozen positions from real and simulated games
    people    how often the build plays what the owner played, by kind of decision, in the real website games
    field     score on a frozen list of battles against the trained bot, the crowd and PvPoke's AI (kept for comparison: these
              opponents come from the same code as the bot)
    exploit   how much a player that reads the build (pogo.reader) gains over the same player not reading it

`check` puts a ladder of known strengths and deliberately broken bots through every judge: a judge earns trust by
ranking the ladder and catching the damage, and repeating with new dice. BUILDS below lists them; results go to runs/bench/.
`score` also accepts engine_versus.py settings, for example "samples=32,shield_margin=0.1".
Use --endgame-limit only for a small smoke run; omit it when measuring strength.
"""
from __future__ import annotations

import argparse
import collections
import glob
import gzip
import json
import math
import multiprocessing
import os
import random
import sys
import time
from contextlib import nullcontext
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_v] = "1"
ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
from pogo.agents import Masher, Planner, varied  # noqa: E402
from pogo.arena import low_priority  # noqa: E402
from pogo.battle import CHARGED, DRAW, FAST, SWITCH, Battle, Mon  # noqa: E402
from pogo.endgame import SolveLimit, Solver, action_values  # noqa: E402
from pogo.engine import Engine  # noqa: E402
from pogo.evaluation import Evaluator  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.learner import Learner, QNet  # noqa: E402
from pogo.pvpoke_ai import PvpokeAI  # noqa: E402
from pogo.reader import Reader  # noqa: E402
from pogo.review import Logged, Replay  # noqa: E402
from pogo.teamshape import mixed_field  # noqa: E402
from engine_versus import parse  # noqa: E402

OUT = ROOT / "runs" / "bench"
ENDGAMES = OUT / "endgame-1.jsonl.gz"
_s: dict = {}


def setup() -> None:
    low_priority()
    gd = GameData()
    pool, draw = mixed_field(gd)
    _s.update(gd=gd, pool=pool, draw=draw, site_pool=gd.meta(50), net=QNet.load(str(ROOT / "runs" / "general-decide" / "q.npz")),
              ev=Evaluator.load(ROOT / "runs" / "eval" / "eval.npz").model)


# ---------------------------------------------------------------- builds

class RandomBot:
    """Any legal move at random: the bottom of the ladder."""

    def __init__(self, seed):
        self.rng = random.Random(seed)

    def act(self, view):
        return self.rng.choice(view.legal())

    def shield(self, view, energy, *move):
        return self.rng.random() < 0.5

    def replace(self, view):
        return self.rng.choice(view.me.bench())

    def clone(self):
        return self


class Broken:
    """The trained bot with one thing deliberately broken, so the damage is known by construction."""

    def __init__(self, inner, shield=None, switch=True, throw=True, replace_first=False):
        self.inner, self._shield, self.switch, self.throw, self.replace_first = inner, shield, switch, throw, replace_first

    def saw_throw(self, *a):
        self.inner.saw_throw(*a)

    def saw_shield(self, *a):
        self.inner.saw_shield(*a)

    def act(self, view):
        action = self.inner.act(view)
        if (action in SWITCH and not self.switch) or (action in CHARGED and not self.throw):
            return FAST
        return action

    def shield(self, view, energy, *move):
        answer = self.inner.shield(view, energy)
        return answer if self._shield is None else self._shield

    def replace(self, view):
        return view.me.bench()[0] if self.replace_first else self.inner.replace(view)

    def clone(self):
        return Broken(self.inner.clone(), self._shield, self.switch, self.throw, self.replace_first)


def trained(seed, **kw):
    return Learner(q=_s["net"], margin=0.02, seed=seed, **kw)


def engine(seed, samples, **kw):
    return Engine(Evaluator(_s["ev"]), _s["site_pool"], rollout="bot", samples=samples, edge=0.03, q=_s["net"], margin=0.02, seed=seed, **kw)


BUILDS = {
    # the ladder, weakest first
    "random": RandomBot,
    "masher": lambda seed: Masher(),
    "rulebook": lambda seed: Planner(seed=seed),
    "trained": trained,
    "engine8": lambda seed: engine(seed, 8),
    "engine8_again": lambda seed: engine(seed + 500_000, 8),  # the same build with other dice, to see how a judge repeats
    "engine32": lambda seed: engine(seed, 32),  # the website's settings, without its time limits
    "matching8": lambda seed: engine(seed, 8, opponents="mix", matching=True),
    "matching32": lambda seed: engine(seed, 32, opponents="mix", matching=True),
    # the trained bot, broken
    "no_shields": lambda seed: Broken(trained(seed), shield=False),
    "all_shields": lambda seed: Broken(trained(seed), shield=True),
    "no_switches": lambda seed: Broken(trained(seed), switch=False),
    "no_throws": lambda seed: Broken(trained(seed), throw=False),
    "first_bench": lambda seed: Broken(trained(seed), replace_first=True),
    "first_listed": lambda seed: trained(seed, even_cost="first"),  # the owner's Hydro Cannon complaint
}
LADDER = ["random", "masher", "rulebook", "trained", "engine8"]
BROKEN = {name: "trained" for name in ("no_shields", "all_shields", "no_switches", "no_throws", "first_bench", "first_listed")}


def build(name: str, seed: int):
    """A named benchmark player, or the same engine settings accepted by engine_versus.py."""
    if name in BUILDS:
        return BUILDS[name](seed)
    kw = parse(name)
    if kw is None:
        return trained(seed)
    ev = Evaluator.load(ROOT / kw.pop("eval")).model if "eval" in kw else _s["ev"]
    q = QNet.load(str(ROOT / kw.pop("q"))) if "q" in kw else _s["net"]
    return Engine(Evaluator(ev), _s["site_pool"], rollout="bot", q=q, seed=seed, **kw)


# ---------------------------------------------------------------- frozen positions

HOME = {"cramorant_gulping": "cramorant", "cramorant_gorging": "cramorant", "mimikyu_busted": "mimikyu", "morpeko_hangry": "morpeko_full_belly"}


def describe(mon) -> dict:
    b = mon.build
    return {"id": b.species_id, "home": getattr(b, "home", None) or b.species_id, "moves": [b.fast.id, *(m.id for m in b.charged)], "level": b.level, "ivs": list(b.ivs),
            "hp": mon.hp, "energy": mon.energy, "atk": mon.atk_stage, "def": mon.def_stage}


def dump(battle) -> dict:
    return {"turn": battle.turn, "sides": [{"team": [describe(m) for m in s.team], "active": s.active, "shields": s.shields,
                                            "switch_wait": s.switch_wait, "busy": s.busy, "shown": list(s.shown)} for s in battle.sides]}


def restore(state: dict) -> Battle:
    gd = _s["gd"]
    teams = []
    for side in state["sides"]:
        team = []
        for m in side["team"]:
            # A form-changing Pokémon is built from its starting form, which holds all its forms.
            home = gd.build(m.get("home") or HOME.get(m["id"], m["id"]), m["moves"], level=m["level"], ivs=tuple(m["ivs"]))
            mon = Mon(home.forms[m["id"]] if home.forms else home, m["hp"], m["energy"])
            mon.atk_stage, mon.def_stage = m["atk"], m["def"]
            team.append(mon)
        teams.append(team)
    battle = Battle(teams[0], teams[1], None, None, seed=0)
    for side, saved in zip(battle.sides, state["sides"]):
        side.active, side.shields, side.switch_wait, side.busy, side.shown = saved["active"], saved["shields"], saved["switch_wait"], saved["busy"], list(saved["shown"])
    battle.turn = state["turn"]
    return battle


class _Scripted:
    def __init__(self, action, shield=False):
        self.action, self.answer = action, shield

    def act(self, view):
        return self.action if self.action in view.legal() else FAST

    def shield(self, view, energy):
        return self.answer

    def replace(self, view):
        return view.me.bench()[0]


class _Dice:
    def __init__(self, x):
        self.x = x

    def random(self):
        return self.x


def shield_values(solver: Solver, battle, side: int) -> dict:
    """If they throw now: what shielding and not shielding are each worth, with us fast-moving, their move as their exact
    best play would choose it (the defender cannot tell which is coming) and the rest of the battle solved exactly."""
    foe_side = 1 - side
    mon = battle.sides[foe_side].mon
    ready = [CHARGED[k] for k, m in enumerate(mon.build.charged) if mon.energy >= m.energy]
    solver.cache.clear()
    root = solver.solve(battle)
    odds = {a: 0.0 for a in ready}
    for plan, weight in zip(root.plans[foe_side], root.mixtures[foe_side]):
        if plan.get((foe_side, "act")) in odds:
            odds[plan[(foe_side, "act")]] += weight
    total = sum(odds.values())
    odds = {a: (w / total if total > 1e-9 else 1 / len(ready)) for a, w in odds.items()}
    cuts = sorted({0.0, 0.5, 1.0} | {m.buff_chance for s in battle.sides for t in s.team for m in t.build.charged if 0 < m.buff_chance < 1})
    worth = {}
    for answer in (True, False):
        value = 0.0
        for action, chance in odds.items():
            for low, high in zip(cuts, cuts[1:]):
                agents = [None, None]
                agents[side], agents[foe_side] = _Scripted(FAST, answer), _Scripted(action)
                twin = battle.clone(*agents)
                twin.rng = _Dice((low + high) / 2)
                twin.step()
                got = solver.solve(twin).value
                value += chance * (high - low) * (got if side == 0 else 1 - got)
        worth["yes" if answer else "no"] = value
    return worth


def endgame_positions(battle, source: str, limit: int, solver: Solver) -> list:
    """Step the battle to its end; every turn the exact solver can handle and a side has a real choice is a position."""
    out, seen = [], set()
    while battle.winner is None:
        if Solver.qualifies(battle) and len(out) < limit:
            for side in (0, 1):
                view = battle.views[side]
                legal = view.legal() if view.me.busy == 0 else []
                if len(legal) < 2:
                    continue
                try:
                    value, worth = action_values(solver, battle, side)
                except SolveLimit:
                    continue
                # A choice that matters, once: the same answers in the same matchup a turn later add no information.
                sig = (side, view.me.active, battle.sides[1 - side].active, tuple(sorted((a, round(float(w), 2)) for a, w in worth.items())))
                if worth and max(worth.values()) - min(worth.values()) >= 0.02 and sig not in seen:
                    seen.add(sig)
                    out.append({"source": source, "kind": "act", "side": side, "state": dump(battle), "value": round(float(value), 4),
                                "worth": {str(a): round(float(w), 4) for a, w in worth.items()}})
            for side in (0, 1):  # could they throw at us now, with a shield in hand?
                foe, me = battle.sides[1 - side], battle.sides[side]
                if me.shields == 0 or foe.busy or not any(foe.mon.energy >= m.energy for m in foe.mon.build.charged):
                    continue
                try:
                    worth = shield_values(solver, battle, side)
                except (SolveLimit, ValueError):
                    continue
                sig = (side, "shield", me.active, foe.active, round(worth["yes"], 2), round(worth["no"], 2))
                if abs(worth["yes"] - worth["no"]) >= 0.02 and sig not in seen:
                    seen.add(sig)
                    out.append({"source": source, "kind": "shield", "side": side, "state": dump(battle), "value": round(float(max(worth.values())), 4),
                                "worth": {k: round(float(w), 4) for k, w in worth.items()}, "foe_energy": foe.mon.energy})
        battle.step()
    return out


def freeze_job(task):
    kind, what = task
    solver = Solver(max_nodes=20000, seconds=0.4)
    if kind == "real":
        saved = json.loads(Path(what).read_text())
        gd = _s["gd"]
        teams = [[gd.build(sid, mv, level=lv, ivs=tuple(iv)) for sid, mv, lv, iv in t] for t in saved["teams"]]
        battle = Battle(teams[0], teams[1], Replay(saved["my_choices"]), Logged(saved["log"]), seed=saved["seed"], record=True)
        return endgame_positions(battle, "real:" + Path(what).stem, 40, solver)
    rng = random.Random(what * 1_000_003 + 11)
    a, b = _s["draw"](rng), _s["draw"](rng)
    dice = rng.getrandbits(32)
    battle = Battle(a, b, trained(dice % 99991), varied(random.Random(dice), _s["pool"]), seed=dice)
    return endgame_positions(battle, f"sim:{what}", 16, solver)


def freeze(args) -> None:
    games = sorted(p for p in glob.glob(str(ROOT / "games" / "played" / "*-web.json")))
    tasks = [("real", g) for g in games] + [("sim", n) for n in range(args.battles)]
    rows = []
    started = time.time()
    with multiprocessing.get_context("spawn").Pool(args.workers, initializer=setup) as pool:
        for got in pool.imap_unordered(freeze_job, tasks, chunksize=1):
            rows += got
    rows.sort(key=lambda r: (r["source"], r["state"]["turn"], r["side"]))
    OUT.mkdir(parents=True, exist_ok=True)
    with gzip.open(ENDGAMES, "wt") as f:
        for row in rows:
            f.write(json.dumps(row, separators=(",", ":")) + "\n")
    real = sum(r["source"].startswith("real") for r in rows)
    print(f"{len(rows)} endgame positions where the choice matters, {sum(r['kind'] == 'shield' for r in rows)} of them shield calls ({real} from {len(games)} real games, the rest from {args.battles} simulated), "
          f"{os.path.getsize(ENDGAMES) // 1024} KB, {time.time() - started:.0f} s")


# ---------------------------------------------------------------- judges

def endgame_job(task):
    """Points given away on one chunk of positions, returned by source so the margin can treat a game as one sample."""
    name, seed, rows = task
    out = []
    for k, row in enumerate(rows):
        battle = restore(row["state"])
        agent = build(name, seed + k)
        view = battle.views[row["side"]]
        if row["kind"] == "shield":
            worth = row["worth"]["yes" if agent.shield(view, row["foe_energy"]) else "no"]
        else:
            worth = row["worth"].get(str(agent.act(view)))
        loss = row["value"] - (worth if worth is not None else min(row["worth"].values()))
        out.append((row["source"], round(max(float(loss), 0.0), 4), row["kind"]))
    return out


class Copying:
    """The recorded game with one build watching: what the build would do against what was played."""

    def __init__(self, script, build, tally):
        self.script, self.build, self.tally = script, build, tally
        self.matchup = None

    def saw_throw(self, *a):
        if hasattr(self.build, "saw_throw"):
            self.build.saw_throw(*a)

    def saw_shield(self, *a):
        if hasattr(self.build, "saw_shield"):
            self.build.saw_shield(*a)

    def act(self, view):
        mine = self.build.act(view)
        played = self.script.act(view)
        new = (view.me.active, id(view.foe)) != self.matchup
        self.matchup = (view.me.active, id(view.foe))
        legal = view.legal()
        ready = any(a in CHARGED for a in legal)
        if played in SWITCH or mine in SWITCH or (new and any(a in SWITCH for a in legal)):
            self.tally.append(("switch", mine == played))
        elif ready:
            self.tally.append(("throw", mine == played))
        return played

    def shield(self, view, energy, *move):
        mine = bool(self.build.shield(view, energy))
        played = bool(self.script.shield(view, energy))
        if view.me.shields > 0:
            self.tally.append(("shield", mine == played))
        return played

    def replace(self, view):
        mine = self.build.replace(view)
        played = self.script.replace(view)
        if len(view.me.bench()) > 1:
            self.tally.append(("replace", mine == played))
        return played


def people_job(task):
    name, path, seed = task
    saved = json.loads(Path(path).read_text())
    gd = _s["gd"]
    teams = [[gd.build(sid, mv, level=lv, ivs=tuple(iv)) for sid, mv, lv, iv in t] for t in saved["teams"]]
    tally: list = []
    person = Copying(Replay(saved["my_choices"]), build(name, seed), tally)
    Battle(teams[0], teams[1], person, Logged(saved["log"]), seed=saved["seed"], record=True).run()
    return Path(path).stem, tally


def points(winner, side):
    return 1.0 if winner == side else 0.5 if winner == DRAW else 0.0


def opponent(kind, dice):
    if kind == "trained":
        return trained(dice % 99991)
    if kind == "crowd":
        return varied(random.Random(dice), _s["pool"])
    return PvpokeAI()


def field_job(task):
    name, kind, start, count, seed = task
    out = {}
    for n in range(start, start + count):
        rng = random.Random(seed * 1_000_003 + n)
        a, b = _s["draw"](rng), _s["draw"](rng)
        dice = rng.getrandbits(32)
        out[n] = points(Battle(a, b, build(name, dice % 99989), opponent(kind, dice), seed=dice).run(), 0)
    return out


def exploit_job(task):
    name, start, count, seed = task
    out = {}
    for n in range(start, start + count):
        rng = random.Random(seed * 1_000_003 + n)
        a, b = _s["draw"](rng), _s["draw"](rng)
        dice = rng.getrandbits(32)
        pair = []
        for cls in (Engine, Reader):
            probe = cls(Evaluator(_s["ev"]), _s["site_pool"], rollout="bot", samples=4, edge=0.03, q=_s["net"], margin=0.02, seed=dice % 99971)
            target = build(name, dice % 99989)
            if cls is Reader:
                probe.target, probe.target_side = target, 1
            pair.append(points(Battle(a, b, probe, target, seed=dice).run(), 0))
        out[n] = pair
    return out


def margin(values) -> float:
    n = len(values)
    if n < 2:
        return float("nan")
    mean = sum(values) / n
    return 1.96 * math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1) / n)


def cluster(rows) -> tuple[float, float]:
    """Mean of (source, value) rows, with a margin treating each source (a game, a battle) as one sample."""
    if not rows:  # a small smoke may have no positions of one kind
        return float("nan"), float("nan")
    groups = collections.defaultdict(list)
    for source, value in rows:
        groups[source].append(value)
    total, n = sum(v for _, v in rows), len(rows)
    mean = total / n
    per = [(sum(v) - mean * len(v)) for v in groups.values()]
    return mean, 1.96 * math.sqrt(sum(x * x for x in per)) / n


def judge_all(names, rulers, workers, seed=1, field_n=400, exploit_n=100, endgame_limit=None) -> dict:
    results = {name: {} for name in names}
    rows = []
    if "endgame" in rulers:
        with gzip.open(ENDGAMES, "rt") as f:
            rows = [json.loads(line) for line in f]
        if endgame_limit is not None:
            rows = rows[:endgame_limit]
            print(f"Smoke only: first {len(rows)} endgame positions", flush=True)
        shields = [r for r in rows if r["kind"] == "shield"]
        print(f"Endgames: {len(rows)} positions, {len(shields)} shield calls "
              f"({sum(r['source'].startswith('real') for r in shields)} shield calls from real games)", flush=True)
    games = sorted(g for g in glob.glob(str(ROOT / "games" / "played" / "*-web.json")) if not json.loads(Path(g).read_text()).get("player"))
    with (multiprocessing.get_context("spawn").Pool(workers, initializer=setup) if workers > 1 else nullcontext()) as pool:
        if pool is None:
            setup()
        if "endgame" in rulers:
            tasks = [(name, seed * 1000 + k, rows[k:k + 50]) for name in names for k in range(0, len(rows), 50)]
            out = pool.map(endgame_job, tasks, chunksize=1) if pool else map(endgame_job, tasks)
            for task, got in zip(tasks, out):
                results[task[0]].setdefault("_endgame", []).extend(got)
            for name in names:
                got = results[name].pop("_endgame")
                both = [(src, v) for src, v, _ in got]
                results[name]["endgame"] = {"points": 100 * cluster(both)[0], "margin": 100 * cluster(both)[1],
                                            "blunders": 100 * sum(v >= 0.1 for _, v in both) / len(both), "n": len(both),
                                            "act": 100 * cluster([(src, v) for src, v, k in got if k == "act"])[0],
                                            "shield": 100 * cluster([(src, v) for src, v, k in got if k == "shield"])[0],
                                            "real": 100 * cluster([(src, v) for src, v, _ in got if src.startswith("real")])[0],
                                            "rows": both}
        if "people" in rulers:
            tasks = [(name, g, seed + k) for name in names for k, g in enumerate(games)]
            out = pool.map(people_job, tasks, chunksize=1) if pool else map(people_job, tasks)
            for task, (game, tally) in zip(tasks, out):
                results[task[0]].setdefault("_people", []).extend((game, kind, same) for kind, same in tally)
            for name in names:
                got = results[name].pop("_people")
                by = {}
                for kind in ("throw", "switch", "shield", "replace"):
                    these = [(g, float(s)) for g, k, s in got if k == kind]
                    if these:
                        by[kind] = 100 * cluster(these)[0]
                both = [(g, float(s)) for g, _, s in got]
                results[name]["people"] = {"agree": 100 * cluster(both)[0], "margin": 100 * cluster(both)[1], "n": len(both), **by,
                                           "rows": [(g, k, bool(s)) for g, k, s in got]}
        if "field" in rulers:
            for kind in ("trained", "crowd", "pvpoke"):
                tasks = [(name, kind, k, 20, seed + 7) for name in names for k in range(0, field_n, 20)]
                out = pool.imap(field_job, tasks, chunksize=1) if pool else map(field_job, tasks)
                for task, got in zip(tasks, out):
                    results[task[0]].setdefault(kind, {}).update(got)
        if "exploit" in rulers:
            tasks = [(name, k, 10, seed + 13) for name in names for k in range(0, exploit_n, 10)]
            out = pool.imap(exploit_job, tasks, chunksize=1) if pool else map(exploit_job, tasks)
            for task, got in zip(tasks, out):
                results[task[0]].setdefault("exploit", {}).update(got)
    return results


def table(results, rulers) -> list:
    lines = []
    head = ["build"]
    if "endgame" in rulers:
        head += ["endgame points lost", "moves", "shields", "real games", "blunders"]
    if "people" in rulers:
        head += ["agrees with owner", "throw", "switch", "shield"]
    if "field" in rulers:
        head += ["v trained", "v crowd", "v PvPoke"]
    if "exploit" in rulers:
        head += ["reader's gain"]
    lines.append("| " + " | ".join(head) + " |")
    lines.append("|" + "---|" * len(head))
    for name, r in results.items():
        cells = [name]
        if "endgame" in rulers:
            e = r["endgame"]
            cells += [f"{e['points']:.2f} ± {e['margin']:.2f}", f"{e['act']:.2f}", f"{e['shield']:.2f}", f"{e['real']:.2f}", f"{e['blunders']:.1f}%"]
        if "people" in rulers:
            p = r["people"]
            cells += [f"{p['agree']:.1f} ± {p['margin']:.1f}", f"{p.get('throw', 0):.0f}", f"{p.get('switch', 0):.0f}", f"{p.get('shield', 0):.0f}"]
        if "field" in rulers:
            for kind in ("trained", "crowd", "pvpoke"):
                v = list(r[kind].values())
                cells.append(f"{100 * sum(v) / len(v):.1f} ± {100 * margin(v):.1f}")
        if "exploit" in rulers:
            v = [b - a for a, b in r["exploit"].values()]
            cells.append(f"{100 * sum(v) / len(v):+.1f} ± {100 * margin(v):.1f}")
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def save(label, results) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    keep = {n: {j: ({k: v for k, v in x.items() if k != "rows"} if j in ("endgame", "people") else {str(k): v for k, v in x.items()})
                for j, x in r.items()} for n, r in results.items()}
    (OUT / f"{label}.json").write_text(json.dumps(keep))


def score(args) -> None:
    rulers = args.rulers.split(",")
    results = judge_all(args.builds, rulers, args.workers, args.seed, endgame_limit=args.endgame_limit)
    print("\n".join(table(results, rulers)))
    save(args.label or "+".join(args.builds)[:60], results)


def check(args) -> None:
    """Does each judge see what we know is there?"""
    rulers = args.rulers.split(",")
    names = list(dict.fromkeys(LADDER + list(BROKEN) + ["engine8_again"]))
    results = judge_all(names, rulers, args.workers, args.seed)
    print("\n".join(table(results, rulers)))
    save("check", results)

    def score_of(name, ruler):  # higher is better on every line
        r = results[name]
        if ruler == "endgame":
            return -r["endgame"]["points"]
        if ruler == "people":
            return r["people"]["agree"]
        if ruler == "exploit":
            return -sum(b - a for a, b in r["exploit"].values()) / len(r["exploit"])
        return sum(r[ruler].values()) / len(r[ruler])

    judges = [j for j in ("endgame", "people", "trained", "crowd", "pvpoke", "exploit") if j in rulers or (j in ("trained", "crowd", "pvpoke") and "field" in rulers)]
    print("\nLadder, weakest to strongest; does the judge rank it in that order? (pairs in the right order, of 10)")
    for j in judges:
        s = [score_of(n, j) for n in LADDER]
        right = sum(s[a] < s[b] for a in range(len(s)) for b in range(a + 1, len(s)))
        print(f"  {j:8s} {right}/10   " + "  ".join(f"{n} {v:.2f}" for n, v in zip(LADDER, s)))
    print("\nBroken bots against the trained bot: difference on the judge's own scale (negative is worse), with its margin, paired")

    def paired(name, base, j):
        if j == "endgame":
            a, b = results[name]["endgame"]["rows"], results[base]["endgame"]["rows"]
            per = collections.defaultdict(float)
            for (s, x), (_, y) in zip(a, b):
                per[s] += y - x
            n = len(a)
            return 100 * sum(per.values()) / n, 100 * 1.96 * math.sqrt(sum(v * v for v in per.values())) / n
        if j == "people":
            a, b = results[name]["people"], results[base]["people"]
            return a["agree"] - b["agree"], math.hypot(a["margin"], b["margin"])
        if j == "exploit":
            d = [(results[base]["exploit"][k][1] - results[base]["exploit"][k][0]) - (results[name]["exploit"][k][1] - results[name]["exploit"][k][0]) for k in results[name]["exploit"]]
            return 100 * sum(d) / len(d), 100 * margin(d)
        d = [results[name][j][k] - results[base][j][k] for k in results[name][j]]
        return 100 * sum(d) / len(d), 100 * margin(d)

    print("  " + f"{'':14s}" + "".join(f"{j:>18s}" for j in judges))
    for name, base in BROKEN.items():
        cells = []
        for j in judges:
            d, m = paired(name, base, j)
            cells.append(f"{d:+7.2f} ±{m:5.2f}{'*' if d + m < 0 else ' '}")
        print(f"  {name:14s}" + "".join(f"{c:>18s}" for c in cells))
    print("  (* caught: worse than the trained bot beyond the margin)")
    print("\nRepeats: the same build (engine, 8 imagined) with different dice; a judge should see no difference")
    for j in judges:
        d, m = paired("engine8_again", "engine8", j)
        print(f"  {j:8s} {d:+.2f} ± {m:.2f}")
    print("\nCost: paired battles or positions to see a given gain at 95%, from the noise in trained against engine8")
    for j in judges:
        if j == "people":
            continue
        d, m = paired("engine8", "trained", j)
        n = results["engine8"]["endgame"]["n"] if j == "endgame" else len(results["engine8"][j])
        sd = m / 1.96 * math.sqrt(n)
        print(f"  {j:8s} " + "  ".join(f"±{x}: {int((1.96 * sd / x) ** 2):,}" for x in (5, 2, 1)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("freeze")
    p.add_argument("--battles", type=int, default=300)
    p.add_argument("--workers", type=int, default=3)
    p = sub.add_parser("score")
    p.add_argument("builds", nargs="+", help="a named build or engine settings as key=value,key=value")
    p.add_argument("--rulers", default="endgame,people,field")
    p.add_argument("--label", default="")
    p.add_argument("--workers", type=int, default=3)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--endgame-limit", type=int, help="smoke only: score the first N frozen positions")
    p = sub.add_parser("check")
    p.add_argument("--rulers", default="endgame,people,field")
    p.add_argument("--workers", type=int, default=3)
    p.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    if args.command == "score":
        for name in args.builds:
            if name not in BUILDS:
                parse(name)  # reject a mistyped setting before starting workers
        if args.endgame_limit is not None and args.endgame_limit < 1:
            parser.error("--endgame-limit must be positive")
    {"freeze": freeze, "score": score, "check": check}[args.command](args)


if __name__ == "__main__":
    main()
