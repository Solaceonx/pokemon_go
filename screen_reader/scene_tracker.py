"""Causal scene continuity; inferred context never overwrites a visible cue."""


class SceneTracker:
    def __init__(self):
        self.last_time = None
        self.context = None
        self.counts = {}
        self.identities = {}
        self.opponent_count_drop = None

    def update(self, reading):
        t = reading["timestamp_seconds"]
        if self.last_time is not None and not 0 < t-self.last_time <= 1:
            self.__init__()
        self.last_time = t
        phase = reading["phase"].get("value")
        changed = []
        for side in ("mine", "opponent"):
            values = reading[side]
            species = values.get("species", {})
            if species.get("status") == "observed" and species.get("value"):
                name = species["value"]
                if side in self.identities and self.identities[side] != name:
                    changed.append(side)
                self.identities[side] = name
            count = values.get("pokemon_left", {}).get("value")
            if count is not None:
                previous = self.counts.get(side)
                if side == "opponent" and previous is not None and count < previous:
                    self.opponent_count_drop = t
                if previous is not None and count > previous:
                    self.context = None
                    self.opponent_count_drop = None
                self.counts[side] = count
        if "opponent" in changed:
            self.opponent_count_drop = None
        if phase:
            self.context = (phase, t)
            reading["phase_estimate"] = {
                "value": phase, "status": "observed",
                "evidence": {"method": "current_frame_cue", "cue": reading["phase"].get("evidence", {})}}
            return reading

        value, reason, origin = None, None, None
        if changed:
            value, reason, origin = "switching_in", "Active header identity changed", t
        elif (self.opponent_count_drop is not None and t-self.opponent_count_drop <= 10 and
              reading["mine"].get("health_bar", {}).get("value") and
              not reading["opponent"].get("health_bar", {}).get("value") and
              not any(b.get("kind") == "charge" for b in reading.get("buttons", []))):
            value, reason, origin = "opponent_replacement_wait", "Opponent party count decreased and its bar is absent", self.opponent_count_drop
        elif self.context:
            before, origin = self.context
            age = t-origin
            if before == "shield_prompt" and age <= 6:
                value, reason = "opponent_charged_warning", "Shield prompt disappeared; waiting for the charge sequence"
            elif before == "my_charged_minigame" and age <= 12:
                value, reason = before, "Recent minigame cue; no resolution or fighting cue yet"
            elif before == "choose_next" and age <= 6:
                value, reason = before, "Recent replacement prompt; no entry cue yet"
            elif before in {"charged_resolution", "opponent_charged_resolution"} and age <= 3:
                value, reason = before, "Recent move announcement; animation may still be resolving"
        reading["phase_estimate"] = ({"value": value, "status": "inferred",
            "evidence": {"method": "causal_scene_continuity", "reason": reason,
                         "last_support_seconds": origin, "support_age_seconds": round(t-origin, 6)}}
            if value else {"value": None, "status": "unknown", "reason": "No current cue or bounded recent scene context"})
        return reading
