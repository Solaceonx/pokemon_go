"""Review a finished game against the bot, chess.com-style: the person's decisions that cost the most (the owner:
"highlight my mistakes, at least obvious ones, like in the chess.com engine").

The game is replayed exactly from its record: the person's choices as they were made, the bot's moves as they were
logged (any version of the bot replays this way). The decisions looked at: every charged move the person threw (or
a fast move instead, or the other move), every switch and replacement (or another, or staying), every shield call
(or the opposite), and every turn the person had a knock-out ready and did not throw it. For each, the chance of
winning after each choice is played out: the choice forced, then both sides played by the trained bot (theirs with
shifted habits, a different one each time), the same dice for every choice of a decision. A first look with a few
play-outs, a closer one for those that look costly. The drop from the best choice to the person's is the cost:

    blunder 25 points or more, mistake 15, inaccuracy 8 (the play-outs are noisy, so smaller ones are not called)

It is "against players like the bot from there on", so a judgement, not a proof. For a lost game, `winning_line`
finds a play-out that wins from the most promising different choice: one way the game could have been won.
"""
from __future__ import annotations

import random

from .agents import varied_settings
from .battle import CHARGED, DRAW, FAST, SWITCH, Battle, damage
from .learner import Learner

LABELS = ((0.25, "blunder"), (0.15, "mistake"), (0.08, "inaccuracy"))


class Replay:
    """The person's side, choice by choice as recorded; fast moves otherwise."""
    scripted = True

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


class Logged:
    """The bot's side from the game's log: its throws, switches and replacements when they happened, its shields
    where the person's throws were shielded, fast moves otherwise."""
    scripted = True

    def __init__(self, log):
        self.acts, self.shields, self.replaces = {}, {}, {}
        fainted = set()
        for turn, side, text in log:
            if side == 1 and text.endswith("faints"):
                fainted.add(turn)
            elif side == 1 and text.startswith("sends in "):
                name = text[len("sends in "):].rsplit(" ", 2)[0]
                (self.replaces if turn in fainted else self.acts)[turn] = ("switch", name)
            elif side == 1 and " throws " in text:
                self.acts[turn] = ("throw", text.split(" throws ", 1)[1].split(":")[0])
            elif side == 0 and " throws " in text:
                self.shields[turn] = text.endswith(": shielded")

    def act(self, view):
        what = self.acts.get(view.turn)
        if what is None:
            return FAST
        kind, name = what
        if kind == "throw":
            moves = [m.name for m in view.me.mon.build.charged]
            action = CHARGED[moves.index(name)] if name in moves else FAST
        else:
            slot = next((j for j, m in enumerate(view.me.team) if m.build.name == name), None)
            action = SWITCH[slot] if slot is not None else FAST
        return action if action in view.legal() else FAST

    def shield(self, view, energy, *move):
        return view.me.shields > 0 and self.shields.get(view.turn, False)

    def replace(self, view):
        bench, name = view.me.bench(), self.replaces.get(view.turn, ("", ""))[1]
        slot = next((j for j in bench if view.me.team[j].build.name == name), None)
        return slot if slot is not None else bench[0]

    def clone(self):
        return self


class _Watch:
    """Plays as `inner` and notes the person's decisions worth reviewing, with the position just before the step."""

    def __init__(self, inner):
        self.inner, self.calls, self.matchup = inner, [], None
        self.sees_move = False

    def act(self, view):
        action = self.inner.act(view)
        mon, foe = view.me.mon, view.foe
        legal = view.legal()
        ready = [CHARGED[k] for k, m in enumerate(mon.build.charged) if mon.energy >= m.energy and CHARGED[k] in legal]
        new = (view.me.active, id(foe)) != self.matchup  # a new matchup: stay in or switch?
        self.matchup = (view.me.active, id(foe))
        switches = [a for a in legal if a in SWITCH]
        if new and switches and action not in CHARGED:
            self.calls.append(("act", action, sorted({FAST, *switches, action})))
        elif action in CHARGED or action in SWITCH:
            options = [FAST, *ready, *(a for a in legal if a in SWITCH and a == action)]
            self.calls.append(("act", action, sorted(set(options) | {action})))
        elif ready and view.foe_shields == 0 and any(damage(mon, mon.build.charged[CHARGED.index(a)], foe) >= foe.hp for a in ready):
            self.calls.append(("act", action, [FAST, *ready]))  # a knock-out was ready and not thrown
        return action

    def shield(self, view, energy, *move):
        choice = bool(self.inner.shield(view, energy, *move))
        if view.me.shields > 0:
            self.calls.append(("shield", choice, [True, False]))
        return choice

    def replace(self, view):
        choice = self.inner.replace(view)
        if len(view.me.bench()) > 1:
            self.calls.append(("replace", choice, list(view.me.bench())))
        return choice


class _Forced:
    """The person's side in a play-out: as recorded until the decision under review, which comes out as `choice`;
    then `on_decide()` hands both sides to the trained bot (a person replayed from a record cannot be asked what they
    would do next) and returns the bot that plays on for the person."""

    def __init__(self, person, kind, choice, on_decide):
        self.inner, self.kind, self.choice, self.on_decide, self.pending = person, kind, choice, on_decide, True
        self.sees_move = False

    def _now(self):
        self.pending = False
        self.inner = self.on_decide()
        return self.choice

    def act(self, view):
        if self.pending and self.kind == "act":
            return self._now()
        return self.inner.act(view)

    def shield(self, view, energy, *move):
        if self.pending and self.kind == "shield":
            return self._now()
        return bool(self.inner.shield(view, energy, *move))

    def replace(self, view):
        if self.pending and self.kind == "replace":
            return self._now()
        return self.inner.replace(view)


def decisions(record: dict, gd, limit: int = 30) -> dict:
    """The person's decisions worth reviewing, in order: {"person", "bot", "items": [(snapshot, turn, kind, choice,
    options)]}; no items if the record does not replay exactly."""
    teams = [[gd.build(sid, mv, level=level, ivs=tuple(ivs)) for sid, mv, level, ivs in t] for t in record["teams"]]
    person, bot = Replay(record["my_choices"]), Logged(record["log"])
    watch = _Watch(person)
    battle = Battle(teams[0], teams[1], watch, bot, seed=record["seed"], record=True)
    items = []
    while battle.winner is None:
        snap = battle.clone(None, None)
        watch.calls = []
        battle.step()
        for kind, choice, options in watch.calls[:1]:  # the first decision of the step: the one a snapshot can replay
            if len(options) > 1:
                items.append((snap, snap.turn, kind, choice, options))
    same = [list(e) for e in battle.log] == [list(e) for e in record["log"]]
    if len(items) > limit:  # keep the throws, shields and switches; drop the plainer fast-move moments first
        items = sorted(items, key=lambda d: (d[2] == "act" and d[3] == FAST, d[1]))[:limit]
        items.sort(key=lambda d: d[1])
    return {"person": person, "bot": bot, "items": items if same else []}


def _play_out(game: dict, snap, kind, choice, r: random.Random, net, pool, log: bool = False):
    """One play-out from the snapshot with this decision forced, then the bot on both sides; the battle after it."""
    holder = {}

    def on_decide():
        twin = holder["battle"]
        foe = Learner(q=net, margin=r.choice((0.02, 0.05, 0.1)), **varied_settings(r, pool))
        twin.agents[1] = foe
        twin._saw_throw[1], twin._saw_shield[1], twin._sees_move[1] = foe.saw_throw, foe.saw_shield, False
        twin.rng.seed(r.getrandbits(32))
        return Learner(q=net, margin=0.02, seed=r.getrandbits(30))

    twin = snap.clone(_Forced(game["person"], kind, choice, on_decide), game["bot"])
    if log:
        twin.log = []
    holder["battle"] = twin
    twin.run()
    return twin


def chance(game: dict, snap, kind, choice, plays: int, seed: int, net, pool) -> float:
    """The person's chance of winning if this decision comes out as `choice`, the bot playing on for both sides
    (theirs with shifted habits, a different one in each play-out; the same ones for every choice)."""
    points = 0.0
    for k in range(plays):
        winner = _play_out(game, snap, kind, choice, random.Random(seed * 7919 + k), net, pool).winner
        points += 1.0 if winner == 0 else 0.5 if winner == DRAW else 0.0
    return points / plays


def winning_line(game: dict, decision, option, net, pool, seed: int, tries: int = 16):
    """A play-out in which the person, choosing `option` at this decision, goes on to win: its log from the decision
    on ([turn, side, text]), or None if none of `tries` play-outs is won."""
    snap = decision[0]
    for k in range(tries):
        twin = _play_out(game, snap, decision[2], option, random.Random(seed * 104729 + k), net, pool, log=True)
        if twin.winner == 0:
            return [[t, side, text] for t, side, text in twin.log]
    return None


def describe(snap, kind, choice) -> str:
    view = snap.views[0]
    me = view.me
    if kind == "shield":
        return "shield" if choice else "no shield"
    if kind == "replace":
        return f"send in {me.team[choice].build.name}"
    if choice == FAST:
        return "fast move"
    if choice in CHARGED:
        return f"throw {me.mon.build.charged[CHARGED.index(choice)].name}"
    return f"switch to {me.team[choice - SWITCH[0]].build.name}"


def judge(game: dict, decision, net, pool, seed: int, screen: int = 4, confirm: int = 12) -> dict:
    """One decision: the person's choice and the best one, with their chances, and a label when it cost enough."""
    snap, turn, kind, choice, options = decision
    first = {o: chance(game, snap, kind, o, screen, seed, net, pool) for o in options}
    best = max(first, key=first.get)
    if best == choice or first[best] - first[choice] < 0.08:
        mine, top = first[choice], first[best]
    else:
        mine = chance(game, snap, kind, choice, confirm, seed + 1, net, pool)
        top = chance(game, snap, kind, best, confirm, seed + 1, net, pool)
    cost = max(0.0, top - mine) if best != choice else 0.0
    label = next((name for limit, name in LABELS if cost >= limit), None)
    view = snap.views[0]
    return {"turn": turn, "kind": kind, "did": _past(describe(snap, kind, choice)), "better": describe(snap, kind, best),
            "option": best,
            "mine": round(mine, 3), "best": round(top, 3), "cost": round(cost, 3), "label": label,
            "mon": view.me.mon.build.name, "foe": view.foe.build.name}


def _past(text: str) -> str:
    """What the person did, in words: "fast move" -> "kept fast-moving", "throw X" -> "threw X", and so on."""
    for now, then in (("fast move", "kept fast-moving"), ("no shield", "didn't shield"), ("shield", "shielded"),
                      ("throw ", "threw "), ("switch to ", "switched to "), ("send in ", "sent in ")):
        if text.startswith(now):
            return then + text[len(now):]
    return text
