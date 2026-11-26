"""Engine-lab players (2026-11-24): opt-in search architectures, never the default.

`engine_class(name)` gives the class behind an `engine=<name>` setting in scripts/engine_versus.py, and
`setting(key, value)` reads that class's own settings from their text form.
"""
from __future__ import annotations

# The settings each lab engine adds on top of the Engine's, with how to read them from "key=value" text.
_INT = ("depth", "sims")
_FLOAT = ("c_puct", "prior_temp", "k0", "gumbel", "gscale")
_BOOL = ("adversary", "protect_pick", "closed", "fix_stay", "fix_judged")
_TEXT = ("root", "tree_heads")
KEYS = frozenset(("engine",) + _INT + _FLOAT + _BOOL + _TEXT)


def setting(key: str, value: str):
    """A lab setting's value from its text in a spec ("depth=2", "tree_heads=throw+swap")."""
    if key == "engine":
        engine_class(value)  # fail early on an unknown name
        return value
    if key in _INT:
        return int(value)
    if key in _FLOAT:
        return float(value)
    if key in _BOOL:
        return value not in ("0", "false", "False", "")
    if key == "tree_heads":
        return tuple(value.split("+"))
    if key == "root":
        if value not in ("flat", "sh"):
            raise ValueError(f"unknown root {value!r} (flat | sh)")
        return value
    raise KeyError(key)


def engine_class(name: str):
    if name == "tree":
        from .tree import TreeEngine
        return TreeEngine
    raise ValueError(f"unknown lab engine {name!r} (tree)")
