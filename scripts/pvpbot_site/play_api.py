"""A battle against the bot, run inside Pyodide for the web page (play.html), one turn at a time.

The page keeps the clock and asks for one step at a time with the person's queued action. A step that needs the
person (a shield or a replacement) is wound back and reported; the page asks and sends the step again with the
answer, and since the battle and the bot are copied with their dice, the step comes out the same up to that point.
Games are recorded in the format of scripts/play.py, so scripts/losses.py --played can replay them.
"""
import json
import random
import re
import time
from pathlib import Path

from pogo.agents import varied_settings  # noqa: F401  (kept importable for the line-up chance)
from pogo.battle import DRAW, FAST, MAX_TURNS, Battle
from pogo.evaluation import Evaluator
from pogo.gamedata import GameData
from pogo.learner import Learner, QNet
from pogo.lineup import win_chance
from pogo.realtime import RealTime
from pogo.roster import builds

HERE = Path(__file__).resolve().parent
TURN = 0.5
_s = {}


class NeedInput(Exception):
    def __init__(self, kind, options=None):
        super().__init__(kind)
        self.kind, self.options = kind, options


class Person:
    """The person at the page: their queued action, and answers given so far in this step."""

    def __init__(self):
        self.action, self.answers, self.choices = None, [], []

    def act(self, view):
        self.took = True  # the page keeps an action queued until a step actually asks for it
        action, self.action = self.action, None
        if action is not None:
            self.choices.append([view.turn, 0, action])
        return action if action is not None and action in view.legal() else FAST

    def shield(self, view, energy, *move):
        if view.me.shields == 0:
            return False
        if not self.answers:
            raise NeedInput("shield")
        answer = bool(self.answers.pop(0))
        self.choices.append([view.turn, 0, f"shield:{answer}"])
        return answer

    def replace(self, view):
        bench = view.me.bench()
        if len(bench) == 1:
            return bench[0]
        if not self.answers:
            raise NeedInput("replace", bench)
        slot = self.answers.pop(0)
        slot = slot if slot in bench else bench[0]
        self.choices.append([view.turn, 0, f"replace:{slot}"])
        return slot


def setup() -> str:
    gd = GameData()
    _s.update(gd=gd, pool=gd.meta(50), net=QNet.load(str(HERE / "runs" / "general-decide" / "q.npz")),
              ev=Evaluator.load(HERE / "runs" / "eval" / "eval.npz"), owned=builds(gd))
    return "{}"


def _describe(build):
    return [build.species_id, [build.fast.id, *(m.id for m in build.charged)], build.level, list(build.ivs)]


def new(job: str) -> str:
    """job: {"mine": [3 ids], "theirs": [3 ids], "owned": bool, "bot": "learner" | "engine", "tick_ms": real ms a turn}"""
    j = json.loads(job)
    gd, s = _s["gd"], _s
    mine = [(s["owned"].get(sid) if j["owned"] else None) or gd.default(sid) for sid in j["mine"]]
    theirs = [gd.default(sid) for sid in j["theirs"]]
    seed, bot_seed = random.getrandbits(32), random.getrandbits(30)
    if j["bot"] == "engine":
        bot = RealTime(Evaluator(s["ev"].model), s["pool"], rollout="bot", samples=4, edge=0.03,
                       q=s["net"], margin=0.02, seed=bot_seed,
                       turn_ms=j["tick_ms"], cap_ms=max(50, j["tick_ms"] - 100), clock=time.perf_counter)
    else:
        bot = Learner(q=s["net"], margin=0.02, seed=bot_seed)
    person = Person()
    s.pop("lineup_win_chance", None)
    s["evals"] = []  # (game seconds, the engine's evaluation from our side) after each turn, for the graph at the end
    s["view_ev"] = Evaluator(s["ev"].model)  # a separate cache for this game's human-side evaluation graph
    s.update(battle=Battle(mine, theirs, person, bot, seed=seed, record=True), person=person, bot=bot,
             record={"bot": j["bot"], "seed": seed, "bot_seed": bot_seed, "mine": j["mine"], "theirs": j["theirs"],
                     "teams": [[_describe(b) for b in mine], [_describe(b) for b in theirs]], "owned": j["owned"]})
    return json.dumps({"state": state()})


def step(job: str) -> str:
    """job: {"action": queued action or null, "answers": [answers for this step so far]}"""
    j = json.loads(job)
    s = _s
    battle, person = s["battle"], s["person"]
    snap = (battle.clone(None, None), s["bot"].clone(), list(battle.log), list(battle.hits), len(person.choices))
    person.action, person.answers, person.took = j["action"], list(j["answers"]), False
    seen = len(battle.log)
    try:
        battle.step()
    except NeedInput as need:
        twin, bot, log, hits, kept = snap
        restored = twin.clone(person, bot)
        restored.log, restored.hits = log, hits
        del person.choices[kept:]
        s["battle"], s["bot"] = restored, bot
        return json.dumps({"need": need.kind, "options": need.options, "state": state()})
    throwers = sorted({side for _, side, text in battle.log[seen:] if " throws " in text})
    if battle.winner is None and battle.sides[0].mon.hp > 0 and battle.sides[1].mon.hp > 0:
        s["evals"].append((round(battle.turn * TURN, 1), round(float(s["view_ev"](battle.views[0])), 3)))
    return json.dumps({"throwers": throwers, "took": person.took, "state": state()})


def finish(notes: str) -> str:
    """The record of the finished battle, with the line-up's win chance and the person's notes."""
    s = _s
    battle = s["battle"]
    rec = dict(s["record"])
    if "lineup_win_chance" not in s:
        chance, margin = win_chance(s["net"], s["pool"], *[[m.build for m in side.team] for side in battle.sides], battles=100,
                                    seed=rec["seed"] % 100003)
        s["lineup_win_chance"] = [round(chance, 3), round(margin, 3)]
    rec.update(result={DRAW: "draw", 0: "win", 1: "loss"}[battle.winner], turns=battle.turn,
               log=[list(e) for e in battle.log], my_choices=s["person"].choices,
               lineup_win_chance=s["lineup_win_chance"], notes=json.loads(notes), evaluation=s["evals"], review=review())
    rows = getattr(s["bot"], "rows", None)
    if rows:  # the engine's searches: what came before, kind, ms allowed, ms taken, wait, cut short, fell back
        rec["bot_searches"] = [[c, k, round(b), round(t, 1), round(w, 1), cut, fell] for c, k, b, t, w, cut, fell in rows]
    return json.dumps(rec)


def review() -> dict:
    """As scripts/play.py's review: the evaluation over the battle, and the moments it moved most with what happened."""
    battle, points = _s["battle"], list(_s["evals"])
    if battle.winner is not None and points:
        points.append((round(battle.turn * TURN, 1), 1.0 if battle.winner == 0 else 0.5 if battle.winner == DRAW else 0.0))
    swings = []
    for (t0, e0), (t1, e1) in zip(points, points[1:]):
        happened = [(side, re.sub(r" -?\d+/\d+hp \d+e", "", text)) for turn, side, text in battle.log
                    if t0 <= turn * TURN < t1 + 0.01 and ("throws" in text or "sends in" in text or "faints" in text)]
        if happened:
            swings.append({"t": t0, "change": round(e1 - e0, 3),
                           "what": "; ".join(("You: " if side == 0 else "Bot: ") + text for side, text in happened[:3])})
    swings.sort(key=lambda w: -abs(w["change"]))
    return {"points": points, "swings": sorted(swings[:5], key=lambda w: w["t"]), "learned": True}


def state() -> dict:
    s = _s
    battle, gd = s["battle"], s["gd"]
    me, foe = battle.sides

    def sprite(build):
        regional = {"alolan": "alola", "galarian": "galar", "hisuian": "hisui", "paldean": "paldea", "female": "f"}
        plain = {"shadow", "altered", "incarnate", "standard", "average", "male", "normal", "land", "aria", "ordinary"}
        base, *rest = build.species_id.split("_")
        form = "".join(regional.get(w, w) for w in rest if w not in plain)
        return {"showdown": base + (f"-{form}" if form else ""), "dex": gd.species[build.species_id]["dex"],
                "shadow": build.species_id.endswith("_shadow")}

    def mon(m, own):
        out = {"name": m.build.name, "species": m.build.species_id, "types": list(m.build.types), "cp": m.build.cp,
               "hp": max(m.hp, 0), "hp_max": m.build.hp, "sprite": sprite(m.build)}
        if own:
            out.update(energy=m.energy, fast={"name": m.build.fast.name, "type": m.build.fast.type},
                       charged=[{"name": c.name, "type": c.type, "energy": c.energy} for c in m.build.charged])
        return out

    return {
        "clock": round(max(0, MAX_TURNS - battle.turn) * TURN, 1),
        "winner": None if battle.winner is None else {DRAW: "draw", 0: "win", 1: "loss"}[battle.winner],
        "me": {"active": me.active, "shields": me.shields, "switch_wait": round(me.switch_wait * TURN),
               "team": [mon(m, True) for m in me.team]},
        "foe": {"active": mon(foe.mon, False), "shields": foe.shields, "left": foe.left(),
                "seen": [foe.team[j].build.name for j in foe.shown]},
        "log": [{"turn": t, "side": sd, "text": re.sub(r" -?\d+/\d+hp \d+e", "", x)} for t, sd, x in (battle.log or [])[-8:]],
    }
