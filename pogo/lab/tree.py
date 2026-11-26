"""A search tree over our own later decisions, and a root that spends its battles where they decide (engine lab).

The website engine (pogo.engine, flat Monte Carlo) plays each option of a decision the same number of times
(`samples`), with the trained bot choosing for us for the rest of every imagined battle. This engine changes that in
separate settings, each off at its default, so that with depth=0, root="flat" and gumbel=0 it plays move for move as
Engine / RealTime with the same settings and seed (tests/test_lab_tree.py):

- depth > 0: our later decisions inside the imagined battles (the throw, swap, mid-swap and replace calls the bot
  makes) become nodes of a tree shared by all the imagined battles of one decision. It is an open-loop,
  information-set tree: a node is our own sequence of choices so far plus what we see when deciding (our Pokémon in
  play, theirs, both shield counts); their unseen Pokémon and the dice change from battle to battle. The first time a
  node is reached it plays the trained bot's pick; later visits choose by PUCT, with the trained bot's q values as the
  prior (softmax of q plus `margin` on the rulebook's advice, over `prior_temp`, so its argmax is the bot's pick) and
  as `k0` virtual visits of value (q's differences between options, shifted so that the options visited average to
  their observed mean: q is a win chance, the look-ahead's values are evaluations). One new node per imagined battle, at most `depth` of ours below the root; beyond
  the tree the bot plays as before. An option is then worth what it leads to when we also play our next calls well,
  not only as the bot would play them.
- root="sh": sequential halving at the root (Karnin, Koren and Somekh 2013; as in Gumbel MuZero, Danihelka et al.
  2022). The same total number of imagined battles as the flat engine (samples x options, or `sims`), in rounds that
  drop the worse half of the options, so the last two get more battles each. Every option alive in a round is played
  on the same seeds (the same imagined teams and dice), so comparisons stay paired as in the flat engine.
  protect_pick (on) keeps the trained bot's pick to the end, so the edge rule compares on the same battles.
- gumbel > 0: Gumbel noise of this scale on the prior's logits, and the choice is the survivor with the best
  noise + logit + sigma(mean), sigma(q) = gscale x (50 + most battles of an option) x q (Danihelka et al.). A mixed
  strategy, random in close calls only, that in expectation improves on the prior. The edge rule is not used then.
- adversary=1 (opponents="bot" only): their decisions inside the imagined battles are nodes too, keyed by our root
  choice, their own choices and what they see, chosen by PUCT for them (their value is 1 - ours). The look-ahead
  then answers an opponent that adapts inside the tree, not only the trained bot's fixed picks.
- fix_stay=1: the "stay" option of a swap or mid-swap decision is played as staying. Engine._look plays it with no
  first action, so the fresh imagined bot asks the same swap question again and, when the trained bot's pick is a
  switch, makes that switch: in the website engine "stay" is then scored as the bot's switch (equal worths, to the last
  digit, in every such search checked) and the engine can never overrule a switch of the bot's by staying.
- fix_judged=1: imagined players are fresh, so each asks its matchup's swap question again at its first free act. The
  opponent in a look can then swap at its first step where its real counterpart settled the matchup long ago (the
  Rage Fist position: the imagined Altaria swaps to Jellicent before our throw lands, so both throws score the same),
  and after a throw our own imagined bot can swap out. This carries over our judgement of the matchup in play (throw
  and shield decisions) and treats theirs as settled when the matchup stood at our previous decision with their
  switch free.
- closed=0 drops "what we see" from node keys (pure open loop: one node per sequence of our own choices).
- tree_heads: which of our decisions inside the look-ahead become nodes (default the searched heads, without
  shields; "throw+swap+mid_swap+replace+shield" adds our shield calls).

The search is per decision: no tree is kept from one decision to the next (the position moves on by several turns
and new information arrives between decisions).
"""
from __future__ import annotations

import math
import random

from ..arena import decisive
from ..battle import CHARGED, FAST, SWITCH
from ..engine import _First, _FirstShield, imagine
from ..learner import Learner, describe, form_state, known_foes
from .engines import ModelledEngine


def bot_values(agent: Learner, head: str, view, mask: tuple, advice: int, foe_energy: int | None = None):
    """The trained bot's pick and its q value for each option, worked out as Learner._decide does (values None when
    its networks have no head for this decision)."""
    q = agent.q
    if q is None or head not in q.params:
        return advice, None
    x = describe(agent, view, foe_energy) + [float(advice == k) for k in range(3)]
    if agent.wide:
        x += known_foes(view)
    if agent.forms:
        x += form_state(view)
    v = q.values(head, x[:q.params[head][0].shape[0]])
    if head == "throw":  # holding is worth whatever the best length of hold is worth
        v = [max(v[0], v[3], v[4]), v[1], v[2]]
    v = [float(u) for u in v[:len(mask)]]
    best = max((k for k in range(len(mask)) if mask[k]), key=lambda k: v[k])
    margin = agent._head_margin(head, view)
    choice = best if v[best] - v[advice] > margin else advice
    if head == "shield" and agent.shield_toward and advice:
        choice = advice
    return choice, v


def prior_logits(values, advice: int, size: int, margin: float, temp: float) -> list:
    """Logits whose argmax is the trained bot's pick: (q + margin on the rulebook's advice) / temp."""
    if values is None:
        return [1.0 if k == advice else 0.0 for k in range(size)]
    return [(values[k] + (margin if k == advice else 0.0)) / temp for k in range(size)]


def softmax(logits: list, legal: list) -> dict:
    top = max(logits[k] for k in legal)
    e = {k: math.exp(logits[k] - top) for k in legal}
    z = sum(e.values())
    return {k: e[k] / z for k in legal}


class Node:
    """One decision inside the look-ahead, for the side that makes it: visits and summed value by option."""

    __slots__ = ("visits", "total", "logits", "q0")

    def __init__(self, size: int, logits: list, q0):
        self.visits = [0] * size
        self.total = [0.0] * size
        self.logits = logits
        self.q0 = q0  # the trained bot's value of each option, or None

    def select(self, mask: tuple, c: float, k0: float, pick: int) -> int:
        legal = [k for k in range(len(mask)) if mask[k]]
        p = softmax(self.logits, legal)
        n = sum(self.visits[k] for k in legal)
        if n == 0:
            return pick
        mean = sum(self.total[k] for k in legal) / n
        root = math.sqrt(n)
        # The bot's q values are win chances, the look-ahead's values are evaluations on another scale: use q only
        # for the differences between options, anchored so that the options played so far average to their mean.
        shift = mean - sum(self.visits[k] * self.q0[k] for k in legal) / n if self.q0 is not None else 0.0

        def score(k: int) -> float:
            base = self.q0[k] + shift if self.q0 is not None else mean
            value = (self.total[k] + k0 * base) / (self.visits[k] + k0) if k0 > 0 or self.visits[k] else base
            return value + c * p[k] * root / (1 + self.visits[k])

        return max(legal, key=lambda k: (score(k), k == pick))

    def update(self, option: int, value: float) -> None:
        self.visits[option] += 1
        self.total[option] += value


class Search:
    """The tree of one decision's look-ahead, shared by every imagined battle of that decision."""

    def __init__(self, depth: int, c: float, k0: float, temp: float, heads: tuple, closed: bool):
        self.depth, self.c, self.k0, self.temp, self.heads, self.closed = depth, c, k0, temp, heads, closed
        self.nodes: dict = {}
        self.expanded = False  # a node was added in the current imagined battle


class _Stay:
    """The first action of the "stay" option at a swap or mid-swap decision (fix_stay=1): no switch now. The player
    counts the matchup as judged and makes its own fast move or throw, as Planner.act does once it stays."""

    def __init__(self, inner):
        self.inner, self.first = inner, True
        self.sees_move = getattr(inner, "sees_move", False)

    def act(self, view):
        if not self.first:
            return self.inner.act(view)
        self.first = False
        player = self.inner
        player._judged = (view.me.active, view.foe.build.uid)
        player._sweeper_slot(view)
        action = player._pick_move(view) if player.moves else FAST
        if action == FAST:
            player._fasted = player._judged
        return action

    def shield(self, view, energy, *move):
        return self.inner.shield(view, energy, *move)

    def replace(self, view):
        return self.inner.replace(view)


def seen(view) -> tuple:
    """What a side sees that a node is keyed by (with closed=1): Pokémon in play on both sides, both shield counts."""
    return (view.me.active, view.foe.build.uid, view.me.shields, view.foe_shields)


class TreeLearner(Learner):
    """The trained bot, except that its calls in `search.heads` are nodes of the search tree (see the module notes)."""

    def __init__(self, *args, search: Search | None = None, side: int = 0, path: tuple = (), **kwargs):
        super().__init__(*args, **kwargs)
        self.search, self.side, self.path = search, side, path
        self.trail: list = []  # (node, option) of every node passed in this imagined battle
        self.in_tree = 0  # nodes of ours passed in this imagined battle
        self._busy = False

    def _decide(self, head, view, mask, planner_choice, foe_energy=None):
        s = self.search
        # Advice asked for inside another decision (Planner._doomed asks its own shield advice) is not a decision.
        if s is None or self._busy or head in self.forced or head not in s.heads or sum(mask) < 2:
            return super()._decide(head, view, mask, planner_choice, foe_energy)
        self._busy = True
        try:
            return self._node_decide(s, head, view, mask, planner_choice, foe_energy)
        finally:
            self._busy = False

    def _node_decide(self, s: Search, head, view, mask, planner_choice, foe_energy):
        key = (self.side, self.path, head, seen(view) if s.closed else None)
        node = s.nodes.get(key)
        if node is None and (s.expanded or self.in_tree >= s.depth):
            return super()._decide(head, view, mask, planner_choice, foe_energy)
        advice = planner_choice()
        pick, values = bot_values(self, head, view, mask, advice, foe_energy)
        if node is None:
            margin = self._head_margin(head, view)
            node = s.nodes[key] = Node(len(mask), prior_logits(values, advice, len(mask), margin, s.temp), values)
            s.expanded = True
            choice = pick
        else:
            choice = node.select(mask, s.c, s.k0, pick)
        self.trail.append((node, choice))
        self.path = self.path + ((head, choice),)
        self.in_tree += 1
        return choice


class TreeEngine(ModelledEngine):
    def __init__(self, *args, depth: int = 0, root: str = "flat", sims: int | None = None, c_puct: float = 0.5,
                 prior_temp: float = 0.1, k0: float = 1.0, gumbel: float = 0.0, gscale: float = 1.0,
                 adversary: bool = False, protect_pick: bool = True, closed: bool = True,
                 tree_heads: tuple | None = None, fix_stay: bool = False, fix_judged: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        if root not in ("flat", "sh"):
            raise ValueError(f"unknown root {root!r}")
        if adversary and self.opponents != "bot":
            raise ValueError("adversary needs opponents='bot' (the imagined opponent must be the trained bot)")
        self.depth, self.root, self.sims, self.c_puct, self.prior_temp, self.k0 = depth, root, sims, c_puct, prior_temp, k0
        self.gumbel, self.gscale, self.adversary, self.protect_pick, self.closed = gumbel, gscale, adversary, protect_pick, closed
        self.fix_stay, self.fix_judged = fix_stay, fix_judged
        self._last_pair, self._last_foe_free, self._foe_settled = None, False, False
        self.tree_heads = tuple(tree_heads) if tree_heads is not None else tuple(h for h in self.heads if h != "shield")
        self._search: Search | None = None
        self.nodes_made = 0  # tree nodes over all searches, for reports
        self.record: list | None = None  # set to a list to keep every searched decision (scripts/lab/search_positions.py)
        self.last: dict | None = None

    def clone(self) -> TreeEngine:
        twin = super().clone()
        twin._search, twin.record, twin.last = None, None, None
        return twin

    def act(self, view):
        # fix_judged: the opponent has settled this matchup when it stood at our last decision with their switch free
        pair = (view.me.active, view.foe.build.uid)
        self._foe_settled = self.fix_judged and self._last_pair == pair and self._last_foe_free
        try:
            return super().act(view)
        finally:
            self._last_pair, self._last_foe_free = pair, view.foe_switch_wait == 0

    def _search_decision(self, head, view, mask, planner_choice, foe_energy=None):
        # Keep Engine._decide's hypothetical-shield guard and completed-swap marker.
        if head == "throw":
            self.last_throw_probability = 1.0
        if self.stay_after_replace and head in ("swap", "mid_swap") and view.turn == self._replaced_at:
            return 0
        if self._mix_fallback or head in self.forced or head not in self.heads:
            return Learner._decide(self, head, view, mask, planner_choice, foe_energy)
        options = [k for k in range(len(mask)) if mask[k]]
        memo = []

        def advice() -> int:
            if not memo:
                memo.append(planner_choice())
            return memo[0]

        pick = Learner._decide(self, head, view, mask, advice, foe_energy)  # the trained bot's choice
        if len(options) < 2:
            return pick
        self.mid_swap_searches += head == "mid_swap"
        self._foe_energy = foe_energy if foe_energy is not None else view.foe.energy
        _, values = bot_values(self, head, view, mask, advice(), foe_energy)
        margin = self._head_margin(head, view)
        logits = prior_logits(values, advice(), len(mask), margin, self.prior_temp)
        self._search = Search(self.depth, self.c_puct, self.k0, self.prior_temp, self.tree_heads, self.closed)
        shared_choice = (
            (head == "shield" and (self.shield_mix is not None or self.shield_floor > 0))
            or (head == "throw" and (self.throw_mix is not None or self.equilibrium or self.no_tell_bait))
            or (head in ("swap", "mid_swap") and self.switch_edge != 0)
            or self.temperature > 0
        )
        try:
            theirs = self._mixed_actions(head, view)
            if theirs:
                seeds = [self.rng.getrandbits(32) for _ in range(self.samples)]
                mixed = self._mixed(view, head, options, seeds, theirs, pick)
                if mixed is not None:
                    return mixed
            seeds = []
            choice, worth, battles = self._halving(view, head, options, pick, logits, seeds)
            if choice is not None and shared_choice:
                choice = self._choose_worth(view, head, options, pick, worth, seeds)
        finally:
            nodes = len(self._search.nodes)
            self.nodes_made += nodes
            self._search = None
        self.looks += 1
        if choice is None:
            self.fell_back += 1
            choice = pick
        if not shared_choice:
            self.changed += choice != pick
        self.last = dict(turn=view.turn, head=head, options=options, pick=pick, choice=choice, q=values,
                         worth=worth, battles=battles, nodes=nodes)
        if self.record is not None:
            self.record.append(self.last)
        return choice

    def _halving(self, view, head: str, options: list, pick: int, logits: list, searched_seeds=None):
        """Sequential halving at the root ("flat": one round, every option on every seed). Returns the choice (None
        with no complete round), each option's mean worth and its number of imagined battles."""
        m = len(options)
        rounds = 1 if self.root == "flat" else max(1, math.ceil(math.log2(m)))
        budget = self.sims if self.sims is not None else self.samples * m
        alive = list(options)
        values = {k: [] for k in options}  # worth of each battle, in seed order: alive options share their seeds
        noise = {k: 0.0 for k in options}
        if self.gumbel > 0:
            noise = {k: -self.gumbel * math.log(-math.log(self._mix_rng.random() or 1e-12)) for k in options}
        used, stopped = 0, False
        for r in range(rounds):
            per = max(1, (budget - used) // (len(alive) * (rounds - r)))
            seeds = [self.rng.getrandbits(32) for _ in range(per)]
            if searched_seeds is not None:
                searched_seeds.extend(seeds)
            for s in seeds:
                done = {}
                for k in alive:
                    if self._out_of_time():
                        break
                    done[k] = self._timed_look(view, head, k, s)
                if len(done) < len(alive):
                    stopped = True
                    break
                for k in alive:
                    values[k].append(done[k])
                used += len(alive)
            if not values[alive[0]]:
                return None, {}, {}
            if stopped:
                self.cut += 1
                break
            if r < rounds - 1 and len(alive) > 2:
                keep = max(2, math.ceil(len(alive) / 2))
                ranked = sorted(alive, key=lambda k: self._score(k, values, noise, logits), reverse=True)
                survivors = ranked[:keep]
                if self.protect_pick and pick in alive and pick not in survivors:
                    survivors[-1] = pick
                alive = survivors
        worth = {k: sum(v) / len(v) for k, v in values.items() if v}
        battles = {k: len(v) for k, v in values.items()}
        if self.gumbel > 0:
            return max(alive, key=lambda k: (self._score(k, values, noise, logits), k == pick)), worth, battles
        best = max(alive, key=lambda k: (worth[k], k == pick))
        if best == pick or not values[pick]:
            return best, worth, battles
        if len(values[best]) == len(values[pick]):
            gain = worth[best] - worth[pick]  # as the flat engine works it out
        else:
            n = min(len(values[best]), len(values[pick]))  # the seeds both were played on
            gain = sum(a - b for a, b in zip(values[best][:n], values[pick][:n])) / n
        return (best if gain > self.edge else pick), worth, battles

    def _score(self, k: int, values: dict, noise: dict, logits: list) -> float:
        mean = sum(values[k]) / len(values[k])
        if self.gumbel <= 0:
            return mean
        most = max(len(v) for v in values.values())
        return noise[k] + logits[k] + self.gscale * (50 + most) * mean

    def _look(self, view, head: str, option: int, seed: int) -> float:
        """Engine._look, with tree players for us (and, with adversary, for them) while a search is running."""
        search = self._search
        if search is None:
            if not (self.fix_stay or self.fix_judged):
                return super()._look(view, head, option, seed)
            # Direct looks and simultaneous switch matrices also use the opt-in fixes.
            search = Search(0, self.c_puct, self.k0, self.prior_temp, self.tree_heads, self.closed)
        rng = random.Random(seed)
        others = [j for j in range(3) if j != view.me.active]
        first = None
        if head == "simultaneous":
            first = option
        elif head == "throw":
            first = FAST if option == 0 else CHARGED[option - 1]
        elif head in ("swap", "mid_swap"):
            first = None if option == 0 else SWITCH[others[option - 1]]
        search.expanded = False
        root = ((head, option),)
        us = TreeLearner(q=self.q, margin=self.margin, seed=rng.getrandbits(32), even_cost=self.even_cost,
                         search=search if search.depth > 0 else None, side=0, path=root)
        if self.adversary and search.depth > 0:
            them = TreeLearner(q=self.q, margin=self.margin, seed=rng.getrandbits(32), search=search, side=1, path=root)
        else:
            them = self._imagined_opponent(rng)
        if self._their_first is not None and head != "shield":
            them = _First(them, self._their_first)
        if self._their_shield is not None:
            them = _FirstShield(them, self._their_shield, view.turn)
        stays = self.fix_stay and head in ("swap", "mid_swap") and option == 0
        battle = imagine(view, rng, self.pool, _Stay(us) if stays else _First(us, first), them, teams=self._teams,
                         team_builds=self._team_builds)
        if self.fix_judged:
            self._settle(view, head, us, them, battle)
        value = self._play(battle, view, head, option, others, rng)
        for node, k in us.trail:
            node.update(k, value)
        for node, k in getattr(them, "trail", ()):
            node.update(k, 1.0 - value)
        return value

    def _settle(self, view, head: str, us, them, battle) -> None:
        """fix_judged=1: imagined players start fresh, so each asks its matchup's swap question again at its first free
        act, even where the real one settled that matchup long ago: we may swap out right after the throw being judged,
        and they may swap at the first step of every look. Carry over what was settled: our own judgement of the
        matchup in play, and theirs when the matchup stood at our previous decision with their switch free."""
        if head in ("throw", "shield", "mid_swap") and self._judged == (view.me.active, view.foe.build.uid):
            us._judged = self._judged
        player = getattr(them, "inner", them)
        while hasattr(player, "inner"):
            player = player.inner
        if self._foe_settled and head != "replace" and hasattr(player, "_judged"):
            foes = battle.sides[1]
            player._judged = (foes.active, battle.sides[0].mon.build.uid)

    def _play(self, battle, view, head: str, option: int, others: list, rng) -> float:
        if head == "replace":
            battle.sides[0].active = others[option]
            if others[option] not in battle.sides[0].shown:
                battle.sides[0].shown.append(others[option])
        if head == "shield":
            self._land_their_throw(battle, rng, shielded=option == 1)
            if battle.winner is not None:
                return decisive(battle, 0)
        foes = battle.sides[1]
        if foes.mon.hp <= 0:
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
