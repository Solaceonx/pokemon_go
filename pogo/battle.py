"""Pokémon GO trainer battles, one half-second turn at a time.

The rules follow PvPoke's simulator:

- A fast move takes 1-5 turns; its damage and energy arrive on its last turn.
- A charged move costs energy, resolves on the turn it is chosen, and can be
  shielded (1 damage). Its stat changes apply whether or not it is shielded.
- Within a turn, switches go first, then charged moves, then fast moves. If
  both players throw a charged move, the higher attack stat goes first (a coin
  flip when equal), and a Pokémon knocked out by the first one does not get
  its own move off.
- A fast move still in progress when a charged move is thrown lands straight
  after it, unless its user was just knocked out by that charged move.
- Switching takes the turn, clears the leaving Pokémon's stat changes and
  starts a 45 s timer. Replacing a fainted Pokémon is free.

Simplifications: every charged move is assumed fully charged; each one takes a
flat 10 s off the clock and off both switch timers; form-changing Pokémon are
left out; a battle that reaches the time limit goes to the player with more
Pokémon left, then more health.
"""
from __future__ import annotations

import random

from .gamedata import MAX_STAGE, STAGE, Build, Move

ENERGY_CAP = 100
SHIELDS = 2
SWITCH_TURNS = 90  # 45 s
CHARGED_TURNS = 20  # clock time one charged move takes
MAX_TURNS = 480  # 4 min

# actions
FAST = 0
CHARGED = (1, 2)  # first and second charged move
SWITCH = (3, 4, 5)  # to team slot 0, 1, 2
DRAW = -1


class Mon:
    """A Pokémon's state during one battle."""

    __slots__ = ("build", "hp", "energy", "atk_stage", "def_stage")

    def __init__(self, build: Build, hp: int | None = None, energy: int = 0):
        self.build = build
        self.hp = build.hp if hp is None else hp
        self.energy = energy
        self.atk_stage = 0
        self.def_stage = 0

    def copy(self) -> Mon:
        twin = Mon(self.build, self.hp, self.energy)
        twin.atk_stage, twin.def_stage = self.atk_stage, self.def_stage
        return twin

    def __repr__(self) -> str:
        return f"{self.build.name} {max(self.hp, 0)}/{self.build.hp}hp {self.energy}e"


def damage(user: Mon, move: Move, target: Mon) -> int:
    build, other = user.build, target.build
    base = build._cache.get((move.id, other.uid))
    if base is None:
        base = build.base_damage(move, other)
    a, d = user.atk_stage, target.def_stage
    if a or d:
        base = base * (STAGE[a + MAX_STAGE] / STAGE[d + MAX_STAGE])
    return int(base) + 1


# Morpeko's rule is a "toggle", but PvPoke's simulator only ever changes it to Hangry: after its first charged move it
# stays Hangry until it switches out (tests/data/pvpoke_forms.txt depends on this). True alternates it on every
# charged move instead, if that is what the game does.
MORPEKO_TOGGLES = False


def change_form(mon: Mon, form_id: str) -> None:
    """Turn a form-changing Pokémon into another of its forms (pogo.gamedata: Build.forms), keeping its health,
    energy and stat stages, and adding the new form's own stages (Busted Mimikyu), as PvPoke's changeForm does."""
    new = mon.build.forms[form_id]
    if new is mon.build:
        return
    mon.build = new
    a, d = new.native
    if a or d:
        mon.atk_stage = max(-MAX_STAGE, min(MAX_STAGE, mon.atk_stage + a))
        mon.def_stage = max(-MAX_STAGE, min(MAX_STAGE, mon.def_stage + d))


def _triggers(rule: dict, move: Move) -> bool:
    return rule.get("moveId") == "ANY" or rule.get("moveId") == move.id or move.id in (rule.get("moveIDs") or ())


def leave_field(mon: Mon) -> None:
    """A Pokémon switching out: stat stages back to its form's own, and back to its starting form where the rule says."""
    build = mon.build
    if build.forms is not None and build.rule and build.rule.get("resetOnSwitch") and build.species_id != build.home:
        mon.build = build = build.forms[build.home]
    mon.atk_stage, mon.def_stage = build.native


def apply_buffs(user: Mon, target: Mon, move: Move) -> None:
    """Apply a charged move's stat changes to both Pokémon."""
    user.atk_stage = max(-MAX_STAGE, min(MAX_STAGE, user.atk_stage + move.self_buffs[0]))
    user.def_stage = max(-MAX_STAGE, min(MAX_STAGE, user.def_stage + move.self_buffs[1]))
    target.atk_stage = max(-MAX_STAGE, min(MAX_STAGE, target.atk_stage + move.foe_buffs[0]))
    target.def_stage = max(-MAX_STAGE, min(MAX_STAGE, target.def_stage + move.foe_buffs[1]))


class Side:
    __slots__ = ("team", "active", "shields", "switch_wait", "busy", "shown")

    def __init__(self, team: list[Mon], shields: int = SHIELDS):
        self.team = team
        self.active = 0
        self.shields = shields
        self.switch_wait = 0  # turns until a switch is allowed
        self.busy = 0  # turns left on the fast move in progress
        self.shown = [0]  # team slots the opponent has seen, in order

    @property
    def mon(self) -> Mon:
        return self.team[self.active]

    def copy(self) -> Side:
        twin = Side([m.copy() for m in self.team], self.shields)
        twin.active, twin.switch_wait, twin.busy, twin.shown = self.active, self.switch_wait, self.busy, list(self.shown)
        return twin

    def bench(self) -> list[int]:
        """Slots that could come in: not active, not fainted."""
        return [j for j, m in enumerate(self.team) if j != self.active and m.hp > 0]

    def left(self) -> int:
        return sum(m.hp > 0 for m in self.team)


class View:
    """What one player can see. Agents should decide from this alone.

    The opponent's energy is included because it can be counted from their fast
    moves, and their moves are taken to be the standard set for the species.
    Their unrevealed Pokémon are hidden.
    """

    def __init__(self, battle: Battle, index: int):
        self._battle = battle
        self.me: Side = battle.sides[index]
        self._foe = battle.sides[1 - index]

    @property
    def foe(self) -> Mon:
        foe = self._foe
        return foe.team[foe.active]

    @property
    def foe_shields(self) -> int:
        return self._foe.shields

    @property
    def foe_switch_wait(self) -> int:
        return self._foe.switch_wait

    @property
    def foe_busy(self) -> int:
        return self._foe.busy

    @property
    def foe_left(self) -> int:
        return self._foe.left()

    @property
    def foe_shown(self) -> list[Mon]:
        return [self._foe.team[j] for j in self._foe.shown]

    @property
    def turn(self) -> int:
        return self._battle.turn

    def legal(self) -> list[int]:
        me, mon = self.me, self.me.mon
        out = [FAST]
        out += [CHARGED[k] for k, move in enumerate(mon.build.charged) if mon.energy >= move.energy]
        if me.switch_wait == 0:
            out += [SWITCH[j] for j in me.bench()]
        return out


class Battle:
    def __init__(self, team_a: list, team_b: list, agent_a, agent_b,
                 seed: int | None = None, shields: tuple[int, int] = (SHIELDS, SHIELDS),
                 switch_wait: tuple[int, int] = (0, 0), record: bool = False):
        """Teams are lists of Builds (fresh Pokémon) or Mons (to start from a given state)."""
        teams = [[m if isinstance(m, Mon) else Mon(m) for m in team] for team in (team_a, team_b)]
        self.sides = [Side(teams[0], shields[0]), Side(teams[1], shields[1])]
        self.sides[0].switch_wait, self.sides[1].switch_wait = switch_wait
        self.agents = [agent_a, agent_b]
        self.views = [View(self, 0), View(self, 1)]
        self.rng = random.Random(seed)
        self.turn = 0
        self.winner: int | None = None
        self.hits: list | None = [] if record else None  # (side, move id, damage) for every move that lands
        # Optional agent hooks, for players that learn how the opponent plays.
        self._saw_throw = [getattr(a, "saw_throw", None) for a in self.agents]
        self._saw_shield = [getattr(a, "saw_shield", None) for a in self.agents]
        # A player with sees_move = True is told which charged move it is deciding whether to shield.
        self._sees_move = [getattr(a, "sees_move", False) for a in self.agents]
        self.log: list | None = [] if record else None

    def clone(self, agent_a, agent_b) -> Battle:
        """The same position, down to the dice, with the given players: for trying out what happens next."""
        twin = Battle.__new__(Battle)
        twin.sides = [side.copy() for side in self.sides]
        twin.agents = [agent_a, agent_b]
        twin.views = [View(twin, 0), View(twin, 1)]
        twin.rng = random.Random()
        twin.rng.setstate(self.rng.getstate())
        twin.turn, twin.winner, twin.log, twin.hits = self.turn, self.winner, None, None
        twin._saw_throw = [getattr(a, "saw_throw", None) for a in twin.agents]
        twin._saw_shield = [getattr(a, "saw_shield", None) for a in twin.agents]
        twin._sees_move = [getattr(a, "sees_move", False) for a in twin.agents]
        return twin

    def run(self) -> int:
        """Play to the end. Returns 0 or 1 for the winning side, DRAW for a draw."""
        while self.winner is None:
            self.step()
        return self.winner

    def _note(self, side: int, text: str) -> None:
        if self.log is not None:
            self.log.append((self.turn, side, text))

    def _check(self, i: int, action: int) -> None:
        side, mon = self.sides[i], self.sides[i].mon
        if action == FAST:
            return
        if action in CHARGED:
            k = action - CHARGED[0]
            if k < len(mon.build.charged) and mon.energy >= mon.build.charged[k].energy:
                return
        elif action in SWITCH:
            if side.switch_wait == 0 and (action - SWITCH[0]) in side.bench():
                return
        raise ValueError(f"side {i} chose illegal action {action} with {mon}")

    def _enter(self, i: int, slot: int) -> None:
        side = self.sides[i]
        side.active = slot
        if slot not in side.shown:
            side.shown.append(slot)
        self._note(i, f"sends in {side.mon}")

    def _throw(self, i: int, k: int) -> None:
        me, foe = self.sides[i], self.sides[1 - i]
        user, target = me.mon, foe.mon
        rule = user.build.rule
        if rule and rule.get("trigger") == "activate_charged" and _triggers(rule, user.build.charged[k]):
            change_form(user, rule["alternativeFormId"])  # Aegislash takes Blade form to strike
        move = user.build.charged[k]
        # The defender chooses before the cost comes off, so the energy it sees does not give the move away.
        energy, could_shield = user.energy, foe.shields > 0
        if not could_shield:
            shielded = False
        elif self._sees_move[1 - i]:
            shielded = bool(self.agents[1 - i].shield(self.views[1 - i], energy, move))
        else:
            shielded = bool(self.agents[1 - i].shield(self.views[1 - i], energy))
        user.energy -= move.energy
        if self._saw_throw[1 - i]:
            self._saw_throw[1 - i](self.views[1 - i], move, energy, could_shield)  # the move shows once thrown
        if could_shield and self._saw_shield[i]:
            self._saw_shield[i](self.views[i], shielded)
        guard = target.build.rule
        disguised = False
        if shielded:
            foe.shields -= 1
            dealt = 1
            if guard and guard.get("trigger") == "activate_shield":
                change_form(target, guard["alternativeFormId"])  # Aegislash back to Shield form
        elif guard and guard.get("trigger") == "charged_move_damage" and guard.get("effect") == "protect" and not move.instant:
            dealt, disguised = 1, True  # Mimikyu's disguise takes the hit
        else:
            dealt = damage(user, move, target)
        target.hp -= dealt
        self._note(i, f"{user.build.name} throws {move.name}: " + ("shielded" if shielded else
                                                                     "disguise busted" if disguised else f"{dealt} damage"))
        if self.hits is not None:
            self.hits.append((i, move.id, dealt))
        if move.buff_chance and (move.buff_chance >= 1 or self.rng.random() < move.buff_chance):
            apply_buffs(user, target, move)
        if rule:
            self._after_charged(user, move)
        if guard and not shielded and not move.instant:
            if target.build.gulp is not None:
                self._gulp(1 - i, target, user)
            elif guard.get("trigger") == "charged_move_damage":
                change_form(target, guard["alternativeFormId"])

    def _after_charged(self, user: Mon, move: Move) -> None:
        """Form changes after a charged move: Cramorant after Surf or Dive, Morpeko after any, back after Gulp Missile."""
        rule = user.build.rule
        if not rule or rule.get("trigger") != "charged_move" or not _triggers(rule, move):
            return
        new = rule["alternativeFormId"]
        if new == "variable":  # Cramorant: Gulping above half health, Gorging at half or below
            new = user.build.home + ("_gulping" if user.hp / user.build.hp > 0.5 else "_gorging")
        elif rule.get("type") == "toggle" and MORPEKO_TOGGLES:
            new = rule["defaultFormId"] if user.build.species_id == rule["alternativeFormId"] else rule["alternativeFormId"]
        change_form(user, new)

    def _gulp(self, i: int, cramorant: Mon, target: Mon) -> None:
        """A Gulping or Gorging Cramorant hit by a charged move spits its catch: a share of the attacker's health,
        a stat drop, and back to its usual form. It cannot be shielded and comes even if Cramorant fainted."""
        move = cramorant.build.gulp
        dealt = int(move.power / 100 * target.build.hp) + 1
        target.hp -= dealt
        self._note(i, f"{cramorant.build.name} fires {move.name}: {dealt} damage")
        if self.hits is not None:
            self.hits.append((i, move.id, dealt))
        apply_buffs(cramorant, target, move)
        self._after_charged(cramorant, move)

    def step(self) -> None:
        # Written for speed: this runs millions of times inside play-outs. The rules are in the module header.
        agents, views = self.agents, self.views
        s0, s1 = self.sides

        # Both players choose at once; a player in the middle of a fast move has no choice.
        a0 = a1 = None
        if s0.busy == 0:
            a0 = agents[0].act(views[0])
            if a0 != FAST:
                self._check(0, a0)
        if s1.busy == 0:
            a1 = agents[1].act(views[1])
            if a1 != FAST:
                self._check(1, a1)

        first_switch = SWITCH[0]
        if a0 is not None and a0 >= first_switch:
            leave_field(s0.team[s0.active])
            s0.switch_wait = SWITCH_TURNS
            self._enter(0, a0 - first_switch)
        if a1 is not None and a1 >= first_switch:
            leave_field(s1.team[s1.active])
            s1.switch_wait = SWITCH_TURNS
            self._enter(1, a1 - first_switch)

        thrown = 0
        throws0, throws1 = a0 in CHARGED, a1 in CHARGED
        if throws0 or throws1:
            order = (0, 1)
            if throws0 and throws1:
                a, b = s0.team[s0.active].build.cmp_atk, s1.team[s1.active].build.cmp_atk
                if b > a or (a == b and self.rng.random() < 0.5):
                    order = (1, 0)
            for i in order:
                action = a0 if i == 0 else a1
                if action in CHARGED:
                    side = s0 if i == 0 else s1
                    if side.team[side.active].hp > 0:
                        self._throw(i, action - CHARGED[0])
                        thrown += 1

        # Fast moves: start new ones, then land those that finish this turn or were cut short by a charged move.
        m0, m1 = s0.team[s0.active], s1.team[s1.active]
        land0 = land1 = False
        if a0 == FAST:
            s0.busy = m0.build.fast.turns
        if s0.busy:
            s0.busy -= 1
            if s0.busy == 0 or thrown:
                s0.busy = 0
                land0 = True
        if a1 == FAST:
            s1.busy = m1.build.fast.turns
        if s1.busy:
            s1.busy -= 1
            if s1.busy == 0 or thrown:
                s1.busy = 0
                land1 = True
        if land0 or land1:
            both_up = m0.hp > 0 and m1.hp > 0  # both hits are worked out before either is applied
            d0 = damage(m0, m0.build.fast, m1) if land0 and both_up else None
            d1 = damage(m1, m1.build.fast, m0) if land1 and both_up else None
            if d0 is not None:
                if self.hits is not None:
                    self.hits.append((0, m0.build.fast.id, d0))
                m1.hp -= d0
                energy = m0.energy + m0.build.fast.energy_gain
                m0.energy = energy if energy < ENERGY_CAP else ENERGY_CAP
            if d1 is not None:
                if self.hits is not None:
                    self.hits.append((1, m1.build.fast.id, d1))
                m0.hp -= d1
                energy = m1.energy + m1.build.fast.energy_gain
                m1.energy = energy if energy < ENERGY_CAP else ENERGY_CAP

        elapsed = 1 + CHARGED_TURNS * thrown
        self.turn += elapsed
        wait = s0.switch_wait
        if wait:
            s0.switch_wait = wait - elapsed if wait > elapsed else 0
        wait = s1.switch_wait
        if wait:
            s1.switch_wait = wait - elapsed if wait > elapsed else 0

        if m0.hp <= 0 or m1.hp <= 0:
            sides = self.sides
            fainted = [i for i in (0, 1) if sides[i].mon.hp <= 0]
            for i in fainted:
                self._note(i, f"{sides[i].mon.build.name} faints")
            out = [i for i in fainted if sides[i].left() == 0]
            if out:
                self.winner = DRAW if len(out) == 2 else 1 - out[0]
                return
            picks = [(i, agents[i].replace(views[i])) for i in fainted]
            for i, slot in picks:
                if slot not in sides[i].bench():
                    raise ValueError(f"side {i} chose illegal replacement {slot}")
                self._enter(i, slot)
            s0.busy = s1.busy = 0

        if self.turn >= MAX_TURNS:
            self.winner = self._on_time()

    def _on_time(self) -> int:
        def standing(side: Side) -> tuple[int, float]:
            return (side.left(), sum(max(m.hp, 0) / m.build.hp for m in side.team))

        a, b = standing(self.sides[0]), standing(self.sides[1])
        return DRAW if a == b else (0 if a > b else 1)
