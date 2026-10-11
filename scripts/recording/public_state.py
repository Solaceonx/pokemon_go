"""An evidence ledger for public footage, independent of default model builds.

Persistent identities and bench health keep their observation timestamps.
No IVs, forms, unseen moves, starting energy or initial counters are fabricated.
"""
from __future__ import annotations

import copy
import re


def unknown(reason):
    return {"value": None, "status": "unknown", "reason": reason}


def evidence(value, at, status="observed", **extra):
    return {"value": value, "status": status, "observed_at_seconds": at, **extra}


def energy_candidates(fills, costs, ready, tolerance=.065):
    """Whole-number energies compatible with both disc readings.

    A ready disc may show its first full helping or the fill of its second.
    This is a pixel tolerance, not a calibrated statistical confidence band.
    """
    if len(fills) != 2 or len(costs) != 2 or any(c is None or c <= 0 for c in costs):
        return []
    if any(not isinstance(f, (int, float)) or not 0 <= f <= 1 for f in fills):
        return []
    candidates = []
    for amount in range(101):
        fits = True
        for fill, cost, can_throw in zip(fills, costs, ready):
            if can_throw and amount < cost:
                fits = False
                break
            levels = [min(1, amount / cost)]
            if amount >= cost:
                levels.append(min(1, (amount - cost) / cost))
            if min(abs(fill - level) for level in levels) > tolerance:
                fits = False
                break
        if fits:
            candidates.append(amount)
    return candidates


class PublicState:
    def __init__(self, move_costs, *, incomplete_start=False):
        self.move_costs = move_costs
        self.incomplete_start = incomplete_start
        self.sides = {s: {"active": None, "pokemon": {}, "shields": unknown("No confirmed counter"),
                          "left": unknown("No confirmed counter"), "counter_runs": {}}
                      for s in ("mine", "opponent")}
        self.last_time = None
        self.charge_owner = None
        self.move_names = {re.sub(r"[^A-Z]", "", name.upper()): name for name in move_costs}
        self.last_charge = {}

    def counter(self, state, name, field, t):
        value = field.get("value") if field.get("status") == "observed" else None
        if value is None:
            state["counter_runs"].pop(name, None)
            return None
        run = state["counter_runs"].get(name)
        if run is None or run["value"] != value or t - run["last"] > .2:
            run = {"value": value, "start": t, "last": t, "count": 0, "active_at_start": state["active"]}
        run["last"], run["count"] = t, run["count"] + 1
        state["counter_runs"][name] = run
        if run["count"] < 3 or t - run["start"] < .12:
            return None
        old = state[name].get("value")
        if old is not None and value > old:
            state[name] = unknown("Counter increased inside one match; possible misread or edit")
            return None
        state[name] = evidence(value, t, method="sustained_visible_counter")
        return (old, value, run["active_at_start"]) if old is not None and old != value else None

    def update(self, frame, slim):
        t = frame["timestamp_seconds"]
        if self.last_time is not None and t <= self.last_time:
            raise ValueError("State evidence must move forward in video time")
        self.last_time = t
        phase = frame.get("phase", {}).get("value")
        if phase == "my_charged_minigame":
            self.charge_owner = "mine"
        elif phase in ("opponent_charged_warning", "shield_prompt", "opponent_charged_resolution"):
            self.charge_owner = "opponent"
        for side in ("mine", "opponent"):
            visible, state = frame[side], self.sides[side]
            drop = self.counter(state, "left", visible["pokemon_left"], t)
            self.counter(state, "shields", visible["shields_left"], t)
            if drop and drop[1] < drop[0] and drop[2] in state["pokemon"]:
                state["pokemon"][drop[2]]["fainted"] = evidence(True, t, "inferred", method="party_counter_decreased")
            species, cp = visible["species"], visible["cp"]
            identity = None
            if species.get("value") and cp.get("value") is not None:
                identity = f"{species['value']}:{cp['value']}"
                seen = species.get("evidence", {}).get("observed_at_seconds", t)
                if seen is not None and 0 <= t - seen <= .75:
                    if identity not in state["pokemon"]:
                        if len(state["pokemon"]) < 3:
                            state["pokemon"][identity] = {
                                "species": evidence(species["value"], seen), "cp": evidence(cp["value"], seen),
                                "health": unknown("No settled bar for this identity"),
                                "energy": unknown("Move costs and settled disc fill required"),
                                "charged_moves": {}, "fast_move": unknown("No fast-move name shown"),
                                "attack_stage": unknown("Buff history has not been verified"),
                                "defense_stage": unknown("Buff history has not been verified"),
                                "fainted": unknown("No independent faint confirmation"),
                                "form": unknown("Header does not identify the form or Shadow status"),
                                "maximum_hp": unknown("CP alone does not fix IVs or maximum HP"),
                            }
                    if identity in state["pokemon"]:
                        state["active"] = identity
                        state["pokemon"][identity]["species"] = evidence(species["value"], seen)
                        state["pokemon"][identity]["cp"] = evidence(cp["value"], seen)
            mon = state["pokemon"].get(state["active"])
            if not mon or identity != state["active"]:
                continue
            health = visible.get("health_estimate", {})
            if health.get("status") == "estimated" and health.get("identity") == f"{side}:{identity}":
                mon["health"] = evidence(health["fraction_range"], t, "estimated", units="fraction",
                                          integer_hp_range=health.get("integer_hp_range"), maximum_hp=health.get("maximum_hp"))
            if side == "mine":
                for button in frame["buttons"]:
                    if button.get("identity_status") == "observed" and button.get("move") in self.move_costs:
                        mon["charged_moves"][button["id"]] = evidence(button["move"], t)
                names = [mon["charged_moves"].get(f"charge_{i}", {}).get("value") for i in (0, 1)]
                values = [slim["b"][key] for key in ("l", "r")]
                if all(v[1] for v in values) and all(names):
                    amounts = energy_candidates([v[0] for v in values], [self.move_costs[n] for n in names], [v[2] for v in values])
                    if amounts:
                        mon["energy"] = evidence([min(amounts), max(amounts)], t, "estimated",
                            units="whole_energy_units", candidates=amounts, method="two_visible_discs_and_observed_move_costs",
                            tolerance_note="Unvalidated pixel tolerance; animation and fill wrap can leave several possibilities")
        if frame.get("text_observation", {}).get("fresh_this_frame"):
            for record in frame["text_observation"]["records"]:
                key = re.sub(r"[^A-Z]", "", record["text"].upper())
                if "USED" not in key:
                    continue
                actor, move = key.split("USED", 1)
                name = self.move_names.get(move)
                if name is None:
                    continue
                matching = [side for side, state in self.sides.items() if state["active"]
                            and re.sub(r"[^A-Z]", "", state["pokemon"][state["active"]]["species"]["value"].upper()) == actor]
                owner = matching[0] if len(matching) == 1 else self.charge_owner if self.charge_owner in matching else None
                if owner:
                    state = self.sides[owner]
                    signature = (owner, state["active"], name)
                    if t - self.last_charge.get(signature, -100) > 5:
                        state["pokemon"][state["active"]]["charged_moves"]["used_" + move] = evidence(name, t,
                            method="exact_announced_move_name", raw_text=record["text"])
                    self.last_charge[signature] = t
        out = {"schema": "public-game-state-v1", "t": t, "phase": frame.get("phase_estimate", frame["phase"]),
               "incomplete_start": self.incomplete_start, "accuracy_verified": False,
               "battle_clock": unknown("Action start and uninterrupted game clock are not verified"),
               "switch_cooldown": unknown("Switch cause and timer have not been independently confirmed"),
               "controls": frame["buttons"], "result": frame["result"], "sides": {}}
        for side, state in self.sides.items():
            values = {k: copy.deepcopy(v) for k, v in state.items() if k != "counter_runs"}
            for mon in values["pokemon"].values():
                for key in ("species", "cp", "health", "energy"):
                    field = mon[key]
                    age = t - field.get("observed_at_seconds", t)
                    if field.get("value") is not None and age > .75:
                        field["status"] = "stale"
                    field["age_seconds"] = round(age, 6)
            for key in ("shields", "left"):
                field = values[key]
                if field.get("value") is not None and t - field["observed_at_seconds"] > .75:
                    field["status"] = "stale"
            out["sides"][side] = values
        return out
