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
- robust=p (with opponents="mix"): the imagined opponents go round the styles in turn, so each style judges every
  option with looks of its own, and an option is worth (1 - p) x the styles' weighted mean + p x its worst style.
  p = 0 is the mix with the weights applied after the looks; p = 1 plays for the worst case over the styles. A best
  response to one imagined opponent is only right against that opponent (docs/benchmarking.md: the engine's gain
  falls from +17 to -2 as the opponent gets less like what it imagines); this trades some of it for play that holds
  up whoever they are.
- mix=True: when both sides have a charged move ready, solve the small game of our options against theirs and
  draw our choice from the mix; temperature > 0: choose among close options at random, weighted by worth
  (task 29). Those draws use their own generator (`_mix_rng`), so a probe that copies the engine's search cannot
  copy its dice.
- mix_shield=True (with the shield head): shield or not when multiple incoming moves are affordable.
  mix_switch=True: all legal first actions against their fast move, ready throws and living bench when both
  switches are free. Unseen bench slots are imagined, never read from the real battle.
  random_hold=True: vary the hold rule's equally well-timed throw moments inside its safe window.
- judge: where each look stops to be judged. "steps" (as before): after `horizon` steps, which can be different
  moments of the game for different options, as throws and faints take turns of their own; "turn": at the same game
  turn for every option, `horizon` turns on; "end": played to the end and scored by decisive() (task 35).
- The owner: in linear games, win the matchups and keep the switch. switch_edge: a swap the search finds must beat
  staying by this much more (staying keeps the switch); stay_after_replace=True: never swap out on the turn a
  Pokémon came in after a faint (send in the one wanted instead) (task 35).
- mid_swap_search: ask again in a judged matchup without needing a learned mid_swap head. "ready" uses task 20's
  gate, "hit" asks after their charged move, and "both" uses either gate (task 43). Off by default.
- shield_mix / throw_mix: optional head-specific logit temperatures (zero: the usual search argmax with edge).
  shield_floor bounds close shield calls; equilibrium solves bait/big move versus shield/take exactly.
  These enable shield search at real prompts, preserving the last-Pokemon rule, only when explicitly requested.
"""
from __future__ import annotations

import json
import math
import random
import time
from pathlib import Path

from .agents import Planner, _rollout, varied_settings
from .arena import decisive
from .battle import DRAW, ENERGY_CAP, CHARGED, CHARGED_TURNS, FAST, SWITCH, Battle, Mon, View, apply_buffs, damage
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


class _FirstShield(_First):
    """Fix the response to this step's throw, never a later Pokemon's throw after a CMP knockout."""

    def __init__(self, inner, shielded, turn):
        super().__init__(inner, None)
        self.shielded, self.turn = shielded, turn

    def shield(self, view, energy, *move):
        if self.shielded is not None:
            answer, self.shielded = self.shielded, None
            if view.turn == self.turn:
                return answer
        return super().shield(view, energy, *move)


def imagine(view: View, rng: random.Random, pool: list, me_agent, foe_agent, teams: list | None = None,
            team_builds: dict | None = None) -> Battle:
    """A battle standing where this view stands, with the opponent's unseen Pokémon drawn from the pool, or with
    `teams` (weight, species) from a listed team that holds every one seen so far, when one does."""
    me = view.me
    mine = [m.copy() for m in me.team]
    seen = view.foe_shown
    theirs = [m.copy() for m in seen]
    # Never more than three in all: live, the header can still count a Pokémon of theirs whose bar shows empty
    # (2026-11-08: a fainted Stunfisk with "3 left" made a team of four, and a switch choice failed on slot 3).
    unseen = max(0, min(view.foe_left - sum(m.hp > 0 for m in seen), 3 - len(seen)))
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
                 mix: bool = False, temperature: float = 0.0, mix_shield: bool = False,
                 mix_switch: bool = False, random_hold: bool = False, matching: bool = False,
                 no_tell_bait: bool = False, judge: str = "steps", switch_edge: float = 0.0,
                 stay_after_replace: bool = False, robust: float | None = None,
                 shield_margin: float | None = None, shield_toward: bool = False,
                 mid_swap_search: str | None = None, shield_mix: float | None = None,
                 throw_mix: float | None = None, shield_floor: float = 0.0,
                 equilibrium: bool = False, swap_after_throw: bool = False, **settings):
        super().__init__(shield_margin=shield_margin, shield_toward=shield_toward, **settings)
        self.swap_after_throw = swap_after_throw
        self.swap_after_throws = 0
        self._swap_throw_pending = False
        self.evaluator, self.pool = evaluator, pool
        self.horizon, self.samples, self.edge, self.heads = horizon, samples, edge, tuple(heads)
        for name, tau in (("shield_mix", shield_mix), ("throw_mix", throw_mix)):
            if tau is not None and (not math.isfinite(tau) or tau < 0):
                raise ValueError(f"{name} must be finite and nonnegative")
        if not math.isfinite(shield_floor) or not 0 <= shield_floor <= 0.5:
            raise ValueError("shield_floor must be between 0 and 0.5")
        self.shield_mix, self.throw_mix = shield_mix, throw_mix
        self.shield_floor, self.equilibrium = shield_floor, equilibrium
        self._lab_shield = shield_mix is not None or shield_floor > 0 or equilibrium
        if self._lab_shield or throw_mix is not None:
            from .lab.mixed import validate_mixing
            validate_mixing(shield_mix=shield_mix, throw_mix=throw_mix, shield_floor=shield_floor,
                            equilibrium=equilibrium, mix=mix, temperature=temperature,
                            mix_shield=mix_shield, mix_switch=mix_switch)
        if self._lab_shield and "shield" not in self.heads:
            self.heads += ("shield",)
        if (throw_mix is not None or equilibrium) and "throw" not in self.heads:
            self.heads += ("throw",)
        self.last_shield_probability = self.last_throw_probability = None
        self._decision_depth = 0  # shield advice inside another decision is not a real shield prompt
        self._their_shield = None  # first opposing shield response in a bait matrix cell
        if judge not in ("steps", "turn", "end"):
            raise ValueError(f"unknown judge {judge!r}")
        self.judge = judge
        self.switch_edge, self.stay_after_replace = switch_edge, stay_after_replace
        if mid_swap_search not in (None, False, "ready", "hit", "both"):
            raise ValueError(f"unknown mid_swap_search {mid_swap_search!r}")
        self.mid_swap_search = mid_swap_search
        self._swap_hit = None  # (turn, our slot) of their last charged move, consumed at our next action
        self.mid_swap_searches = 0
        if robust is not None and opponents != "mix":
            raise ValueError("robust needs opponents='mix'")
        self.robust = robust  # None: off; 0.0 still gives each style its own looks
        self._forced_style = None  # the style of the imagined opponent in the current round of looks (robust)
        self._style_turn = 0  # where the round of styles continues at the next decision (robust)
        self.style_rounds = {}  # rounds of looks each style has had in this game (robust)
        self._replaced_at = None  # the turn of our last replacement after a faint
        # Who plays inside the look-ahead: "quick", the cheap rollout player, or "bot", the trained bot itself.
        self.rollout = rollout
        self.opponents, self.profile, self.unseen, self.mix, self.temperature = opponents, profile, unseen, mix, temperature
        self.mix_shield, self.mix_switch, self.random_hold = mix_shield, mix_switch, random_hold
        self._hold_window = False
        self._mix_fallback = False
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
        # matching=True (with opponents="mix"): weigh each style by how likely it was to make every decision of
        # theirs seen so far (scripts/predict_bench.py), not only by their shield and bait rates.
        self.matching = matching
        # no_tell_bait=True (the owner, puzzled by some throws): the search may not throw the cheaper move into a
        # shield while the dearer one is not yet affordable, which their energy count gives away, unless waiting
        # for the dearer one is unsafe; the trained bot's own pick, or another fast move, instead.
        self.no_tell_bait = no_tell_bait
        self._loglik = {name: 0.0 for name in (self._styles or {})}
        self._pending = self._pending_shield = self._their_throw = None
        self._mix_rng = random.Random(hash(self.rng.getstate()))  # for mixing only; does not touch self.rng
        if self._lab_shield or throw_mix is not None or self.bait_mix is not None:
            # hash(getstate()) contains None, whose hash varies between Python processes. Derive the new
            # options' private stream from a COPY of the player's RNG so workers and restarts replay.
            from .lab.mixed import private_rng
            self._mix_rng = private_rng(self.rng)
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
        twin._loglik = dict(self._loglik)
        twin._pending = twin._pending_shield = twin._their_throw = None
        return twin

    # what this opponent does, for profile=True

    def saw_shield(self, view: View, shielded: bool) -> None:
        super().saw_shield(view, shielded)
        if self._pending_shield is not None:
            self._learn(self._pending_shield, "shield" if shielded else "take")
            self._pending_shield = None
        self._obs["shield"][0] += shielded
        self._obs["shield"][1] += 1

    def saw_throw(self, view: View, move, foe_energy: int, could_shield: bool) -> None:
        super().saw_throw(view, move, foe_energy, could_shield)
        if self.mid_swap_search in ("hit", "both"):
            # The callback precedes damage; only the next action can search the position after it lands.
            # Shielded moves count too. A faint discards this trigger in replace().
            self._swap_hit = (view.turn, view.me.active)
        charged = view.foe.build.charged
        self._their_throw = next((k for k, m in enumerate(charged) if m is move or m.id == move.id), None)
        ready = [m for m in view.foe.build.charged if m.energy <= foe_energy]
        if len(ready) > 1 and min(m.energy for m in ready) < max(m.energy for m in ready):
            self._obs["bait"][0] += move.energy == min(m.energy for m in ready)
            self._obs["bait"][1] += 1

    # matching=True: what each style would have done in their place, and how likely that made what they did

    def _style_shares(self, view: View, shield_energy: int | None = None) -> dict:
        """{style: {option: share of its players choosing it}} for their decision now (a fast move, either charged
        move or a switch; or, with shield_energy, shielding our throw), in a battle imagined from what we can see."""
        rng = random.Random(view.turn * 7919 + 17)
        battle = imagine(view, rng, self.pool, None, None, self._teams, self._team_builds)
        out = {}
        for k, name in enumerate(self._styles):
            players = [style_player(name, random.Random(1000 * k + j), self.q, self.margin, self.pool, self._human_settings)
                       for j in range(1 if name in ("bot", "pvpoke") else 6)]
            votes = {}
            for player in players:
                twin = battle.clone(None, None)
                try:
                    if shield_energy is None:
                        a = player.act(twin.views[1])
                        option = "fast" if a == FAST else f"charged{CHARGED.index(a)}" if a in CHARGED else "switch"
                    else:
                        option = "shield" if player.shield(twin.views[1], shield_energy) else "take"
                except Exception:  # a style that cannot judge this position (PvPoke's AI outside one-on-one) abstains
                    continue
                votes[option] = votes.get(option, 0) + 1
            n = sum(votes.values())
            if n:
                out[name] = {o: v / n for o, v in votes.items()}
        return out

    def _learn(self, shares: dict, did: str) -> None:
        options = 2 if did in ("shield", "take") else 4
        for name in self._loglik:
            p = shares.get(name, {}).get(did, 0.0) * 0.9 + 0.1 / options if name in shares else 1.0 / options
            self._loglik[name] += math.log(p)

    def _watch(self, view: View) -> None:
        """Settle their last decision we predicted, then predict the one they face now."""
        if self._pending is not None:
            shares, mon = self._pending
            if self._their_throw is not None:
                self._learn(shares, f"charged{self._their_throw}")
            elif view.foe is not mon and mon.hp > 0:
                self._learn(shares, "switch")
            elif view.foe is mon:
                self._learn(shares, "fast")
            self._pending = None
        self._their_throw = None
        foe = view.foe
        if view.foe_busy == 0 and foe.build.charged and foe.energy >= min(m.energy for m in foe.build.charged):
            self._pending = (self._style_shares(view), foe)

    def _style_weights(self) -> dict:
        weights = {name: s["weight"] for name, s in self._styles.items()}
        if self.matching:
            top = max(self._loglik.values(), default=0.0)
            weights = {name: w * math.exp(self._loglik.get(name, 0.0) - top) for name, w in weights.items()}
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
        if self.opponents == "people":
            from .lab.people import people_player
            return people_player(rng, self.q, self.pool)
        if self.opponents != "mix":
            return Learner(q=self.q, margin=self.margin, seed=rng.getrandbits(32))
        if self._forced_style is not None:
            name = self._forced_style
        else:
            weights = self._style_weights()
            name = rng.choices(list(weights), list(weights.values()))[0]
        return style_player(name, rng, self.q, self.margin, self.pool, self._human_settings)

    def _robust_worth(self, by_style: dict, options: list) -> dict:
        """Each option's worth from per-style looks: (1 - p) x the styles' weighted mean + p x the worst style."""
        weights = self._style_weights()
        means = {name: {k: totals[k] / n for k in options} for name, (totals, n) in by_style.items()}
        total = sum(weights[name] for name in means) or 1.0
        out = {}
        for k in options:
            mean = sum(weights[name] * m[k] for name, m in means.items()) / total
            worst = min(m[k] for m in means.values())
            out[k] = (1.0 - self.robust) * mean + self.robust * worst
        return out

    # deciding

    def act(self, view: View) -> int:
        self._decision_depth += 1
        try:
            if self.matching and self._styles:
                self._watch(view)
                action = self._act(view)
                if action in CHARGED and view.foe_shields > 0:
                    self._pending_shield = self._style_shares(view, shield_energy=view.me.mon.energy)
                return action
            return self._act(view)
        finally:
            self._decision_depth -= 1
            self._swap_hit = None  # no delayed hit search when the switch was unavailable

    def _pick_move(self, view: View) -> int:
        # Also cover direct move probes and Learner's timing post-check, after its throw head returns.
        self._decision_depth += 1
        try:
            return super()._pick_move(view)
        finally:
            self._decision_depth -= 1

    def _mid_swap_gate(self, view: View) -> bool:
        if not self.mid_swap_search:
            return super()._mid_swap_gate(view)
        if not self.mid_swap or "mid_swap" not in self.heads:
            return False
        ready = self.mid_swap_search in ("ready", "both") and self._mid_swap_ready(view)
        hit = (self.mid_swap_search in ("hit", "both") and self._swap_hit is not None
               and view.turn > self._swap_hit[0] and view.me.active == self._swap_hit[1])
        return ready or hit

    def _act(self, view: View) -> int:
        theirs = self._mixed_actions("simultaneous", view) if self.switches and "mid_swap" in self.heads else []
        if not theirs:
            self._searched_swap = False
            pending, self._swap_throw_pending = self._swap_throw_pending, False
            action = super().act(view)
            if (self.swap_after_throw and not pending and action in SWITCH and view.turn > 0
                    and self._searched_swap):
                from .lab.tactics import before_swap
                throw = before_swap(view)
                if throw is not None:
                    self._swap_throw_pending = True
                    self.swap_after_throws += 1
                    self._hold = 0
                    self._judged = None  # reopen the swap question after our throw
                    return self._bait_action(view, throw)
            return action
        # The whole first action is simultaneous: staying can mean a fast move or either ready throw.
        # First obtain the trained bot's fallback and update its remembered matchup/hold as usual.
        self._mix_fallback = True
        try:
            pick = super().act(view)
        finally:
            self._mix_fallback = False
        options = view.legal()
        seeds = [self.rng.getrandbits(32) for _ in range(self.samples)]
        choice = self._mixed(view, "simultaneous", options, seeds, theirs, pick)
        if choice is None:
            self.looks += 1
            self.fell_back += 1
            return self._bait_action(view, pick)
        # The fallback throw head's probability does not describe the simultaneous action mix.
        self.last_throw_probability = None
        if choice == FAST:
            self._fasted = (view.me.active, view.foe.build.uid)
        else:
            self._hold = 0
        return self._bait_action(view, choice)

    def replace(self, view: View) -> int:
        self._swap_hit = None
        self._swap_throw_pending = False
        self._replaced_at = view.turn
        return super().replace(view)

    def shield(self, view: View, foe_energy: int) -> bool:
        if self._lab_shield and self._decision_depth:
            return super().shield(view, foe_energy)
        self.last_shield_probability = 1.0
        if not self._lab_shield or view.me.left() == 1:
            return super().shield(view, foe_energy)
        if view.me.shields <= 0:
            return False
        # Explicit lab options search real prompts ahead of people_shield shortcuts, but retain
        # Learner's measured last-Pokemon rule above.
        return bool(self._decide("shield", view, (True, True),
                                 lambda: int(Planner.shield(self, view, foe_energy)), foe_energy))

    def _decide(self, head: str, view: View, mask: tuple, planner_choice, foe_energy: int | None = None) -> int:
        if head == "shield" and self._lab_shield and self._decision_depth:
            # Learner.shield dispatches back here: use its ordinary answer without lab search or dice.
            return super()._decide(head, view, mask, planner_choice, foe_energy)
        self._decision_depth += 1
        try:
            looks, fallback = self.looks, self.fell_back
            choice = self._search_decision(head, view, mask, planner_choice, foe_energy)
            if (self.swap_after_throw and head in ("swap", "mid_swap") and choice
                    and self.looks > looks and self.fell_back == fallback):
                self._searched_swap = True
            return choice
        finally:
            self._decision_depth -= 1

    def _search_decision(self, head: str, view: View, mask: tuple, planner_choice,
                         foe_energy: int | None = None) -> int:
        if head == "throw":
            self.last_throw_probability = 1.0
        if self.stay_after_replace and head in ("swap", "mid_swap") and view.turn == self._replaced_at:
            return 0
        if self._mix_fallback or head in self.forced or head not in self.heads:
            return super()._decide(head, view, mask, planner_choice, foe_energy)
        options = [k for k in range(len(mask)) if mask[k]]
        pick = super()._decide(head, view, mask, planner_choice, foe_energy)
        if len(options) < 2:
            return pick
        self.mid_swap_searches += head == "mid_swap"
        self._foe_energy = foe_energy if foe_energy is not None else view.foe.energy
        seeds = [self.rng.getrandbits(32) for _ in range(self.samples)]
        theirs = self._mixed_actions(head, view)
        if theirs:
            mixed = self._mixed(view, head, options, seeds, theirs, pick)
            if mixed is not None:
                return mixed
        totals, rounds = dict.fromkeys(options, 0.0), 0
        # robust: the rounds go round the styles in turn, and each style's looks are kept apart
        names = [n for n, s in self._styles.items() if s["weight"] > 0] if self.robust is not None else []
        by_style = {}
        if names:  # carry the round on from decision to decision, so few samples still reach every style in time
            names = names[self._style_turn:] + names[:self._style_turn]
            self._style_turn = (self._style_turn + len(seeds)) % len(names)
        for i, s in enumerate(seeds):
            self._forced_style = names[i % len(names)] if names else None
            done = {}
            try:
                for k in options:
                    if self._out_of_time():
                        break
                    done[k] = self._timed_look(view, head, k, s)
            finally:
                self._forced_style = None
            if len(done) < len(options):
                break
            for k in options:
                totals[k] += done[k]
            rounds += 1
            if names:
                name = names[i % len(names)]
                style_totals, n = by_style.get(name, (dict.fromkeys(options, 0.0), 0))
                for k in options:
                    style_totals[k] += done[k]
                by_style[name] = (style_totals, n + 1)
                self.style_rounds[name] = self.style_rounds.get(name, 0) + 1
        self.looks += 1
        if rounds == 0:
            self.fell_back += 1
            return pick
        self.cut += rounds < len(seeds)
        worth = self._robust_worth(by_style, options) if by_style else {k: totals[k] / rounds for k in options}
        return self._choose_worth(view, head, options, pick, worth, seeds)

    def _choose_worth(self, view, head, options, pick, worth, seeds):
        """Apply the shared choice controls after either flat or tree search values its options."""
        if self.switch_edge and head in ("swap", "mid_swap"):
            worth = {k: v - (self.switch_edge if k else 0.0) for k, v in worth.items()}  # option 0 stays
        tau = self.shield_mix if head == "shield" else self.throw_mix if head == "throw" else None
        if tau is not None or (head == "shield" and self.shield_floor) or (head == "throw" and self.equilibrium):
            from .lab.mixed import logit, shield_floor
            probabilities = logit(worth, pick, self.edge, tau or 0.0)
            if head == "shield":
                probabilities = shield_floor(probabilities, worth, self.edge, self.shield_floor)
            elif self.equilibrium and all(k in options for k in (1, 2)) and view.foe_shields > 0:
                moves = view.me.mon.build.charged
                mass = probabilities[1] + probabilities[2]
                if mass and moves[0].energy != moves[1].energy:
                    table, n = self._matrix(view, head, [1, 2], seeds, [True, False], shield_columns=True)
                    self.cut += n < len(seeds)
                    if n:
                        from .lab.mixed import equilibrium
                        p = equilibrium(table)
                        probabilities[1], probabilities[2] = mass * p[0], mass * p[1]
                        self.mixed += 1
            if head == "throw" and self.no_tell_bait:
                for k in options:
                    if self._tell_bait(view, k):
                        probabilities[0] += probabilities[k]
                        probabilities[k] = 0.0
            return self._draw(head, probabilities, pick)
        if self.temperature > 0:
            # Close calls at random, weighted by worth; the trained bot's pick keeps its edge as a head start.
            scores = {k: worth[k] + (self.edge if k == pick else 0.0) for k in options}
            top = max(scores.values())
            choice = self._mix_rng.choices(options, [math.exp((scores[k] - top) / self.temperature) for k in options])[0]
            if head in ("shield", "throw"):
                setattr(self, f"last_{head}_probability", None)  # legacy random choices are excluded
            self.changed += choice != pick
            return choice
        best = max(options, key=lambda k: (worth[k], k == pick))
        if worth[best] - worth[pick] > self.edge:
            if head == "throw" and self.no_tell_bait and self._tell_bait(view, best):
                return 0 if self._tell_bait(view, pick) else pick
            self.changed += best != pick
            return best
        if head == "throw" and self.no_tell_bait and self._tell_bait(view, pick):
            return 0
        return pick

    def _tell_bait(self, view: View, option: int) -> bool:
        """Throw option `option` (1 or 2: a charged move) is the cheaper move into a shield while the dearer one is not
        yet affordable and could be reached safely: a bait the opponent's energy count sees through."""
        if option not in (1, 2) or view.foe_shields == 0:
            return False
        mon = view.me.mon
        moves = mon.build.charged
        if len(moves) < 2:
            return False
        k = option - 1
        dear = max(range(len(moves)), key=lambda j: moves[j].energy)
        if k == dear or moves[k].energy == moves[dear].energy or mon.energy >= moves[dear].energy:
            return False
        fast = mon.build.fast
        turns = -(-(moves[dear].energy - mon.energy) // fast.energy_gain) * fast.turns
        return mon.energy + fast.energy_gain <= ENERGY_CAP and not self._may_faint(view, turns)

    def _their_throws(self, view: View) -> list:
        """Their first actions worth considering when they have a charged move ready: farm, or each move ready."""
        foe = view.foe
        ready = [CHARGED[k] for k, m in enumerate(foe.build.charged) if foe.energy >= m.energy]
        return [FAST, *ready] if ready and view.foe_busy == 0 else []

    def _mixed_actions(self, head: str, view: View) -> list:
        if self.mix and head == "throw":
            return self._their_throws(view)
        if (self.mix_shield or self.equilibrium) and head == "shield":
            energy = self._foe_energy if self._foe_energy is not None else view.foe.energy
            ready = [CHARGED[k] for k, m in enumerate(view.foe.build.charged) if energy >= m.energy]
            return ready if len(ready) > 1 else []  # a known incoming move has no opposing choice to mix against
        if (self.mix_switch and head == "simultaneous" and not view.me.switch_wait and not view.me.busy
                and not view.foe_switch_wait and not view.foe_busy and view.me.bench()):
            # imagine() orders the opposing side as the visible slots followed by guessed slots.
            seen = view.foe_shown
            bench = [i for i, m in enumerate(seen) if m is not view.foe and m.hp > 0]
            unseen = max(0, min(view.foe_left - sum(m.hp > 0 for m in seen), 3 - len(seen)))
            bench += list(range(len(seen), len(seen) + unseen))
            if bench:
                return [*(self._their_throws(view) or [FAST]), *(SWITCH[i] for i in bench)]
        return []

    def _hold_plan(self, view: View) -> int | None:
        self._hold_window = self.random_hold
        try:
            return super()._hold_plan(view)
        finally:
            self._hold_window = False

    def _latest_good_turn(self, view: View, room: int) -> int:
        latest = super()._latest_good_turn(view, room)
        if not self._hold_window:
            return latest
        mine, theirs = view.me.mon.build.fast.turns, view.foe.build.fast.turns
        phase = (theirs - view.foe_busy) % theirs
        best_phase = (phase + latest * mine) % theirs
        choices = [j for j in range(room + 1) if (phase + j * mine) % theirs == best_phase]
        return self._mix_rng.choice(choices)

    def _draw(self, head: str, probabilities: dict, pick: int) -> int:
        pure = next((k for k, p in probabilities.items() if p == 1.0), None)
        choice = pure if pure is not None else self._mix_rng.choices(list(probabilities), list(probabilities.values()))[0]
        if head in ("shield", "throw"):
            setattr(self, f"last_{head}_probability", probabilities[choice])
        self.changed += choice != pick
        return choice

    def _matrix(self, view: View, head: str, options: list, seeds: list, theirs: list,
                shield_columns: bool = False) -> tuple[list, int]:
        """Our options against their fixed first choices, with the same imagined state and dice in every cell."""
        totals = [[0.0] * len(theirs) for _ in options]
        rounds = 0
        for s in seeds:
            cells = {}
            for i, k in enumerate(options):
                for j, action in enumerate(theirs):
                    if self._out_of_time():
                        break
                    old_first, old_shield = self._their_first, self._their_shield
                    if shield_columns:
                        self._their_shield = action
                    else:
                        self._their_first = action
                    try:
                        cells[i, j] = self._timed_look(view, head, k, s)
                    finally:
                        self._their_first, self._their_shield = old_first, old_shield
            if len(cells) < len(options) * len(theirs):
                break
            for (i, j), v in cells.items():
                totals[i][j] += v
            rounds += 1
        return ([[v / rounds for v in row] for row in totals] if rounds else []), rounds

    def _mixed(self, view: View, head: str, options: list, seeds: list, theirs: list, pick: int) -> int | None:
        table, rounds = self._matrix(view, head, options, seeds, theirs)
        if rounds == 0:
            return None
        self.looks += 1
        self.mixed += 1
        self.cut += rounds < len(seeds)
        if self.equilibrium and head == "shield":
            from .lab.mixed import equilibrium, shield_floor
            probabilities = dict(zip(options, equilibrium(table)))
            # For an equilibrium, closeness means the two rows' security values (worst column).
            worth = {k: min(row) for k, row in zip(options, table)}
            return self._draw(head, shield_floor(probabilities, worth, self.edge, self.shield_floor), pick)
        import numpy as np
        from .sixes import solve
        _, p, _ = solve(np.array(table), rounds=3000)
        choice = self._mix_rng.choices(options, list(p))[0]
        if head in ("shield", "throw"):
            setattr(self, f"last_{head}_probability", None)  # legacy random choices are excluded
        self.changed += choice != pick
        return choice

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
        if head == "simultaneous":
            first = option  # the matrix rows are actual legal action codes
        elif head == "throw":
            first = FAST if option == 0 else CHARGED[option - 1]
        elif head in ("swap", "mid_swap"):
            first = None if option == 0 else SWITCH[others[option - 1]]
        if self.rollout == "bot":
            # Both imagined players keep the default shield margin and direction, and imagined trained
            # bots make no mid-matchup swap search. These settings change only the engine's own decisions.
            us = Learner(q=self.q, margin=self.margin, seed=rng.getrandbits(32), even_cost=self.even_cost)
            them = self._imagined_opponent(rng)
        else:
            us, them = _rollout(), _rollout()
        if self._their_first is not None and head != "shield":
            them = _First(them, self._their_first)
        if self._their_shield is not None:
            them = _FirstShield(them, self._their_shield, view.turn)
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
        if self.judge == "end":
            battle.run()
            return decisive(battle, 0)
        if self.judge == "turn":
            stop = view.turn + self.horizon
            while battle.turn < stop and battle.winner is None:
                battle.step()
        else:
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
        if (self.mix_shield or self.equilibrium) and self._their_first in CHARGED:
            move = thrower.build.charged[self._their_first - CHARGED[0]]
        else:
            move = ready[0] if len(ready) == 1 or rng.random() < bait else ready[-1]
        if self._lab_shield:
            # The old task-25 landing predates form rules. The opt-in path uses the battle's real hit
            # resolution (Disguise, Gulp Missile, shield/charged form changes and buffs included).
            thrower.energy = energy
            player = battle.agents[0]
            battle.agents[0] = _FirstShield(player, shielded, battle.turn)
            try:
                battle._throw(1, thrower.build.charged.index(move))
            finally:
                battle.agents[0] = player
        else:
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
        if self._lab_shield:
            out = [i for i, side in enumerate(battle.sides) if side.left() == 0]
            if out:
                battle.winner = DRAW if len(out) == 2 else 1 - out[0]
            else:
                # As in Battle.step, both choices precede either entry (Gulp Missile can faint both).
                picks = [(i, battle.agents[i].replace(battle.views[i]))
                         for i, side in enumerate(battle.sides) if side.mon.hp <= 0]
                for i, slot in picks:
                    battle._enter(i, slot)
            return
        if target.hp <= 0:
            if ours.left() == 0:
                battle.winner = 1
            else:
                battle._enter(0, battle.agents[0].replace(battle.views[0]))
