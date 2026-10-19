"""An opening book: a prepared first plan for each opposing lead (the owner's idea).

A plan says what to do in the lead matchup before the bot plays on as usual:

- {"swap": None}: stay in; the bot decides everything as it always does;
- {"swap": slot, "after_fast": n}: stay for n fast moves (0: at once), then switch to that team slot;
- {"swap": slot, "after_charged": True}: stay until our first charged move is thrown (to draw a shield), then switch.

Until the plan's switch the bot may not switch; after it (or if the plan cannot be carried out: the slot fainted, the
switch is locked, the lead fainted) the bot is in charge again. `Booked` wraps any player with a book
{opposing lead species: plan}; scripts/openings.py builds books by simulation.
"""
from __future__ import annotations

from .battle import CHARGED, FAST, SWITCH


def describe(plan: dict, team_names: list) -> str:
    if plan.get("swap") is None:
        return "stay in"
    to = team_names[plan["swap"]]
    if plan.get("after_charged"):
        return f"throw first, then swap to {to}"
    n = plan.get("after_fast", 0)
    return f"swap to {to} at once" if n == 0 else f"stay {n} fast moves, then swap to {to}"


class Booked:
    """Plays as `inner`, following the book's plan for the opposing lead during the opening."""

    def __init__(self, inner, book: dict):
        self.inner, self.book = inner, book
        self.plan, self.fast, self.thrown, self.done = None, 0, False, False
        self.sees_move = getattr(inner, "sees_move", False)
        for hook in ("saw_throw", "saw_shield"):
            if hasattr(inner, hook):
                setattr(self, hook, getattr(inner, hook))

    def clone(self):
        twin = Booked(self.inner.clone(), self.book)
        twin.plan, twin.fast, twin.thrown, twin.done = self.plan, self.fast, self.thrown, self.done
        return twin

    def __getattr__(self, name):  # anything else (rows, looks, ...) is the inner player's
        return getattr(self.inner, name)

    def act(self, view):
        if self.plan is None and not self.done:
            self.plan = self.book.get(view.foe.build.species_id, {"swap": None})
            if self.plan.get("swap") is None:
                self.done = True
        if not self.done:
            me = view.me
            slot = self.plan["swap"]
            if me.active != 0 or me.mon.hp <= 0 or slot not in me.bench():
                self.done = True  # the lead is gone or the plan cannot be carried out: the bot is in charge
            else:
                due = self.thrown if self.plan.get("after_charged") else self.fast >= self.plan.get("after_fast", 0)
                if due and me.switch_wait == 0:
                    self.done = True
                    self.inner.act(view)  # keep the bot's own bookkeeping in step
                    return SWITCH[slot]
                action = self.inner.act(view)
                if action in SWITCH[:]:
                    action = FAST  # no switching before the plan's switch
                if action == FAST:
                    self.fast += 1
                elif action in CHARGED:
                    self.thrown = True
                return action
        return self.inner.act(view)

    def shield(self, view, energy, *move):
        return self.inner.shield(view, energy, *move)

    def replace(self, view):
        self.done = True
        return self.inner.replace(view)


class Answers:
    """Plays as `inner`, with a prepared answer whenever a new opposing Pokémon comes in (the owner's friend: "if
    someone safe swapped Ninetales into your Melmetal lead, go instantly to Altaria; if they safe swap Sableye, Double
    Iron Bash and then go to Altaria").

    book: {our species: {their species: plan}}, plans as for Booked but naming the Pokémon to swap to ("to": species)
    or its team slot ("swap"). A plan starts when their Pokémon arrives (the lead at the start, a switch, or a
    replacement after a faint) while that Pokémon of ours is in; fast moves and throws are counted from then. Until its
    switch the bot may not switch; after it, or once it cannot be carried out, the bot is in charge until the next
    arrival. `fired` counts the arrivals the book had an entry for (plan or not), for the scripts that build books.
    """

    def __init__(self, inner, book: dict):
        self.inner, self.book = inner, book
        self.foe_slot, self.plan, self.ours, self.fast, self.thrown, self.fired = None, None, None, 0, False, 0
        self.sees_move = getattr(inner, "sees_move", False)
        for hook in ("saw_throw", "saw_shield"):
            if hasattr(inner, hook):
                setattr(self, hook, getattr(inner, hook))

    def clone(self):
        twin = Answers(self.inner.clone(), self.book)
        twin.foe_slot, twin.plan, twin.ours, twin.fast, twin.thrown, twin.fired = (
            self.foe_slot, self.plan, self.ours, self.fast, self.thrown, self.fired)
        return twin

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def _arrival(self, view) -> None:
        me = view.me
        slot = view._foe.active
        if slot == self.foe_slot:
            return
        self.foe_slot, self.plan, self.fast, self.thrown = slot, None, 0, False
        entry = self.book.get(me.mon.build.species_id, {}).get(view.foe.build.species_id)
        if entry is None:
            return
        self.fired += 1
        if entry.get("swap") is None and entry.get("to") is None:
            return
        to = entry["to"] if entry.get("to") is not None else me.team[entry["swap"]].build.species_id
        target = next((j for j, m in enumerate(me.team) if m.build.species_id == to), None)
        if target is not None:
            self.plan, self.ours = {**entry, "slot": target}, me.active

    def act(self, view):
        self._arrival(view)
        plan, me = self.plan, view.me
        if plan is None:
            return self.inner.act(view)
        if me.active != self.ours or me.mon.hp <= 0 or plan["slot"] not in me.bench():
            self.plan = None
            return self.inner.act(view)
        due = self.thrown if plan.get("after_charged") else self.fast >= plan.get("after_fast", 0)
        if due and me.switch_wait == 0:
            self.plan = None
            self.inner.act(view)  # keep the bot's own bookkeeping in step
            return SWITCH[plan["slot"]]
        action = self.inner.act(view)
        if action in SWITCH[:]:
            action = FAST
        if action == FAST:
            self.fast += 1
        elif action in CHARGED:
            self.thrown = True
        return action

    def shield(self, view, energy, *move):
        return self.inner.shield(view, energy, *move)

    def replace(self, view):
        self.plan = None
        return self.inner.replace(view)
