"""Players for the battle simulator.

An agent answers three questions, each from a View of the battle:
    act(view)                 -> FAST, CHARGED[k] or SWITCH[slot], whenever it is free to act
    shield(view, foe_energy)  -> True to shield; it is not told which charged move is coming
    replace(view)             -> team slot to send in after a faint
"""
from __future__ import annotations

import copy
import random

from .battle import CHARGED, ENERGY_CAP, FAST, MAX_TURNS, SWITCH, SWITCH_TURNS, Battle, Mon, View, apply_buffs, damage


class Masher:
    """Throws a charged move the moment one is ready, always shields, never switches."""

    def act(self, view: View) -> int:
        mon, foe = view.me.mon, view.foe
        ready = [k for k, move in enumerate(mon.build.charged) if mon.energy >= move.energy]
        if not ready:
            return FAST
        return CHARGED[max(ready, key=lambda k: damage(mon, mon.build.charged[k], foe))]

    def shield(self, view: View, foe_energy: int) -> bool:
        return True

    def replace(self, view: View) -> int:
        return view.me.bench()[0]

    def clone(self) -> Masher:
        return self


_MASHER = Masher()
_seeds = random.Random(20261009)


def duel(mine: Mon, theirs: Mon, my_shields: int, their_shields: int, coming_in: bool = False) -> float:
    """Play out a one-on-one between two mashers from the given states.

    Returns my share of health left minus theirs, between -1 (I faint at their
    full health) and +1.
    """
    a, b = mine.copy(), theirs.copy()
    if coming_in:
        a.atk_stage = a.def_stage = 0  # a Pokémon coming in starts without stat changes
    Battle([a], [b], _MASHER, _MASHER, seed=0, shields=(my_shields, their_shields)).run()
    return max(a.hp, 0) / a.build.hp - max(b.hp, 0) / b.build.hp


_safety: dict = {}


def safety(build, field: list) -> float:
    """How well a fresh Pokémon holds up against the field on average: mean one-on-one margin at one shield each."""
    key = (build.uid, id(field))
    if key not in _safety:
        _safety[key] = sum(duel(Mon(build), Mon(other), 1, 1) for other in field) / len(field)
    return _safety[key]


def position_features(team: list[Mon], active: int, shields: int, switch_wait: int,
                      foe_unseen: int, foe_shields: int, turn: int, field: list) -> list[float]:
    """Numbers describing one side's remaining Pokémon against opponents it has not seen yet.

    Pokémon are described by health, energy and how well their kind holds up against
    the field, not by name, so the same model serves any team.
    """
    order = [team[active]] + sorted((m for j, m in enumerate(team) if j != active), key=lambda m: -m.hp / m.build.hp)
    x: list[float] = []
    for k in range(3):
        m = order[k] if k < len(order) else None
        if m is None or m.hp <= 0:
            x += [0.0, 0.0, 0.0, 0.0]
        else:
            x += [1.0, m.hp / m.build.hp, m.energy / ENERGY_CAP, 3.0 * safety(m.build, field)]
    return x + [shields / 2, switch_wait / SWITCH_TURNS, foe_unseen / 2, foe_shields / 2, turn / MAX_TURNS]


def fasts_to_wait(my_turns: int, foe_turns: int, foe_busy: int) -> int:
    """How many more fast moves to use before throwing a charged move, for the best timing.

    A fast move the opponent has in progress lands in full when a charged move
    is thrown, so the turns it had left are free turns for them. Throwing on the
    last turn of their fast move gives away none. Returns 0 to throw now.
    """
    phase = (foe_turns - foe_busy) % foe_turns  # turns into their fast move as this turn starts
    return min(range(foe_turns), key=lambda j: (foe_turns - 1 - (phase + j * my_turns) % foe_turns, j))


def solve_2x2(a: float, b: float, c: float, d: float) -> float:
    """How often to play the first row of the game [[a, b], [c, d]].

    The row player wants the payoff high and the column player wants it low,
    each choosing without seeing the other's choice. The answer is the mix the
    column player cannot take advantage of.
    """
    row_floor = (min(a, b), min(c, d))
    if max(row_floor) >= min(max(a, c), max(b, d)) - 1e-12:  # one row is simply right
        return 1.0 if row_floor[0] >= row_floor[1] else 0.0
    return min(1.0, max(0.0, (d - c) / (a - b - c + d)))


class Planner:
    """A rule-based player. Its parts can be set separately to measure them or to imitate a style.

    moves:    False throws whatever is ready; True saves for the better charged move once
              shields are down, takes knockouts with the cheapest move that does it, and
              does not waste a charged move on a Pokémon the next fast move will finish.
    timing:   holds a charged move for the turn that gives the opponent the fewest free
              turns, unless waiting risks fainting or wasting energy.
    bait:     what to throw into shields. "cheap" throws the cheapest move as soon as it
              is ready; "never" always goes for the biggest hit; "farm" builds energy for
              the dearer move, so the defender cannot tell which is coming, then throws
              the cheaper; "mix" does the same but weighs all four outcomes and varies;
              "read" does the same but picks by how often this opponent has shielded;
              "even" does the same but picks at random, half and half.
    shields:  "always"; "never" (until the last Pokémon); "threshold" shields hits that
              would knock out or take a large share of health; "lookahead" plays the rest
              of the visible battle both ways and shields only if that leaves it better off.
    guess:    for "lookahead", when either charged move could be coming: "worst" assumes
              the harder hit; "mix" weighs all four outcomes and varies; "read" goes by
              which one this opponent has thrown in that spot before.
    switches: plays out each one-on-one in advance to choose replacements and to leave a
              losing matchup when the switch timer allows.
    field:    the Pokémon opponents tend to bring. With it, a swap can weigh how well the
              incoming Pokémon holds up against whatever answers it (safe_weight 1) and
              not only how it does against the one in front of it (safe_weight 0).
    punish:   when the opponent's switch timer is running they cannot answer a swap, so
              bring the hardest counter and ignore safety.
    farm:     in a matchup that fast moves alone will win at little cost, keep the energy
              and throw only when it would overflow.
    sac:      keep a nearly fainted Pokémon as a third shield: swap it out before it
              goes down for nothing, and bring it back to take a charged move the
              opponent has ready.
    replace_by: choose the replacement after a faint by the one-on-one "outlook" or by
              playing the visible battle forward ("lookahead").
    value:    a trained ValueModel. With it (and a field), the lookahead judges what is
              left after the visible battle by the model's win chance against the
              opponent's unseen Pokémon, not by adding up health and shields.
    """

    def __init__(self, moves: bool = True, timing: bool = True, bait: str = "mix", shields: str = "lookahead",
                 guess: str = "read", switches: bool = True, shield_share: float = 0.4, shield_worth: float = 0.35,
                 energy_worth: float = 0.0, switch_margin: float = 0.35, seed: int | None = None,
                 expect_shield: float = 0.7, expect_bait: float = 0.5, belief: float = 2.0,
                 field: list | None = None, safe_weight: float = 0.0, bad_matchup: float = -0.2,
                 punish: bool = False, farm: bool = True, farm_cost: float = 0.35,
                 sac: bool = True, sac_margin: float = 0.1, replace_by: str = "outlook", value=None,
                 odds: bool = False, hold: bool = True, hold_cost: float = 0.5,
                 last_gasp: bool = True, timed_farm: bool = True):
        if bait not in ("cheap", "never", "farm", "mix", "read", "even"):
            raise ValueError(f"unknown bait rule {bait!r}")
        if shields not in ("always", "never", "threshold", "lookahead"):
            raise ValueError(f"unknown shield rule {shields!r}")
        if guess not in ("worst", "mix", "read"):
            raise ValueError(f"unknown guess rule {guess!r}")
        self.moves = moves
        self.timing = timing
        self.bait = bait
        self.shields = shields
        self.guess = guess
        self.switches = switches
        self.shield_share = shield_share  # threshold rule: shield a hit worth this share of full health
        self.shield_worth = shield_worth  # lookahead: one unused shield, in units of one full Pokémon
        self.energy_worth = energy_worth  # lookahead: 100 stored energy, in the same units
        self.switch_margin = switch_margin  # how much better a bench Pokémon must look
        self.bad_matchup = bad_matchup  # leave a matchup that looks worse than this
        self.field = field
        self.safe_weight = safe_weight if field else 0.0
        self.punish = punish
        self.farm = farm
        self.farm_cost = farm_cost  # farm if it costs no more than this share of current health
        # Hold a charged move that is ready and keep building energy for as long as the opponent cannot throw
        # one of theirs, provided their fast moves in that time cost no more than this share of current health.
        self.hold, self.hold_cost = hold, hold_cost
        # Throw before you faint: with a move ready and a knock-out coming before the next chance to act
        # (their fast moves, or a charged move that would not be blocked), throw now instead of taking the
        # energy down with the Pokémon.
        self.last_gasp = last_gasp
        # While farming or holding, plan the throw for a turn that suits the opponent's fast move instead of
        # farming until forced to throw at a bad moment.
        self.timed_farm = timed_farm
        self.sac = sac
        self.sac_margin = sac_margin
        self.replace_by = replace_by
        self.value = value if field else None
        # Weigh every charged move the opponent may have by its chance, where the view offers the chances
        # (the Tracker's does), instead of taking their usual two moves as certain.
        self.odds = odds
        self._sac_checked = None
        self.rng = random.Random(_seeds.getrandbits(32) if seed is None else seed)
        self._judged = None  # the matchup last considered for a switch
        # What this opponent has done so far, starting from an assumption worth `belief` observations.
        self._shield_seen = [expect_shield * belief, belief]  # times they shielded, of times they could
        self._bait_seen = [expect_bait * belief, belief]  # times they threw the softer move, of times either could come

    def clone(self) -> Planner:
        """A copy that will make the same choices from here, including the random ones."""
        twin = copy.copy(self)
        twin.rng = random.Random()
        twin.rng.setstate(self.rng.getstate())
        twin._shield_seen, twin._bait_seen = list(self._shield_seen), list(self._bait_seen)
        return twin

    # charged moves

    def _pick_move(self, view: View) -> int:
        mon, foe = view.me.mon, view.foe
        moves = mon.build.charged
        ready = [k for k, move in enumerate(moves) if mon.energy >= move.energy]
        if not ready:
            return FAST
        fast = mon.build.fast
        hit = [damage(mon, move, foe) for move in moves]
        if self.last_gasp:
            # Before anything else, including finishing them with a fast move that I may not live to land.
            both = mon.energy >= 2 * min(move.energy for move in moves)  # two throws need a turn more
            if self._doomed(view, fast.turns + int(both)):
                lethal = [k for k in ready if hit[k] >= foe.hp]
                return CHARGED[min(lethal, key=lambda k: moves[k].energy) if lethal else max(ready, key=lambda k: hit[k])]
        if foe.hp <= damage(mon, fast, foe):
            return FAST  # the fast move finishes it; keep the energy

        planned = False  # the farm or hold rule has already chosen this turn as the one to throw on
        if self.farm and mon.energy + fast.energy_gain <= ENERGY_CAP and self._can_farm(view):
            if not self.timed_farm:
                return FAST
            room = (ENERGY_CAP - mon.energy) // fast.energy_gain
            to_finish = -(-foe.hp // damage(mon, fast, foe))
            if to_finish <= room or self._latest_good_turn(view, room) > 0:
                return FAST  # fast moves finish it, or a better moment to throw is still ahead
            planned = True
        if not planned and self.hold and mon.energy + fast.energy_gain <= ENERGY_CAP:
            wait = self._hold_plan(view)
            if wait:
                return FAST
            planned = self.timed_farm and wait == 0

        def short_of(k: int) -> bool:
            """True if move k is not ready yet and it is safe to keep building towards it."""
            if k in ready:
                return False
            turns = -(-(moves[k].energy - mon.energy) // fast.energy_gain) * fast.turns
            return mon.energy + fast.energy_gain <= ENERGY_CAP and not self._may_faint(view, turns)

        undecided = None  # a pair of moves to choose between at the moment of throwing
        if view.foe_shields > 0:
            cheap = min(range(len(moves)), key=lambda k: moves[k].energy)
            dear = max(range(len(moves)), key=lambda k: moves[k].energy)
            if self.bait == "cheap" or moves[cheap].energy == moves[dear].energy:
                choice = min(ready, key=lambda k: moves[k].energy)
            elif self.bait == "never":
                choice = max(range(len(moves)), key=lambda k: hit[k])
                if short_of(choice):
                    return FAST
                if choice not in ready:
                    choice = max(ready, key=lambda k: hit[k])
            else:
                if short_of(dear):
                    return FAST  # keep the defender guessing: wait until either move could be coming
                choice = cheap
                if dear in ready and self.bait in ("mix", "read", "even"):
                    undecided = (cheap, dear)
        else:
            lethal = [k for k in ready if hit[k] >= foe.hp]
            if lethal:
                return CHARGED[min(lethal, key=lambda k: moves[k].energy)]
            choice = max(range(len(moves)), key=lambda k: hit[k] / moves[k].energy)
            if short_of(choice):
                return FAST
            if choice not in ready:
                choice = max(ready, key=lambda k: hit[k])

        if self.timing and not planned:
            wait = fasts_to_wait(fast.turns, foe.build.fast.turns, view.foe_busy)
            if (wait and mon.energy + wait * fast.energy_gain <= ENERGY_CAP
                    and not self._may_faint(view, wait * fast.turns)):
                return FAST
        if undecided and self.bait == "even":
            choice = self.rng.choice(undecided)
        elif undecided:
            cheap, dear = undecided
            value = {(k, s): self._after_throw(view, k, s) for k in undecided for s in (True, False)}
            if self.bait == "read":
                p = self._shield_seen[0] / self._shield_seen[1]  # how likely they are to shield
                choice = max(undecided, key=lambda k: p * value[k, True] + (1 - p) * value[k, False])
            else:
                odds = solve_2x2(value[cheap, True], value[cheap, False], value[dear, True], value[dear, False])
                choice = cheap if self.rng.random() < odds else dear
        return CHARGED[choice]

    def saw_shield(self, view: View, shielded: bool) -> None:
        self._shield_seen[0] += shielded
        self._shield_seen[1] += 1

    def saw_throw(self, view: View, move, foe_energy: int, could_shield: bool) -> None:
        mon, foe = view.me.mon, view.foe
        threats = [m for m in foe.build.charged if m.energy <= foe_energy]
        if could_shield and len(threats) > 1:  # with no shield to draw out, the choice says nothing about baiting
            soft = min(threats, key=lambda m: damage(foe, m, mon))
            hard = max(threats, key=lambda m: damage(foe, m, mon))
            if soft is not hard:
                self._bait_seen[0] += move is soft
                self._bait_seen[1] += 1

    def _can_farm(self, view: View) -> bool:
        """Can I hold my energy cheaply, until it is full or fast moves alone finish the opponent?"""
        mon, foe = view.me.mon, view.foe
        fast, foe_fast = mon.build.fast, foe.build.fast
        to_finish = -(-foe.hp // damage(mon, fast, foe)) * fast.turns
        to_fill = -(-(ENERGY_CAP - mon.energy) // fast.energy_gain) * fast.turns
        turns = min(to_finish, to_fill)
        phase = (foe_fast.turns - view.foe_busy) % foe_fast.turns
        landing = (phase + turns) // foe_fast.turns
        energy = foe.energy + landing * foe_fast.energy_gain
        throws = energy // min(m.energy for m in foe.build.charged)
        incoming = landing * damage(foe, foe_fast, mon) + throws * max(damage(foe, m, mon) for m in foe.build.charged)
        return incoming <= self.farm_cost * mon.hp

    def _hold_plan(self, view: View) -> int | None:
        """How many more fast moves to use before throwing, under the owner's rule: farm until they are about
        to get a move, unless it hurts. None when the rule does not apply (they have a move already, or the
        wait costs too much health); 0 to throw now."""
        mon, foe = view.me.mon, view.foe
        fast, foe_fast = mon.build.fast, foe.build.fast
        need = min(m.energy for m in foe.build.charged) - foe.energy
        if need <= 0:
            return None  # they have a move already
        hits = -(-need // foe_fast.energy_gain)  # their fast moves still to land before they do
        reach = (view.foe_busy or foe_fast.turns) + (hits - 1) * foe_fast.turns  # turns until then, counting this one
        if hits * damage(foe, foe_fast, mon) > self.hold_cost * mon.hp:
            return None
        room = min((reach - 1) // fast.turns, (ENERGY_CAP - mon.energy) // fast.energy_gain)
        if not self.timed_farm:
            return 1 if room >= 1 else 0
        return self._latest_good_turn(view, room)

    def _can_hold(self, view: View) -> bool:
        return bool(self._hold_plan(view))

    def _latest_good_turn(self, view: View, room: int) -> int:
        """Of the next `room` fast moves of mine, after how many is the best moment to throw: the one that
        leaves the opponent's fast move in progress the fewest turns to run (a charged move lets it land in
        full), and of equally good moments the latest, so as to farm the longest."""
        mine, theirs = view.me.mon.build.fast.turns, view.foe.build.fast.turns
        phase = (theirs - view.foe_busy) % theirs
        free = lambda j: theirs - 1 - (phase + j * mine) % theirs  # turns given away by throwing after j more
        return min(range(room + 1), key=lambda j: (free(j), -j))

    def _doomed(self, view: View, turns: int) -> bool:
        """Will I be knocked out within that many turns, counting a charged move of theirs I would not block?"""
        mon, foe = view.me.mon, view.foe
        foe_fast = foe.build.fast
        phase = (foe_fast.turns - view.foe_busy) % foe_fast.turns
        landing = (phase + turns) // foe_fast.turns
        incoming = landing * damage(foe, foe_fast, mon)
        if incoming >= mon.hp:
            return True
        energy = min(ENERGY_CAP, foe.energy + landing * foe_fast.energy_gain)
        worst = max((damage(foe, move, mon) for move in foe.build.charged if move.energy <= energy), default=0)
        if incoming + worst < mon.hp:
            return False
        return view.me.shields == 0 or not self.shield(view, energy)

    def _may_faint(self, view: View, turns: int) -> bool:
        """Could this Pokémon faint within that many turns, if the opponent keeps attacking?"""
        mon, foe = view.me.mon, view.foe
        foe_fast = foe.build.fast
        phase = (foe_fast.turns - view.foe_busy) % foe_fast.turns
        landing = (phase + turns) // foe_fast.turns  # their fast moves that land in that time
        incoming = landing * damage(foe, foe_fast, mon)
        if view.me.shields == 0:
            foe_energy = foe.energy + landing * foe_fast.energy_gain
            incoming += max((damage(foe, move, mon) for move in foe.build.charged if move.energy <= foe_energy), default=0)
        return incoming >= mon.hp

    # shields

    def shield(self, view: View, foe_energy: int) -> bool:
        if self.shields == "always" or view.me.left() == 1:
            return True  # with one Pokémon left there is nothing to save shields for
        if self.shields == "never":
            return False
        mon, foe = view.me.mon, view.foe
        may_have = getattr(view, "foe_move_odds", None) if self.odds and self.shields == "lookahead" else None
        if may_have and any(0.03 < p < 0.97 for _, p in may_have):
            # Their moves are not settled: a move is coming, and each one they may have and could pay for is
            # weighed by the chance of both.
            energy = view.foe_energy_odds
            weights = [(move, p * sum(q for e, q in energy.items() if e >= move.energy)) for move, p in may_have]
            total = sum(w for _, w in weights)
            if total > 0:
                left = view.me.shields
                gain = sum(w * (self._after_hit(view, move, True, left) - self._after_hit(view, move, False, left))
                           for move, w in weights if w > 0.02 * total)
                return gain > 0
        threats = [move for move in foe.build.charged if move.energy <= foe_energy]
        if not threats:
            return True
        soft = min(threats, key=lambda move: damage(foe, move, mon))
        hard = max(threats, key=lambda move: damage(foe, move, mon))
        if self.shields == "threshold":
            if mon.hp <= 2 * damage(foe, foe.build.fast, mon):
                return False  # nearly gone either way
            worst = damage(foe, hard, mon)
            return worst >= mon.hp or worst >= self.shield_share * mon.build.hp
        left = view.me.shields
        if soft is hard or self.guess == "worst":
            return self._after_hit(view, hard, True, left) > self._after_hit(view, hard, False, left)
        value = {(m.id, s): self._after_hit(view, m, s, left) for m in (soft, hard) for s in (True, False)}
        if self.guess == "read":
            q = self._bait_seen[0] / self._bait_seen[1]  # how likely the softer move is
            return (q * value[soft.id, True] + (1 - q) * value[hard.id, True]
                    > q * value[soft.id, False] + (1 - q) * value[hard.id, False])
        odds = solve_2x2(value[soft.id, True], value[hard.id, True], value[soft.id, False], value[hard.id, False])
        return self.rng.random() < odds

    # looking ahead

    def _after_hit(self, view: View, move, shielded: bool, shields: int) -> float:
        """Where I stand after the opponent's charged move lands or is shielded."""
        me = view.me
        hurt, thrower = me.mon.copy(), view.foe.copy()
        hurt.hp -= 1 if shielded else damage(view.foe, move, me.mon)
        thrower.energy -= move.energy
        if move.buff_chance >= 1:
            apply_buffs(thrower, hurt, move)
        return self._play_out(view, hurt, thrower, shields - shielded, view.foe_shields)

    def _after_throw(self, view: View, k: int, shielded: bool) -> float:
        """Where I stand after throwing charged move k, shielded or not."""
        me = view.me
        thrower, hurt = me.mon.copy(), view.foe.copy()
        move = thrower.build.charged[k]
        thrower.energy -= move.energy
        hurt.hp -= 1 if shielded else damage(me.mon, move, view.foe)
        if move.buff_chance >= 1:
            apply_buffs(thrower, hurt, move)
        return self._play_out(view, thrower, hurt, me.shields, view.foe_shields - shielded)

    def _worth(self, team: list[Mon], shields: int) -> float:
        return sum(m.hp / m.build.hp + self.energy_worth * m.energy / ENERGY_CAP for m in team if m.hp > 0) \
            + self.shield_worth * shields

    def _play_out(self, view: View, mine: Mon, theirs: Mon, my_shields: int, foe_shields: int,
                  bench: list[Mon] | None = None, switch_wait: int | None = None) -> float:
        """Play the rest of the battle against the Pokémon seen so far, from the given active pair.

        Returns what I have left minus what they have left: health, unused shields
        and stored energy. Their unseen Pokémon are left out, so this compares
        options rather than predicting the result.
        """
        me = view.me
        if bench is None:
            bench = [m for j, m in enumerate(me.team) if j != me.active and m.hp > 0]
        if switch_wait is None:
            switch_wait = me.switch_wait
        foes = [m for m in [theirs] + [m for m in view.foe_shown if m is not view.foe] if m.hp > 0]
        if mine.hp > 0:
            orders = [[mine] + bench]
        else:
            orders = [[lead] + [m for m in bench if m is not lead] for lead in bench]
        unseen = view.foe_left - sum(m.hp > 0 for m in view.foe_shown)
        if not foes or not orders:
            return self._standing([mine] + bench, 0, my_shields, switch_wait, foes, foe_shields, unseen, view.turn)
        best = None
        for order in orders:
            battle = Battle([m.copy() for m in order], [m.copy() for m in foes], _rollout(), _rollout(), seed=0,
                            shields=(my_shields, foe_shields), switch_wait=(switch_wait, view.foe_switch_wait))
            battle.run()
            a, b = battle.sides
            value = self._standing(a.team, a.active, a.shields, a.switch_wait, b.team, b.shields, unseen,
                                   view.turn + battle.turn)
            best = value if best is None else max(best, value)
        return best

    def _standing(self, mine: list[Mon], active: int, my_shields: int, switch_wait: int,
                  theirs: list[Mon], foe_shields: int, unseen: int, turn: int) -> float:
        """How good the position is once the visible battle is over."""
        tally = self._worth(mine, my_shields) - self._worth(theirs, foe_shields)
        if self.value is None:
            return tally
        if not any(m.hp > 0 for m in mine):
            chance = 0.0
        elif any(m.hp > 0 for m in theirs):
            chance = 0.5  # ran out of time with both sides standing
        elif unseen == 0:
            chance = 1.0
        else:
            chance = self.value(position_features(mine, active, my_shields, switch_wait, unseen, foe_shields, turn, self.field))
        return chance + 0.02 * tally  # the tally only separates options the model rates the same

    # switching

    def _outlook(self, view: View, slot: int) -> float:
        return duel(view.me.team[slot], view.foe, view.me.shields, view.foe_shields, coming_in=slot != view.me.active)

    def _pick_switch(self, view: View) -> int | None:
        me, mon = view.me, view.me.mon
        if me.switch_wait or not me.bench():
            return None
        if self.sac:
            slot = self._pick_sacrifice(view)
            if slot is None:
                slot = self._pick_rescue(view)
            if slot is not None:
                return SWITCH[slot]
        matchup = (me.active, view.foe.build.uid)
        if matchup == self._judged:
            return None
        self._judged = matchup
        slot = self._swap_choice(view)
        return None if slot is None else SWITCH[slot]

    def _swap_choice(self, view: View) -> int | None:
        """Faced with a new matchup and free to switch: the slot to bring in, or None to stay."""
        me, mon = view.me, view.me.mon
        if self._spent(mon):
            return None  # too hurt to fight elsewhere; any rescue was decided above
        staying = self._outlook(view, me.active)
        if staying > self.bad_matchup:
            return None
        w = 0.0 if self.punish and view.foe_switch_wait else self.safe_weight

        def appeal(j: int) -> float:
            here = self._outlook(view, j)
            return here if not w else (1 - w) * here + w * safety(me.team[j].build, self.field)

        slot = max(me.bench(), key=appeal)
        return slot if appeal(slot) - staying >= self.switch_margin else None

    def _spent(self, mon: Mon) -> bool:
        return mon.hp <= 0.3 * mon.build.hp

    def _loaded(self, view: View) -> bool:
        """Does the opponent have a charged move ready?"""
        return any(m.energy <= view.foe.energy for m in view.foe.build.charged)

    def _pick_rescue(self, view: View) -> int | None:
        """Swap out a nearly fainted Pokémon that would go down without getting a charged move off."""
        me, mon = view.me, view.me.mon
        healthy = [j for j in me.bench() if not self._spent(me.team[j])]
        if not self._spent(mon) or not healthy or self._loaded(view):
            return None  # if they have a move ready, staying in to take it is the sacrifice
        fast = mon.build.fast
        needed = min(m.energy for m in mon.build.charged) - mon.energy
        if needed <= 0 or not self._may_faint(view, -(-needed // fast.energy_gain) * fast.turns):
            return None  # it can still get a charged move off
        return max(healthy, key=lambda j: self._outlook(view, j))

    def _pick_sacrifice(self, view: View) -> int | None:
        """A nearly fainted bench Pokémon to swap in so that it takes the charged move they have ready."""
        me, mon, foe = view.me, view.me.mon, view.foe
        ready = [m for m in foe.build.charged if m.energy <= foe.energy]
        spent = [j for j in me.bench() if self._spent(me.team[j])]
        if not ready or not spent or self._spent(mon):
            return None
        situation = (me.active, foe.build.uid, foe.energy // 15, tuple(spent))
        if situation == self._sac_checked:
            return None
        self._sac_checked = situation
        threat = max(damage(foe, m, mon) for m in ready)
        if threat < mon.hp and threat < 0.3 * mon.build.hp:
            return None  # nothing coming that is worth dodging
        best, best_value = None, self._play_out(view, mon.copy(), foe.copy(), me.shields, view.foe_shields) + self.sac_margin
        for j in spent:
            bench = [m for k, m in enumerate(me.team) if k != j and m.hp > 0]
            value = self._play_out(view, me.team[j].copy(), foe.copy(), me.shields, view.foe_shields,
                                   bench=bench, switch_wait=SWITCH_TURNS)
            if value > best_value:
                best, best_value = j, value
        return best

    def act(self, view: View) -> int:
        if self.switches:
            switch = self._pick_switch(view)
            if switch is not None:
                return switch
        if self.moves:
            return self._pick_move(view)
        return _MASHER.act(view)

    def replace(self, view: View) -> int:
        me = view.me
        if not self.switches:
            return me.bench()[0]
        if self.sac:
            spent = [j for j in me.bench() if self._spent(me.team[j])]
            fresh = [j for j in me.bench() if j not in spent]
            if spent and fresh:
                if view.foe.hp > 0 and self._loaded(view):
                    return min(spent, key=lambda j: me.team[j].hp)  # let it take the move they have ready
                return max(fresh, key=lambda j: self._outlook(view, j))  # keep the third shield for later
        if self.replace_by == "lookahead":
            def value(j: int) -> float:
                bench = [m for k, m in enumerate(me.team) if k not in (j, me.active) and m.hp > 0]
                return self._play_out(view, me.team[j].copy(), view.foe.copy(), me.shields, view.foe_shields, bench=bench)
            return max(me.bench(), key=value)
        return max(me.bench(), key=lambda j: self._outlook(view, j))


def _rollout() -> Planner:
    """The quick player used to play positions forward inside the lookahead."""
    return Planner(timing=False, bait="cheap", shields="threshold", switches=False, farm=False, sac=False, seed=0)


def expert(field: list | None = None) -> Planner:
    """A strong player, as lyxia describes them.

    Times charged moves; builds energy for the dearer move and then baits about
    half the time; reads the opponent when either move could be coming; weighs
    each shield on the situation; leaves a bad matchup for the safe swap, or for
    the hard counter when the opponent cannot answer; farms energy in matchups
    it dominates; keeps a nearly fainted Pokémon as a third shield.
    """
    return Planner(bait="even", shields="lookahead", guess="read", field=field, safe_weight=0.7, punish=True)


def varied(rng: random.Random, field: list | None = None) -> Planner:
    """A strong player like ours with every habit shifted a little.

    Drawn fresh for each battle, so a strategy is trained and tested against a
    crowd of players centred on how we play, not against one fixed opponent.
    """
    return Planner(**varied_settings(rng, field))


def varied_settings(rng: random.Random, field: list | None = None) -> dict:
    """The shifted habits themselves, for building any Planner-based player."""
    def near(value: float, spread: float) -> float:
        return value * 2.718281828 ** rng.gauss(0, spread)

    return dict(
        timing=rng.random() < 0.9,
        bait=rng.choice(("mix", "mix", "read", "even", "farm", "cheap")),
        shields="lookahead" if rng.random() < 0.85 else "threshold",
        guess=rng.choice(("read", "read", "worst", "mix")),
        shield_share=min(0.9, near(0.4, 0.3)), shield_worth=near(0.35, 0.4),
        switch_margin=near(0.35, 0.4), bad_matchup=-near(0.2, 0.5),
        farm=rng.random() < 0.8, farm_cost=near(0.35, 0.4), sac=rng.random() < 0.8,
        hold=rng.random() < 0.8, hold_cost=near(0.5, 0.4),
        last_gasp=rng.random() < 0.8, timed_farm=rng.random() < 0.8,
        field=field, safe_weight=rng.choice((0.0, 0.0, 0.35, 0.7)), punish=rng.random() < 0.5,
        expect_shield=min(0.95, max(0.3, rng.gauss(0.7, 0.15))), expect_bait=min(0.9, max(0.1, rng.gauss(0.5, 0.2))),
        seed=rng.getrandbits(32),
    )


# Cruder ways to play, kept as sanity checks.
STYLES = {
    "masher": Masher,
    "spammer": lambda: Planner(timing=False, bait="cheap", shields="threshold"),
    "baiter": lambda: Planner(bait="farm", shields="threshold"),
    "straight": lambda: Planner(bait="never", shields="threshold"),
    "shield saver": lambda: Planner(bait="cheap", shields="never"),
    "stayer": lambda: Planner(bait="cheap", shields="threshold", switches=False),
}
