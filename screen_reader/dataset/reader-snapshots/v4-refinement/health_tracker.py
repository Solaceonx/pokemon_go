"""Causal visible-health estimates. Integer HP requires a supplied maximum HP.

Ranges are engineering tolerances, not statistical confidence intervals. Mixed
color bars and recognized animation scenes remain unknown; no attack attribution occurs.
"""
import math


def same_geometry(a, b):
    # Compression can move the detected outline by a pixel or two.
    return (abs(a[0]-b[0]) <= 6 and len(a[1]) == len(b[1]) and
            all(abs(x-y) <= 6 for x, y in zip(a[1], b[1])))


def integer_hp_range(interval, maximum):
    if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum <= 0:
        raise ValueError("Maximum HP must be a positive integer")
    low = max(0, math.ceil(interval[0] * maximum - 1e-9))
    high = min(maximum, math.floor(interval[1] * maximum + 1e-9))
    return [low, high] if low <= high else None


class HealthTracker:
    def __init__(self, maximum_hp=None, settle_seconds=0.10):
        # Explicit identity keys: "mine:Raichu:1495", etc. No default-IV lookup.
        self.maximum_hp = maximum_hp or {}
        self.settle_seconds = settle_seconds
        self.sides = {}

    def update(self, reading):
        t = reading["timestamp_seconds"]
        for side in ("mine", "opponent"):
            reading[side]["health_estimate"] = self._side(reading, side, t)
        return reading

    def _side(self, reading, side, t):
        values = reading[side]
        state = self.sides.setdefault(side, {})
        def unknown(reason, reset=True):
            if reset:
                state.pop("candidate", None)
            return {"status": "unknown", "fraction": None, "reason": reason}
        # Avoid assigning an animation bar to the old, cached active identity.
        for field in ("species", "cp"):
            value = values.get(field, {})
            seen = value.get("evidence", {}).get("observed_at_seconds", t)
            if value.get("value") is None or seen is None or not 0 <= t-seen <= 0.75:
                return unknown("Active identity is not recently readable")
        identity = f'{side}:{values["species"]["value"]}:{values["cp"]["value"]}'
        if state.get("identity") != identity:
            state.clear()
            state["identity"] = identity
        phase = reading.get("phase", {}).get("value")
        context = reading.get("phase_estimate", {}).get("value")
        if phase not in {"normal_fighting", None} or (phase is None and context not in {None, "normal_fighting", "opponent_replacement_wait"}):
            return unknown("Wait for a settled fighting view")
        bar = values.get("health_bar", {}).get("value")
        if not bar:
            return unknown("Health bar is not visible", reset=False)
        segments = bar.get("segments", [])
        if bar.get("filled_pixels") == 0:
            return unknown("Empty candidate needs independent faint confirmation", reset=False)
        colors = {}
        for segment in segments:
            colors[segment["color"]] = colors.get(segment["color"], 0)+segment["pixels"]
        minority = sum(colors.values())-max(colors.values(), default=0)
        if not segments or minority > 2:
            return unknown("Mixed bar colors: damage animation or ambiguous pixels", reset=False)
        width = bar.get("interior_width_pixels", 0)
        if width <= 0 or "filled_pixels" not in bar:
            return unknown("No calibrated pixel measurement")
        if abs(width-138) > 6:
            return unknown("Detected outline is too far from calibrated bar width", reset=False)
        fraction = bar["filled_pixels"] / width
        # Two pixels cover edge selection, resampling and compressed video noise.
        tolerance = 2+abs(width-138)
        interval = [max(0, fraction-tolerance/width), min(1, fraction+tolerance/width)]
        geometry = (width, tuple(bar.get("bounds_px", bar.get("bounds", []))))
        candidate = state.get("candidate")
        if (not candidate or t-candidate["last"] > 0.2 or
                not same_geometry(candidate["geometry"], geometry) or
                max(interval[0], candidate["range"][0]) > min(interval[1], candidate["range"][1])):
            candidate = {"start": t, "last": t, "range": interval, "geometry": geometry, "count": 0}
            state["candidate"] = candidate
        candidate["count"] += 1
        candidate["last"] = t
        candidate["range"] = [max(interval[0], candidate["range"][0]), min(interval[1], candidate["range"][1])]
        if candidate["count"] < 3 or t-candidate["start"]+1e-6 < self.settle_seconds:
            return {"status": "settling", "fraction": None, "reason": "Waiting for consistent frames"}
        interval = candidate["range"][:]
        previous = state.get("confirmed")
        # A large apparent heal is conflicting evidence, not silently clamped HP.
        if previous and t-previous["t"] <= 0.75 and interval[0] > previous["range"][1]:
            return {"status": "conflict", "fraction": None, "reason": "Apparent health increase; check bar or identity"}
        maximum = self.maximum_hp.get(identity)
        hp = integer_hp_range(interval, maximum) if maximum is not None else None
        if maximum is not None and hp is None:
            return {"status": "conflict", "fraction": None, "reason": "Pixels do not fit the supplied maximum HP"}
        damage = None
        if hp and previous and previous.get("hp") and same_geometry(previous["geometry"], geometry) and t-previous["t"] <= 0.75:
            if hp[1] < previous["hp"][0]:
                damage = [previous["hp"][0]-hp[1], previous["hp"][1]-hp[0]]
        state["confirmed"] = {"t": t, "range": interval, "hp": hp, "geometry": geometry}
        return {"status": "estimated", "fraction": round(sum(interval)/2, 5),
                "fraction_range": [round(v, 5) for v in interval],
                "pixel_fraction": [bar["filled_pixels"], width], "pixel_tolerance": tolerance,
                "minority_color_pixels": minority,
                "maximum_hp": maximum, "integer_hp_range": hp, "integer_damage_range": damage,
                "identity": identity, "settled_since_seconds": candidate["start"],
                "scene_context": phase or context or "unclassified_visible_bar",
                "meaning": "Settled visible extent; applied versus pending damage is not verified"}
