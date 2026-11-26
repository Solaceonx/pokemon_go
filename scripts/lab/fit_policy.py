#!/usr/bin/env python3
"""Fit a policy (pogo.lab.policy.PolicyNet) to someone's decisions, as the trained bot sees them (lab-learn).

    python scripts/lab/fit_policy.py engine --games DIR [DIR ...] [--out runs/lab-learn/engine-policy/policy.npz]
    python scripts/lab/fit_policy.py owner [--games runs/people/owner_games.jsonl] [--out runs/lab-learn/owner-policy/policy.npz]

engine: the website engine's own choices, from task 39's self-play games (scripts/engine_loop.py's round_N/games/ part
files: at every decision of either side the bot's inputs, its legal options, the trained bot's pick and the engine's
pick). Round 1's games are E_0 against itself: the website's settings, horizon 20, no clock, the shipped q and the
evaluation of the time. Games numbered 0 mod 10 are held back, as task 39 holds them back. A model of the engine as an
opponent, for pogo.lab.engines.ModelledEngine (engine_versus "website,opp_policy=PATH").

owner: the owner's own website games (runs/people/owner_games.jsonl, task 42's export: teams, dice and both sides'
choices, every game replays exactly). Each game is replayed with the trained bot watching the owner's side; at each of
the bot's decisions the owner's choice is the label: a throw decision, the owner's action that turn (a fast move is
holding; a switch that turn is no throw decision and is skipped); a swap decision at a new matchup, a switch by the
owner within --swap-window turns (before any charged move of theirs) is that swap, else staying; shields and
replacements as made. Decisions on the turns of a game's `held_out` list (the exam's) are never used. Scored by
game-wise cross-validation; then fitted on every game. The anchor for piKL play (engine_versus
"bot,anchor=PATH,lam=...").

Both print, on decisions not fitted on: how often the policy's likeliest option is the one chosen, against how often
the trained bot's pick is; the same where the chooser departed from the trained bot; and the log loss against the
trained bot's pick taken with the chooser's overall rate of departing (a fair baseline). With --bot-input (the
default) the policy also sees the trained bot's pick.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path[:0] = [str(ROOT)]
from pogo.battle import CHARGED, FAST, SWITCH, Battle  # noqa: E402
from pogo.lab.policy import POLICY_HEADS, PolicyNet  # noqa: E402
from pogo.learner import Q_HEADS, Learner, QNet  # noqa: E402

SHIPPED_Q = ROOT / "runs" / "general-decide" / "q.npz"
ENGINE_HEADS = list(Q_HEADS)  # decision kinds by number in engine_loop.py's saved games


def onehot(index: np.ndarray, n: int = 3) -> np.ndarray:
    out = np.zeros((len(index), n))
    out[np.arange(len(index)), index.astype(int)] = 1.0
    return out


# --- the engine's choices --------------------------------------------------------------------------------------------

def engine_rows(folders: list[str]) -> dict:
    """Per kind of decision: inputs, legal options, the trained bot's pick, the engine's pick, the game number."""
    parts = [(k, p) for k, f in enumerate(folders) for p in sorted(Path(f).glob("part_*.npz"))]
    if not parts:
        raise SystemExit(f"no part_*.npz files in {folders}")
    keys = ("head", "x", "legal", "bot", "pick", "game", "side")
    cols = {k: [] for k in keys}
    for k, path in parts:
        d = np.load(path)
        for key in keys:
            cols[key].append(d[key] + (1_000_000 * k if key == "game" else 0))  # game numbers apart for each folder
    data = {k: np.concatenate(v) for k, v in cols.items()}
    out = {}
    for code, head in enumerate(ENGINE_HEADS):
        rows = data["head"] == code
        if head in POLICY_HEADS and rows.any():
            out[head] = {"x": data["x"][rows].astype(np.float64), "mask": data["legal"][rows][:, :POLICY_HEADS[head]],
                         "bot": data["bot"][rows].astype(int), "target": data["pick"][rows].astype(int),
                         "game": data["game"][rows]}
    print(f"{len(parts)} part files, {len(data['head'])} decisions, {len(np.unique(data['game']))} games; "
          + ", ".join(f"{h} {len(r['x'])} ({100 * (r['bot'] != r['target']).mean():.1f}% the engine overrode)"
                      for h, r in out.items()), flush=True)
    return out


# --- the owner's choices ---------------------------------------------------------------------------------------------

class Watched:
    """The owner's side as recorded (pogo.review.Replay), with the trained bot watching: at each of the bot's decisions
    its inputs, legal options and pick are kept with the turn, the slot in play and, for shields, the owner's answer."""

    def __init__(self, script, bot: Learner):
        self.script, self.bot, self.rows = script, bot, []

    def saw_throw(self, view, move, energy, could_shield):
        self.bot.saw_throw(view, move, energy, could_shield)

    def saw_shield(self, view, shielded):
        self.bot.saw_shield(view, shielded)

    def _keep(self, view, seen: int, heads: tuple, last: bool = False, **extra) -> None:
        # Advice asked inside a decision (Planner._doomed asks its own shield advice during a throw decision) is not a
        # decision of the game: keep only the kinds this call decides, and for a shield or a send-in only the last.
        logged = [r for r in self.bot.log[seen:] if r[0] in heads]
        for head, x, mask, pick in logged[-1:] if last else logged:
            self.rows.append({"turn": view.turn, "head": head, "x": list(x), "mask": list(mask), "bot": int(pick),
                              "active": view.me.active, **extra})

    def act(self, view):
        seen = len(self.bot.log)
        self.bot.act(view)
        self._keep(view, seen, ("throw", "swap"))
        return self.script.act(view)

    def shield(self, view, energy, *move):
        seen = len(self.bot.log)
        self.bot.shield(view, energy)
        answer = bool(self.script.shield(view, energy))
        self._keep(view, seen, ("shield",), last=True, answer=int(answer))
        return answer

    def replace(self, view):
        seen = len(self.bot.log)
        self.bot.replace(view)
        slot = self.script.replace(view)
        self._keep(view, seen, ("replace",), last=True, answer_slot=slot)
        return slot


def label(row: dict, acts: dict, window: int) -> int | None:
    """The owner's choice at one of the bot's decisions, numbered as the bot numbers the options; None: not a choice
    of that kind."""
    head, turn, active = row["head"], row["turn"], row["active"]
    others = [j for j in range(3) if j != active]
    if head == "shield":
        return row["answer"]
    if head == "replace":
        return others.index(row["answer_slot"]) if row["answer_slot"] in others else None
    if head == "throw":
        action = acts.get(turn, FAST)
        if action == FAST:
            return 0
        return CHARGED.index(action) + 1 if action in CHARGED else None
    if head == "swap":
        for t in range(turn, turn + window + 1):
            action = acts.get(t)
            if action in CHARGED:
                return 0
            if action in SWITCH:
                slot = action - SWITCH[0]
                return others.index(slot) + 1 if slot in others else 0
        return 0
    return None


def owner_rows(path: Path, window: int) -> dict:
    from pogo.gamedata import GameData
    from pogo.review import Logged, Replay
    gd, q = GameData(), QNet.load(SHIPPED_Q)
    games = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    rows, skipped, held = [], [], 0
    for g, game in enumerate(games):
        teams = [[gd.build(sid, moves, level=level, ivs=tuple(ivs)) for sid, moves, level, ivs in t] for t in game["teams"]]
        script = Replay(game["my_choices"])
        watched = Watched(script, Learner(q=q, margin=0.02, log=[], mid_swap=False, seed=g))
        battle = Battle(teams[0], teams[1], watched, Logged(game["log"]), seed=game["seed"], record=True)
        battle.run()
        if [list(e) for e in battle.log] != [list(e) for e in game["log"]]:
            skipped.append(game["game"])  # the bot watching must not change the game; a game that differs is left out
            continue
        out_turns = {turn for side, turn, _ in game.get("held_out", []) if side == 0}
        for row in watched.rows:
            if row["turn"] in out_turns:
                held += 1
                continue
            y = label(row, script.acts, window)
            if y is not None and row["mask"][y]:
                rows.append({**row, "target": y, "game": g})
    print(f"{len(games)} games, {len(skipped)} not replaying with the bot watching {skipped}; {held} decisions on "
          f"held-out (exam) turns left out; {len(rows)} decisions kept", flush=True)
    out = {}
    for head in POLICY_HEADS:
        r = [row for row in rows if row["head"] == head]
        if r:
            out[head] = {"x": np.array([row["x"] for row in r], float),
                         "mask": np.array([row["mask"] + [False] * (POLICY_HEADS[head] - len(row["mask"])) for row in r], bool),
                         "bot": np.array([row["bot"] for row in r]), "target": np.array([row["target"] for row in r]),
                         "game": np.array([row["game"] for row in r])}
    print(", ".join(f"{h} {len(r['x'])} ({100 * (r['bot'] != r['target']).mean():.1f}% the owner departed from the bot)"
                    for h, r in out.items()), flush=True)
    return out


# --- fitting and scoring ---------------------------------------------------------------------------------------------

def inputs(rows: dict, bot_input: bool) -> np.ndarray:
    return np.hstack([rows["x"], onehot(rows["bot"])]) if bot_input else rows["x"]


def score(net: PolicyNet, head: str, rows: dict, train_departure: float, bot_input: bool) -> dict:
    """How the policy and the trained bot do as predictions of the chooser on these rows."""
    p = net.probabilities(head, inputs(rows, bot_input), rows["mask"])
    target, bot, mask = rows["target"], rows["bot"], rows["mask"]
    guess = np.where(mask, p, -1).argmax(axis=1)
    n = len(target)
    departed = bot != target
    legal = mask.sum(axis=1)
    eps = min(max(train_departure, 1e-3), 0.5)
    base = np.where(departed, eps / np.maximum(legal - 1, 1), 1 - eps)  # the bot's pick, departing at the usual rate
    out = {"decisions": int(n), "departed": int(departed.sum()),
           "policy_top1": float((guess == target).mean()), "bot_top1": float((bot == target).mean()),
           "policy_top1_where_departed": float((guess == target)[departed].mean()) if departed.any() else None,
           "policy_predicts_departure": float((guess != bot).mean()),
           "policy_departure_precision": float((guess == target)[guess != bot].mean()) if (guess != bot).any() else None,
           "policy_log_loss": float(-np.log(np.clip(p[np.arange(n), target], 1e-12, 1)).mean()),
           "bot_log_loss": float(-np.log(base).mean()),
           "policy_mean_prob_departure": float((1 - p[np.arange(n), bot]).mean())}
    return out


def show(head: str, s: dict) -> str:
    pct = lambda v: "-" if v is None else f"{100 * v:.1f}%"  # noqa: E731
    return (f"  {head:8s} {s['decisions']:7d} decisions ({s['departed']} departed from the bot): likeliest option chosen "
            f"{pct(s['policy_top1'])} against the bot's {pct(s['bot_top1'])}; where departed {pct(s['policy_top1_where_departed'])}; "
            f"predicts a departure at {pct(s['policy_predicts_departure'])} (right {pct(s['policy_departure_precision'])}); "
            f"log loss {s['policy_log_loss']:.4f} against {s['bot_log_loss']:.4f}")


def fit_heads(data: dict, train: dict, args, seed: int) -> PolicyNet:
    width = 48 if args.bot_input else 45
    net = PolicyNet.new(inputs=width, hidden=args.hidden, seed=seed, bot_input=args.bot_input)
    for head, rows in data.items():
        t = train[head]
        net.fit(head, inputs(rows, args.bot_input)[t], rows["mask"][t], rows["target"][t], epochs=args.epochs,
                batch=args.batch, rate=args.rate, decay=args.decay, seed=seed)
    net.params = {h: p for h, p in net.params.items() if h in data}
    return net


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", choices=("engine", "owner"))
    parser.add_argument("--games", nargs="+", help="engine: round_N/games folders; owner: the jsonl file")
    parser.add_argument("--out", help="the policy's path (default runs/lab-learn/<source>-policy/policy.npz)")
    parser.add_argument("--hidden", type=int)
    parser.add_argument("--epochs", type=int)
    parser.add_argument("--batch", type=int)
    parser.add_argument("--rate", type=float, default=2e-3)
    parser.add_argument("--decay", type=float)
    parser.add_argument("--no-bot-input", dest="bot_input", action="store_false")
    parser.add_argument("--folds", type=int, default=5, help="owner: game-wise folds for the scores")
    parser.add_argument("--swap-window", type=int, default=6, help="owner: turns after a new matchup a switch counts as its swap")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    big = args.source == "engine"
    args.hidden = args.hidden or (64 if big else 16)
    args.epochs = args.epochs or (6 if big else 60)
    args.batch = args.batch or (1024 if big else 64)
    args.decay = args.decay if args.decay is not None else (1e-5 if big else 3e-3)
    out = Path(args.out or ROOT / "runs" / "lab-learn" / f"{args.source}-policy" / "policy.npz")
    t0 = time.time()
    if big:
        data = engine_rows(args.games or [str(ROOT / "runs" / "engine-loop" / "round_1" / "games")])
        folds = [{h: r["game"] % 10 == 0 for h, r in data.items()}]
    else:
        data = owner_rows(Path(args.games[0]) if args.games else ROOT / "runs" / "people" / "owner_games.jsonl", args.swap_window)
        games = np.unique(np.concatenate([r["game"] for r in data.values()]))
        fold_of = dict(zip(np.random.default_rng(args.seed).permutation(games), np.arange(len(games)) % args.folds))
        folds = [{h: np.array([fold_of[g] == k for g in r["game"]]) for h, r in data.items()} for k in range(args.folds)]
    report = {"source": args.source, "settings": {k: v for k, v in vars(args).items() if k not in ("games",)},
              "games": args.games, "held_back": {}}
    pooled: dict = {h: [] for h in data}
    for k, test in enumerate(folds):
        train = {h: ~t for h, t in test.items()}
        net = fit_heads(data, train, args, args.seed + k)
        for head, rows in data.items():
            held = {key: v[test[head]] for key, v in rows.items()}
            if len(held["target"]):
                rate = float((rows["bot"][train[head]] != rows["target"][train[head]]).mean())
                pooled[head].append((held, net, rate))
    print(f"\nnot fitted on ({'games 0 mod 10' if big else f'{args.folds} game-wise folds'}):")
    for head, parts in pooled.items():
        # each fold's policy scored on its own held-back games, pooled by decision
        scores = [score(net, head, held, rate, args.bot_input) for held, net, rate in parts]
        n = sum(s["decisions"] for s in scores)
        merged = {"decisions": n, "departed": sum(s["departed"] for s in scores)}
        for key in scores[0]:
            if key in merged:
                continue
            values = [(s[key], s["decisions"]) for s in scores if s[key] is not None]
            merged[key] = sum(v * w for v, w in values) / sum(w for _, w in values) if values else None
        report["held_back"][head] = merged
        print(show(head, merged), flush=True)
    final = fit_heads(data, {h: np.ones(len(r["target"]), bool) for h, r in data.items()}, args, args.seed) if not big else net
    final.save(out, source=args.source, bot_input=args.bot_input, hidden=args.hidden,
               decisions={h: int(len(r["target"])) for h, r in data.items()})
    report["minutes"] = round((time.time() - t0) / 60, 1)
    (out.parent / "report.json").write_bytes((json.dumps(report, indent=1) + "\n").encode("utf-8"))
    print(f"\npolicy: {out.relative_to(ROOT).as_posix() if out.is_relative_to(ROOT) else out}; report.json beside it; "
          f"{report['minutes']} min")


if __name__ == "__main__":
    main()
