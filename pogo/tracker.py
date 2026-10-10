"""A running picture of one battle, built from what the screen shows.

The Tracker starts each game from scratch, knowing only our own team. Every look
at the screen is passed in as an Observation; the Tracker works out what must
have happened since the last look (their fast moves landing, which charged move
they threw, switches, faints) and updates its picture: health, energy, shields,
switch timers and where the opponent is in their fast move. Things the screen
never shows are counted: the opponent's energy is kept as a range, because a
shielded charged move does not say which move it was.

The picture is offered to a player through view(), which looks like the View the
simulator gives, so the same strategy runs on either. With a path, every event
is also written to a file for that game, one line each.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .battle import CHARGED, CHARGED_TURNS, ENERGY_CAP, FAST, SWITCH, Mon, Side, apply_buffs, damage
from .gamedata import Build, GameData

TURN = 0.5  # seconds
SWITCH_SECONDS = 45.0


@dataclass
class Observation:
    """One look at the screen. Leave a field as None when it could not be read this time."""

    t: float  # seconds since the battle started
    my_species: str | None = None
    my_hp: float | None = None  # filled share of my health bar
    foe_species: str | None = None
    foe_hp: float | None = None
    my_shields: int | None = None
    foe_shields: int | None = None
    my_left: int | None = None  # Pokémon not yet fainted
    foe_left: int | None = None
    my_energy: float | None = None  # from how full my charged-move buttons are
    my_switch: float | None = None  # seconds left on my switch countdown
    my_cp: int | None = None
    foe_cp: int | None = None
    my_charged: int | None = None  # I threw this charged move (0 or 1) since the last look
    foe_charged: bool = False  # they threw a charged move since the last look
    foe_move: str | None = None  # its id or name, if the screen showed it


class Foe:
    """What we believe about one opposing Pokémon."""

    def __init__(self, build: Build):
        self.mon = Mon(build)
        self.lo = self.hi = 0  # range their energy must lie in
        self.used: dict[str, int] = {}  # charged moves we have seen them throw, and how often
        self.cp: int | None = None
        self.fast_from = "guessed"  # "inferred" once the steps in our health bar have shown which fast move it is
        # Quiet looks, for working out the fast move: my Pokémon hit, fighting turns covered, health lost,
        # and whether this look starts a new unbroken stretch.
        self.steps: list[tuple[Mon, int, int, bool]] = []
        self.base = (0, 0)  # their energy range when the count last restarted (at their last charged move)
        self.lost: list[tuple[Mon | None, int]] = []  # since then: my Pokémon and the health it lost, or (None, hits)
        self.clock = 0  # fighting turns it has spent on the field since the count last restarted
        self.ruled_out: set[str] = set()  # fast moves that could not have paid for a charged move it threw
        self.misfit: dict[str, float] = {}  # how badly each fast move it could have fits those steps; lower is better

    def gain(self, amount: int) -> None:
        self.lo, self.hi = min(ENERGY_CAP, self.lo + amount), min(ENERGY_CAP, self.hi + amount)
        self.mon.energy = (self.lo + self.hi) // 2

    def by_clock(self) -> int:
        """A second opinion on their energy: what they would have if they never paused between fast moves."""
        fast = self.mon.build.fast
        return min(ENERGY_CAP, sum(self.base) // 2 + self.clock // fast.turns * fast.energy_gain)

    def spend(self, costs: list[int]) -> None:
        """They threw a charged move with one of these costs."""
        costs = [c for c in costs if c <= self.hi] or [min(costs)]
        self.lo = min(max(self.lo, c) - c for c in costs)
        self.hi = max(self.hi, min(costs)) - min(costs)
        self.mon.energy = (self.lo + self.hi) // 2


class TrackedView:
    """The Tracker's picture, in the shape the players expect."""

    def __init__(self, tracker: Tracker):
        self._t = tracker

    @property
    def me(self) -> Side:
        return self._t.me

    @property
    def foe(self) -> Mon:
        return self._t.foe.mon

    @property
    def foe_shields(self) -> int:
        return self._t.foe_shields

    @property
    def foe_switch_wait(self) -> int:
        return max(0, round((self._t.foe_switch_at - self._t.t) / TURN))

    @property
    def foe_busy(self) -> int:
        """Turns left on the fast move they have in progress, assuming they attack without pause."""
        length = self._t.foe.mon.build.fast.turns
        k = (self._t.turn - self._t.beat) % length
        return 0 if k == 0 else length - k

    @property
    def foe_left(self) -> int:
        return self._t.foe_left

    @property
    def foe_shown(self) -> list[Mon]:
        return [self._t.foes[s].mon for s in self._t.order]

    @property
    def turn(self) -> int:
        return round(self._t.t / TURN)

    def legal(self) -> list[int]:
        me, mon = self._t.me, self._t.me.mon
        out = [FAST] + [CHARGED[k] for k, move in enumerate(mon.build.charged) if mon.energy >= move.energy]
        if me.switch_wait == 0:
            out += [SWITCH[j] for j in me.bench()]
        return out


class Tracker:
    def __init__(self, gd: GameData, my_team: list[Build], path: Path | None = None,
                 moves_known: list[bool] | None = None):
        """my_team may be incomplete (footage of someone else's game): Pokémon are added as they appear.
        moves_known says, per Pokémon, whether its moves come from a team sheet or are the usual ones assumed."""
        self.gd = gd
        self.me = Side([Mon(b) for b in my_team])
        self.my_moves_known = list(moves_known) if moves_known else [True] * len(my_team)
        self.my_seen_first = [False] * len(my_team)  # True for Pokémon we only learnt of from the screen
        self.my_used: dict[tuple[int, int], int] = {}
        self.my_cp: dict[int, int] = {}
        self.my_left = 3
        self.warnings = 0
        self.foes: dict[str, Foe] = {}
        self.order: list[str] = []  # opposing species in the order they appeared
        self.foe: Foe | None = None  # their active Pokémon
        self.foe_shields = 2
        self.foe_left = 3
        self.t = 0.0
        self.turn = 0  # fighting turns so far; charged moves stop this clock
        self.beat = 0  # fighting turn on which their fast-move rhythm last restarted
        self.taken = 0.0  # health I have lost that is not yet matched to a whole fast move of theirs
        self.dealt = 0.0  # the same for the health they have lost to my fast moves
        self.hp_turn = 0  # fighting turn at which my health was last read
        self.quiet = False  # the last look had no charged move and no change of Pokémon
        self.stretch = False  # an unbroken run of quiet looks is under way
        self.my_switch_at = 0.0  # time at which my switch is ready again
        self.foe_switch_at = 0.0
        self._file = open(path, "w") if path else None
        self._note(0.0, "start", my_team=[b.species_id for b in my_team])

    def view(self) -> TrackedView:
        return TrackedView(self)

    def close(self, result: str | None = None) -> None:
        if self._file:
            self._note(self.t, "end", result=result)
            self._file.close()
            self._file = None

    def _note(self, t: float, event: str, **details) -> None:
        if self._file:
            self._file.write(json.dumps({"t": round(t, 2), "event": event, **details}) + "\n")

    # each look

    def tick(self, t: float) -> None:
        """No usable look this time: just let the clocks run."""
        turns = round((t - self.t) / TURN)
        if 0 < turns <= 3:  # a longer gap means a charged move is playing, which stops the turn clock
            self.turn += turns
            if self.foe:
                self.foe.clock += turns
        self.t = t
        self.me.switch_wait = max(0, round((self.my_switch_at - t) / TURN))

    def update(self, obs: Observation) -> None:
        me = self.me
        thrown = int(obs.foe_charged) + int(obs.my_charged is not None)
        turns = max(0, round((obs.t - self.t) / TURN) - CHARGED_TURNS * thrown)
        self.turn += turns
        if self.foe:
            self.foe.clock += turns
        my_shields_before, foe_shields_before = me.shields, self.foe_shields
        if obs.my_shields is not None:
            me.shields = obs.my_shields
        if obs.foe_shields is not None:
            self.foe_shields = obs.foe_shields

        # A Pokémon that just fainted to a fast move still paid out energy for that last hit.
        was_mine, was_theirs = me.mon, self.foe
        i_changed = self._my_active(obs)
        they_changed = self._their_active(obs)
        if obs.my_left is not None:
            self.my_left = obs.my_left
        if obs.foe_left is not None:
            self.foe_left = obs.foe_left
        if obs.my_cp is not None:
            self.my_cp[me.active] = obs.my_cp
        if obs.foe_cp is not None and self.foe is not None:
            self.foe.cp = obs.foe_cp
        if self.foe is None:
            self.t = obs.t
            return
        if i_changed == "faint" and was_theirs and not obs.foe_charged and they_changed != "faint":
            was_theirs.gain(was_theirs.mon.build.fast.energy_gain)
            was_theirs.lost.append((None, 1))
        if they_changed == "faint" and obs.my_charged is None and i_changed != "faint":
            was_mine.energy = min(ENERGY_CAP, was_mine.energy + was_mine.build.fast.energy_gain)
        mon, foe = me.mon, self.foe

        # What they did to me, from my health bar. After a switch the drop is measured on the Pokémon now in.
        quiet = not thrown and not i_changed and not they_changed
        if obs.my_hp is not None:
            hp = round(obs.my_hp * mon.build.hp)
            drop = mon.hp - hp
            mon.hp = hp
            if they_changed != "faint" and i_changed != "faint":
                if quiet and self.quiet and self.turn > self.hp_turn:
                    foe.steps.append((mon, self.turn - self.hp_turn, drop, not self.stretch))
                    self.stretch = True
                self._their_attacks(obs, drop, my_shields_before)
            elif obs.foe_charged and they_changed != "faint":
                self._their_attacks(obs, None, my_shields_before)
            self.hp_turn = self.turn
        elif obs.foe_charged and they_changed != "faint":
            self._their_attacks(obs, None, my_shields_before)

        # What I did to them, from their health bar and my own energy.
        if obs.my_charged is not None and i_changed != "faint" and obs.my_charged < len(mon.build.charged):
            move = mon.build.charged[obs.my_charged]
            mon.energy = max(0, mon.energy - move.energy)
            if move.buff_chance >= 1:
                apply_buffs(mon, foe.mon, move)
            self.my_used[me.active, obs.my_charged] = self.my_used.get((me.active, obs.my_charged), 0) + 1
            blocked = self.foe_shields < foe_shields_before
            self._note(obs.t, "my_charged", move=move.id, shielded=blocked)
            expected = 1 if blocked else damage(mon, move, foe.mon)
            if obs.foe_hp is not None and they_changed != "faint":
                seen = round(obs.foe_hp * foe.mon.build.hp)
                if foe.mon.hp - seen < 0.6 * expected:  # their bar has not caught up with the hit yet
                    foe.mon.hp = max(0, foe.mon.hp - expected)
                    obs = Observation(**{**asdict(obs), "foe_hp": None})
        if obs.foe_hp is not None:
            hp = round(obs.foe_hp * foe.mon.build.hp)
            if obs.my_charged is None and not i_changed and they_changed != "faint":
                landed, self.dealt = _whole_hits(self.dealt + foe.mon.hp - hp, damage(mon, mon.build.fast, foe.mon))
                mon.energy = min(ENERGY_CAP, mon.energy + landed * mon.build.fast.energy_gain)
            foe.mon.hp = hp
        if obs.my_energy is not None and abs(obs.my_energy - mon.energy) > 4:
            mon.energy = int(round(obs.my_energy))  # the buttons are the better witness

        if thrown or i_changed or they_changed:
            self.beat = self.turn  # everyone starts afresh after a charged move or a change of Pokémon
            self.taken = self.dealt = 0.0
            self.hp_turn = self.turn
        self.quiet = quiet
        if not quiet:
            self.stretch = False
        if obs.my_switch is not None:
            self.my_switch_at = obs.t + obs.my_switch
        me.switch_wait = max(0, round((self.my_switch_at - obs.t) / TURN))
        self.t = obs.t

    def _my_active(self, obs: Observation) -> str | None:
        """Notice my active Pokémon changing. Returns "switch", "faint" or None."""
        me = self.me
        if obs.my_species is None or obs.my_species == me.mon.build.species_id:
            return None
        slot = next((j for j, m in enumerate(me.team) if m.build.species_id == obs.my_species), None)
        if slot is None:
            if len(me.team) >= 3:
                return None
            me.team.append(Mon(self.gd.default(obs.my_species, allow_forms=True)))  # a team-mate we had not been told about
            self.my_moves_known.append(False)
            self.my_seen_first.append(True)
            slot = len(me.team) - 1
            self._note(obs.t, "my_seen", species=obs.my_species)
        if obs.my_left is not None and obs.my_left < self.my_left:
            how = "faint"
            me.mon.hp = 0
            self._note(obs.t, "my_faint", next=obs.my_species)
        else:
            how = "switch"
            me.mon.atk_stage = me.mon.def_stage = 0
            self.my_switch_at = obs.t + SWITCH_SECONDS
            self._note(obs.t, "my_switch", to=obs.my_species)
        me.active = slot
        return how

    def _their_active(self, obs: Observation) -> str | None:
        """Notice their active Pokémon changing. Returns "switch", "faint", "first" or None."""
        if obs.foe_species is None or (self.foe and obs.foe_species == self.foe.mon.build.species_id):
            return None
        how = "first"
        if self.foe is not None:
            if obs.foe_left is not None and obs.foe_left < self.foe_left:
                how = "faint"
                self.foe.mon.hp = 0
                self._note(obs.t, "foe_faint", next=obs.foe_species)
            else:
                how = "switch"
                self.foe.mon.atk_stage = self.foe.mon.def_stage = 0
                self.foe_switch_at = obs.t + SWITCH_SECONDS
                self._note(obs.t, "foe_switch", to=obs.foe_species)
        if obs.foe_species not in self.foes:
            # Assume the usual moveset and typical stats for the species until shown otherwise.
            self.foes[obs.foe_species] = Foe(self.gd.default(obs.foe_species, allow_forms=True))
            self.order.append(obs.foe_species)
            self._note(obs.t, "foe_seen", species=obs.foe_species)
        self.foe = self.foes[obs.foe_species]
        return how

    def _learn_move(self, t: float, foe: Foe, name: str):
        """They threw a charged move we had not assumed: give them that move in place of an unconfirmed one."""
        build = foe.mon.build
        entry = self.gd.species[build.species_id]
        move = next((self.gd.moves[i] for i in entry["chargedMoves"]
                     if i in self.gd.moves and name in (i, self.gd.moves[i].name)), None)
        if move is None:
            return None
        kept = [m.id for m in build.charged if foe.used.get(m.id)]
        spare = [m.id for m in build.charged if not foe.used.get(m.id)]
        charged = ([move.id] + kept + spare)[:max(len(build.charged), 1)]
        foe.mon.build = self.gd.build(build.species_id, [build.fast.id, *charged], level=build.level, ivs=build.ivs, allow_forms=True)
        self._note(t, "foe_move_learned", species=build.species_id, move=move.id)
        return move

    def _fit_fast(self, t: float, foe: Foe) -> None:
        """Work out their fast move from the size and rhythm of the steps in my health bar."""
        if sum(1 for step in foe.steps if step[2] > 0) < 3:
            return
        build = foe.mon.build
        options = [m for m in self._fast_options(foe) if m.id not in foe.ruled_out]
        stretches: list[tuple[Mon, list[tuple[int, int]]]] = []  # running totals of turns and health lost
        for target, turns, lost, starts in foe.steps:
            if starts or not stretches:
                stretches.append((target, [(turns, lost)]))
            else:
                run = stretches[-1][1]
                run.append((run[-1][0] + turns, run[-1][1] + lost))

        def misfit(move) -> float:
            """How far the health lost strays from this move landing on its beat without a pause."""
            off = total = 0.0
            for target, run in stretches:
                per_hit = damage(foe.mon, move, target)
                off += min(sum(abs(lost - (turns + phase) // move.turns * per_hit) for turns, lost in run)
                           for phase in range(move.turns))
                total += sum(lost for _, lost in run)
            return off / max(total, 1.0)

        scores = {m.id: misfit(m) for m in options}
        ranked = sorted(options, key=lambda m: scores[m.id])
        best = ranked[0]
        clear = len(ranked) < 2 or scores[best.id] < 0.6 * scores[ranked[1].id] - 0.05
        foe.misfit = {k: round(v, 2) for k, v in scores.items()}
        if not clear or scores[best.id] > 0.3:
            return  # not enough to tell them apart yet
        if best.id == build.fast.id:
            foe.fast_from = "inferred"
            return
        if sum(1 for step in foe.steps if step[2] > 0) < 4:
            return  # dropping the usual move takes a little more
        self._set_fast(t, foe, best)

    def _fast_options(self, foe: Foe) -> list:
        return [self.gd.moves[i] for i in self.gd.species[foe.mon.build.species_id]["fastMoves"] if i in self.gd.moves]

    def _set_fast(self, t: float, foe: Foe, move) -> None:
        """Change the fast move we believe they have, and count their energy again from where the count restarted."""
        build = foe.mon.build
        foe.mon.build = self.gd.build(build.species_id, [move.id, *(m.id for m in build.charged)], level=build.level,
                                      ivs=build.ivs, allow_forms=True)
        foe.fast_from = "inferred"
        gained, left_over = 0, 0.0
        for target, lost in foe.lost:
            if target is None:
                hits = lost
            else:
                hits, left_over = _whole_hits(left_over + lost, damage(foe.mon, move, target))
            gained += hits * move.energy_gain
        foe.lo, foe.hi = foe.base
        foe.gain(gained)
        if foe is self.foe:
            self.taken, self.beat = left_over, self.turn
        self._note(t, "foe_fast_learned", species=build.species_id, move=move.id, misfit=foe.misfit,
                   ruled_out=sorted(foe.ruled_out))

    def _rule_out_fast(self, t: float, foe: Foe, cost: int) -> None:
        """They just paid this much for a charged move. A fast move that could not have earned it, even landing
        without a pause for every turn they have been on the field, is not the one they have."""
        options = self._fast_options(foe)
        can_pay = [m for m in options if foe.base[1] + (foe.clock // m.turns + 1) * m.energy_gain >= cost]
        if not can_pay or len(can_pay) == len(options):
            return
        foe.ruled_out |= {m.id for m in options} - {m.id for m in can_pay}
        if foe.mon.build.fast.id in foe.ruled_out:
            self._set_fast(t, foe, min(can_pay, key=lambda m: foe.misfit.get(m.id, 9.0)))
        elif len(can_pay) == 1:
            foe.fast_from = "inferred"

    def _their_attacks(self, obs: Observation, drop: int | None, my_shields_before: int) -> None:
        """Split a drop in my health into their fast moves and, if they threw one, their charged move."""
        mon, foe = self.me.mon, self.foe
        fast = foe.mon.build.fast
        per_hit = damage(foe.mon, fast, mon)
        if not obs.foe_charged:
            if drop:
                # A hit can show up spread over two looks, so what is left over waits for the next one.
                lost = self.taken + drop
                landed, self.taken = _whole_hits(lost, per_hit)
                landed = min(landed, (self.turn - self.hp_turn) // fast.turns + 1)  # no more than the time allows
                if (abs(lost - landed * per_hit) if landed else -lost) > max(1.0, 0.3 * per_hit):
                    # The drop is not a whole number of their assumed fast move: wrong move, wrong stats, or a misread.
                    self.warnings += 1
                    self._note(obs.t, "unexplained", what="my health drop", drop=drop, expected_per_hit=per_hit)
                foe.lost.append((mon, drop))
                if landed:
                    foe.gain(landed * fast.energy_gain)
                    # Keep their rhythm if these hits fit it; otherwise restart it from now.
                    on_beat = self.beat + landed * fast.turns
                    self.beat = on_beat if 0 <= self.turn - on_beat < fast.turns else self.turn
            self._fit_fast(obs.t, foe)
            return

        moves = [m for m in foe.mon.build.charged if m.energy <= foe.hi] or list(foe.mon.build.charged)
        shielded = self.me.shields < my_shields_before
        named = [m for m in foe.mon.build.charged if obs.foe_move in (m.id, m.name)]
        if obs.foe_move and not named:
            learned = self._learn_move(obs.t, foe, obs.foe_move)
            if learned:
                named = [learned]
        extra = 0  # their fast move in progress lands with the charged move
        if named:
            moves = named
            if drop is not None:
                expected = 1 if shielded else damage(foe.mon, named[0], mon)
                extra = min(1, max(0, round((drop - expected) / per_hit)))
                if drop < 0.6 * expected:  # the bar is still showing the health from before the hit
                    mon.hp = max(0, mon.hp + drop - expected)
        elif shielded:
            if drop is not None:
                extra = min(1, max(0, round((drop - 1) / per_hit)))
        elif drop is not None:
            best = min(((abs(drop - damage(foe.mon, m, mon) - j * per_hit), k, j)
                        for k, m in enumerate(moves) for j in (0, 1, 2)))
            moves, extra = [moves[best[1]]], best[2]
        self._rule_out_fast(obs.t, foe, min(m.energy for m in moves))
        before, by_clock = [foe.lo, foe.hi], foe.by_clock()
        if foe.hi < min(m.energy for m in moves) <= by_clock:
            foe.hi = by_clock  # the count missed hits while the bars were hidden; the clock is the ceiling
        foe.spend([m.energy for m in moves])
        if extra:
            foe.gain(extra * fast.energy_gain)
        foe.base, foe.lost, foe.clock = (foe.lo, foe.hi), [], 0
        if len(moves) == 1:
            foe.used[moves[0].id] = foe.used.get(moves[0].id, 0) + 1
        if len(moves) == 1 and moves[0].buff_chance >= 1:
            apply_buffs(foe.mon, mon, moves[0])
        self._note(obs.t, "foe_charged", move=moves[0].id if len(moves) == 1 else None, shielded=shielded,
                   energy=[foe.lo, foe.hi], energy_before=before, energy_before_by_clock=by_clock)


def _whole_hits(lost: float, per_hit: int) -> tuple[int, float]:
    """How many whole fast moves a loss of health amounts to, and what is left over."""
    landed = max(0, round(lost / per_hit))
    return landed, (0.0 if landed else lost)  # only a part-hit waits; a mismatch must not pile up


def _pokemon(mon: Mon, known_from: str, moves_from: str, used: dict, stats_assumed: bool, cp: int | None,
             fast_from: str | None = None) -> dict:
    b = mon.build
    return {
        "species": b.species_id, "name": b.name, "types": list(b.types), "known_from": known_from,
        "cp": cp if cp is not None else b.cp, "cp_read_from_screen": cp is not None,
        "stats_assumed": stats_assumed, "level": b.level, "ivs": list(b.ivs),
        "hp": max(mon.hp, 0), "hp_max": b.hp, "hp_share": round(max(mon.hp, 0) / b.hp, 3),
        "energy": mon.energy, "fainted": mon.hp <= 0,
        "attack_stage": mon.atk_stage, "defense_stage": mon.def_stage,
        "fast_move": {"id": b.fast.id, "name": b.fast.name, "type": b.fast.type, "turns": b.fast.turns,
                      "energy_gain": b.fast.energy_gain, "known_from": fast_from or moves_from},
        "charged_moves": [{"id": m.id, "name": m.name, "type": m.type, "energy": m.energy,
                           "known_from": "seen" if used.get(m.id) else moves_from, "times_used": used.get(m.id, 0)}
                          for m in b.charged],
    }


def _move_facts(user: Mon, move, target: Mon, charged: bool) -> dict:
    """What a move does right now: damage on the Pokémon in front of it, stat changes included."""
    facts = {"id": move.id, "name": move.name, "type": move.type, "damage": damage(user, move, target)}
    if charged:
        facts["energy"] = move.energy
    else:
        facts.update(energy_gain=move.energy_gain, turns=move.turns)
    return facts


def _matchup(t: Tracker, full: bool) -> dict:
    """Every move in play between the two active Pokémon, with its damage and energy, from PvPoke's data."""
    mine, foe = t.me.mon, t.foe
    theirs = foe.mon
    out = {
        "ours": {
            "fast": _move_facts(mine, mine.build.fast, theirs, False),
            "charged": [dict(_move_facts(mine, m, theirs, True), ready=mine.energy >= m.energy) for m in mine.build.charged],
        },
        "theirs": {
            "stats_assumed": True,  # their damage on us can be off by a point or two until their stats are known
            "fast": _move_facts(theirs, theirs.build.fast, mine, False),
            "charged": [dict(_move_facts(theirs, m, mine, True), could_be_ready=foe.hi >= m.energy, surely_ready=foe.lo >= m.energy)
                        for m in theirs.build.charged],
        },
    }
    if full:  # everything their species can have, for when they turn out not to run the usual moves
        entry = t.gd.species[theirs.build.species_id]
        out["theirs"]["every_fast_move_possible"] = [_move_facts(theirs, t.gd.moves[i], mine, False)
                                                     for i in entry["fastMoves"] if i in t.gd.moves]
        out["theirs"]["every_charged_move_possible"] = [_move_facts(theirs, t.gd.moves[i], mine, True)
                                                        for i in entry["chargedMoves"] if i in t.gd.moves]
    return out


def state(tracker: Tracker, full: bool = False) -> dict:
    """The whole picture of the game right now, as plain data.

    known_from says how we know each thing: "team_sheet" (we were told), "seen" (the screen
    showed it) or "guessed" (the usual choice for that species, not yet confirmed).
    "matchup" gives the damage and energy of every move between the two active Pokémon;
    with full=True it also lists every move the opponent's species could have.
    """
    t, me = tracker, tracker.me
    mine = []
    for j, mon in enumerate(me.team):
        used = {mon.build.charged[k].id: n for (slot, k), n in t.my_used.items() if slot == j}
        mine.append(_pokemon(mon, "seen" if t.my_seen_first[j] else "team_sheet",
                             "team_sheet" if t.my_moves_known[j] else "guessed", used,
                             stats_assumed=not t.my_moves_known[j], cp=t.my_cp.get(j)))
    theirs = []
    for species in t.order:
        foe = t.foes[species]
        entry = _pokemon(foe.mon, "seen", "guessed", foe.used, stats_assumed=True, cp=foe.cp, fast_from=foe.fast_from)
        entry["energy_range"] = [foe.lo, foe.hi]
        entry["energy_by_clock"] = foe.by_clock()
        entry["fast_move"]["misfit"] = foe.misfit
        theirs.append(entry)
    view = t.view() if t.foe else None
    return {
        "t": round(t.t, 2), "fighting_turns": t.turn, "warnings": t.warnings,
        "matchup": _matchup(t, full) if t.foe else None,
        "me": {
            "active": me.active, "shields": me.shields, "left": t.my_left,
            "switch_ready_in": round(max(0.0, t.my_switch_at - t.t), 1), "pokemon": mine,
        },
        "opponent": {
            "active": t.order.index(t.foe.mon.build.species_id) if t.foe else None,
            "shields": t.foe_shields, "left": t.foe_left,
            "unseen": t.foe_left - sum(1 for f in t.foes.values() if f.mon.hp > 0),
            "switch_ready_in": round(max(0.0, t.foe_switch_at - t.t), 1),
            "fast_move_turns_left": view.foe_busy if view else None,
            "pokemon": theirs,
        },
    }


def describe(obs: Observation) -> dict:
    """An Observation as a plain dictionary without the empty fields, for logging."""
    return {k: v for k, v in asdict(obs).items() if v is not None and v is not False}
