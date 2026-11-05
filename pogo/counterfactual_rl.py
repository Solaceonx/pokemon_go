"""Training-only counterfactual action returns for the standalone policy.

Every input is encoded from the public View. The simulator's complete training
state is used to obtain outcome labels, never as an inference feature. Runtime
checkpoints retain the ordinary independent-network format and need no search.
"""
from __future__ import annotations

import copy
import random
from dataclasses import dataclass

import numpy as np

from .standalone_rl import StandaloneAgent, encode, mask_for
from .standalone_rl_v2 import ActorCritic


def clone_player(player):
    """Copy controller history and dice, without sharing mutable outlook caches."""
    # The training recorder wraps an otherwise unchanged frozen engine.
    player = getattr(player, "teacher", player)
    twin = player.clone()
    if twin is player:
        twin = copy.copy(player)
    if hasattr(twin, "_outlooks"):
        twin._outlooks = dict(twin._outlooks)
    if hasattr(twin, "departures"):
        twin.departures = dict(twin.departures)
    if getattr(twin, "evaluator", None) is not None:
        twin.evaluator = copy.copy(twin.evaluator)
        twin.evaluator._agent = twin.evaluator._agent.clone()
        twin.evaluator._agent._outlooks = dict(twin.evaluator._agent._outlooks)
    return twin


class FirstAction:
    """Replace one physical action while consuming the policy's normal RNG draw."""
    def __init__(self, inner, action):
        self.inner, self.action = inner, action

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def act(self, view):
        choice = self.inner.act(view)
        if self.action is None:
            return choice
        action, self.action = self.action, None
        if action not in view.legal():
            raise ValueError("counterfactual action is not legal at this position")
        return action


@dataclass
class TrainingPosition:
    battle: object
    side: int
    features: np.ndarray
    mask: np.ndarray


def capture(battle, side: int) -> TrainingPosition:
    """Capture BEFORE step(), with this player able to act.

    A shield/faint callback is in the middle of a step and is deliberately not
    accepted here: restarting that partial step would duplicate game effects.
    """
    if side not in (0, 1) or battle.winner is not None:
        raise ValueError("need a live training battle and a valid side")
    view = battle.views[side]
    if view.me.busy or view.me.mon.hp <= 0:
        raise ValueError("capture only at an available pre-step action")
    if not isinstance(battle.agents[side], StandaloneAgent):
        raise TypeError("the forced side must be a standalone policy")
    twin = battle.clone(*(clone_player(p) for p in battle.agents))
    # A later optimizer step must not change the policy that these labels play
    # out. Forks may share this captured model, but not the live training model.
    frozen_models = {}
    for player in twin.agents:
        if isinstance(player, StandaloneAgent):
            key = id(player.model)
            if key not in frozen_models:
                frozen_models[key] = copy.deepcopy(player.model)
            player.model = frozen_models[key]
    return TrainingPosition(twin, side, encode(view), mask_for(view, "act"))


def branch(position: TrainingPosition, action: int, seeds=None, *, greedy_continuation=None):
    if not 0 <= action < len(position.mask) or not position.mask[action]:
        raise ValueError("illegal counterfactual action")
    players = [clone_player(p) for p in position.battle.agents]
    if greedy_continuation is not None:
        players[position.side].greedy = bool(greedy_continuation)
    if seeds is not None:
        if len(seeds) != 3:
            raise ValueError("need environment and two policy seeds")
        for player, seed in zip(players, seeds[1:]):
            if isinstance(getattr(player, "rng", None), np.random.Generator):
                player.rng = np.random.default_rng(seed)
            elif hasattr(getattr(player, "rng", None), "seed"):
                player.rng.seed(seed)
            if hasattr(player, "_mix_rng"):
                player._mix_rng.seed(seed)
    players[position.side] = FirstAction(players[position.side], action)
    twin = position.battle.clone(*players)
    if seeds is not None:
        twin.rng.seed(seeds[0])
    return twin


def action_returns(position: TrainingPosition, *, playouts: int = 2, seed: int = 0):
    """Average complete-battle scores for ALL legal actions with common dice.

    Counterfactual alternatives get the same environment/policy seeds within a
    playout, and fresh streams between playouts. Illegal options remain NaN.
    Our continuation uses the deployed greedy policy. These are Monte Carlo
    terminal returns, not short-horizon search values.
    """
    if playouts < 1:
        raise ValueError("playouts must be positive")
    rng = random.Random(seed)
    totals = np.zeros(6, dtype=np.float64)
    for _ in range(playouts):
        seeds = tuple(rng.getrandbits(64) for _ in range(3))
        for action in np.flatnonzero(position.mask):
            winner = branch(position, int(action), seeds, greedy_continuation=True).run()
            totals[action] += .5 if winner == -1 else float(winner == position.side)
    return np.where(position.mask, totals / playouts, np.nan).astype(np.float32)


class CounterfactualModel(ActorCritic):
    """An independent-network policy improved with complete action-return labels.

    The loss maximizes sum_a pi(a|public_state) Q(a). All legal alternatives are
    labelled, so no selected-action importance estimate is needed. The inherited
    PPO update remains available for ordinary on-policy shield/replacement data.
    """
    def improve_actions(self, x, mask, returns, *, rate=2e-4, entropy=.001, reference=None, anchor=.01,
                        train_critic=False):
        if returns.shape != mask.shape or not np.isfinite(returns[mask]).all():
            raise ValueError("every legal option needs a finite terminal-return label")
        if np.any((returns[mask] < 0) | (returns[mask] > 1)):
            raise ValueError("terminal scores must be in [0, 1]")
        if not mask.any(axis=1).all():
            raise ValueError("each position needs at least one legal action")
        p, value, (actor, critic) = self.forward(x, "act", mask)
        q = np.where(mask, returns, 0.)
        expected = (p * q).sum(axis=1)
        logp = np.log(np.maximum(p, 1e-12))
        ent = -(p * logp).sum(axis=1)
        dz = p * (expected[:, None] - q) / len(x)
        dz += entropy * p * (logp + ent[:, None]) / len(x)
        if reference is not None:
            dz += anchor * (p - reference) / len(x)
        actor_norm = self._adam(self._backward(x, "act", actor, np.where(mask, dz, 0.)), rate)
        # Continuations use the deployed greedy policy. Its value at this state
        # is the return of its pre-update argmax, not an oracle maximum target.
        target = q[np.arange(len(x)), p.argmax(axis=1)]
        # A hybrid PPO collector may use a stochastic behavior policy. Do not
        # mix its value targets with greedy-continuation targets by default.
        critic_norm = 0.
        if train_critic:
            critic_norm = self._adam(self._backward(x, "critic", critic, (value - target)[:, None] / len(x)), rate * 2)
        self.updates += 1
        return {"expected_score": float(expected.mean()), "entropy": float(ent.mean()),
                "value_mse": float(((value - target) ** 2).mean()),
                "actor_grad_norm": float(actor_norm), "critic_grad_norm": float(critic_norm)}
