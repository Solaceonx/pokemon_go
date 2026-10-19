"""Players for the battle simulator.

An agent answers three questions, each from a View of the battle:
    act(view)                 -> FAST, CHARGED[k] or SWITCH[slot], whenever it is free to act
    shield(view, foe_energy)  -> True to shield; it is not told which charged move is coming
    replace(view)             -> team slot to send in after a faint
"""
from __future__ import annotations

import copy
import heapq
import json
import random
from functools import lru_cache

from .battle import CHARGED, ENERGY_CAP, FAST, MAX_TURNS, SWITCH, SWITCH_TURNS, Battle, Mon, View, apply_buffs, damage
from .gamedata import DATA, effectiveness


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


@lru_cache(maxsize=1)
def _sweeper_field() -> tuple:
    """A prior for an unseen last Pokémon, never the hidden battle roster."""
    from .gamedata import GameData
    return tuple(GameData().meta(50))


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


@lru_cache(maxsize=1)
def _matchup_table() -> dict:
    """Saved fresh one-on-ones, averaged over 0, 1 and 2 shields by scripts/teams.py."""
    path = DATA / "matchups.json"
    return json.loads(path.read_text()) if path.exists() else {}


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
              "even" does the same but picks at random, half and half; "calibrated" (the owner: a bait
              rate calibrated to how risky or rewarding the bait is) starts from the shield rate that would
              leave us indifferent between the two moves, given what each costs and gains, moves it towards
              this opponent's record as that builds up, plays the mix while it is close to that, and takes the
              better move once the record says they shield more or less than that.
    shields:  "always"; "never" (until the last Pokémon); "threshold" shields hits that
              would knock out or take a large share of health; "lookahead" plays the rest
              of the visible battle both ways and shields only if that leaves it better off.
    shield_matchups: for lookahead on a nearly fainted Pokémon, let both sides choose
              switches and replacements by their remaining matchups in each rollout.
              Compare spending the shield here with keeping it for the teammates.
              shield_matchup_hp sets the maximum share of full health for this rule.
    guess:    for "lookahead", when either charged move could be coming: "worst" assumes
              the harder hit; "mix" weighs all four outcomes and varies; "read" goes by
              which one this opponent has thrown in that spot before; "calibrated" starts from the bait rate
              that would leave us indifferent between shielding and not (what shielding their harder move
              saves against what shielding a bait wastes: p = saves / (saves + wastes)), moves it towards this
              opponent's record, plays the mix while it is close, and the better answer once it is not.
    switches: plays out each one-on-one in advance to choose replacements and to leave a
              losing matchup when the switch timer allows.
    good_matchup: blend the saved one-on-one table into those choices. matchup_weight is
              the table's share; the rest uses current health, energy and shields. Missing
              pairs use the live duel alone. The table assumes the usual builds and moves.
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
    catch:    read an affordable charged move while the opponent is free to throw,
              and switch to a surviving resist. catch_gain is the minimum health
              saved, measured as fractions of each Pokémon's full health.
    replace_by: choose the replacement after a faint by the one-on-one "outlook" or by
              playing the visible battle forward ("lookahead").
    value:    a trained ValueModel. With it (and a field), the lookahead judges what is
              left after the visible battle by the model's win chance against the
              opponent's unseen Pokémon, not by adding up health and shields.
    rush:     once the opponent has no shields, stop holding and farming and knock their Pokémon out in
              as few turns as our moves allow, before it does too much (the owner). With rush_threat,
              only once holding no longer pays (they have a move ready or soon, or waiting hurts).
    punish_gain: once they have switched and are locked in, bring the bench Pokémon that beats staying by
              at least this much, even when already ahead (the owner: punish with the harder counter).
    known_team: once every Pokémon they have left has been seen, swap in a bench Pokémon that beats at
              least two of them even without the usual margin: whatever they switch to, it is a matchup
              we win (the owner). known_edge is how far ahead a one-on-one must be to count as beaten.
    sweeper:  extra value per shield saved or drawn while setting up a teammate after
              losing the lead and being counter-swapped. Zero disables the rule.
              sweep_chance is the required fraction of shieldless two-opponent
              continuations that teammate wins; unseen opponents use field (or the
              top-50 prior), never the hidden team.
    """

    def __init__(self, moves: bool = True, timing: bool = True, bait: str = "mix", shields: str = "lookahead",
                 guess: str = "read", switches: bool = True, shield_share: float = 0.9724, shield_worth: float = 0.3918,
                 energy_worth: float = 0.5, switch_margin: float = 0.0577, seed: int | None = None,
                 expect_shield: float = 0.4458, expect_bait: float = 0.5011, belief: float = 1.8395,
                 field: list | None = None, safe_weight: float = 0.2118, bad_matchup: float = -0.1786,
                 punish: bool = False, farm: bool = True, farm_cost: float = 0.3869,
                 sac: bool = True, sac_margin: float = 0.0286, replace_by: str = "outlook", value=None,
                 odds: bool = False, hold: bool = True, hold_cost: float = 0.9031,
                 last_gasp: bool = True, timed_farm: bool = True,
                 win_switch: float | None = 0.0, switch_worth: float = 0.2886,
                 good_matchup: bool = True, matchup_weight: float = 0.741,
                 sweeper: float = 0.0, sweep_chance: float = 0.75,
                 shield_matchups: bool = False, shield_matchup_hp: float = 0.3,
                 catch: bool = False, catch_gain: float = 0.2,
                 rush: bool = False, rush_threat: bool = False, known_team: bool = False, known_edge: float = 0.4,
                 punish_gain: float | None = None, fast_first: float = 0.0, last_always: bool = True):
        if bait not in ("cheap", "never", "farm", "mix", "read", "even", "calibrated"):
            raise ValueError(f"unknown bait rule {bait!r}")
        if shields not in ("always", "never", "threshold", "lookahead"):
            raise ValueError(f"unknown shield rule {shields!r}")
        if guess not in ("worst", "mix", "read", "calibrated"):
            raise ValueError(f"unknown guess rule {guess!r}")
        if not 0.0 <= matchup_weight <= 1.0:
            raise ValueError("matchup_weight must be between 0 and 1")
        if sweeper < 0 or not 0 < sweep_chance <= 1:
            raise ValueError("sweeper must be nonnegative and sweep_chance in (0, 1]")
        self.moves = moves
        self.timing = timing
        self.bait = bait
        self.shields = shields
        self.guess = guess
        # The owner: on the last Pokémon a shield still matters within the matchup: shield a bait and the thrower
        # outpaces you (the Melmetal mirror, scripts/mirror.py). False: decide the last Pokémon's shields as any other.
        self.last_always = last_always
        self.switches = switches
        self.good_matchup = good_matchup
        self.matchup_weight = matchup_weight
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
        # Winning the switch (the owner's rule). When the opponent has just swapped they cannot swap again for
        # 45 seconds, so the matchup is ours to choose: if we are not already winning it, bring the Pokémon
        # that wins it by at least `win_switch` more than staying would (None: the ordinary swap rule only).
        self.win_switch = win_switch
        # And then win it: while a switch clock is running on either side, coming out of the present matchup
        # on top is worth this much extra when weighing a shield, on top of what is left on each side.
        self.switch_worth = switch_worth
        self.sweeper, self.sweep_chance = sweeper, sweep_chance
        self._setup_swap = None  # (our safe-swap slot, their original lead uid)
        self._setup_checked = False
        self._sweep_plan = None  # (safe-swap slot, counter-swap uid, sweeper slot)
        self.shield_matchups = shield_matchups
        self.shield_matchup_hp = shield_matchup_hp
        self.catch, self.catch_gain = catch, catch_gain
        self.rush = rush
        self.rush_threat = rush_threat  # only once holding no longer pays: they have a move coming, or it hurts
        self.known_team, self.known_edge = known_team, known_edge
        # Punish harder (the owner): when they have just switched and cannot switch again, bring the bench
        # Pokémon that beats staying by at least this much, even if we are already winning or only a little behind.
        self.punish_gain = punish_gain
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
        # The owner's observation: many players, above all with a fast move of two turns or more, use one fast move
        # in a new matchup before swapping out of it. fast_first is the chance of that, drawn once per matchup.
        self.fast_first = fast_first
        self._fasted = self._fast_first_for = None  # matchups in which we have fast-moved / drawn the chance
        self._fast_first_now = False
        # What this opponent has done so far, starting from an assumption worth `belief` observations.
        self._shield_seen = [expect_shield * belief, belief]  # times they shielded, of times they could
        self._bait_seen = [expect_bait * belief, belief]  # times they threw the softer move, of times either could come
        self._belief, self._prior = belief, (expect_shield, expect_bait)

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
        if self.rush and view.foe_shields == 0 and (not self.rush_threat or self._hold_plan(view) is None):
            turns, first = self._fastest_kill(view, hit)
            if first != FAST and self.timing:
                # Time the throw to their fast move as usual, as long as that does not make the knock-out later.
                wait = fasts_to_wait(fast.turns, foe.build.fast.turns, view.foe_busy)
                if wait and mon.energy + fast.energy_gain <= ENERGY_CAP and not self._may_faint(view, wait * fast.turns):
                    after = foe.copy()
                    after.hp = max(0, foe.hp - damage(mon, fast, foe))
                    later, _ = self._fastest_kill(view, hit, hp=after.hp, energy=mon.energy + fast.energy_gain)
                    if fast.turns + later <= turns:
                        return FAST
            return first

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
                if dear in ready and self.bait in ("mix", "read", "even", "calibrated"):
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
            elif self.bait == "calibrated" and self._bait_lean(value, cheap, dear) is not None:
                choice = self._bait_lean(value, cheap, dear)
            else:
                odds = solve_2x2(value[cheap, True], value[cheap, False], value[dear, True], value[dear, False])
                choice = cheap if self.rng.random() < odds else dear
        return CHARGED[choice]

    def _lean(self, seen: list, prior: float, fair: float) -> float | None:
        """This opponent's rate (of shielding, or of baiting), starting from `fair` instead of the fixed prior and
        moved by what they have done; None while it is too close to `fair` to choose by (then play the mix)."""
        done, chances = seen[0] - prior * self._belief, seen[1] - self._belief  # their own record, without the prior
        q = (self._belief * fair + done) / (self._belief + chances)
        return None if chances < 1 or abs(q - fair) < 0.05 else q

    def _bait_lean(self, value: dict, cheap: int, dear: int) -> int | None:
        """The move to throw when this opponent's shield record says which is better; None to play the mix."""
        gain = value[dear, False] - value[cheap, False]  # what the harder move adds if they take it
        loss = value[cheap, True] - value[dear, True]  # what throwing it into a shield costs over the bait
        if gain <= 0 or loss <= 0:
            return None
        fair = gain / (gain + loss)  # the shield rate at which both moves are worth the same
        p = self._lean(self._shield_seen, self._prior[0], fair)
        if p is None:
            return None
        return cheap if p > fair else dear

    def _fastest_kill(self, view: View, hit: list[int], hp: int | None = None, energy: int | None = None) -> tuple[int, int]:
        """The shortest way, in turns, to knock their Pokémon out with our own moves alone (no shields left to
        stop them), from its health and our energy now (or those given): (turns, first step). A charged move
        takes one turn; ties go to doing damage sooner."""
        mon, foe = view.me.mon, view.foe
        fast, moves = mon.build.fast, mon.build.charged
        fast_hit = damage(mon, fast, foe)
        start = (foe.hp if hp is None else hp, mon.energy if energy is None else energy)
        best = {start: 0}
        queue = [(0, 0, start[0], start[1], None)]  # turns, -damage so far, health left, energy, first step
        while queue:
            turns, _, hp, energy, first = heapq.heappop(queue)
            if hp <= 0:
                return turns, FAST if first is None else first
            if best.get((hp, energy), turns) < turns:
                continue
            steps = [(CHARGED[k], 1, hit[k], energy - m.energy) for k, m in enumerate(moves) if energy >= m.energy]
            steps.append((FAST, fast.turns, fast_hit, min(ENERGY_CAP, energy + fast.energy_gain)))
            for action, cost, dealt, left in steps:
                state, when = (max(0, hp - dealt), left), turns + cost
                if when < best.get(state, 1 << 30):
                    best[state] = when
                    heapq.heappush(queue, (when, -(start[0] - state[0]), state[0], left, first if first is not None else action))
        return 0, FAST

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
        if self.shields == "always" or (view.me.left() == 1 and self.last_always):
            return True  # with one Pokémon left there is nothing to save shields for (but see last_always)
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
        at_stake = self.switch_worth and view.me.left() > 1 and view.foe_left > 1 \
            and (view.foe_switch_wait > 0 or view.me.switch_wait > 0)

        def after(move, shielded: bool) -> float:
            worth = self._after_hit(view, move, shielded, left)
            if at_stake:  # does this choice leave me the winner of the matchup we are in?
                hurt, thrower = self._hit_state(view, move, shielded)
                worth += self.switch_worth * (hurt.hp > 0 and duel(hurt, thrower, left - shielded, view.foe_shields) > 0)
            return worth

        if soft is hard or self.guess == "worst":
            return after(hard, True) > after(hard, False)
        value = {(m.id, s): after(m, s) for m in (soft, hard) for s in (True, False)}
        if self.guess == "read":
            q = self._bait_seen[0] / self._bait_seen[1]  # how likely the softer move is
            return (q * value[soft.id, True] + (1 - q) * value[hard.id, True]
                    > q * value[soft.id, False] + (1 - q) * value[hard.id, False])
        if self.guess == "calibrated":
            saves = value[hard.id, True] - value[hard.id, False]  # what shielding their harder move saves
            wastes = value[soft.id, False] - value[soft.id, True]  # what shielding a bait throws away
            if saves > 0 and wastes > 0:
                fair = saves / (saves + wastes)  # the bait rate at which shielding and not are worth the same
                q = self._lean(self._bait_seen, self._prior[1], fair)
                if q is not None:
                    return q * wastes < (1 - q) * saves  # shield unless baits are likelier than they are worth
        odds = solve_2x2(value[soft.id, True], value[hard.id, True], value[soft.id, False], value[hard.id, False])
        return self.rng.random() < odds

    # looking ahead

    def _hit_state(self, view: View, move, shielded: bool) -> tuple[Mon, Mon]:
        """My active Pokémon and theirs just after their charged move lands or is shielded."""
        hurt, thrower = view.me.mon.copy(), view.foe.copy()
        hurt.hp -= 1 if shielded else damage(view.foe, move, view.me.mon)
        thrower.energy -= move.energy
        if move.buff_chance >= 1:
            apply_buffs(thrower, hurt, move)
        return hurt, thrower

    def _after_hit(self, view: View, move, shielded: bool, shields: int) -> float:
        """Where I stand after the opponent's charged move lands or is shielded."""
        hurt, thrower = self._hit_state(view, move, shielded)
        matchups = (self.shield_matchups and view.me.left() > 1 and shields > 0
                    and view.me.mon.hp <= self.shield_matchup_hp * view.me.mon.build.hp)
        return self._play_out(view, hurt, thrower, shields - shielded, view.foe_shields,
                              matchups=matchups)

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
                  bench: list[Mon] | None = None, switch_wait: int | None = None,
                  matchups: bool = False) -> float:
        """Play the rest of the battle against the Pokémon seen so far, from the given active pair.

        Returns what I have left minus what they have left: health, unused shields
        and stored energy. Their unseen Pokémon are left out, so this compares
        options rather than predicting the result.
        """
        me = view.me
        # A specific setup opportunity, not a general bonus to saving shields.
        # Reward the immediate shield trade; the ordinary rollout still prices
        # the health and alignment lost by spending the safe swap this way.
        setup = self.sweeper * (my_shields - foe_shields) if self._sweeper_slot(view) is not None else 0.0
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
            return setup + self._standing([mine] + bench, 0, my_shields, switch_wait, foes, foe_shields, unseen, view.turn)
        best = None
        for order in orders:
            battle = Battle([m.copy() for m in order], [m.copy() for m in foes],
                            _rollout(matchups), _rollout(matchups), seed=0,
                            shields=(my_shields, foe_shields), switch_wait=(switch_wait, view.foe_switch_wait))
            battle.run()
            a, b = battle.sides
            value = self._standing(a.team, a.active, a.shields, a.switch_wait, b.team, b.shields, unseen,
                                   view.turn + battle.turn)
            best = value if best is None else max(best, value)
        return setup + best

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

    def _sweep_chance(self, view: View, slot: int) -> float:
        """Can this teammate beat their last two once the counter-swap is removed?

        Carry health, energy and shields through both opponents, in both orders.
        Unknown last Pokémon are averaged over the supplied field, excluding
        species already revealed. This is a prior, not knowledge of their team.
        """
        known = [m for m in view.foe_shown if m is not view.foe and m.hp > 0]
        unseen = view.foe_left - sum(m.hp > 0 for m in view.foe_shown)
        if len(known) + unseen != 2 or unseen > 1:
            return 0.0
        if unseen:
            shown = {m.build.species_id for m in view.foe_shown}
            field = self.field if self.field is not None else _sweeper_field()
            teams = [known + [Mon(b)] for b in field if b.species_id not in shown]
        else:
            teams = [known]
        if not teams:
            return 0.0
        wins = 0
        for team in teams:
            # Count a team only if it can be swept in either order; two fresh
            # independent duels would overestimate a sweep by resetting our HP.
            swept = True
            for order in (team, team[::-1]):
                mine = view.me.team[slot].copy()
                mine.atk_stage = mine.def_stage = 0
                foes = [m.copy() for m in order]
                for foe in foes:
                    foe.atk_stage = foe.def_stage = 0
                battle = Battle([mine], foes, _MASHER, _MASHER, seed=0,
                                shields=(view.me.shields, 0))
                if battle.run() != 0:
                    swept = False
                    break
            wins += swept
        return wins / len(teams)

    def _sweeper_slot(self, view: View) -> int | None:
        """Recognize the owner's losing-lead / safe-swap / counter-swap sequence."""
        if not self.sweeper or self._setup_swap is None:
            return None
        me = view.me
        slot, lead = self._setup_swap
        if me.active != slot or not me.switch_wait:
            self._sweep_plan = None
            self._setup_swap = None
            return None
        if self._sweep_plan is not None:
            _, counter, sweeper = self._sweep_plan
            if view.foe_switch_wait and view.foe.build.uid == counter and me.team[sweeper].hp > 0:
                return sweeper
            self._sweep_plan = None
            self._setup_swap = None
            return None
        if self._setup_checked or view.foe.build.uid == lead or not view.foe_switch_wait:
            return None
        self._setup_checked = True
        if self._outlook(view, me.active) <= 0:
            return None  # an unwinnable counter-swap is outside this rule
        candidates = [(self._sweep_chance(view, j), j) for j in me.bench()]
        chance, sweeper = max(candidates, default=(0.0, -1))
        if chance >= self.sweep_chance:
            self._sweep_plan = (slot, view.foe.build.uid, sweeper)
            return sweeper
        return None

    def _outlook(self, view: View, slot: int) -> float:
        mine, foe = view.me.team[slot], view.foe
        live = duel(mine, foe, view.me.shields, view.foe_shields, coming_in=slot != view.me.active)
        if not self.good_matchup or not self.matchup_weight or mine.hp <= 0 or foe.hp <= 0:
            return live
        table = _matchup_table().get(mine.build.species_id, {}).get(foe.build.species_id)
        if table is None:
            return live
        return (1 - self.matchup_weight) * live + self.matchup_weight * table

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
        if self.catch:
            slot = self._pick_catch(view)
            if slot is not None:
                return SWITCH[slot]
        matchup = (me.active, view.foe.build.uid)
        if matchup == self._judged:
            return None
        if self.fast_first and mon.build.fast.turns >= 2 and self._fasted != matchup:
            if self._fast_first_for != matchup:
                self._fast_first_for, self._fast_first_now = matchup, self.rng.random() < self.fast_first
            if self._fast_first_now:
                return None  # one fast move first; the matchup is judged after it
        self._judged = matchup
        slot = self._swap_choice(view)
        return None if slot is None else SWITCH[slot]

    def _pick_catch(self, view: View) -> int | None:
        """Read a throw from visible energy and move choices, without seeing their action.

        Into shields, use the opponent's observed soft/hard bait rate. Without
        shields, expect the cheapest knockout or the best damage per energy.
        Energy being ready is only a read: they can still farm or switch instead.
        """
        me, mon, foe = view.me, view.me.mon, view.foe
        if me.switch_wait or me.busy or view.foe_busy or mon.hp <= 0 or foe.hp <= 0:
            return None
        ready = [m for m in foe.build.charged if m.energy <= foe.energy]
        if not ready:
            return None
        hits = {m: damage(foe, m, mon) for m in ready}
        if me.shields:
            soft, hard = min(ready, key=hits.get), max(ready, key=hits.get)
            bait = self._bait_seen[0] / self._bait_seen[1]
            threats = [(soft, 1.0)] if soft is hard else [(soft, bait), (hard, 1 - bait)]
        else:
            lethal = [m for m in ready if hits[m] >= mon.hp]
            move = min(lethal, key=lambda m: m.energy) if lethal else max(ready, key=lambda m: hits[m] / m.energy)
            threats = [(move, 1.0)]
        threats = [(m, p) for m, p in threats if p > 0]
        incoming = sum(p * min(hits[m], mon.hp) / mon.build.hp for m, p in threats)
        best, best_gain = None, self.catch_gain
        for j in me.bench():
            target = me.team[j].copy()
            target.atk_stage = target.def_stage = 0
            # A catch preserves a living resist; sacrificing a spent Pokémon is
            # handled separately above. Require resistance to every plausible bait.
            if any(effectiveness(m.type, target.build.types) >= 1 or damage(foe, m, target) >= target.hp
                   for m, _ in threats):
                continue
            caught = sum(p * damage(foe, m, target) / target.build.hp for m, p in threats)
            gain = incoming - caught
            if gain > best_gain:
                best, best_gain = j, gain
        return best

    def _swap_choice(self, view: View) -> int | None:
        """Faced with a new matchup and free to switch: the slot to bring in, or None to stay."""
        me, mon = view.me, view.me.mon
        if self._spent(mon):
            return None  # too hurt to fight elsewhere; any rescue was decided above
        staying = self._outlook(view, me.active)
        if self.punish_gain is not None and view.foe_switch_wait > 0:
            fresh = [j for j in me.bench() if not self._spent(me.team[j])]
            best = max(fresh, key=lambda j: self._outlook(view, j), default=None)
            if best is not None and self._outlook(view, best) - staying >= self.punish_gain:
                return best
        if self.win_switch is not None and view.foe_switch_wait > 0:
            if staying >= 0.15:
                return None  # winning as it stands: stay in and keep the switch for later
            best = max(me.bench(), key=lambda j: self._outlook(view, j))
            gain = self._outlook(view, best) - max(staying, 0.0)
            if gain >= self.win_switch and not self._spent(me.team[best]):
                return best
        if self.known_team and staying < self.known_edge:
            slot = self._known_counter(view, staying)
            if slot is not None:
                return slot
        if staying > self.bad_matchup:
            return None
        w = 0.0 if self.punish and view.foe_switch_wait else self.safe_weight

        def appeal(j: int) -> float:
            here = self._outlook(view, j)
            return here if not w else (1 - w) * here + w * safety(me.team[j].build, self.field)

        slot = max(me.bench(), key=appeal)
        return slot if appeal(slot) - staying >= self.switch_margin else None

    def _known_counter(self, view: View, staying: float) -> int | None:
        """With every Pokémon they have left on show: a bench Pokémon of ours that beats two or more of them
        and does better here than staying, or None."""
        me = view.me
        living = [f for f in view.foe_shown if f.hp > 0]
        if len(living) < 2 or len(living) != view.foe_left:
            return None  # someone of theirs is still unseen
        def edge(j: int, foe: Mon) -> float:
            mine = me.team[j]
            live = duel(mine, foe, me.shields, view.foe_shields, coming_in=True)
            table = _matchup_table().get(mine.build.species_id, {}).get(foe.build.species_id) if self.good_matchup else None
            return live if table is None else (1 - self.matchup_weight) * live + self.matchup_weight * table
        options = []
        for j in me.bench():
            if self._spent(me.team[j]):
                continue
            beaten = sum(edge(j, f) >= self.known_edge for f in living)
            here = self._outlook(view, j)
            if beaten >= 2 and here > staying:
                options.append((beaten, here, j))
        return max(options)[2] if options else None

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
                if (self.sweeper and view.me.shown == [0] and view.me.active == 0
                        and len(view.foe_shown) == 1 and view.foe_switch_wait == 0
                        and self._outlook(view, 0) < self.bad_matchup):
                    self._setup_swap = (SWITCH.index(switch), view.foe.build.uid)
                    self._setup_checked = False
                    self._sweep_plan = None
                return switch
        self._sweeper_slot(view)
        if self.moves:
            action = self._pick_move(view)
            if action == FAST:
                self._fasted = (view.me.active, view.foe.build.uid)
            return action
        return _MASHER.act(view)

    def replace(self, view: View) -> int:
        me = view.me
        sweeper = self._sweeper_slot(view)
        if sweeper is not None:
            return sweeper  # inherit the shield advantage and farm the remainder
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


def _rollout(matchups: bool = False) -> Planner:
    """The quick player used inside lookahead, optionally choosing remaining matchups.

    Threshold shielding and outlook replacements keep this from nesting lookaheads.
    Only revealed opponents enter the rollout; hidden teammates are never inspected.
    """
    # The shield_matchups experiment was measured with rollouts that switch by the live duel alone. The rollout keeps
    # the standard values: the evolved rules were found and confirmed with this rollout inside them.
    return Planner(**STANDARD_RULES, timing=False, bait="cheap", shields="threshold", switches=matchups,
                   farm=False, sac=False, shield_matchups=False, good_matchup=not matchups, seed=0)


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


# The rulebook evolved by CMA-ES (task 30, docs/status.md "Evolving the rulebook"): Planner(**EVOLVED_RULES) beat the
# standard rules 54.0% ± 0.9 head to head and +3.4 ± 1.0 against the crowd on a fresh seed, and the trained bot on top of it
# beat the bot on the standard rules 51.6% ± 0.8. The default since 2026-10-19 (the owner); STANDARD_RULES are the
# values before, which the crowd (varied_settings) stays centred on so that it measures as it always has.
EVOLVED_RULES = dict(
    shield_share=0.9724, shield_worth=0.3918, energy_worth=0.5, switch_margin=0.0577, expect_shield=0.4458,
    expect_bait=0.5011, belief=1.8395, safe_weight=0.2118, bad_matchup=-0.1786, farm_cost=0.3869, sac_margin=0.0286,
    hold_cost=0.9031, win_switch=0.0, matchup_weight=0.741, switch_worth=0.2886, known_edge=0.4,
)

STANDARD_RULES = dict(
    shield_share=0.4, shield_worth=0.35, energy_worth=0.0, switch_margin=0.35, expect_shield=0.7, expect_bait=0.5,
    belief=2.0, safe_weight=0.0, bad_matchup=-0.2, farm_cost=0.35, sac_margin=0.1, hold_cost=0.5, win_switch=0.1,
    matchup_weight=0.75, switch_worth=0.0, known_edge=0.15,
)


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
        win_switch=near(0.1, 0.4) if rng.random() < 0.8 else None,
        good_matchup=rng.random() < 0.8,
        field=field, safe_weight=rng.choice((0.0, 0.0, 0.35, 0.7)), punish=rng.random() < 0.5,
        expect_shield=min(0.95, max(0.3, rng.gauss(0.7, 0.15))), expect_bait=min(0.9, max(0.1, rng.gauss(0.5, 0.2))),
        seed=rng.getrandbits(32),
        # The owner: many players use one fast move of two turns or more before swapping out of a new matchup.
        fast_first=rng.choice((0.0, 0.5, 1.0)),
        # not drawn above: the standard values, as before the evolved rules became the default
        **{k: STANDARD_RULES[k] for k in ("energy_worth", "belief", "sac_margin", "matchup_weight", "switch_worth", "known_edge")},
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
