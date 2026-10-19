"""A search at the bot's judgement calls, the way a chess engine searches: look ahead, judge the positions reached.

At a decision (throw a charged move or keep fast-moving, swap or stay, which replacement), the `Engine` rebuilds
the battle from what it can see, with what it cannot (the opponent's unseen Pokémon) drawn at random, plays each
option `horizon` turns ahead several times with the same dice for every option, and judges where it ends up with
an evaluation (pogo.evaluation; a battle that ends inside the horizon is scored by pogo.arena.decisive). It takes
the best option if it beats the trained bot's own pick by `edge`; otherwise it plays as the trained bot.

Both sides are played inside the look-ahead by the quick rollout player (pogo.agents._rollout), or by the trained
bot (rollout="bot", the confirmed setting). Options for the engine-strength tasks, all off by default so the engine
plays as before (docs/tasks.md, 25, 28 and 29):

- heads including "shield": search the shield decision too. The defender does not know which move is coming, so
  each imagined battle draws the move from those the attacker can afford, the cheaper one as often as this
  opponent has baited, and starts just after it lands (task 25).
- opponents="mix": the opponent inside the look-ahead is drawn from a mix of styles (STYLES) instead of always being
  the trained bot; profile=True weights the mix by how well each style's shield and bait rates fit what this
  opponent has done; unseen="teams" draws their unseen Pokémon from listed teams that fit what has been seen
  (task 28).
- mix=True: when both sides have a charged move ready, solve the small game of our options against theirs and
  draw our choice from the mix; temperature > 0: choose among close options at random, weighted by worth
  (task 29). Those draws use their own generator (`_mix_rng`), so a probe that copies the engine's search cannot
  copy its dice.
"""
from __future__ import annotations

import json
import math
import random
import time
from pathlib import Path

from .agents import _rollout, varied_settings
from .arena import decisive
from .battle import CHARGED, CHARGED_TURNS, FAST, SWITCH, Battle, Mon, View, apply_buffs, damage
from .learner import Learner

DATA = Path(__file__).resolve().parent.parent / "data"

# Opponent styles inside the look-ahead (opponents="mix"): weight in the mix, and the share of chances to shield
# that the style takes and the share of throws that are the cheaper move when both are ready, used by profile=True.
# The rates are first guesses; scripts/calibrate_styles.py measures them and writes data/opponent_styles.json,
# which is read instead when it exists.
STYLES = {"bot": {"weight": 0.4, "shield": 0.7, "bait": 0.5},
          "varied": {"weight": 0.3, "shield": 0.65, "bait": 0.5},
          "human": {"weight": 0.2, "shield": 0.8, "bait": 0.35},
          "pvpoke": {"weight": 0.1, "shield": 0.9, "bait": 0.3}}


def styles(path: str | Path | None = None) -> dict:
    explicit = path is not None
    path = Path(path) if path is not None else DATA / "opponent_styles.json"
    if not path.is_absolute():
        path = DATA.parent / path
    if explicit or path.exists():
        return {**STYLES, **json.loads(path.read_text())["styles"]}
    return STYLES


def style_player(name: str, rng: random.Random, q, margin: float, pool: list, human: dict | None = None):
    """A player of one of the STYLES: the trained bot, the bot with shifted habits, the human-like guess, PvPoke's AI."""
    if name == "pvpoke":
        from .pvpoke_ai import PvpokeAI
        return PvpokeAI()
    if name == "varied":
        return Learner(q=q, margin=rng.choice((0.02, 0.05, 0.1)), **varied_settings(rng, pool))
    if name == "human":
        return Learner(q=q, margin=rng.choice((0.02, 0.05)), **human_settings(rng, pool, human))
    return Learner(q=q, margin=margin, seed=rng.getrandbits(32))


def human_settings(rng: random.Random, field: list | None = None, overrides: dict | None = None) -> dict:
    """A first guess at how people differ from the bot (status.md, "The bot against real players' decisions"): they
    keep fast-moving where the bot would throw, and many use a fast move before swapping out of a new matchup."""
    settings = varied_settings(rng, field)
    settings.update(hold=True, hold_cost=min(1.5, 0.9 * 2.718281828 ** rng.gauss(0, 0.3)), timed_farm=True,
                    fast_first=rng.choice((0.5, 1.0)), last_gasp=rng.random() < 0.6)
    settings.update(overrides or {})
    return settings


class _First:
    """A player whose first action is fixed; after that, `inner` plays."""

    def __init__(self, inner, action):
        self.inner, self.action = inner, action
        self.sees_move = getattr(inner, "sees_move", False)

    def act(self, view):
        if self.action is not None:
            action, self.action = self.action, None
            if action in view.legal():
                return action
        return self.inner.act(view)

    def shield(self, view, energy, *move):
        return self.inner.shield(view, energy, *move)

    def replace(self, view):
        return self.inner.replace(view)


def imagine(view: View, rng: random.Random, pool: list, me_agent, foe_agent, teams: list | None = None,
            team_builds: dict | None = None) -> Battle:
    """A battle standing where this view stands, with the opponent's unseen Pokémon drawn from the pool, or with
    `teams` (weight, species) from a listed team that holds every one seen so far, when one does."""
    me = view.me
    mine = [m.copy() for m in me.team]
    seen = view.foe_shown
    theirs = [m.copy() for m in seen]
    unseen = max(0, view.foe_left - sum(m.hp > 0 for m in seen))
    taken = {m.build.species_id for m in seen}
    fitting = [(w, t) for w, t in teams if w > 0 and taken <= set(t)] if teams and unseen else []
    by_id = {b.species_id: b for b in pool}
    if team_builds:
        by_id.update(team_builds)
    if fitting:
        team = rng.choices([t for _, t in fitting], [w for w, _ in fitting])[0]
        extra = [by_id[sp] for sp in team if sp not in taken and sp in by_id][:unseen]
        extra += rng.sample([b for b in pool if b.species_id not in taken and b not in extra], unseen - len(extra))
        theirs += [Mon(b) for b in extra]
    else:
        theirs += [Mon(b) for b in rng.sample([b for b in pool if b.species_id not in taken], unseen)]
    battle = Battle(mine, theirs, me_agent, foe_agent, seed=rng.getrandbits(32),
                    shields=(me.shields, view.foe_shields), switch_wait=(me.switch_wait, view.foe_switch_wait))
    ours, foes = battle.sides
    ours.active, ours.busy, ours.shown = me.active, me.busy, list(me.shown)
    foes.active = next(i for i, m in enumerate(seen) if m is view.foe)
    foes.busy, foes.shown = view.foe_busy, list(range(len(seen)))
    battle.turn = view.turn
    return battle


class Engine(Learner):
    def __init__(self, evaluator, pool: list, horizon: int = 20, samples: int = 6, edge: float = 0.0,
                 heads: tuple = ("throw", "swap", "mid_swap", "replace"), rollout: str = "quick",
                 opponents: str = "bot", profile: bool = False, unseen: str = "pool",
                 team_file: str | Path | None = None,
                 style_file: str | Path | None = None,
                 mix: bool = False, temperature: float = 0.0, **settings):
        super().__init__(**settings)
        self.evaluator, self.pool = evaluator, pool
        self.horizon, self.samples, self.edge, self.heads = horizon, samples, edge, tuple(heads)
        # Who plays inside the look-ahead: "quick", the cheap rollout player, or "bot", the trained bot itself.
        self.rollout = rollout
        self.opponents, self.profile, self.unseen, self.mix, self.temperature = opponents, profile, unseen, mix, temperature
        self._styles = styles(style_file) if opponents == "mix" else None
        self._human_settings = {}
        if opponents == "mix":
            path = Path(style_file) if style_file is not None else DATA / "opponent_styles.json"
            if not path.is_absolute():
                path = DATA.parent / path
            if path.exists():
                self._human_settings = json.loads(path.read_text()).get("human_settings", {})
        self._teams = None
        self._team_builds = None
        if unseen == "teams":
            from .gamedata import GameData
            from .teamlist import weights_for
            path = Path(team_file or DATA / "teams.json")
            if not path.is_absolute():
                path = DATA.parent / path
            listed = json.loads(path.read_text())["teams"]
            self._teams = list(zip(weights_for(listed), [e["team"] for e in listed]))
            self._team_builds = {b.species_id: b for b in pool}
            missing = {sp for e in listed for sp in e["team"]} - self._team_builds.keys()
            if missing:
                gd = GameData()
                self._team_builds.update({sp: gd.default(sp) for sp in missing})
        self._obs = {"shield": [0, 0], "bait": [0, 0]}  # what this opponent has done: [times, chances]
        self._mix_rng = random.Random(hash(self.rng.getstate()))  # for mixing only; does not touch self.rng
        self._their_first = None  # the opponent's first action in each look, when fixed (mixed tables, readers)
        self._foe_energy = None  # the attacker's energy, for shield looks
        self.looks = 0  # decisions searched
        self.changed = 0  # of those, how many went against the trained bot's pick
        self.mixed = 0  # decisions made by solving a small game
        # A deadline for the search, on `clock` (None: no limit; pogo.realtime sets it per decision). The search
        # goes round by round, one imagined battle per option each round, and decides on the complete rounds.
        self.clock, self._deadline = time.process_time, None
        self.cut = 0  # searches stopped by the deadline before all their rounds
        self.fell_back = 0  # searches with no complete round, which play the trained bot's pick
        self._look_time, self._timed_looks = 0.0, 0

    def clone(self) -> Engine:
        twin = super().clone()
        twin._mix_rng = random.Random()
        twin._mix_rng.setstate(self._mix_rng.getstate())
        twin._obs = {k: list(v) for k, v in self._obs.items()}
        return twin

    # what this opponent does, for profile=True

    def saw_shield(self, view: View, shielded: bool) -> None:
        super().saw_shield(view, shielded)
        self._obs["shield"][0] += shielded
        self._obs["shield"][1] += 1

    def saw_throw(self, view: View, move, foe_energy: int, could_shield: bool) -> None:
        super().saw_throw(view, move, foe_energy, could_shield)
        ready = [m for m in view.foe.build.charged if m.energy <= foe_energy]
        if len(ready) > 1 and min(m.energy for m in ready) < max(m.energy for m in ready):
            self._obs["bait"][0] += move.energy == min(m.energy for m in ready)
            self._obs["bait"][1] += 1

    def _style_weights(self) -> dict:
        weights = {name: s["weight"] for name, s in self._styles.items()}
        if self.profile:
            for name, s in self._styles.items():
                for kind in ("shield", "bait"):
                    k, n = self._obs[kind]
                    rate = min(max(s[kind], 0.02), 0.98)
                    weights[name] *= rate ** k * (1 - rate) ** (n - k)
        total = sum(weights.values()) or 1.0
        prior = sum(s["weight"] for s in self._styles.values()) or 1.0
        # Keep a tenth of the starting mix, so a few games never rule a style out for good.
        return {name: 0.9 * w / total + 0.1 * self._styles[name]["weight"] / prior for name, w in weights.items()}

    def _imagined_opponent(self, rng: random.Random):
        if self.opponents != "mix":
            return Learner(q=self.q, margin=self.margin, seed=rng.getrandbits(32))
        weights = self._style_weights()
        name = rng.choices(list(weights), list(weights.values()))[0]
        return style_player(name, rng, self.q, self.margin, self.pool, self._human_settings)

    # deciding

    def _decide(self, head: str, view: View, mask: tuple, planner_choice, foe_energy: int | None = None) -> int:
        if head in self.forced or head not in self.heads:
            return super()._decide(head, view, mask, planner_choice, foe_energy)
        options = [k for k in range(len(mask)) if mask[k]]
        pick = super()._decide(head, view, mask, planner_choice, foe_energy)  # the trained bot's choice
        if len(options) < 2:
            return pick
        self._foe_energy = foe_energy if foe_energy is not None else view.foe.energy
        seeds = [self.rng.getrandbits(32) for _ in range(self.samples)]
        if self.mix and head == "throw" and self._their_throws(view):
            mixed = self._mixed(view, head, options, seeds)
            if mixed is not None:
                return mixed
        totals, rounds = dict.fromkeys(options, 0.0), 0
        for s in seeds:
            done = {}
            for k in options:
                if self._out_of_time():
                    break
                done[k] = self._timed_look(view, head, k, s)
            if len(done) < len(options):
                break
            for k in options:
                totals[k] += done[k]
            rounds += 1
        self.looks += 1
        if rounds == 0:
            self.fell_back += 1
            return pick
        self.cut += rounds < len(seeds)
        worth = {k: totals[k] / rounds for k in options}
        if self.temperature > 0:
            # Close calls at random, weighted by worth; the trained bot's pick keeps its edge as a head start.
            scores = {k: worth[k] + (self.edge if k == pick else 0.0) for k in options}
            top = max(scores.values())
            choice = self._mix_rng.choices(options, [math.exp((scores[k] - top) / self.temperature) for k in options])[0]
            self.changed += choice != pick
            return choice
        best = max(options, key=lambda k: (worth[k], k == pick))
        if worth[best] - worth[pick] > self.edge:
            self.changed += best != pick
            return best
        return pick

    def _their_throws(self, view: View) -> list:
        """Their first actions worth considering when they have a charged move ready: farm, or each move ready."""
        foe = view.foe
        ready = [CHARGED[k] for k, m in enumerate(foe.build.charged) if foe.energy >= m.energy]
        return [FAST, *ready] if ready and view.foe_busy == 0 else []

    def _mixed(self, view: View, head: str, options: list, seeds: list) -> int | None:
        """Both sides can throw: our options against theirs as a small game, solved; our choice drawn from the mix."""
        from .sixes import solve
        theirs = self._their_throws(view)
        totals = [[0.0] * len(theirs) for _ in options]
        rounds = 0
        for s in seeds:
            cells = {}
            for i, k in enumerate(options):
                for j, action in enumerate(theirs):
                    if self._out_of_time():
                        break
                    self._their_first = action
                    try:
                        cells[i, j] = self._timed_look(view, head, k, s)
                    finally:
                        self._their_first = None
            if len(cells) < len(options) * len(theirs):
                break
            for (i, j), v in cells.items():
                totals[i][j] += v
            rounds += 1
        if rounds == 0:
            return None
        import numpy as np
        table = np.array(totals) / rounds
        _, p, _ = solve(table, rounds=3000)
        self.looks += 1
        self.mixed += 1
        return self._mix_rng.choices(options, list(p))[0]

    def _out_of_time(self) -> bool:
        """Would one more imagined battle, of the average length so far, pass the deadline?"""
        if self._deadline is None:
            return False
        average = self._look_time / self._timed_looks if self._timed_looks else 0.0
        return self.clock() + average > self._deadline

    def _timed_look(self, view: View, head: str, option: int, seed: int) -> float:
        if self._deadline is None:
            return self._look(view, head, option, seed)
        start = self.clock()
        worth = self._look(view, head, option, seed)
        self._look_time += self.clock() - start
        self._timed_looks += 1
        return worth

    def _look(self, view: View, head: str, option: int, seed: int) -> float:
        """Play one option `horizon` turns ahead in one imagined battle; judge the position reached."""
        rng = random.Random(seed)
        others = [j for j in range(3) if j != view.me.active]
        first = None
        if head == "throw":
            first = FAST if option == 0 else CHARGED[option - 1]
        elif head in ("swap", "mid_swap"):
            first = None if option == 0 else SWITCH[others[option - 1]]
        if self.rollout == "bot":
            us = Learner(q=self.q, margin=self.margin, seed=rng.getrandbits(32))
            them = self._imagined_opponent(rng)
        else:
            us, them = _rollout(), _rollout()
        if self._their_first is not None:
            them = _First(them, self._their_first)
        battle = imagine(view, rng, self.pool, _First(us, first), them, teams=self._teams,
                         team_builds=self._team_builds)
        if head == "replace":
            battle.sides[0].active = others[option]
            if others[option] not in battle.sides[0].shown:
                battle.sides[0].shown.append(others[option])
        if head == "shield":
            self._land_their_throw(battle, rng, shielded=option == 1)
            if battle.winner is not None:
                return decisive(battle, 0)
        foes = battle.sides[1]
        if foes.mon.hp <= 0:  # they fainted on the same turn: they send in someone too
            if not foes.bench():
                return decisive(battle, 0) if battle.winner is not None else 0.5
            foes.active = foes.bench()[0]
            foes.shown.append(foes.active)
        for _ in range(self.horizon):
            if battle.winner is not None:
                return decisive(battle, 0)
            battle.step()
        if battle.winner is not None:
            return decisive(battle, 0)
        return self.evaluator(battle.views[0])

    def _land_their_throw(self, battle: Battle, rng: random.Random, shielded: bool) -> None:
        """The imagined battle just after their charged move: which move is drawn from those they can afford, the
        cheaper as often as this opponent has thrown the cheaper one when it could (Planner's bait record)."""
        ours, foes = battle.sides
        thrower, target = foes.mon, ours.mon
        energy = self._foe_energy if self._foe_energy is not None else thrower.energy
        ready = sorted((m for m in thrower.build.charged if energy >= m.energy), key=lambda m: m.energy)
        if not ready:
            return
        bait = self._bait_seen[0] / self._bait_seen[1] if self._bait_seen[1] else 0.5
        move = ready[0] if len(ready) == 1 or rng.random() < bait else ready[-1]
        thrower.energy = energy - move.energy
        if shielded:
            ours.shields -= 1
            target.hp -= 1
        else:
            target.hp -= damage(thrower, move, target)
        if move.buff_chance and (move.buff_chance >= 1 or rng.random() < move.buff_chance):
            apply_buffs(thrower, target, move)
        ours.busy = foes.busy = 0
        elapsed = 1 + CHARGED_TURNS
        battle.turn += elapsed
        for side in (ours, foes):
            side.switch_wait = max(0, side.switch_wait - elapsed)
        if target.hp <= 0:
            if ours.left() == 0:
                battle.winner = 1
            else:
                battle._enter(0, battle.agents[0].replace(battle.views[0]))
