"""Retain unaffected facts while a visible charged attack awaits resolution.

This tracks evidence, not animation duration. A cue does not prove damage or a
shield spend. A move announcement proves its cost, but the resulting balance
still needs a fresh reading; a previously read balance may omit an in-flight hit.
"""
from __future__ import annotations

import copy


CUES = {"my_charged_minigame": "mine", "opponent_charged_warning": "opponent", "shield_prompt": "opponent"}
RESOLUTION = {"charged_resolution", "opponent_charged_resolution", "my_charged_resolution"}
STABLE = {"species", "cp", "form", "maximum_hp", "fast_move", "fainted", "charged_moves", "result"}


class StateContinuity:
    def __init__(self):
        self.attack = None
        self.sequence = 0
        self.concerns = {}
        self.fighting_since = None
        self.fighting_count = 0
        self.previous_phase = None
        self.last_time = None
        self.carryable = set()

    def mark(self, sides, side, identity, field, reason, t):
        target = sides[side] if identity is None else sides[side]["pokemon"].get(identity, {})
        if target.get(field, {}).get("value") is not None:
            self.concerns[(side, identity, field)] = {
                "event_id": self.attack["id"] if self.attack else None,
                "reason": reason, "since_seconds": t}

    def begin(self, side, t, sides):
        self.sequence += 1
        other = "opponent" if side == "mine" else "mine"
        self.attack = {"id": self.sequence, "side": side, "started_at_seconds": t,
                       "attacker": sides[side]["active"], "defender": sides[other]["active"],
                       "stage": "charging", "move": None, "announced_at_seconds": None,
                       "energy_cost": None, "confirmed_changes": []}
        # An animation cannot restore certainty that was already missing when
        # it began. Freeze only fresh active readings; prior uncertainty survives.
        self.carryable = set()
        for who, state in sides.items():
            for field in ("shields", "left"):
                if state[field].get("value") is not None and t - state[field].get("observed_at_seconds", -100) <= .75:
                    self.carryable.add((who, None, field))
            identity = state["active"]
            if identity:
                for field in ("health", "energy"):
                    value = state["pokemon"][identity][field]
                    if value.get("value") is not None and not value.get("unconfirmed_at_exit") and t - value.get("observed_at_seconds", -100) <= .75:
                        self.carryable.add((who, identity, field))
        if self.attack["attacker"]:
            self.mark(sides, side, self.attack["attacker"], "energy", "Charged attack may spend energy", t)
        if self.attack["defender"]:
            self.mark(sides, other, self.attack["defender"], "health", "Incoming charged damage is not resolved", t)
        self.mark(sides, other, None, "shields", "Shield decision is not resolved", t)
        # Only already-known stages can be retained or marked pending.
        for who, identity in ((side, self.attack["attacker"]), (other, self.attack["defender"])):
            if identity:
                for field in ("attack_stage", "defense_stage"):
                    self.mark(sides, who, identity, field, "Possible charged-move stat change", t)

    def resolving(self, t, sides):
        if not self.attack or self.attack.get("resolution_started_at_seconds") is not None:
            return
        self.attack["stage"] = "resolving"
        self.attack["resolution_started_at_seconds"] = t
        side = self.attack["side"]
        other = "opponent" if side == "mine" else "mine"
        # A fast move already in progress may also land at resolution.
        if self.attack["attacker"]:
            self.mark(sides, side, self.attack["attacker"], "health", "Possible fast move landing at charge resolution", t)
        for who in (side, other):
            self.mark(sides, who, None, "left", "Resolution may cause a faint", t)

    def advance(self, frame, slim, sides):
        t = frame["timestamp_seconds"]
        if self.last_time is not None and t - self.last_time > 1:
            for side, state in sides.items():
                for identity in state["pokemon"]:
                    for field in ("health", "energy"):
                        self.mark(sides, side, identity, field, "Unobserved time gap may contain changes", t)
                for field in ("shields", "left"):
                    self.mark(sides, side, None, field, "Unobserved time gap may contain changes", t)
        self.last_time = t
        phase = frame.get("phase", {}).get("value")
        cue = CUES.get(phase)
        if cue:
            new = (not self.attack or self.attack["stage"] == "awaiting_readback" or self.attack["side"] != cue
                   or (self.attack["announced_at_seconds"] is not None
                       and phase != self.previous_phase and t - self.attack["announced_at_seconds"] > .75))
            if new:
                self.begin(cue, t, sides)
        if phase in RESOLUTION:
            self.resolving(t, sides)
        live = phase == "normal_fighting" and (
            all(slim.get("b", {}).get(key, [0, 0])[1] for key in ("l", "r"))
            or all(frame[side].get("health_estimate", {}).get("status") == "estimated" for side in sides))
        if live:
            if self.fighting_since is None:
                self.fighting_since = t
            self.fighting_count += 1
        else:
            self.fighting_since, self.fighting_count = None, 0
        if (self.attack and self.fighting_since is not None and self.fighting_count >= 3
                and t - self.fighting_since >= .12 and t - self.attack["started_at_seconds"] > 1):
            self.resolving(t, sides)
            self.attack["stage"] = "awaiting_readback"
        self.previous_phase = phase

    def announcement(self, side, name, cost, t, sides):
        if not self.attack or self.attack["side"] != side or self.attack["stage"] == "awaiting_readback":
            self.begin(side, t, sides)
        if self.attack["move"] is None:
            self.attack.update(move=name, energy_cost=cost, announced_at_seconds=t)
            self.attack["confirmed_changes"] = [{"side": side, "identity": self.attack["attacker"],
                                                 "field": "energy", "operation": "spent", "amount": cost}]
        self.resolving(t, sides)

    @property
    def holding(self):
        return bool(self.attack and self.attack["stage"] != "awaiting_readback")

    def observed(self, side, identity, field, *, changed=False):
        # A changed counter proves its change during the animation. An unchanged
        # counter/bar is read back only after sustained fighting resumes.
        if changed or not self.holding:
            self.concerns.pop((side, identity, field), None)

    def decorate(self, field, side, identity, name, t, *, bench=False):
        value = copy.deepcopy(field)
        age = t - field.get("observed_at_seconds", t)
        value["age_seconds"] = round(age, 6)
        if field.get("value") is None:
            return value
        concern = self.concerns.get((side, identity, name))
        if concern:
            value.update(status="pending", source_status=field["status"], state_validity="pending_change",
                         pending_event=copy.deepcopy(concern), last_known_value=copy.deepcopy(field["value"]))
        elif age > .75:
            stable = name in STABLE or (not field.get("unconfirmed_at_exit") and
                (bench or (self.holding and (side, identity, name) in self.carryable)))
            value.update(status="retained" if stable else "stale", source_status=field["status"],
                         state_validity="carried_forward" if stable else "unconfirmed")
        else:
            value["state_validity"] = "recent_reading"
        return value

    def snapshot(self):
        if self.attack and self.attack["stage"] == "awaiting_readback":
            if not any(c["event_id"] == self.attack["id"] for c in self.concerns.values()):
                self.attack = None
        return copy.deepcopy(self.attack)
