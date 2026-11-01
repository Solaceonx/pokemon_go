#!/usr/bin/env python3
"""Positions from real website games for the owner's exam (docs/benchmarking.md).

    python3 scripts/exam_positions.py [--workers 3] [--seed 1] [--tag exam-1]

Every saved website game is replayed exactly, with four versions of the bot (the rulebook, the trained bot, the website's
engine, the engine with `matching`) shadowing both sides: at each decision every version says what it would do, and
the move actually played goes through. The exam takes:

    flagged   decisions the play-out judge called costly in the bot's losses (does the owner agree with the judge?)
    disagree  decisions where the versions differ, engine against matching first, by kind: throw, switch, shield, replace
    control   decisions where all four agree, to catch a blind spot they share
    repeat    a few of the above again, late, with the options in another order (how consistent are the answers?)

Games already decided (the judge gives every option under 8% or over 92%) are left out. Writes data/exam/<tag>.json, the
positions as the page shows them, with nothing about who chose what, and runs/exam/<tag>-key.json, what each version
chose, what was played and the judge's chance for each option.
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import multiprocessing
import os
import random
import re
import sys
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_v] = "1"
ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
import losses as L  # noqa: E402
from pogo.agents import Planner  # noqa: E402
from pogo.battle import CHARGED, FAST, SWITCH, Battle, damage  # noqa: E402
from pogo.engine import Engine  # noqa: E402
from pogo.evaluation import Evaluator  # noqa: E402
from pogo.learner import Learner  # noqa: E402
from pogo.review import Logged, Replay  # noqa: E402

_s: dict = {}
QUOTA = {"throw": 10, "switch": 7, "shield": 5, "replace": 2}
CONTROL = {"throw": 3, "shield": 2, "switch": 1}
FLAGGED, REPEATS = 6, 4


def setup() -> None:
    L.setup()
    _s.update(ev=Evaluator.load(ROOT / "runs" / "eval" / "eval.npz"))


def versions(seed: int) -> dict:
    gd, net, pool = L._state["gd"], L._state["net"], L._state["pool"]

    def engine(k, **extra):
        return Engine(Evaluator(_s["ev"].model), pool, rollout="bot", samples=32, edge=0.03, q=net, margin=0.02, seed=seed + k, **extra)

    return {"rulebook": Planner(seed=seed), "trained": Learner(q=net, margin=0.02, seed=seed + 1), "engine": engine(2),
            "matching": engine(3, opponents="mix", matching=True)}


def key_of(action) -> str:
    if action == FAST:
        return "fast"
    return f"c{CHARGED.index(action)}" if action in CHARGED else f"s{action - SWITCH[0]}"


def mon_info(mon, target) -> dict:
    b = mon.build
    return {"name": b.name, "types": list(b.types), "hp": max(mon.hp, 0), "hp_max": b.hp, "energy": mon.energy,
            "atk": mon.atk_stage, "def": mon.def_stage,
            "fast": {"name": b.fast.name, "type": b.fast.type, "gain": b.fast.energy_gain, "turns": b.fast.turns, "dmg": damage(mon, b.fast, target)},
            "charged": [{"name": m.name, "type": m.type, "cost": m.energy, "dmg": damage(mon, m, target)} for m in b.charged]}


def position(view, kind: str, options: list, energy=None) -> dict:
    me, foe = view.me, view.foe
    battle = view._battle
    side = battle.views.index(view)
    recent = []
    for turn, who, text in (battle.log or [])[-6:]:
        text = re.sub(r"(sends in .*?) \d+/\d+hp \d+e$", r"\1", text)
        recent.append(("You: " if who == side else "They: ") + text)
    target = me.mon if me.mon.hp > 0 else me.team[(options and int(options[0]["key"][1:])) or 0]
    return {"kind": kind, "turn": view.turn, "seconds": view.turn / 2, "recent": recent, "incoming_energy": energy, "options": options,
            "you": {"active": mon_info(me.mon, foe), "shields": me.shields, "switch_wait": me.switch_wait, "busy": me.busy,
                    "bench": [{**mon_info(m, foe), "taken": [damage(foe, x, m) for x in (foe.build.fast, *foe.build.charged)]}
                              for j, m in enumerate(me.team) if j != me.active and m.hp > 0],
                    "fainted": sum(1 for m in me.team if m.hp <= 0)},
            "foe": {"active": mon_info(foe, target), "shields": view.foe_shields, "switch_wait": view.foe_switch_wait, "busy": view.foe_busy,
                    "bench": [mon_info(m, target) for m in view.foe_shown if m is not foe and m.hp > 0],
                    "fainted": sum(1 for m in view.foe_shown if m.hp <= 0), "unseen": 3 - len(view.foe_shown)}}


def label(view, key: str) -> str:
    mon = view.me.mon
    if key == "fast":
        return f"Fast move ({mon.build.fast.name})"
    if key[0] == "c":
        return f"Throw {mon.build.charged[int(key[1:])].name}"
    return f"Switch to {view.me.team[int(key[1:])].build.name}"


class Shadow:
    """Plays the recorded game; every version says what it would do first and hears what it would hear."""

    def __init__(self, script, builds: dict, side: int, game: str):
        self.script, self.builds, self.side, self.game, self.rows, self.matchup, self.step = script, builds, side, game, [], None, 0

    def saw_throw(self, view, move, energy, could_shield):
        for b in self.builds.values():
            if hasattr(b, "saw_throw"):
                b.saw_throw(view, move, energy, could_shield)

    def saw_shield(self, view, shielded):
        for b in self.builds.values():
            if hasattr(b, "saw_shield"):
                b.saw_shield(view, shielded)

    def _row(self, kind, view, picks, played, options, energy=None, **extra):
        self.rows.append({"game": self.game, "side": self.side, "turn": view.turn, "step": self.step, "kind": kind, "picks": picks, "played": played,
                          "position": position(view, kind, options, energy), **extra})

    def act(self, view):
        picks = {n: key_of(b.act(view)) for n, b in self.builds.items()}
        action = self.script.act(view)
        played, legal = key_of(action), view.legal()
        new = (view.me.active, id(view.foe)) != self.matchup
        self.matchup = (view.me.active, id(view.foe))
        keys = [key_of(a) for a in legal]
        ready = any(k[0] == "c" for k in keys)
        switching = any(k[0] == "s" for k in keys)
        everyone = set(picks.values()) | {played}
        kind = "switch" if any(k[0] == "s" for k in everyone) else "throw" if any(k[0] == "c" for k in everyone) or ready else "switch" if new and switching else None
        if kind:
            hydro = (self.side == 1 and played[0] == "c" and view.foe.build.name == "Jellicent"
                     and view.me.mon.build.charged[int(played[1:])].name == "Hydro Cannon")
            self._row(kind, view, picks, played, [{"key": k, "label": label(view, k)} for k in keys], hydro=hydro)
        return action

    def shield(self, view, energy, *move):
        picks = {n: "yes" if b.shield(view, energy) else "no" for n, b in self.builds.items()}
        choice = bool(self.script.shield(view, energy))
        if view.me.shields > 0:
            self._row("shield", view, picks, "yes" if choice else "no",
                      [{"key": "yes", "label": "Shield"}, {"key": "no", "label": "Don't shield"}], energy)
        return choice

    def replace(self, view):
        picks = {n: f"r{b.replace(view)}" for n, b in self.builds.items()}
        choice = self.script.replace(view)
        bench = view.me.bench()
        if len(bench) > 1:
            self._row("replace", view, picks, f"r{choice}", [{"key": f"r{j}", "label": f"Send in {view.me.team[j].build.name}"} for j in bench])
        return choice


def load_game(path):
    saved = json.loads(Path(path).read_text())
    gd = L._state["gd"]
    teams = [[gd.build(sid, moves, level=level, ivs=tuple(ivs)) for sid, moves, level, ivs in team] for team in saved["teams"]]
    return saved, teams


def shadow_job(path: str):
    saved, teams = load_game(path)
    name = Path(path).stem
    seed = saved["seed"] % 100_000
    shadows = [Shadow(Replay(saved["my_choices"]), versions(seed), 0, name), Shadow(Logged(saved["log"]), versions(seed + 10), 1, name)]
    battle = Battle(teams[0], teams[1], shadows[0], shadows[1], seed=saved["seed"], record=True)
    while battle.winner is None:  # a decision may come after the turn count has moved on: the judge starts from the step
        shadows[0].step = shadows[1].step = battle.turn
        battle.step()
    same = [list(e) for e in battle.log] == [list(e) for e in saved["log"]]
    return name, same, (shadows[0].rows + shadows[1].rows) if same else []


def to_action(key: str):
    if key == "fast":
        return "act", FAST
    if key[0] == "c":
        return "act", CHARGED[int(key[1:])]
    if key[0] == "s":
        return "act", SWITCH[int(key[1:])]
    return ("shield", key == "yes") if key in ("yes", "no") else ("replace", int(key[1:]))


def judge_job(task):
    """The judge's chance for each option of one decision: that choice forced, the trained bot on our side after it,
    a varied one against it (pogo/review.py's judge, without the screening)."""
    row, plays = task
    saved, teams = load_game(ROOT / "games" / "played" / f"{row['game']}.json")
    scripts = [Replay(saved["my_choices"]), Logged(saved["log"])]
    battle = Battle(teams[0], teams[1], scripts[0], scripts[1], seed=saved["seed"], record=True)
    while battle.turn < row["step"] and battle.winner is None:
        battle.step()
    snap = (battle.clone(None, None), scripts[row["side"]].clone(), scripts[1 - row["side"]])
    out = {}
    for option in row["position"]["options"]:
        kind, choice = to_action(option["key"])
        try:
            out[option["key"]] = round(L.win_chance(snap, kind, choice, plays, seed=row["turn"] * 31 + 7, side=row["side"]), 3)
        except ValueError:  # the step holds an earlier decision of this kind, so this one cannot be forced from its start
            return row["_id"], None
    return row["_id"], out


def choose(rows: list, seed: int) -> dict:
    """Candidates for each group, most useful first, limited to a few a game and spaced apart."""
    r = random.Random(seed)
    rows.sort(key=lambda x: (x["game"], x["side"], x["turn"], x["kind"]))  # the workers finish in any order
    r.shuffle(rows)
    flagged = set()
    for line in (ROOT / "runs" / "losses" / "played.jsonl").read_text().splitlines():
        rec = json.loads(line)
        for swing in rec.get("swings", []):
            flagged.add((rec["battle"], swing["situation"]["turn"]))
    groups = collections.defaultdict(list)
    for row in rows:
        picks = set(row["picks"].values())
        if row.get("hydro") or (row["side"] == 1 and (row["game"], row["turn"]) in flagged):
            groups["flagged"].append(row)
        elif len(picks) > 1:
            groups["disagree", row["kind"]].append(row)
        else:
            groups["control", row["kind"]].append(row)
    for key, group in groups.items():  # engine against matching first
        group.sort(key=lambda x: (not x.get("hydro"), x["picks"]["engine"] == x["picks"]["matching"]))
    return groups


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--tag", default="exam-1")
    parser.add_argument("--pool", type=int, default=4, help="candidates judged per place in the exam")
    parser.add_argument("--plays", type=int, default=48)
    args = parser.parse_args()
    games = sorted(p for p in glob.glob(str(ROOT / "games" / "played" / "*.json"))
                   if not json.loads(Path(p).read_text()).get("player") and json.loads(Path(p).read_text()).get("source") == "website")
    out_runs = ROOT / "runs" / "exam"
    out_runs.mkdir(parents=True, exist_ok=True)
    with multiprocessing.get_context("spawn").Pool(args.workers, initializer=setup) as pool:
        rows, bad = [], []
        for name, same, got in pool.imap_unordered(shadow_job, games):
            rows += got
            if not same:
                bad.append(name)
            print(f"  {name}: {len(got)} decisions{'' if same else ' (does not replay)'}", flush=True)
        print(f"{len(games)} games, {len(bad)} do not replay, {len(rows)} decisions", flush=True)
        groups = choose(rows, args.seed)
        candidates = []
        wanted = {"flagged": FLAGGED, **{("disagree", k): v for k, v in QUOTA.items()}, **{("control", k): v for k, v in CONTROL.items()}}
        for key, n in wanted.items():
            for row in groups.get(key, [])[: n * args.pool * 3]:
                row["group"] = key if isinstance(key, str) else key[0]
                candidates.append(row)
        for k, row in enumerate(candidates):
            row["_id"] = k
        print(f"judging {len(candidates)} candidates", flush=True)
        for k, chances in pool.imap_unordered(judge_job, [(row, args.plays) for row in candidates]):
            candidates[k]["judge"] = chances

    candidates = [row for row in candidates if row["judge"]]

    def live(row):
        values = list(row["judge"].values())
        return max(values) >= 0.08 and min(values) <= 0.92

    r = random.Random(args.seed)
    chosen, per_game, seen_matchups = [], collections.Counter(), set()

    def fits(row):
        pos = row["position"]
        pair = (pos["you"]["active"]["name"], pos["foe"]["active"]["name"], row["kind"])
        near = any(c["game"] == row["game"] and abs(c["turn"] - row["turn"]) < 12 for c in chosen)
        return live(row) and per_game[row["game"]] < 3 and not near and pair not in seen_matchups

    def take(row):
        pos = row["position"]
        chosen.append(row)
        per_game[row["game"]] += 1
        seen_matchups.add((pos["you"]["active"]["name"], pos["foe"]["active"]["name"], row["kind"]))

    for key, n in wanted.items():
        group = [row for row in candidates if row["group"] == (key if isinstance(key, str) else key[0]) and
                 (isinstance(key, str) or row["kind"] == key[1])]
        spread = [row for row in group if max(row["judge"].values()) - min(row["judge"].values()) >= 0.1]
        flat = [row for row in group if row not in spread]
        got = 0
        for row in sorted(group, key=lambda x: not x.get("hydro")) if isinstance(key, str) else []:
            if got < n and fits(row):
                take(row)
                got += 1
        low = max(1, n // 5)  # at most a fifth where the judge sees nothing at stake: the owner may
        for row in spread + flat[:low]:
            if got < n and fits(row):
                take(row)
                got += 1
    order = list(chosen)
    r.shuffle(order)
    repeats = r.sample([c for c in chosen if c["group"] != "flagged"], REPEATS)
    positions, key = [], []
    for row in order:
        options = list(row["position"]["options"])
        r.shuffle(options)
        positions.append({"id": f"p{len(positions) + 1:02d}", **row["position"], "options": options})
        key.append({"id": positions[-1]["id"], "game": row["game"], "side": row["side"], "turn": row["turn"], "kind": row["kind"],
                    "group": row["group"], "picks": row["picks"], "played": row["played"], "judge": row["judge"], "hydro": bool(row.get("hydro"))})
    for row in repeats:  # late in the exam, options reordered
        first = next(k for k in key if k["game"] == row["game"] and k["turn"] == row["turn"] and k["side"] == row["side"] and k["group"] != "repeat")
        original = next(p for p in positions if p["id"] == first["id"])
        options = list(original["options"])
        options.reverse()
        positions.append({**original, "id": f"p{len(positions) + 1:02d}", "options": options})
        key.append({**first, "id": positions[-1]["id"], "group": "repeat", "repeat_of": first["id"]})
    tail = positions[-REPEATS:]
    head = positions[:-REPEATS]
    for k, p in enumerate(tail):  # spread through the second half, at least ten after the original
        original = next(i for i, q in enumerate(head) if q["id"] == next(x["repeat_of"] for x in key if x["id"] == p["id"]))
        at = max(original + 10, len(head) // 2 + k * 4)
        head.insert(min(at, len(head)), p)
    (ROOT / "data" / "exam").mkdir(parents=True, exist_ok=True)
    (ROOT / "data" / "exam" / f"{args.tag}.json").write_text(json.dumps(head, indent=0))
    (out_runs / f"{args.tag}-key.json").write_text(json.dumps(key, indent=1))
    print(f"{len(head)} positions:", dict(collections.Counter(k["group"] for k in key)), dict(collections.Counter(k["kind"] for k in key)),
          "sides", dict(collections.Counter(k["side"] for k in key)), "hydro", sum(k["hydro"] for k in key))


if __name__ == "__main__":
    main()
