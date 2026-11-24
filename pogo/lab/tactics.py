"""Opt-in tactic spec parsing and a deliberately narrow throw-before-swap rule."""
import math

from pogo.battle import CHARGED, damage

KEYS = ("finish_safe", "bait_mix", "shield_two", "shield_one", "swap_after_throw")
BOT_KEYS = ("finish_safe", "bait_mix", "shield_two", "shield_one", "shield_margin", "shield_toward")


def setting(key: str, value: str):
    if key in ("finish_safe", "swap_after_throw", "shield_toward"):
        if value not in ("0", "1"):
            raise SystemExit(f"{key} must be 0 or 1")
        return bool(int(value))
    # Explicit off is needed for bait_mix: p=0 means always throw the dearer move.
    if value == "off":
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0 or (key == "bait_mix" and number > 1):
        raise SystemExit(f"invalid {key}: {value}")
    return number


def before_swap(view) -> int | None:
    """Skip a one-fast finish. With shields up demand KO pressure; otherwise out-hit a fast.

    Choose the cheapest affordable KO, else the hardest affordable hit. The engine reconsiders
    its next action normally; there is no forced switch or additional throw search.
    """
    mon, foe = view.me.mon, view.foe
    fast_hit = damage(mon, mon.build.fast, foe)
    if foe.hp <= fast_hit:
        return None
    moves = mon.build.charged
    ready = [k for k, m in enumerate(moves) if mon.energy >= m.energy]
    if not ready:
        return None
    hits = {k: damage(mon, moves[k], foe) for k in ready}
    lethal = [k for k in ready if hits[k] >= foe.hp]
    if lethal:
        return CHARGED[min(lethal, key=lambda k: moves[k].energy)]
    if view.foe_shields > 0:
        return None
    best = max(ready, key=lambda k: (hits[k], -moves[k].energy))
    return CHARGED[best] if hits[best] > fast_hit else None
