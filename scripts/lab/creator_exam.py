#!/usr/bin/env python3
"""The creator exam: an engine asked at every checked decision of the creators, judged by play-outs to the end.

    python -X utf8 scripts/lab/creator_exam.py website bot "website,temperature=0.02"         [--opponent crowd|people|bot] [--games 100] [--limit 60] [--workers 2] [--asks 1] [--seed 1]

    from creator_exam import league_scores        # for scripts/lab/league.py
    league_scores(["website", "bot"], workers=2, seed=1)  # {spec: {"score", "margin", "n", "agree", "regret", ...}}

A decision-quality benchmark that is not win rate against bots (engine lab, 2026-11-24). 657 decisions from task 46's
29 creator records that pass every check (--all for every record):
- switch (157): switch or stay at each new matchup, and every switch they made (scripts/real_decisions.py);
- shield (114): shield or not at every charged move thrown at them with a shield up (real_decisions.py);
- throw (168): every charged move they threw, which move (real_decisions.py; the footage shows no energy, so it
  records no holds);
- hold (218, new here): the first look in each stretch of a matchup at which the tracker's energy ledger has them
  8+ over their cheapest move and they kept fast-moving.

Two caches, so a new engine costs only its own answers (both are committed for the crowd and people at 100 play-outs):

1. Values (once per opponent model, --games and --value-seed): at every decision, every legal first action (every
   move, every switch, shield or not) is played on to the end of the battle --games times with the same dice for
   every action. Our side is continued by the trained bot; their side by --opponent: "crowd" (the varied crowd, as
   real_decisions.py), "bot" (the trained bot) or "people" (a people-like opponent: the "human" style of
   pogo.engine, with shield calls drawn from the creators' shield network, pogo.people_shield, at its probability;
   that network was fitted on these records). Unknowns (their unseen Pokémon, their exact energy within the
   tracker's range) are drawn afresh in each play-out. runs/lab-creators/exam/values-<opponent>-g<games>-s<seed>.json;
   about 10 minutes per opponent on 2 workers at 100 play-outs.
2. Answers: each engine (a scripts/engine_versus.py spec) is asked once at every decision (--asks for engines that
   mix; their value is the mean over the asks). runs/lab-creators/exam/answers-<spec>-s<seed>.json; the website
   engine takes about 1 minute on 2 workers, the bot seconds.

Printed per decision kind and engine: agreement with the player (a switch decision compares switch-to-whom against
staying, whatever the staying move), regret against the player (the engine's action's value minus the player's, in
win-share points: positive means the engine's choice wins more often in the play-outs), the same where the two
differ, how far each falls short of the best action, and "near best": the share of decisions within --near (0.03) of
the best action (the league's score). The best is picked on the same noisy values, so "short of best" leans high for
everyone alike. Then each engine against the first one named, paired on the same decisions (the tightest margins),
and how predictable the shield calls are from a coarse description of the situation, for the player and for each
engine on the very same positions. Margins are 95% over decisions.

The judge is our own simulator continued by our own bot, which favours choices like the bot's (and like the
engine's, whose look-ahead uses the same bot): read a positive regret against the player as "no worse by our
simulator", not as better play. Comparisons between engines are fairer than comparisons with the player. Energy is
the tracker's ledger; where the player threw a move the ledger says they could not afford, the position is given
them the energy ("energy raised", 1 decision).

Fixed here and not in real_decisions.py: the rebuilt battle marks which Pokémon each side has seen. real_decisions
left both sides at the lead only (Side.shown = [0]), so in 280 of its 439 decisions the bot's inputs for their bench
and unseen count were wrong (the fix changes 32 of the bot's 439 answers, agreement 56% -> 59%), and the engine's
imagined battles cannot be built when their active Pokémon is not their lead (pogo.engine.imagine, StopIteration).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_v] = "1"

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import engine_versus as ev  # noqa: E402
from advise import rebuild  # noqa: E402
from real_decisions import Forced, decisions, lines, same_kind  # noqa: E402
from real_decisions import describe as _describe  # noqa: E402
from pogo.agents import varied  # noqa: E402
from pogo.battle import CHARGED, DRAW, FAST, SWITCH  # noqa: E402
from pogo.learner import Learner  # noqa: E402
from pogo.lab.people import PEOPLE, PeopleLike, people_player  # noqa: E402,F401

CREATORS = ROOT / "games" / "creators"
OUT = ROOT / "runs" / "lab-creators" / "exam"
_w: dict = {}


# --- the decisions -------------------------------------------------------------------------------------------------

def records(everything: bool) -> list[Path]:
    out = []
    for folder in sorted(CREATORS.glob("*/*/")):
        verdict = folder / "verdict.json"
        if not verdict.exists() or not (folder / "states.jsonl.gz").exists():
            continue
        if everything or json.loads(verdict.read_text(encoding="utf-8"))["verdict"] == "pass":
            out.append(folder)
    return out


def our_seen(folder: Path) -> dict:
    """{state time: the slots of ours that have been out by then}: what the opponent has seen of our team."""
    seen, out = set(), {}
    for s in lines(folder, "states.jsonl"):
        if s["me"]["active"] is not None:
            seen.add(s["me"]["active"])
        out[round(s["t"], 2)] = sorted(seen)
    return out


HOLD_SPARE = 8  # a hold counts when the ledger has them this much over their cheapest move's cost


def holds(folder: Path) -> list[dict]:
    """Moments the player held: the first look in each stretch of one matchup at which the tracker's ledger has
    them at least HOLD_SPARE energy over their cheapest move and they kept fast-moving (no throw, switch or faint
    on that look). The footage does not show energy, so real_decisions.py records no holds for the creators; these
    rest on the ledger (about 75% of throws land within its range, task 46), hence the margin."""
    states, looks = lines(folder, "states.jsonl"), lines(folder, "observations.jsonl")
    if len(states) != len(looks):
        return []
    events = lines(folder, "events.jsonl")
    switch_times = {round(e["t"], 2) for e in events if e["event"] in ("my_switch", "foe_switch")}
    out, armed = [], {}
    for k in range(1, len(looks)):
        prev, look, now = states[k - 1], looks[k], states[k]
        me, foe = prev["me"], prev["opponent"]
        if foe["active"] is None or me["active"] is None:
            continue
        pair = (me["active"], foe["active"])
        mine, theirs = me["pokemon"][me["active"]], foe["pokemon"][foe["active"]]
        if look.get("my_charged") is not None:
            armed[pair] = True  # a throw starts a new stretch
            continue
        if (mine["fainted"] or theirs["fainted"] or look.get("foe_charged") or round(look["t"], 2) in switch_times
                or now["me"]["active"] != me["active"] or now["opponent"]["active"] != foe["active"]):
            continue
        costs = [m["energy"] for m in mine["charged_moves"]]
        if not costs or mine["energy"] < min(costs) + HOLD_SPARE or not armed.get(pair, True):
            continue
        armed[pair] = False
        out.append({"game": folder.name, "t": look["t"], "state": prev, "mine": mine["species"],
                    "theirs": theirs["species"], "kind": "hold", "human": FAST})
    return out


def points(everything: bool = False) -> list[dict]:
    """Every checked decision, with a key that names it (game, time, kind) and what the opponent had seen of us."""
    out = []
    for folder in records(everything):
        try:
            ds = decisions(folder) + holds(folder)
        except (ValueError, KeyError) as error:
            print(f"  skipped {folder.parent.name}/{folder.name}: {error}", file=sys.stderr)
            continue
        seen = our_seen(folder)
        for d in ds:
            d["channel"] = folder.parent.name
            d["seen"] = seen.get(round(d["state"]["t"], 2), [d["state"]["me"]["active"]])
            d["key"] = f"{folder.parent.name}/{d['game']}@{d['t']:.2f}:{d['kind']}"
            out.append(d)
    keys = [d["key"] for d in out]
    if len(set(keys)) != len(keys):  # two decisions of one kind at one look: number them
        count = defaultdict(int)
        for d in out:
            count[d["key"]] += 1
            if count[d["key"]] > 1:
                d["key"] += f"#{count[d['key']]}"
    return out


def position(d: dict, rng: random.Random, me_agent, foe_agent):
    """The battle at this decision, with the seen Pokémon marked on both sides and, if the player threw a move the
    ledger says they could not afford, the energy for it."""
    battle = rebuild(_w["gd"], d["state"], _w["pool"], rng, me_agent, foe_agent)
    ours, theirs = battle.sides
    seen_theirs = len(d["state"]["opponent"]["pokemon"])
    theirs.shown = list(range(seen_theirs))
    ours.shown = list(dict.fromkeys([*d["seen"], ours.active]))
    if d["kind"] == "throw" and d["human"] in CHARGED:
        mon = ours.mon
        move = mon.build.charged[d["human"] - CHARGED[0]]
        if mon.energy < move.energy:
            mon.energy = move.energy
    return battle


def describe(d: dict, choice) -> str:
    return _describe({**d, "kind": "throw"} if d["kind"] == "hold" else d, choice)


def raised(d: dict) -> bool:
    if d["kind"] != "throw" or d["human"] not in CHARGED:
        return False
    me = d["state"]["me"]
    mon = me["pokemon"][me["active"]]
    return mon["energy"] < mon["charged_moves"][d["human"] - CHARGED[0]]["energy"]


def options(d: dict) -> list:
    if d["kind"] == "shield":
        return [True, False]
    battle = position(d, random.Random(0), None, None)
    return battle.views[0].legal()


def seed_of(key: str, seed: int) -> int:
    return int(hashlib.sha256(f"{seed}|{key}".encode()).hexdigest()[:12], 16)


# --- players ----------------------------------------------------------------------------------------------------------

def opponent(kind: str, rng: random.Random):
    if kind == "crowd":
        return varied(rng, _w["pool"])
    net = ev._state["net"]
    if kind == "bot":
        return Learner(q=net, margin=0.02, seed=rng.getrandbits(32))
    if kind == "people":
        return people_player(rng, net, _w["pool"])
    raise SystemExit(f"unknown opponent {kind!r}")


def ours(seed: int):
    return Learner(q=ev._state["net"], margin=0.02, seed=seed)


# --- workers ----------------------------------------------------------------------------------------------------------

def setup() -> None:
    ev.setup()
    _w.update(gd=ev._state["gd"], pool=ev._state["pool"])


def play_out(d: dict, first, seed: int, foe_kind: str) -> float:
    rng = random.Random(seed)
    me = ours(rng.getrandbits(32))
    foe = opponent(foe_kind, rng)
    if d["kind"] == "shield":
        battle = position(d, rng, Forced(me, action=FAST, shield=first), foe)
        thrower = battle.sides[1].mon
        names = [m.id for m in thrower.build.charged]
        k = names.index(d["move"]) if d["move"] in names else 0
        thrower.energy = max(thrower.energy, thrower.build.charged[k].energy)
        battle.sides[1].busy = 0
        battle.agents[1] = Forced(foe, action=CHARGED[k])
    else:
        battle = position(d, rng, Forced(me, action=first), foe)
    winner = battle.run()
    return 1.0 if winner == 0 else 0.5 if winner == DRAW else 0.0


def value_job(task):
    d, foe_kind, games, seed = task
    base = random.Random(seed_of(d["key"], seed))
    seeds = [base.getrandbits(32) for _ in range(games)]
    out = {}
    for first in options(d):
        out[str(first)] = sum(play_out(d, first, s, foe_kind) for s in seeds) / games
    return d["key"], out


def answer_job(task):
    d, spec, asks, seed = task
    settings = ev.parse(spec)
    choices, errors, spent = [], [], 0.0
    for a in range(asks):
        rng = random.Random(seed_of(d["key"], seed))  # the same position for every engine and every ask
        engine = ev.pilot(settings, seed_of(f"{spec}|{a}", seed) & 0xFFFFFFFF)
        battle = position(d, rng, engine, varied(random.Random(1), _w["pool"]))
        view = battle.views[0]
        start = time.process_time()
        try:
            if d["kind"] == "shield":
                choices.append(bool(engine.shield(view, d["energy"])))
            else:
                choices.append(int(engine.act(view)))
        except Exception as error:  # noqa: BLE001 - recorded and reported, never silently dropped
            errors.append(f"{type(error).__name__}: {error}")
        spent += time.process_time() - start
    return spec, d["key"], choices, errors, spent


# --- running ----------------------------------------------------------------------------------------------------------

def slug(spec: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.=+-]+", "_", spec.replace(",", "__")).replace("=", "-")[:120] or "engine"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=0, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def run(jobs: list, function, workers: int, on_result) -> None:
    from scripts.wide_teams import run_jobs
    last = time.time()
    done = 0
    for result in run_jobs(function, jobs, workers, setup, (), spawn=True):
        on_result(result, time.time() - last > 30)
        done += 1
        if time.time() - last > 30:
            last = time.time()
            print(f"    {done} of {len(jobs)}", flush=True)
    on_result(None, True)


def margin(values: list) -> tuple[float, float]:
    n = len(values)
    if n == 0:
        return float("nan"), float("nan")
    m = sum(values) / n
    if n == 1:
        return m, float("nan")
    return m, 1.96 * math.sqrt(sum((v - m) ** 2 for v in values) / (n - 1) / n)


def fmt(values: list, scale: float = 100.0, sign: bool = True) -> str:
    m, h = margin(values)
    if math.isnan(m):
        return "-"
    s = f"{scale * m:+.1f}" if sign else f"{scale * m:.1f}"
    return s + ("" if math.isnan(h) else f" ± {scale * h:.1f}") + f" ({len(values)})"


def shield_bucket(d: dict) -> tuple:
    """The coarse situation at a shield call, as scripts/lab/creator_habits.py describes it: our shields, how much of
    our health their move takes (under 30%, 30-60%, more, a knock-out), whether this is our last Pokémon, and whether
    they still have a shield."""
    from pogo.battle import damage
    battle = position(d, random.Random(seed_of(d["key"], 0)), None, None)
    me, them = battle.sides[0].mon, battle.sides[1].mon
    moves = {m.id: m for m in them.build.charged}
    move = moves.get(d["move"]) or _w["gd"].moves.get(d["move"]) or them.build.charged[0]
    hit = damage(them, move, me)
    size = "ko" if hit >= me.hp else "small" if hit < 0.3 * me.hp else "mid" if hit < 0.6 * me.hp else "big"
    return (battle.sides[0].shields, size, min(battle.sides[0].left(), 2), battle.sides[1].shields > 0)


def predictability_lines(pts: list, answers_by_spec: dict) -> list[str]:
    """How predictable the shield calls are from the coarse situation, for the player and for each engine on the very
    same positions: if an engine that is deterministic on its full state looks as 'mixed' by these buckets as the
    player, the player's apparent mixing is what the buckets leave out, not dice."""
    sys.path.insert(0, str(ROOT / "scripts" / "lab"))
    from creator_habits import predictability
    shields = [d for d in pts if d["kind"] == "shield"]
    if not shields:
        return []
    buckets = {d["key"]: shield_bucket(d) for d in shields}
    out = ["\nshield calls, predictability from the coarse situation (same positions for everyone):"]
    rows = [{"game": d["game"], "b": buckets[d["key"]], "y": bool(d["human"])} for d in shields]
    out.append(f"  player: {predictability(rows, lambda r: r['b'], lambda r: r['y'])}")
    for spec, answers in answers_by_spec.items():
        rows = [{"game": d["game"], "b": buckets[d["key"]], "y": bool(answers[d["key"]]["choices"][0])}
                for d in shields if answers.get(d["key"], {}).get("choices")]
        out.append(f"  {spec}: {predictability(rows, lambda r: r['b'], lambda r: r['y'])}")
    return out


def score(pts: list, values: dict, answers: dict, near: float = 0.03) -> list:
    """Rows of per-decision results for one engine: agreement share, regret against the player, shortfall to best."""
    rows = []
    for d in pts:
        v, got = values.get(d["key"]), answers.get(d["key"])
        if not v or not got or not got.get("choices"):
            continue
        choices = got["choices"]
        human = str(d["human"])
        if human not in v:
            continue
        valued = [c for c in choices if str(c) in v]
        if not valued:
            continue
        engine_value = sum(v[str(c)] for c in valued) / len(valued)
        agree = sum(same_kind(d, c) == same_kind(d, d["human"]) for c in choices) / len(choices)
        best = max(v.values())
        rows.append({"key": d["key"], "kind": d["kind"], "channel": d["channel"], "agree": agree,
                     "regret": engine_value - v[human], "engine_short": best - engine_value,
                     "player_short": best - v[human], "near_best": engine_value >= best - near,
                     "player_near_best": v[human] >= best - near, "stakes": best - min(v.values()), "raised": raised(d),
                     "human": describe(d, d["human"]),
                     "engine": [describe(d, c) for c in choices][:3]})
    return rows


def summarise(name: str, rows: list) -> list[str]:
    out = [f"\n{name}"]
    for kind in ("switch", "shield", "throw", "hold", "all"):
        sub = [r for r in rows if kind == "all" or r["kind"] == kind]
        if not sub:
            continue
        differ = [r for r in sub if r["agree"] < 1]
        agree = [r["agree"] for r in sub]
        out.append(f"  {kind:6} agrees {fmt(agree, sign=False)}%; regret against the player (engine − player, "
                   f"points) {fmt([r['regret'] for r in sub])}; where they differ {fmt([r['regret'] for r in differ])};"
                   f" short of the best: engine {fmt([r['engine_short'] for r in sub], sign=False)}, player "
                   f"{fmt([r['player_short'] for r in sub], sign=False)}; near best (within the --near): engine "
                   f"{fmt([float(r['near_best']) for r in sub], sign=False)}%, player "
                   f"{fmt([float(r['player_near_best']) for r in sub], sign=False)}%")
    for channel in sorted({r["channel"] for r in rows}):
        sub = [r for r in rows if r["channel"] == channel]
        out.append(f"  {channel:14} agrees {fmt([r['agree'] for r in sub], sign=False)}%; regret "
                   f"{fmt([r['regret'] for r in sub])}")
    worst = sorted(rows, key=lambda r: r["regret"])[:5]
    out.append("  the engine's costliest differences (by the play-outs):")
    for r in worst:
        if r["regret"] < 0:
            out.append(f"    {r['key']}: player {r['human']}, engine {', '.join(r['engine'])}: {100 * r['regret']:+.0f}")
    best = sorted(rows, key=lambda r: -r["regret"])[:3]
    out.append("  the engine's best differences:")
    for r in best:
        if r["regret"] > 0:
            out.append(f"    {r['key']}: player {r['human']}, engine {', '.join(r['engine'])}: {100 * r['regret']:+.0f}")
    return out


def decision_set(everything: bool = False, kinds: str = "switch,shield,throw,hold", limit: int | None = None) -> list:
    """The exam's decisions in a fixed shuffled order, so --limit takes a spread-out sample."""
    wanted = set(kinds.split(","))
    pts = [d for d in points(everything) if d["kind"] in wanted]
    random.Random(12345).shuffle(pts)
    return pts[:limit] if limit else pts


def fill_values(pts: list, opponent: str, games: int, value_seed: int, workers: int, everything: bool = False,
                quiet: bool = False) -> dict:
    vpath = OUT / f"values-{opponent}-g{games}-s{value_seed}{'-all' if everything else ''}.json"
    values = load(vpath)
    todo = [(d, opponent, games, value_seed) for d in pts if d["key"] not in values]
    if todo:
        if not quiet:
            print(f"  values: {len(todo)} decisions to play out ({games} play-outs per action, against the "
                  f"{opponent}) on {workers} workers", flush=True)

        def keep_value(result, flush):
            if result is not None:
                values[result[0]] = result[1]
            if flush:
                save(vpath, values)
        run(todo, value_job, workers, keep_value)
    return values


def ask(spec: str, pts: list, asks: int, seed: int, workers: int, everything: bool = False,
        quiet: bool = False) -> dict:
    apath = OUT / f"answers-{slug(spec)}-s{seed}{'-all' if everything else ''}.json"
    answers = load(apath)
    for k in [k for k, a in answers.items() if a.get("asks", 0) < asks]:
        del answers[k]
    todo = [(d, spec, asks, seed) for d in pts if d["key"] not in answers]
    if todo:
        if not quiet:
            print(f"  {spec}: asking at {len(todo)} decisions on {workers} workers", flush=True)

        def keep_answer(result, flush):
            if result is not None:
                _, key, choices, errors, spent = result
                answers[key] = {"choices": choices, "errors": errors, "seconds": round(spent, 3), "asks": asks}
            if flush:
                save(apath, answers)
        run(todo, answer_job, workers, keep_answer)
    return answers


def league_scores(specs: list, workers: int = 2, seed: int = 1, opponent: str = "crowd", games: int = 100,
                  value_seed: int = 1, near: float = 0.03, limit: int | None = None, asks: int = 1) -> dict:
    """For scripts/lab/league.py: {spec: {"score", "margin", "n", ...}}. The score is the share of the creators'
    checked decisions at which the engine's action is within `near` (win share) of the best action by the play-outs
    to the end against `opponent`, with its 95% half-width over decisions. Also given: "agree" (share agreeing with
    the player) and "regret" (engine's value minus the player's, as a share), each with a margin. The value cache is
    computed once (about 10 minutes on 2 workers for 439 decisions at 100 play-outs; the crowd's is committed); each
    new engine costs only its answers (a minute or two for the website engine on 2 workers)."""
    for spec in specs:
        ev.parse(spec)
    if not _w:
        setup()
    pts = decision_set(limit=limit)
    values = fill_values(pts, opponent, games, value_seed, workers, quiet=True)
    out = {}
    for spec in specs:
        rows = score(pts, values, ask(spec, pts, asks, seed, workers, quiet=True), near)
        ok, oh = margin([float(r["near_best"]) for r in rows])
        am, ah = margin([r["agree"] for r in rows])
        rm, rh = margin([r["regret"] for r in rows])
        out[spec] = {"score": ok, "margin": oh, "n": len(rows), "agree": am, "agree_margin": ah,
                     "regret": rm, "regret_margin": rh, "opponent": opponent, "games": games}
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("engines", nargs="*", default=["website", "bot"], help="engine_versus.py specs")
    parser.add_argument("--opponent", choices=("crowd", "bot", "people"), default="crowd")
    parser.add_argument("--games", type=int, default=100, help="play-outs per action at each decision")
    parser.add_argument("--limit", type=int, help="only this many decisions (a fixed, shuffled, spread-out sample)")
    parser.add_argument("--kinds", default="switch,shield,throw,hold")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--asks", type=int, default=1, help="times each engine is asked at each decision (mixing)")
    parser.add_argument("--seed", type=int, default=1, help="the engines' dice")
    parser.add_argument("--value-seed", type=int, default=1, help="the play-outs' dice (the value cache)")
    parser.add_argument("--near", type=float, default=0.03, help="'near best': within this win share of the best")
    parser.add_argument("--all", action="store_true", help="every creator record, not only those that pass")
    parser.add_argument("--values-only", action="store_true", help="fill the value cache and stop")
    parser.add_argument("--save", help="write the per-decision rows of every engine to this JSON file")
    args = parser.parse_args()
    for spec in args.engines:
        ev.parse(spec)  # fail early on a mistyped setting
    t0 = time.time()
    setup()
    pts = decision_set(args.all, args.kinds, args.limit)
    by_kind = defaultdict(int)
    for d in pts:
        by_kind[d["kind"]] += 1
    print(f"{len(pts)} decisions ({dict(by_kind)}) from {len({d['game'] for d in pts})} records; "
          f"{sum(raised(d) for d in pts)} throws given the energy the ledger lacked", flush=True)
    values = fill_values(pts, args.opponent, args.games, args.value_seed, args.workers, args.all)
    print(f"  values ready ({time.time() - t0:.0f} s)", flush=True)
    if args.values_only:
        return

    everything, all_answers = {}, {}
    for spec in args.engines:
        t1 = time.time()
        answers = ask(spec, pts, args.asks, args.seed, args.workers, args.all)
        errors = [(k, a["errors"]) for k, a in answers.items() if a.get("errors")]
        if errors:
            print(f"  {spec}: {len(errors)} decisions raised errors, e.g. {errors[0]}")
        keys = {d["key"] for d in pts}
        secs = [a["seconds"] / max(1, a["asks"]) for k, a in answers.items() if k in keys]
        rows = score(pts, values, answers, args.near)
        everything[spec] = rows
        all_answers[spec] = answers
        timing = (f"{time.time() - t1:.0f} s; mean {1000 * sum(secs) / max(1, len(secs)):.0f} ms, worst "
                  f"{1000 * max(secs, default=0):.0f} ms per answer")
        for line in summarise(f"{spec}  ({timing})", rows):
            print(line)
    base = args.engines[0]
    for other in args.engines[1:]:  # paired: same decisions, same values
        ra = {r["key"]: r for r in everything[other]}
        rb = {r["key"]: r for r in everything[base]}
        both = sorted(set(ra) & set(rb))
        print(f"\n{other} against {base}, the same {len(both)} decisions:")
        for kind in ("switch", "shield", "throw", "hold", "all"):
            ks = [k for k in both if kind == "all" or ra[k]["kind"] == kind]
            if ks:
                print(f"  {kind:6} value difference {fmt([ra[k]['regret'] - rb[k]['regret'] for k in ks])} points; "
                      f"near best {fmt([float(ra[k]['near_best']) - float(rb[k]['near_best']) for k in ks])} "
                      f"points; they choose alike "
                      f"{fmt([float(ra[k]['engine'][0] == rb[k]['engine'][0]) for k in ks], sign=False)}%")
    for line in predictability_lines(pts, all_answers):
        print(line)
    print(f"\nopponent in the play-outs: {args.opponent}; {args.games} play-outs per action; value seed "
          f"{args.value_seed}; engine seed {args.seed}; {time.time() - t0:.0f} s in all")
    if args.save:
        save(Path(args.save), {"opponent": args.opponent, "games": args.games, "seed": args.seed,
                               "value_seed": args.value_seed, "limit": args.limit, "rows": everything})


if __name__ == "__main__":
    main()
