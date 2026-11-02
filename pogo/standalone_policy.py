"""Load the standalone policy with the inference mode actually selected on validation.

This adapter imports no Planner, Learner, search engine or battle simulator.
"""
from __future__ import annotations

from .standalone_rl import ActorCritic, StandaloneAgent


def load_agent(checkpoint, *, seed: int = 0, greedy: bool | None = None):
    """Return (agent, metadata) from a selected best/locked checkpoint.

    Raw round checkpoints require an explicit mode: their state may mention the
    mode of a previous champion, rather than the round being loaded.
    """
    model, metadata = ActorCritic.load(checkpoint)
    if greedy is None:
        if not (metadata.get("locked") is True or metadata.get("selection") == "validation_only"):
            raise ValueError("unselected checkpoints require explicit greedy=True or greedy=False")
        greedy = metadata.get("state", {}).get("best_greedy", False)
    if not isinstance(greedy, bool):
        raise ValueError("checkpoint inference mode must be boolean")
    return StandaloneAgent(model, seed=seed, greedy=greedy), metadata
