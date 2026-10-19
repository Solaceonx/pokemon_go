#!/usr/bin/env python3
"""Go back through the bot's lost battles and find the decisions that lost them.

    python3 scripts/losses.py [--battles 400] [--workers 3] [--screen 4] [--confirm 16] [--seed 3]

The bot plays itself (an opponent exactly as good as it is) on teams drawn half from the good-team list and
half at random. For every battle side 0 loses, each of its decisions is tried again: every other legal
choice at that moment (fast move, either charged move, a switch to either bench Pokémon; shield or not;
whom to send in after a faint), with the bot playing on after it against a different variation of itself in
each play-out. `--screen` play-outs per
choice find candidates; any choice that looks at least 0.3 better is played `--confirm` more times on
fresh dice, and only those numbers are kept. A decision "lost the battle" when its best alternative wins
at least half the time where ours won under a quarter of the time.

Writes one line per confirmed swing to runs/losses/swings.jsonl and prints:
  how many losses one different decision would have won,
  which kinds of decision those were, the earliest one in each battle by kind and situation,
  and a few concrete examples to judge by eye.
"""
from __future__ import annotations

import argparse
import collections
import json
import multiprocessing
import os
import random
import sys
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_v] = "1"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pogo.agents import duel, varied_settings  # noqa: E402
from pogo.arena import low_priority  # noqa: E402
from pogo.battle import CHARGED, DRAW, FAST, SWITCH, Battle  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.learner import Learner, QNet  # noqa: E402
from pogo.teamlist import drawer  # noqa: E402

MODEL = ROOT / "runs" / "general-decide" / "q.npz"
OUT = ROOT / "runs" / "losses"
_state: dict = {}


class Recorder:
    """Plays as `inner` and notes, for the current step, each decision it makes and the choices it had."""

    def __init__(self, inner):
        self.inner, self.calls = inner, []
        self.sees_move = getattr(inner, "sees_move", False)
        for hook in ("saw_throw", "saw_shield"):
            if hasattr(inner, hook):
                setattr(self, hook, getattr(inner, hook))

    def act(self, view):
        choice = self.inner.act(view)
        self.calls.append(("act", choice, view.legal()))
        return choice

    def shield(self, view, energy, *move):
        choice = bool(self.inner.shield(view, energy, *move))
        self.calls.append(("shield", choice, [True, False]))
        return choice

    def replace(self, view):
        choice = self.inner.replace(view)
        self.calls.append(("replace", choice, list(view.me.bench())))
        return choice


class Forced:
    """Plays as `inner`, except that its first decision of one kind comes out as `choice`. The inner player
    still makes its own pick then, so its bookkeeping goes on as usual; after the forced decision the dice of
    the battle and of both players are reseeded, so repeated play-outs differ from there on."""

    def __init__(self, inner, kind, choice, reseed):
        self.inner, self.kind, self.choice, self.reseed = inner, kind, choice, reseed
        self.pending = True
        self.sees_move = getattr(inner, "sees_move", False)
        for hook in ("saw_throw", "saw_shield"):
            if hasattr(inner, hook):
                setattr(self, hook, getattr(inner, hook))

    def _maybe(self, kind, own):
        if self.pending and kind == self.kind:
            self.pending = False
            self.reseed()
            return self.choice
        return own

    def act(self, view):
        return self._maybe("act", self.inner.act(view))

    def shield(self, view, energy, *move):
        return self._maybe("shield", bool(self.inner.shield(view, energy, *move)))

    def replace(self, view):
        return self._maybe("replace", self.inner.replace(view))


def bot(seed):
    return Learner(q=_state["net"], margin=0.02, seed=seed)


def setup() -> None:
    low_priority()
    gd = GameData()
    pool = gd.meta(50)
    _state.update(gd=gd, pool=pool, draw=drawer(gd, pool), net=QNet.load(str(MODEL)))


def win_chance(snap, kind, choice, plays, seed, vary: bool = True, side: int = 0) -> float:
    """Our win chance if this decision comes out as `choice` and the bot plays on. Right after the decision the
    opponent becomes a variation of the bot (its habits shifted as in the training crowd, as good on average),
    different in each play-out, so a choice counts only if it is better against many equally good players.
    With vary=False nothing is reseeded or replaced, so replaying the choice actually made repeats the battle.
    `side` is the side being analysed (1 for the bot in a game saved by scripts/play.py)."""
    battle, mine, theirs = snap
    points = 0.0
    for k in range(plays):
        r = random.Random(seed * 7919 + k)
        twin_holder = {}

        def reseed():
            if not vary:
                return
            twin = twin_holder["b"]
            twin.rng.seed(r.getrandbits(32))
            if hasattr(forced.inner, "rng"):
                forced.inner.rng.seed(r.getrandbits(32))
            foe = 1 - side
            old = twin.agents[foe]
            new = Learner(q=_state["net"], margin=r.choice((0.02, 0.05, 0.1)),
                          **varied_settings(r, _state["pool"]))
            # What it has seen of us; a person replayed from a saved game has no such record.
            new._shield_seen = list(getattr(old, "_shield_seen", new._shield_seen))
            new._bait_seen = list(getattr(old, "_bait_seen", new._bait_seen))
            twin.agents[foe] = new
            twin._saw_throw[foe], twin._saw_shield[foe] = getattr(new, "saw_throw", None), getattr(new, "saw_shield", None)
            twin._sees_move[foe] = getattr(new, "sees_move", False)

        forced = Forced(mine.clone(), kind, choice, reseed)
        twin = battle.clone(*((forced, theirs.clone()) if side == 0 else (theirs.clone(), forced)))
        twin_holder["b"] = twin
        winner = twin.run()
        points += 1.0 if winner == side else 0.5 if winner == DRAW else 0.0
    return points / plays


def label(view, kind, choice) -> str:
    me = view.me
    if kind == "shield":
        return "shield" if choice else "no shield"
    if kind == "replace":
        return f"send in {me.team[choice].build.name}"
    if choice == FAST:
        return "fast move"
    if choice in CHARGED:
        moves = me.mon.build.charged
        k = choice - CHARGED[0]
        cheap = len(moves) < 2 or moves[k].energy <= moves[1 - k].energy
        return f"throw {moves[k].name} ({'cheaper' if cheap else 'dearer'})"
    return f"switch to {me.team[choice - SWITCH[0]].build.name}"


def kind_of(kind, choice) -> str:
    if kind != "act":
        return kind
    return "fast" if choice == FAST else "throw" if choice in CHARGED else "switch"


def situation(view) -> dict:
    me, mon, foe = view.me, view.me.mon, view.foe
    cheapest = min((m.energy for m in mon.build.charged), default=999)
    foe_cheapest = min((m.energy for m in foe.build.charged), default=999)
    return {
        "turn": view.turn, "left": [me.left(), view.foe_left], "shields": [me.shields, view.foe_shields],
        "hp": [round(mon.hp / mon.build.hp, 2), round(foe.hp / foe.build.hp, 2)],
        "energy": [mon.energy, foe.energy], "mine_ready": mon.energy >= cheapest, "theirs_ready": foe.energy >= foe_cheapest,
        "switch_wait": [me.switch_wait, view.foe_switch_wait],
        "matchup": round(duel(mon, foe, me.shields, view.foe_shields), 2),
        "mon": mon.build.name, "foe": foe.build.name,
    }


def record(seed):
    """Play one battle of the bot against itself; return it and, for each step in which side 0 decided
    something, a snapshot from just before that step and the decisions it made (kind, choice, options)."""
    s = _state
    rng = random.Random(seed)
    teams = [s["draw"](rng), s["draw"](rng)]
    me, them = Recorder(bot(rng.getrandbits(30))), bot(rng.getrandbits(30))
    battle = Battle(teams[0], teams[1], me, them, seed=rng.getrandbits(32))
    steps = []
    while battle.winner is None:
        snap = (battle.clone(None, None), me.inner.clone(), them.clone())
        me.calls = []
        battle.step()
        if me.calls:
            steps.append((snap, list(me.calls)))
    return battle, steps


class Replay:
    """The person's side of a game saved by scripts/play.py, choice by choice; fast moves otherwise."""

    def __init__(self, choices):
        self.acts, self.shields, self.replaces = {}, {}, {}
        for turn, _, what in choices:
            if isinstance(what, str):
                kind, value = what.split(":")
                if kind == "shield":
                    self.shields[turn] = value == "True"
                else:
                    self.replaces[turn] = int(value)
            else:
                self.acts[turn] = what

    def act(self, view):
        action = self.acts.get(view.turn)
        return action if action is not None and action in view.legal() else FAST

    def shield(self, view, energy, *move):
        return view.me.shields > 0 and self.shields.get(view.turn, False)

    def replace(self, view):
        bench, slot = view.me.bench(), self.replaces.get(view.turn)
        return slot if slot in bench else bench[0]

    def clone(self):
        return self


def replay(path):
    """A game saved by scripts/play.py, played again from its seeds with the bot (side 1) recorded as in record().
    Returns the battle, the steps, the saved record and whether the replay repeated the saved log exactly."""
    from pogo.agents import Planner
    from pogo.engine import Engine
    from pogo.evaluation import Evaluator
    s, saved = _state, json.loads(Path(path).read_text())
    gd = s["gd"]
    teams = [[gd.build(sid, moves, level=level, ivs=tuple(ivs)) for sid, moves, level, ivs in side] for side in saved["teams"]]
    seed = saved["bot_seed"]
    if saved["bot"] == "engine":
        ev = Evaluator.load(ROOT / "runs" / "eval" / "eval.npz")
        inner = Engine(ev, s["pool"], rollout="bot", samples=4, edge=0.03, q=s["net"], margin=0.02, seed=seed)
    elif saved["bot"] == "learner":
        inner = bot(seed)
    else:
        inner = Planner(seed=seed)
    me = Recorder(inner)
    battle = Battle(teams[0], teams[1], Replay(saved["my_choices"]), me, seed=saved["seed"], record=True)
    steps = []
    while battle.winner is None:
        snap = (battle.clone(None, None), me.inner.clone(), battle.agents[0])
        me.calls = []
        battle.step()
        if me.calls:
            steps.append((snap, list(me.calls)))
    same = [list(entry) for entry in battle.log] == saved["log"]
    return battle, steps, saved, same


def swings(battle, steps, side, seed, screen, confirm, result) -> dict:
    """Try every other choice at each of `side`'s decisions; keep those that look at least 0.3 better."""
    for index, (snap, calls) in enumerate(steps):
        seen = set()
        for kind, chosen, options in calls:
            if kind in seen or len(options) < 2:
                continue
            seen.add(kind)
            result["decisions"] += 1
            base_seed = seed * 100003 + index * 31 + len(seen)
            ours = win_chance(snap, kind, chosen, screen, base_seed, side=side)
            scored = [(win_chance(snap, kind, o, screen, base_seed, side=side), o) for o in options if o != chosen]
            best, alt = max(scored)
            if best - ours < 0.3:
                continue
            ours = win_chance(snap, kind, chosen, confirm, base_seed + 17, side=side)
            best = win_chance(snap, kind, alt, confirm, base_seed + 17, side=side)
            view = snap[0].views[side]
            result["swings"].append({
                "step": index, "kind": kind_of(kind, chosen), "better_kind": kind_of(kind, alt),
                "chosen": label(view, kind, chosen), "better": label(view, kind, alt),
                "ours": round(ours, 3), "theirs": round(best, 3), "situation": situation(view)})
    return result


def analyse(job):
    number, seed, screen, confirm = job
    battle, steps = record(seed)
    result = {"battle": number, "won": battle.winner == 0, "draw": battle.winner == DRAW,
              "mine": [m.build.species_id for m in battle.sides[0].team],
              "theirs": [m.build.species_id for m in battle.sides[1].team], "decisions": 0, "swings": []}
    if battle.winner != 1:
        return result
    return swings(battle, steps, 0, seed, screen, confirm, result)


def analyse_played(job):
    """One game against a person: if the bot lost, its decisions tried every other way."""
    path, screen, confirm = job
    battle, steps, saved, same = replay(path)
    result = {"battle": Path(path).stem, "bot": saved["bot"], "won": battle.winner == 1, "draw": battle.winner == DRAW,
              "replayed": same, "mine": [m.build.species_id for m in battle.sides[1].team],
              "theirs": [m.build.species_id for m in battle.sides[0].team], "decisions": 0, "swings": []}
    if battle.winner != 0 or not same:
        return result
    return swings(battle, steps, 1, saved["seed"] % 100003, screen, confirm, result)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--battles", type=int, default=400)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--screen", type=int, default=8)
    parser.add_argument("--confirm", type=int, default=24)
    parser.add_argument("--seed", type=int, default=3)
    parser.add_argument("--played", nargs="*", metavar="GAME",
                        help="games against a person saved by scripts/play.py (default: all of games/played/) instead of the bot against itself")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.played is not None:
        return played(args)
    jobs = [(n, args.seed * 1_000_003 + n, args.screen, args.confirm) for n in range(args.battles)]
    results = []
    with multiprocessing.get_context("spawn").Pool(args.workers, initializer=setup) as workers:
        for r in workers.imap_unordered(analyse, jobs, chunksize=2):
            results.append(r)
            if len(results) % 50 == 0:
                print(f"  {len(results)} battles done", flush=True)
    results.sort(key=lambda r: r["battle"])
    with (OUT / "swings.jsonl").open("w") as out:
        for r in results:
            out.write(json.dumps(r) + "\n")

    losses = [r for r in results if not r["won"] and not r["draw"]]
    decisive = lambda w: w["theirs"] >= 0.5 and w["ours"] < 0.25  # noqa: E731
    lost_by = [r for r in losses if any(decisive(w) for w in r["swings"])]
    print(f"\n{len(results)} battles of the bot against itself; side 0 lost {len(losses)}; "
          f"{sum(r['decisions'] for r in losses)} of its decisions in those tried every other way")
    print(f"losses that one different decision would have won (it then wins at least half the time, where ours won "
          f"under a quarter): {len(lost_by)} of {len(losses)} ({100 * len(lost_by) / max(1, len(losses)):.0f}%)")
    every = [w for r in losses for w in r["swings"] if decisive(w)]
    print(f"such decisions in all: {len(every)}, {len(every) / max(1, len(lost_by)):.1f} per battle that had one")

    def table(rows, title):
        print(f"\n{title}")
        count = collections.Counter(f"{w['kind']} -> {w['better_kind']}" for w in rows)
        for key, n in count.most_common():
            print(f"  {key:24s} {n:4d}  ({100 * n / len(rows):.0f}%)")

    if every:
        table(every, "every battle-losing decision, by what we did -> what would have won")
        first = [min((w for w in r["swings"] if decisive(w)), key=lambda w: w["step"]) for r in lost_by]
        table(first, "the earliest battle-losing decision in each battle")

        def share(rows, test):
            return f"{100 * sum(1 for w in rows if test(w['situation'])) / len(rows):.0f}%"

        print("\nsituations at the earliest battle-losing decision (share of those decisions)")
        tests = {
            "we were losing the matchup": lambda x: x["matchup"] < 0,
            "they had a charged move ready": lambda x: x["theirs_ready"],
            "we had a charged move ready": lambda x: x["mine_ready"],
            "both sides still had all three": lambda x: x["left"] == [3, 3],
            "last Pokémon each (1 v 1)": lambda x: x["left"] == [1, 1],
            "we had more shields": lambda x: x["shields"][0] > x["shields"][1],
            "we had fewer shields": lambda x: x["shields"][0] < x["shields"][1],
            "our switch was free": lambda x: x["switch_wait"][0] == 0,
            "their switch was locked": lambda x: x["switch_wait"][1] > 0,
            "in the first minute": lambda x: x["turn"] < 120,
        }
        for kind in sorted({w["kind"] + " -> " + w["better_kind"] for w in first}):
            rows = [w for w in first if w["kind"] + " -> " + w["better_kind"] == kind]
            if len(rows) < 5:
                continue
            print(f"  {kind} ({len(rows)}): " + "; ".join(f"{name} {share(rows, t)}" for name, t in tests.items()))
        print("  all of them for comparison: " + "; ".join(f"{name} {share(first, t)}" for name, t in tests.items()))

        print("\nexamples (the earliest battle-losing decision of the first ten such battles)")
        for r, w in list(zip(lost_by, first))[:10]:
            x = w["situation"]
            print(f"  {' / '.join(r['mine'])} v {' / '.join(r['theirs'])}, turn {x['turn']}: {x['mon']} ({100 * x['hp'][0]:.0f}% health, "
                  f"{x['energy'][0]} energy) v {x['foe']} ({100 * x['hp'][1]:.0f}%, {x['energy'][1]}), shields {x['shields'][0]}-{x['shields'][1]}, "
                  f"left {x['left'][0]}-{x['left'][1]}: we chose {w['chosen']} ({100 * w['ours']:.0f}%), "
                  f"{w['better']} wins {100 * w['theirs']:.0f}%")
    print(f"\nrows: {(OUT / 'swings.jsonl').relative_to(ROOT)}")


def played(args) -> None:
    """The bot's losses in games against a person: which of its decisions would have turned them, in plain words."""
    paths = args.played or sorted(str(p) for p in (ROOT / "games" / "played").glob("*.json"))
    usable = [p for p in paths if "seed" in json.loads(Path(p).read_text())]
    print(f"{len(paths)} saved games, {len(usable)} with seeds to replay (games saved before 17 October have none)")
    with multiprocessing.get_context("spawn").Pool(max(1, min(args.workers, len(usable))), initializer=setup) as workers:
        results = list(workers.imap_unordered(analyse_played, [(p, args.screen, args.confirm) for p in usable]))
    results.sort(key=lambda r: r["battle"])
    with (OUT / "played.jsonl").open("w") as out:
        for r in results:
            out.write(json.dumps(r) + "\n")
    lost = [r for r in results if not r["won"] and not r["draw"]]
    broken = [r["battle"] for r in results if not r["replayed"]]
    print(f"the bot won {sum(r['won'] for r in results)}, lost {len(lost)}, drew {sum(r['draw'] for r in results)}"
          + (f"; could not replay exactly, so left out: {', '.join(broken)}" if broken else ""))
    decisive = lambda w: w["theirs"] >= 0.5 and w["ours"] < 0.25  # noqa: E731
    kinds = collections.Counter()
    for r in lost:
        if not r["replayed"]:
            continue
        found = [w for w in r["swings"] if decisive(w)]
        print(f"\n{r['battle']} ({r['bot']}): the bot's {' / '.join(r['mine'])} lost to {' / '.join(r['theirs'])}; "
              f"{r['decisions']} decisions tried, {len(found)} that would have won")
        for w in found:
            x = w["situation"]
            kinds[f"{w['kind']} -> {w['better_kind']}"] += 1
            print(f"  turn {x['turn']}: {x['mon']} ({100 * x['hp'][0]:.0f}%, {x['energy'][0]} energy) v {x['foe']} "
                  f"({100 * x['hp'][1]:.0f}%, {x['energy'][1]}), shields {x['shields'][0]}-{x['shields'][1]}, left "
                  f"{x['left'][0]}-{x['left'][1]}: chose {w['chosen']} ({100 * w['ours']:.0f}%), {w['better']} wins {100 * w['theirs']:.0f}%")
    if kinds:
        print("\nall of them, by what the bot did -> what would have won: "
              + ", ".join(f"{k} {n}" for k, n in kinds.most_common()))
    print("\nAfter a changed decision the person is played by variations of the bot, so 'would have won' means against"
          "\nplayers like the bot from there on. Hindsight flatters losses (task 26): judge the examples, and count a"
          "\npattern only if it repeats across games.")


if __name__ == "__main__":
    main()
