#!/usr/bin/env python3
"""How well can we predict the opponent? (the owner: "what if we try very hard to predict the opponent")

    python3 scripts/predict_bench.py [--battles 150] [--workers 3] [--seed 12]

The decisions predicted are the opponent's: at every turn they are free to act with a charged move affordable, fast
move, either charged move, or a switch; and every shield call, shield or not. Ground truth comes from battles on the
mixed field between our trained bot and each kind of opponent (the bot itself, the crowd, the human-like style,
PvPoke's AI), and from the owner's decisions in the website games (games/played/*-web.json, replayed from their logs).

Each candidate style is asked what it would do in that exact position (the battle copied, the style in the
opponent's seat): the trained bot; the bot with shifted habits (6 of them, the share choosing each option); the
human-like style (6); PvPoke's AI. From those, the predictors:

  bot       they play like our bot (what the engine assumes now)
  mix       the engine's style mix (task 28), fixed weights
  profile   that mix reweighted by their shield and bait rates so far in the battle (task 28's profile=1)
  match     that mix reweighted by how likely each style made every decision seen so far in the battle
  habit     the shares of their own decisions so far in the battle, by kind

Scored on each decision before it is seen: the chance given to what they did (log loss, lower is better) and how
often the most likely option was it. Positions are copied from the real battle, so a style in the opponent's seat
sees their whole team; the predictions are of decisions in front of them, where that matters little.
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import math
import multiprocessing
import os
import random
import sys
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_v] = "1"
ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
from pogo.agents import varied  # noqa: E402
from pogo.arena import low_priority  # noqa: E402
from pogo.battle import CHARGED, FAST, SWITCH, Battle  # noqa: E402
from pogo.engine import style_player, styles  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.learner import Learner, QNet  # noqa: E402
from pogo.pvpoke_ai import PvpokeAI  # noqa: E402
from pogo.teamshape import mixed_field  # noqa: E402

SAMPLES = 6
STYLE_NAMES = ("bot", "varied", "human", "pvpoke")
_s: dict = {}


def setup():
    low_priority()
    gd = GameData()
    pool, draw = mixed_field(gd)
    _s.update(gd=gd, pool=pool, draw=draw, net=QNet.load(str(ROOT / "runs" / "general-decide" / "q.npz")))


def kind_of(action) -> str:
    if action == FAST:
        return "fast"
    if action in CHARGED:
        return f"charged{CHARGED.index(action)}"
    return "switch"


def candidates(name: str):
    """The players standing for one style: always the same ones, so a style is the same population all along."""
    s = _s
    if name in ("bot", "pvpoke"):
        return [style_player(name, random.Random(7), s["net"], 0.02, s["pool"])]
    return [style_player(name, random.Random(1000 * STYLE_NAMES.index(name) + k), s["net"], 0.02, s["pool"]) for k in range(SAMPLES)]


def shares(battle, side: int, event: str, energy: int | None) -> dict:
    """{style: {option: share of its players choosing it}} in this position."""
    out = {}
    for name in STYLE_NAMES:
        votes = collections.Counter()
        for player in candidates(name):
            twin = battle.clone(None, None)
            view = twin.views[side]
            try:
                if event == "act":
                    votes[kind_of(player.act(view))] += 1
                else:
                    votes["shield" if player.shield(view, energy) else "take"] += 1
            except Exception:  # a style that cannot judge this position (PvPoke's AI outside one-on-one) abstains
                continue
        n = sum(votes.values())
        out[name] = {k: v / n for k, v in votes.items()} if n else {}
    return out


class Watch:
    """Plays as `inner` and notes each decision worth predicting: the position, the styles' shares, what it did."""

    def __init__(self, inner, side: int, events: list):
        self.inner, self.side, self.events = inner, side, events
        self.sees_move = getattr(inner, "sees_move", False)
        self.scripted = getattr(inner, "scripted", False)
        for hook in ("saw_throw", "saw_shield"):
            if hasattr(inner, hook):
                setattr(self, hook, getattr(inner, hook))

    def act(self, view):
        mon = view.me.mon
        cheapest = min((m.energy for m in mon.build.charged), default=999)
        worth = mon.energy >= cheapest
        battle = view._battle.clone(None, None) if worth else None
        action = self.inner.act(view)
        if worth:
            ready = [m.energy <= mon.energy for m in mon.build.charged]
            bait = None
            if action in CHARGED and all(ready) and len(ready) == 2 and view.foe_shields > 0:
                k = CHARGED.index(action)
                bait = mon.build.charged[k].energy < mon.build.charged[1 - k].energy
            self.events.append({"event": "act", "did": kind_of(action), "styles": shares(battle, self.side, "act", None),
                                "bait": bait})
        return action

    def shield(self, view, energy, *move):
        battle = view._battle.clone(None, None)
        choice = bool(self.inner.shield(view, energy, *move))
        self.events.append({"event": "shield", "did": "shield" if choice else "take",
                            "styles": shares(battle, self.side, "shield", energy)})
        return choice

    def replace(self, view):
        return self.inner.replace(view)


def job(task):
    kind, n, seed = task
    s = _s
    events: list = []
    if kind == "website":
        import losses as L
        L._state.update(gd=s["gd"], pool=s["pool"], net=s["net"])
        saved = json.loads(Path(n).read_text())
        teams = [[s["gd"].build(sid, moves, level=level, ivs=tuple(ivs)) for sid, moves, level, ivs in t] for t in saved["teams"]]
        Battle(teams[0], teams[1], Watch(L.Replay(saved["my_choices"]), 0, events), L.Logged(saved["log"]), seed=saved["seed"]).run()
        return kind, events
    rng = random.Random(seed * 1_000_003 + n)
    a, b = s["draw"](rng), s["draw"](rng)
    ours = Learner(q=s["net"], margin=0.02, seed=rng.getrandbits(30))
    if kind == "bot":
        theirs = Learner(q=s["net"], margin=0.02, seed=rng.getrandbits(30))
    elif kind == "crowd":
        theirs = varied(rng, s["pool"])
    elif kind == "pvpoke":
        theirs = PvpokeAI()
    else:
        theirs = style_player("human", rng, s["net"], 0.02, s["pool"])
    Battle(a, b, ours, Watch(theirs, 1, events), seed=rng.getrandbits(32)).run()
    return kind, events


def predict(events: list, rates: dict) -> dict:
    """Each predictor's chance for what they did, decision by decision, using only what came before."""
    prior = {name: rates[name]["weight"] for name in STYLE_NAMES}
    total = sum(prior.values())
    prior = {k: v / total for k, v in prior.items()}
    loglik = {name: 0.0 for name in STYLE_NAMES}
    seen = {"shield": [0, 0], "bait": [0, 0]}
    habit = {"act": collections.Counter(), "shield": collections.Counter()}
    out = []
    for e in events:
        options = ["fast", "charged0", "charged1", "switch"] if e["event"] == "act" else ["shield", "take"]

        def style_p(name, option):
            sh = e["styles"].get(name) or {}
            return (sh.get(option, 0.0) * 0.9 + 0.1 / len(options)) if sh else 1 / len(options)

        def mix(weights):
            return {o: sum(w * style_p(n, o) for n, w in weights.items()) for o in options}

        def floor(weights):  # as the engine does: keep a tenth of the starting mix
            t = sum(weights.values()) or 1.0
            return {n: 0.9 * w / t + 0.1 * prior[n] for n, w in weights.items()}

        prof = {}
        for name in STYLE_NAMES:
            w = prior[name]
            for kind in ("shield", "bait"):
                k, n = seen[kind]
                r = min(max(rates[name][kind], 0.02), 0.98)
                w *= r ** k * (1 - r) ** (n - k)
            prof[name] = w
        top = max(loglik.values())
        match = {n: prior[n] * math.exp(loglik[n] - top) for n in STYLE_NAMES}
        h = habit[e["event"]]
        preds = {"bot": {o: style_p("bot", o) for o in options}, "mix": mix(prior), "profile": mix(floor(prof)),
                 "match": mix(floor(match)),
                 "habit": {o: (h[o] + 0.5) / (sum(h.values()) + 0.5 * len(options)) for o in options}}
        did = e["did"]
        out.append({"event": e["event"], **{k: (p[did] / sum(p.values()), max(p, key=p.get) == did) for k, p in preds.items()}})
        for name in STYLE_NAMES:  # learn from this decision
            loglik[name] += math.log(style_p(name, did))
        habit[e["event"]][did] += 1
        if e["event"] == "shield":
            seen["shield"][0] += did == "shield"
            seen["shield"][1] += 1
        if e.get("bait") is not None:
            seen["bait"][0] += e["bait"]
            seen["bait"][1] += 1
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--battles", type=int, default=150)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--seed", type=int, default=12)
    args = parser.parse_args()
    games = sorted(glob.glob(str(ROOT / "games" / "played" / "*-web.json")))
    tasks = [(k, n, args.seed) for k in ("bot", "crowd", "human", "pvpoke") for n in range(args.battles)]
    tasks += [("website", g, 0) for g in games]
    rates = styles()
    scored = collections.defaultdict(list)
    with multiprocessing.get_context("spawn").Pool(args.workers, initializer=setup) as pool:
        for kind, events in pool.imap_unordered(job, tasks, chunksize=2):
            scored[kind].extend(predict(events, rates))
    preds = ("bot", "mix", "profile", "match", "habit")
    print(f"{args.battles} battles against each kind of opponent on the mixed field, and the owner's {len(games)} website games")
    for event, label in (("act", "throw / fast / switch, with a charged move affordable"), ("shield", "shield calls")):
        print(f"\n{label}: chance given to what they did (higher is better), then how often the top guess was right")
        print(f"  {'opponent':10s} {'decisions':>9s}  " + "  ".join(f"{p:>13s}" for p in preds))
        for kind in ("bot", "crowd", "human", "pvpoke", "website"):
            rows = [r for r in scored[kind] if r["event"] == event]
            if not rows:
                continue
            cells = []
            for p in preds:
                geo = math.exp(sum(math.log(max(r[p][0], 1e-6)) for r in rows) / len(rows))
                acc = sum(r[p][1] for r in rows) / len(rows)
                cells.append(f"{100 * geo:5.1f}% {100 * acc:5.1f}%")
            print(f"  {('owner' if kind == 'website' else kind):10s} {len(rows):9d}  " + "  ".join(f"{c:>13s}" for c in cells))
    print("\n(the first number is the geometric mean of the chance given to what was done: log loss, as a probability)")


if __name__ == "__main__":
    main()
