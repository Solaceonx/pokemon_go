"""A player that learns its key decisions by playing.

The Learner is a Planner whose judgement calls come from small neural
networks instead of hand-written rules:

    shield   shield the incoming charged move, or not
    throw    with a charged move ready: hold, throw the first, or throw the second
    swap     at a new matchup with the switch ready: stay, or bring in a bench Pokémon
    mid_swap in an ongoing matchup, near their charged move: stay, or bring in either bench Pokémon
    replace  which Pokémon to send in after a faint

Everything mechanical (legal moves, finishing with a fast move, the sacrifice
rules) stays as in the Planner. The networks see the situation as numbers such
as health, energy, damage and matchup outlook, never Pokémon names, so one
policy serves any team. They also see what the Planner would do, so they begin
as a copy of it and learn where to depart from it.

Training is in two stages: imitate the Planner, then improve by self-play
(policy gradient). scripts/selfplay.py runs both unattended.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .agents import Planner, duel, fasts_to_wait
from .battle import CHARGED, ENERGY_CAP, FAST, MAX_TURNS, SWITCH, SWITCH_TURNS, View, damage

# Decisions judged option by option. For a throw: hold for one more fast move, throw the first
# charged move, throw the second, hold for four fast moves, hold for ten.
# A swap: stay, or bring in the first or second of the other two. A replacement: the first or second of them.
Q_HEADS = {"shield": 2, "throw": 5, "swap": 3, "replace": 2, "mid_swap": 3}
HOLDS = {0: 1, 3: 4, 4: 10}  # throw options that mean "only fast moves for this many turns"

HEADS = {"shield": 2, "throw": 3, "swap": 3, "replace": 2}
N_SITUATION = 42
N_FEATURES = N_SITUATION + 3  # plus which option the Planner would pick


def describe(agent: Learner, view: View, foe_energy: int | None = None) -> list[float]:
    """The situation as the player sees it, as a fixed list of numbers."""
    me, mon, foe = view.me, view.me.mon, view.foe
    fast, foe_fast = mon.build.fast, foe.build.fast
    hp, foe_hp = max(mon.hp, 1), max(foe.hp, 1)
    their_energy = foe.energy if foe_energy is None else foe_energy
    x = [
        max(mon.hp, 0) / mon.build.hp, mon.energy / ENERGY_CAP, mon.atk_stage / 4, mon.def_stage / 4,
        me.shields / 2, me.switch_wait / SWITCH_TURNS, me.left() / 3,
        max(foe.hp, 0) / foe.build.hp, their_energy / ENERGY_CAP, foe.atk_stage / 4, foe.def_stage / 4,
        view.foe_shields / 2, view.foe_switch_wait / SWITCH_TURNS, view.foe_left / 3,
        (view.foe_left - sum(m.hp > 0 for m in view.foe_shown)) / 2,
        view.turn / MAX_TURNS,
        # the pace of the fight: share of current health lost per ten turns, and energy per turn
        min(10 * damage(mon, fast, foe) / fast.turns / foe_hp, 3.0),
        min(10 * damage(foe, foe_fast, mon) / foe_fast.turns / hp, 3.0),
        fast.energy_gain / fast.turns / 10, foe_fast.energy_gain / foe_fast.turns / 10,
        fasts_to_wait(fast.turns, foe_fast.turns, view.foe_busy) / 4,
    ]
    for user, target, target_hp, energy in ((mon, foe, foe_hp, mon.energy), (foe, mon, hp, their_energy)):
        for k in range(2):
            if k < len(user.build.charged):
                move = user.build.charged[k]
                x += [min(damage(user, move, target) / target_hp, 2.0), move.energy / ENERGY_CAP, float(energy >= move.energy)]
            else:
                x += [0.0, 1.0, 0.0]
    x.append(agent.outlook(view, me.active))
    for j in range(3):
        if j == me.active:
            continue
        if j < len(me.team) and me.team[j].hp > 0:
            m = me.team[j]
            x += [1.0, m.hp / m.build.hp, m.energy / ENERGY_CAP, agent.outlook(view, j)]
        else:
            x += [0.0, 0.0, 0.0, 0.0]
    return x


class Policy:
    """One small network per decision: inputs -> 32 hidden units -> a probability for each option."""

    def __init__(self, params: dict[str, list[np.ndarray]] | None = None, hidden: int = 32, seed: int = 0):
        rng = np.random.default_rng(seed)
        self.params = params or {
            head: [rng.normal(0, np.sqrt(2 / N_FEATURES), (N_FEATURES, hidden)), np.zeros(hidden),
                   rng.normal(0, 0.01, (hidden, n)), np.zeros(n)]
            for head, n in HEADS.items()
        }
        self._adam = {head: [[np.zeros_like(p) for p in ps], [np.zeros_like(p) for p in ps], 0]
                      for head, ps in self.params.items()}

    def probabilities(self, head: str, x: np.ndarray, mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Option probabilities for each row (illegal options get zero), and the hidden layer for training."""
        w1, b1, w2, b2 = self.params[head]
        h = np.maximum(x @ w1 + b1, 0.0)
        z = np.where(mask, h @ w2 + b2, -1e9)
        z = z - z.max(axis=-1, keepdims=True)
        p = np.exp(z)
        return p / p.sum(axis=-1, keepdims=True), h

    def choose(self, head: str, x: list[float], mask: tuple, rng, greedy: bool = False) -> int:
        p, _ = self.probabilities(head, np.asarray(x)[None, :], np.asarray(mask)[None, :])
        if greedy:
            return int(p[0].argmax())
        return min(int(np.searchsorted(np.cumsum(p[0]), rng.random())), len(p[0]) - 1)

    def step(self, head: str, x: np.ndarray, mask: np.ndarray, action: np.ndarray, weight: np.ndarray,
             rate: float, entropy_bonus: float = 0.0) -> float:
        """One Adam step that raises the log-probability of each chosen action in proportion to its weight.

        With all weights 1 this is imitation. With weight = result minus what was
        expected, it is the policy-gradient update. Returns the mean entropy.
        """
        p, h = self.probabilities(head, x, mask)
        n = len(x)
        onehot = np.zeros_like(p)
        onehot[np.arange(n), action] = 1.0
        logp = np.log(np.clip(p, 1e-12, 1.0))
        entropy = -(p * logp).sum(axis=1)
        dz = weight[:, None] * (p - onehot) + entropy_bonus * p * (logp + entropy[:, None])
        dz = np.where(mask, dz, 0.0) / n
        w1, b1, w2, b2 = self.params[head]
        dh = (dz @ w2.T) * (h > 0)
        grads = [x.T @ dh, dh.sum(axis=0), h.T @ dz, dz.sum(axis=0)]
        m, v, t = self._adam[head]
        t += 1
        self._adam[head][2] = t
        for k, g in enumerate(grads):
            m[k] = 0.9 * m[k] + 0.1 * g
            v[k] = 0.999 * v[k] + 0.001 * g * g
            self.params[head][k] = self.params[head][k] - rate * (m[k] / (1 - 0.9 ** t)) / (np.sqrt(v[k] / (1 - 0.999 ** t)) + 1e-8)
        return float(entropy.mean())

    def copy(self) -> Policy:
        return Policy({head: [p.copy() for p in ps] for head, ps in self.params.items()})

    def save(self, path: Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        np.savez(path, **{f"{head}.{k}": p for head, ps in self.params.items() for k, p in enumerate(ps)})

    @classmethod
    def load(cls, path: Path) -> Policy:
        data = np.load(path)
        return cls({head: [data[f"{head}.{k}"] for k in range(4)] for head in HEADS})


class QNet:
    """For each option at a decision, the estimated chance of winning the battle after choosing it.

    Trained on played-out examples: the same position continued once for each option.
    """

    def __init__(self, params: dict[str, list[np.ndarray]] | None = None, hidden: int = 48, seed: int = 0):
        rng = np.random.default_rng(seed)
        self.params = params or {
            head: [rng.normal(0, np.sqrt(2 / N_FEATURES), (N_FEATURES, hidden)), np.zeros(hidden),
                   rng.normal(0, 0.01, (hidden, n)), np.zeros(n)]
            for head, n in Q_HEADS.items()
        }

    def values(self, head: str, x) -> np.ndarray:
        w1, b1, w2, b2 = self.params[head]
        h = np.maximum(np.asarray(x) @ w1 + b1, 0.0)
        return 1.0 / (1.0 + np.exp(-(h @ w2 + b2)))

    def fit(self, head: str, x: np.ndarray, y: np.ndarray, epochs: int = 40, batch: int = 256,
            rate: float = 2e-3, decay: float = 1e-4, seed: int = 0) -> None:
        """y holds the result of each played-out option (1 win, 0 loss, 0.5 draw), NaN where an option was not tried."""
        rng = np.random.default_rng(seed)
        known = ~np.isnan(y)
        target = np.where(known, y, 0.0)
        params = self.params[head]
        m, v, t = [np.zeros_like(p) for p in params], [np.zeros_like(p) for p in params], 0
        for _ in range(epochs):
            order = rng.permutation(len(x))
            for start in range(0, len(x), batch):
                rows = order[start:start + batch]
                w1, b1, w2, b2 = params
                h = np.maximum(x[rows] @ w1 + b1, 0.0)
                out = 1.0 / (1.0 + np.exp(-(h @ w2 + b2)))
                dz = (out - target[rows]) * known[rows] / max(known[rows].sum(), 1)
                dh = (dz @ w2.T) * (h > 0)
                grads = [x[rows].T @ dh + decay * w1, dh.sum(axis=0), h.T @ dz + decay * w2, dz.sum(axis=0)]
                t += 1
                for k, g in enumerate(grads):
                    m[k] = 0.9 * m[k] + 0.1 * g
                    v[k] = 0.999 * v[k] + 0.001 * g * g
                    params[k] = params[k] - rate * (m[k] / (1 - 0.9 ** t)) / (np.sqrt(v[k] / (1 - 0.999 ** t)) + 1e-8)

    def save(self, path: Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        np.savez(path, **{f"{head}.{k}": p for head, ps in self.params.items() for k, p in enumerate(ps)})

    @classmethod
    def load(cls, path: Path) -> QNet:
        data = np.load(path)
        return cls({head: [data[f"{head}.{k}"] for k in range(4)] for head in Q_HEADS if f"{head}.0" in data})


class Learner(Planner):
    """A Planner whose shield, charged-move, swap and replacement choices come from a Policy.

    With no policy it plays exactly as the Planner; give it a log list and it
    records every such decision as (head, features, legal options, choice),
    which is the data for imitation and for learning from results.
    """

    def __init__(self, policy: Policy | None = None, log: list | None = None, greedy: bool = False,
                 q: QNet | None = None, margin: float = 0.03, mid_swap: bool = True, **settings):
        super().__init__(**settings)
        self.policy = policy
        self.log = log
        self.greedy = greedy
        self.q = q  # with a QNet, shields and throws go to the option it rates best
        self.margin = margin  # ... but only when that beats the Planner's pick by this much
        self.mid_swap = mid_swap
        self.departed = 0  # how often it overruled the Planner
        self.departures: dict = {}  # (decision, Planner's pick, its pick) -> count
        self.forced: dict = {}  # decision -> the choice it must make next time, for trying options out
        self._hold = 0  # turns for which it must only use fast moves
        self._outlooks: dict = {}

    def clone(self) -> Learner:
        twin = super().clone()
        twin.log, twin.forced = None, dict(self.forced)
        return twin

    def force(self, head: str, option: int) -> None:
        """Make its next decision of this kind come out as the given option (numbered as in Q_HEADS)."""
        if head == "throw" and option in HOLDS:
            self.forced[head], self._hold = 0, HOLDS[option] - 1
        else:
            self.forced[head] = option

    def outlook(self, view: View, slot: int) -> float:
        """The one-on-one outlook for a team slot, refreshed when health or shields change noticeably."""
        me, mon, foe = view.me, view.me.team[slot], view.foe
        key = (slot, foe.build.uid, me.shields, view.foe_shields, 4 * mon.hp // mon.build.hp, 4 * foe.hp // foe.build.hp)
        if key not in self._outlooks:
            self._outlooks[key] = duel(mon, foe, me.shields, view.foe_shields, coming_in=slot != me.active)
        return self._outlooks[key]

    def _decide(self, head: str, view: View, mask: tuple, planner_choice, foe_energy: int | None = None) -> int:
        # The Planner's own pick is one of the inputs, so the networks start out able to copy
        # it exactly and training only has to learn when to do something else.
        if head in self.forced:
            return self.forced.pop(head)
        advice = planner_choice()
        if self.policy is None and self.q is None and self.log is None:
            return advice
        x = describe(self, view, foe_energy) + [float(advice == k) for k in range(3)]
        if self.q is not None and head in self.q.params:
            v = self.q.values(head, x)
            if head == "throw":  # holding is worth whatever the best length of hold is worth
                v = [max(v[0], v[3], v[4]), v[1], v[2]]
            best = max((k for k in range(len(mask)) if mask[k]), key=lambda k: v[k])
            choice = best if v[best] - v[advice] > self.margin else advice
            if choice != advice:
                self.departed += 1
                self.departures[head, advice, choice] = self.departures.get((head, advice, choice), 0) + 1
        elif self.policy is None or head not in self.policy.params:
            choice = advice
        else:
            choice = self.policy.choose(head, x, mask, self.rng, self.greedy)
        if self.log is not None:
            self.log.append((head, x, mask, choice))
        return choice

    def shield(self, view: View, foe_energy: int) -> bool:
        if view.me.left() == 1:
            return True
        return bool(self._decide("shield", view, (True, True),
                                 lambda: int(Planner.shield(self, view, foe_energy)), foe_energy))

    def _pick_move(self, view: View) -> int:
        if self._hold > 0:
            self._hold -= 1
            return FAST
        mon, foe = view.me.mon, view.foe
        moves = mon.build.charged
        ready = [mon.energy >= move.energy for move in moves]
        if not any(ready) or foe.hp <= damage(mon, mon.build.fast, foe):
            return FAST

        def planner_choice() -> int:
            action = Planner._pick_move(self, view)
            return 0 if action == FAST else action - CHARGED[0] + 1

        choice = self._decide("throw", view, (True, ready[0], len(moves) > 1 and ready[1]), planner_choice)
        return FAST if choice == 0 else CHARGED[choice - 1]

    def _swap_choice(self, view: View) -> int | None:
        me = view.me
        others = [j for j in range(3) if j != me.active]
        bench = me.bench()

        def planner_choice() -> int:
            slot = Planner._swap_choice(self, view)
            return 0 if slot is None else others.index(slot) + 1

        choice = self._decide("swap", view, (True, others[0] in bench, others[1] in bench), planner_choice)
        return None if choice == 0 else others[choice - 1]

    def _pick_switch(self, view: View) -> int | None:
        me, foe = view.me, view.foe
        # Old models keep their original path, without describing extra positions. Logging
        # and forced choices also enable the head before it has been fitted for the first time.
        enabled = self.mid_swap and (self.log is not None or "mid_swap" in self.forced
                                    or (self.q is not None and "mid_swap" in self.q.params))
        if (not enabled or me.busy or me.mon.hp <= 0 or me.switch_wait or not me.bench()
                or self._judged != (me.active, foe.build.uid)
                or foe.energy + 2 * foe.build.fast.energy_gain
                < min((move.energy for move in foe.build.charged), default=float("inf"))):
            return Planner._pick_switch(self, view)

        others = [j for j in range(3) if j != me.active]
        bench = me.bench()

        def planner_choice() -> int:
            # Preserve the Planner's sacrifice/rescue advice as the default option.
            action = Planner._pick_switch(self, view)
            return 0 if action is None else others.index(action - SWITCH[0]) + 1

        choice = self._decide("mid_swap", view, (True, others[0] in bench, others[1] in bench), planner_choice)
        if choice == 0:
            return None
        self._hold = 0
        return SWITCH[others[choice - 1]]

    def replace(self, view: View) -> int:
        me = view.me
        bench = me.bench()
        self._hold = 0
        if len(bench) == 1 or not self.switches:
            return bench[0]
        others = [j for j in range(3) if j != me.active]
        choice = self._decide("replace", view, (others[0] in bench, others[1] in bench),
                              lambda: others.index(Planner.replace(self, view)))
        return others[choice]


def batches(log: list) -> dict[str, tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]]:
    """Group logged decisions by head as arrays: features, legal options, choices, and each one's weight."""
    out = {}
    for head, n in HEADS.items():
        rows = [r for r in log if r[0] == head]
        if rows:
            mask = np.array([list(r[2]) + [False] * (n - len(r[2])) for r in rows], dtype=bool)
            out[head] = (np.array([r[1] for r in rows]), mask, np.array([r[3] for r in rows]),
                         np.array([r[4] if len(r) > 4 else 1.0 for r in rows]))
    return out
