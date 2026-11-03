#!/usr/bin/env python3
"""Train the engine on its own games: the trained bot learns the engine's choices, the evaluation learns who won
(docs/tasks.md, task 39; the AlphaZero loop, both halves).

    python3 scripts/engine_loop.py --run engine-loop-timing --timing 50 [--workers 3]   core-seconds a game
    python3 scripts/engine_loop.py [--run engine-loop] [--rounds 3] [--games 10000] [--workers W]
    python3 scripts/engine_loop.py [--run engine-loop] --confirm [--workers W]

Round r plays the engine E_{r-1} against itself (E_0 is the website's: pogo.realtime.WEBSITE, horizon 20, no clock)
and makes E_r from its games:

1. Self-play. `--games` games on the mixed field (pogo.teamshape.mixed_field), a fresh seed each round, a fresh
   evaluation cache for each player and for each side's position recorder in every game (task 27's bug). At every
   decision of either side: the trained bot's inputs and legal options (as scripts/decide.py has them), its pick,
   the engine's pick (so whether the engine overrode it) and who won. At random moments (`--sample` a turn) both
   sides' positions with how the game ended for each (pogo.arena.decisive), as scripts/selfplay_eval.py keeps them.
   Games are saved in parts as they finish (round_N/games/) and a stopped run resumes.
2. Evaluation. A new one fitted on this round's positions, as task 31 does (64 and 32 hidden units, 30 epochs, from
   scratch); held-out log loss against the previous one.
3. Trained bot. Each head of q (shield, throw, swap, replace) refitted from the previous round's: the chosen option's
   output regresses to who won (1 win, 0.5 draw, 0 loss; log loss, as QNet.fit), plus 0.3 x cross-entropy toward the
   engine's pick over the softmax of the head's outputs divided by 0.02 (the margin). Throw options are read as the
   bot reads them: holding is worth the best of its three hold lengths. The two numbers are fixed in advance, as are
   QNet.fit's own settings (40 epochs, batches of 256, rate 0.002, decay 0.0001); the network sizes do not change.
   A tenth of the games (number % 10 == 0) are held back for both fits: on them, the fit (log loss of the chosen
   option against who won) and the agreement (the bot, margin 0.02 over the rulebook's advice as it plays, picks
   what the engine picked), new against old.
4. Measure E_r against E_0, not the previous round, so the rounds read as one curve: scripts/engine_versus.py with
   `q=` and `eval=`, the same battles every round (`--compare` pairings both ways and crowd battles, half as many
   against PvPoke's AI), at 32 samples, with search times. E_0's own crowd and PvPoke battles are played once.

Rounds go on from the newest networks whatever the result. --confirm then plays the round with the best head to
head against E_0 again on a fresh seed. Files in runs/<run>/: round_N/q.npz, eval.npz and fit.json (small),
round_N/games/ (large, not in git, made again by the same command), rounds.json, confirm.json.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import random
import sys
import time
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_v] = "1"
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
from pogo.arena import decisive, low_priority, mean_and_margin  # noqa: E402
from pogo.battle import DRAW, Battle  # noqa: E402
from pogo.engine import Engine  # noqa: E402
from pogo.evaluation import Evaluator  # noqa: E402
from pogo.learner import N_SITUATION, Q_HEADS, QNet  # noqa: E402
from pogo.realtime import WEBSITE  # noqa: E402
from pogo.value import ValueModel, log_loss  # noqa: E402

START_Q = ROOT / "runs" / "general-decide" / "q.npz"
START_EVAL = ROOT / "runs" / "eval" / "eval.npz"
SETTINGS = {**WEBSITE, "horizon": 20}  # E_r: the website's engine with no clock, with round r's networks
HEADS = list(Q_HEADS)  # decision kinds by number in the saved games
OPTIONS = 3  # legal options are saved padded to this many
CHOICE_WEIGHT, TEMPERATURE = 0.3, 0.02  # fixed in advance by the brief, not tuned
FIT = {"epochs": 40, "batch": 256, "rate": 2e-3, "decay": 1e-4}  # QNet.fit's own
GAME_KEYS = ("head", "x", "legal", "bot", "pick", "side", "game", "result",
             "pos_x", "pos_y", "pos_side", "pos_game", "games", "game_cpu", "game_turns", "game_winner")
_world: dict = {}


class Recorder(Engine):
    """The engine, writing down each of its decisions as the trained bot sees it in `record`:
    (kind, inputs, legal options, the trained bot's pick, the engine's pick)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.record: list | None = []

    def clone(self) -> Recorder:
        twin = super().clone()
        twin.record = None
        return twin

    def _decide(self, head, view, mask, planner_choice, foe_energy=None):
        # Advice asked inside a decision (Planner._doomed asks its own shield advice) is not a decision of the game.
        if self.record is None or self.log is not None:
            return super()._decide(head, view, mask, planner_choice, foe_energy)
        # Learner._decide logs the bot's inputs and pick while self.log is a list. Set only for this call:
        # Learner._pick_switch reads a log as a reason to take mid-matchup swap decisions, which this q has no head for.
        self.log = []
        try:
            choice = super()._decide(head, view, mask, planner_choice, foe_energy)
        finally:
            logged, self.log = self.log, None
        # The decision is logged last, after any advice asked on the way; nothing is logged for a forced choice.
        if logged and logged[-1][0] == head:
            _, x, legal, bot = logged[-1]
            self.record.append((head, x, legal, bot, choice))
        return choice


def points(winner: int, side: int) -> float:
    return 1.0 if winner == side else 0.5 if winner == DRAW else 0.0


def play(n: int, seed: int, q: QNet, model, pool: list, draw, sample: float, settings: dict) -> dict:
    """Game number n of a round, E against E: its decisions, its sampled positions, who won, and its CPU seconds."""
    start = time.process_time()
    rng = random.Random(seed * 1_000_003 + n)
    teams = draw(rng), draw(rng)
    # The evaluation cache is keyed by team slot and opposing species, not by our team, so each player and each
    # side's position recorder gets its own in every game: shared, one could change another's features (task 27).
    players = [Recorder(Evaluator(model), pool, q=q, seed=rng.getrandbits(32), **settings) for _ in range(2)]
    battle = Battle(*teams, *players, seed=rng.getrandbits(32))
    keep = random.Random(rng.getrandbits(32))  # when to keep positions; apart from the game's dice
    recorders = [Evaluator(), Evaluator()]
    seen = []
    while battle.winner is None:
        if keep.random() < sample:
            for side in (0, 1):
                view = battle.views[side]
                if view.me.mon.hp > 0 and view.foe.hp > 0:
                    seen.append((side, recorders[side].features(view)))
        battle.step()
    return {"decisions": [(side, *row) for side, player in enumerate(players) for row in player.record],
            "positions": [(side, x, decisive(battle, side)) for side, x in seen],
            "winner": battle.winner, "turns": battle.turn, "cpu": time.process_time() - start}


def world(field: str, q_path: str, eval_path: str):
    """The pool and team draw of a field (as scripts/engine_versus.py has them), and the networks; once a process."""
    key = (field, q_path, eval_path)
    if key not in _world:
        import engine_versus
        engine_versus.setup(field)
        s = engine_versus._state
        _world.clear()
        _world[key] = (s["pool"], s["draw"], QNet.load(q_path), Evaluator.load(eval_path).model)
    return _world[key]


def part_path(folder: Path, start: int) -> Path:
    return folder / f"part_{start:06d}.npz"


def chunk(task) -> dict:
    """Games start .. start + count - 1 of a round, saved together in one file of the round's games folder."""
    folder, q_path, eval_path, field, seed, start, count, sample, settings = task
    low_priority()
    pool, draw, q, model = world(field, q_path, eval_path)
    rows, positions, games = [], [], []
    for n in range(start, start + count):
        g = play(n, seed, q, model, pool, draw, sample, settings)
        won = [points(g["winner"], side) for side in (0, 1)]
        rows += [(HEADS.index(head), x, list(legal) + [False] * (OPTIONS - len(legal)), bot, pick, side, n, won[side])
                 for side, head, x, legal, bot, pick in g["decisions"]]
        positions += [(x, y, side, n) for side, x, y in g["positions"]]
        games.append((n, g["cpu"], g["turns"], g["winner"]))
    columns = list(zip(*rows)) if rows else [()] * 8
    pos = list(zip(*positions)) if positions else [()] * 4
    inputs = max(ps[0].shape[0] for ps in q.params.values())  # what the bot sees: describe(), its advice, any extras
    out = {"head": np.array(columns[0], dtype=np.int8), "x": np.array(columns[1], dtype=np.float32).reshape(-1, inputs),
           "legal": np.array(columns[2], dtype=bool).reshape(-1, OPTIONS), "bot": np.array(columns[3], dtype=np.int8),
           "pick": np.array(columns[4], dtype=np.int8), "side": np.array(columns[5], dtype=np.int8),
           "game": np.array(columns[6], dtype=np.int64), "result": np.array(columns[7], dtype=np.float32),
           "pos_x": np.array(pos[0], dtype=np.float32).reshape(-1, N_SITUATION), "pos_y": np.array(pos[1], dtype=np.float32),
           "pos_side": np.array(pos[2], dtype=np.int8), "pos_game": np.array(pos[3], dtype=np.int64),
           "games": np.array([g[0] for g in games], dtype=np.int64), "game_cpu": np.array([g[1] for g in games]),
           "game_turns": np.array([g[2] for g in games], dtype=np.int32), "game_winner": np.array([g[3] for g in games], dtype=np.int8)}
    path = part_path(Path(folder), start)
    temporary = path.with_name("tmp_" + path.name)  # a stopped run never leaves a half-written part behind
    np.savez_compressed(temporary, **out)
    os.replace(temporary, path)
    return {"games": count, "cpu": float(out["game_cpu"].sum()), "decisions": len(rows),
            "changed": int((out["bot"] != out["pick"]).sum()), "positions": len(positions)}


def load_games(folder: Path) -> dict:
    parts = [np.load(p) for p in sorted(folder.glob("part_*.npz"))]
    return {k: np.concatenate([p[k] for p in parts]) for k in GAME_KEYS}


def selfplay(here: Path, q_path: Path, eval_path: Path, seed: int, args) -> dict:
    folder = here / "games"
    folder.mkdir(parents=True, exist_ok=True)
    tasks = [(str(folder), str(q_path), str(eval_path), args.field, seed, start, min(args.chunk, args.games - start),
              args.sample, SETTINGS)
             for start in range(0, args.games, args.chunk) if not part_path(folder, start).exists()]
    done_before = args.games - sum(t[6] for t in tasks)
    print(f"{here.name}: self-play of {rel(q_path)} with {rel(eval_path)}, {args.games} games "
          f"({done_before} already saved), seed {seed}, {args.workers} workers", flush=True)
    t0, last, games, cpu = time.time(), time.time(), 0, 0.0
    if tasks:
        with multiprocessing.get_context("spawn").Pool(args.workers) as pool:
            for info in pool.imap_unordered(chunk, tasks):
                games, cpu = games + info["games"], cpu + info["cpu"]
                if time.time() - last > 600 or games + done_before == args.games:
                    last = time.time()
                    left = (args.games - done_before - games) * (time.time() - t0) / games / 60
                    print(f"  {games + done_before} of {args.games} games, {(time.time() - t0) / 60:.0f} min, "
                          f"{cpu / games:.1f} core-seconds a game, about {left:.0f} min to go", flush=True)
    return load_games(folder)


def option_values(q: QNet, head: str, x: np.ndarray):
    """The head's outputs as the bot reads them, one column per option; which output each column is; all outputs;
    the hidden layer."""
    w1, b1, w2, b2 = q.params[head]
    h = np.maximum(x @ w1 + b1, 0.0)
    v = 1.0 / (1.0 + np.exp(-(h @ w2 + b2)))
    if head == "throw":  # holding is worth whatever the best length of hold is worth (Learner._decide)
        holds = np.array([0, 3, 4])
        which = np.stack([holds[v[:, holds].argmax(axis=1)], np.ones(len(v), int), np.full(len(v), 2)], axis=1)
    else:
        which = np.broadcast_to(np.arange(v.shape[1]), v.shape)
    return np.take_along_axis(v, which, axis=1), which, v, h


def bot_picks(q: QNet, head: str, x: np.ndarray, legal: np.ndarray, margin: float = WEBSITE["margin"]) -> np.ndarray:
    """What the trained bot plays: its best legal option if that beats the rulebook's advice (one of its inputs) by
    the margin, else the advice (Learner._decide)."""
    u = option_values(q, head, x)[0]
    advice = x[:, N_SITUATION:N_SITUATION + 3].argmax(axis=1)
    best = np.where(legal[:, :u.shape[1]], u, -np.inf).argmax(axis=1)
    r = np.arange(len(x))
    return np.where(u[r, best] - u[r, advice] > margin, best, advice)


def loss(q: QNet, head: str, x: np.ndarray, legal: np.ndarray, pick: np.ndarray, result: np.ndarray):
    """The two parts of the loss, averaged over rows: the log loss of the chosen option's output against who won, and
    the cross-entropy toward the engine's pick over the legal options' outputs divided by TEMPERATURE. Also the
    gradient of value + CHOICE_WEIGHT x choice with respect to the head's output logits, and the hidden layer."""
    u, which, v, h = option_values(q, head, x)
    legal = legal[:, :u.shape[1]]
    n, r = len(x), np.arange(len(x))
    chosen = which[r, pick]
    p = np.clip(v[r, chosen], 1e-12, 1 - 1e-12)
    value = float(-(result * np.log(p) + (1 - result) * np.log(1 - p)).mean())
    s = np.where(legal, u / TEMPERATURE, -np.inf)
    s = s - s.max(axis=1, keepdims=True)
    logp = s - np.log(np.exp(s).sum(axis=1, keepdims=True))
    choice = float(-logp[r, pick].mean())
    dz = np.zeros_like(v)
    np.add.at(dz, (r, chosen), v[r, chosen] - result)  # log loss through the sigmoid
    onehot = np.zeros_like(u)
    onehot[r, pick] = 1.0
    du = CHOICE_WEIGHT * (np.exp(logp) - onehot) / TEMPERATURE * u * (1 - u)
    np.add.at(dz, (np.repeat(r, u.shape[1]), which.ravel()), du.ravel())
    return value, choice, dz / n, h


def refit(q: QNet, head: str, x, legal, pick, result, seed: int = 0, epochs: int = FIT["epochs"],
          batch: int = FIT["batch"], rate: float = FIT["rate"], decay: float = FIT["decay"]) -> None:
    """Adam on loss(), from the head's current weights (as QNet.fit, with this loss)."""
    rng = np.random.default_rng(seed)
    params = q.params[head]
    m, v, t = [np.zeros_like(p) for p in params], [np.zeros_like(p) for p in params], 0
    for _ in range(epochs):
        order = rng.permutation(len(x))
        for start in range(0, len(x), batch):
            rows = order[start:start + batch]
            _, _, dz, h = loss(q, head, x[rows], legal[rows], pick[rows], result[rows])
            w1, b1, w2, b2 = params
            dh = (dz @ w2.T) * (h > 0)
            grads = [x[rows].T @ dh + decay * w1, dh.sum(axis=0), h.T @ dz + decay * w2, dz.sum(axis=0)]
            t += 1
            for k, g in enumerate(grads):
                m[k] = 0.9 * m[k] + 0.1 * g
                v[k] = 0.999 * v[k] + 0.001 * g * g
                params[k] = params[k] - rate * (m[k] / (1 - 0.9 ** t)) / (np.sqrt(v[k] / (1 - 0.999 ** t)) + 1e-8)


def fit(here: Path, data: dict, q_path: Path, eval_path: Path, seed: int) -> dict:
    """The round's new eval and q, saved in `here`, with how each does on the held-back games."""
    report = {"games": int(len(data["games"])), "decisions": int(len(data["head"])),
              "engine_overrode": int((data["bot"] != data["pick"]).sum()), "positions": int(len(data["pos_y"]))}
    x, y = data["pos_x"].astype(np.float64), data["pos_y"].astype(np.float64)
    held = data["pos_game"] % 10 == 0
    model = ValueModel.train(x[~held], y[~held], hidden=(64, 32), epochs=30, seed=seed)
    model.save(here / "eval.npz")
    report["eval"] = {"train": int((~held).sum()), "held": int(held.sum()),
                      "log_loss": [log_loss(model.predict(x[held]), y[held]), log_loss(Evaluator.load(eval_path).many(x[held]), y[held])]}
    print(f"  eval: {len(y)} positions; held-out log loss {report['eval']['log_loss'][0]:.4f} new against "
          f"{report['eval']['log_loss'][1]:.4f} before", flush=True)
    old, new = QNet.load(q_path), QNet.load(q_path)
    held = data["game"] % 10 == 0
    report["q"] = {}
    for code, head in enumerate(HEADS):
        rows = data["head"] == code
        if head not in new.params or not rows.any():
            continue
        x, legal = data["x"][rows].astype(np.float64), data["legal"][rows]
        pick, bot, result, out = data["pick"][rows].astype(int), data["bot"][rows], data["result"][rows].astype(np.float64), held[rows]
        refit(new, head, x[~out], legal[~out], pick[~out], result[~out], seed=seed + code)
        x, legal, pick, bot, result = x[out], legal[out], pick[out], bot[out], result[out]  # the held-back games from here
        overrode = bot != pick
        entry = {"train": int((~out).sum()), "held": int(out.sum()), "overrode_held": int(overrode.sum()),
                 # the bot's picks worked out from the saved inputs, against those it made in the games (a check)
                 "replayed": float((bot_picks(old, head, x, legal) == bot).mean()) if len(x) else None}
        for name, net in (("new", new), ("old", old)):
            entry[name] = dict.fromkeys(("fit", "choice", "agreement", "agreement_overrode"))
            if len(x):
                value, choice, _, _ = loss(net, head, x, legal, pick, result)
                agree = bot_picks(net, head, x, legal) == pick
                entry[name].update(fit=value, choice=choice, agreement=float(agree.mean()),
                                   agreement_overrode=float(agree[overrode].mean()) if overrode.any() else None)
        report["q"][head] = entry
        print(f"  q {head}: {entry['train']} decisions, {entry['held']} held back ({entry['overrode_held']} the engine overrode); "
              f"fit {show(entry['new']['fit'])} new against {show(entry['old']['fit'])} before; agreement "
              f"{pct(entry['new']['agreement'])} against {pct(entry['old']['agreement'])}, where the engine overrode "
              f"{pct(entry['new']['agreement_overrode'])} against {pct(entry['old']['agreement_overrode'])}; "
              f"old bot's picks replayed {pct(entry['replayed'])}", flush=True)
    new.save(here / "q.npz")
    (here / "fit.json").write_text(json.dumps(report, indent=1) + "\n")  # written last: the round's fit is complete
    return report


def show(value) -> str:
    return "-" if value is None else f"{value:.4f}"


def pct(value) -> str:
    return "-" if value is None else f"{100 * value:.1f}%"


def rel(path) -> str:
    path = Path(path).resolve()
    return path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path)


def versus(tag: str, candidate: str, pairings: int, seed: int, args) -> dict:
    """scripts/engine_versus.py, E_0 as the baseline; the candidate's three changes against E_0 and its search times."""
    import engine_versus
    base = f"samples={WEBSITE['samples']}"
    sys.argv = ["engine_versus", "--tag", tag, "--baseline", base, "--candidates", candidate,
                "--pairings", str(pairings), "--crowd", str(pairings), "--pvpoke", str(pairings // 2),
                "--workers", str(args.workers), "--seed", str(seed), "--field", args.field]
    print("  $ python3 scripts/engine_versus.py " + " ".join(f'"{a}"' if "=" in a else a for a in sys.argv[1:]), flush=True)
    engine_versus.main()
    saved = json.loads((ROOT / "runs" / "engine_versus" / f"{tag}.json").read_text())
    results = saved["results"]

    def values(kind, spec):
        got = results.get(kind, {}).get(spec, {})
        return [got[k] for k in sorted(got, key=int)]

    out = {"candidate": candidate, "baseline": base, "seed": seed,
           "head_to_head": list(mean_and_margin(values("h2h", candidate)))}
    for kind in ("crowd", "pvpoke"):
        mine, theirs = values(kind, candidate), values(kind, base)
        out[kind] = {"score": list(mean_and_margin(mine)), "change": list(mean_and_margin([a - b for a, b in zip(mine, theirs)]))}
    for name, spec in (("search_ms", candidate), ("search_ms_baseline", base)):
        t = np.array([float(ms) for ms, count in saved["search_ms"].get(spec, {}).items() for _ in range(count)])
        out[name] = [float(np.median(t)), float(np.percentile(t, 99)), float(t.max())] if len(t) else None
    return out


def timing(data: dict, args) -> None:
    cpu = data["game_cpu"]
    c = float(cpu.mean())
    per = 10000 if c <= 40 else 6000
    p, rounds = args.compare, args.rounds
    # Rough: a game of E against E is two engines; a crowd or PvPoke battle one, taken as half a game.
    measure = 2 * p * c + 1.5 * p * c / 2
    confirm = 2 * args.confirm_pairings * c + 2 * 1.5 * args.confirm_pairings * c / 2  # E_0's battles again, fresh seed
    total = rounds * (per * c + measure) + 1.5 * p * c / 2 + confirm
    print(f"\ntiming: {len(cpu)} games on {args.workers} workers: {c:.1f} core-seconds a game (median "
          f"{np.median(cpu):.1f}, 90th percentile {np.percentile(cpu, 90):.1f}, longest {cpu.max():.1f}); "
          f"{data['game_turns'].mean():.0f} turns, {len(data['head']) / len(cpu):.0f} decisions a game, the engine "
          f"overrode the bot at {100 * (data['bot'] != data['pick']).mean():.1f}% of them", flush=True)
    print(f"the brief: 10,000 games a round, 6,000 if a game takes over 40 core-seconds; so {per:,} games a round", flush=True)
    print(f"rough job: self-play {rounds * per * c / 3600:.0f} core-hours, measuring {rounds * measure / 3600:.0f}, "
          f"E_0's own battles {1.5 * p * c / 2 / 3600:.0f}, confirmation {confirm / 3600:.0f}: about {total / 3600:.0f} "
          f"core-hours ({total / 3600 / max(1, args.workers):.0f} hours on {args.workers} workers)", flush=True)


def check_run(folder: Path, args) -> None:
    """A run resumes only with the settings it started with (the games' numbering and dice depend on them)."""
    fixed = {"seed": args.seed, "games": args.timing or args.games, "chunk": args.chunk, "sample": args.sample,
             "field": args.field, "compare": args.compare, "settings": SETTINGS}
    path = folder / "run.json"
    if path.exists():
        saved = json.loads(path.read_text())
        differ = [k for k in fixed if saved.get(k) != fixed[k]]
        if differ:
            raise SystemExit(f"{path} was started with other settings ({', '.join(differ)}); use those or another --run")
    folder.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fixed, indent=1) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", default="engine-loop", help="folder under runs/")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--games", type=int, default=10000, help="self-play games a round")
    parser.add_argument("--timing", type=int, default=0, metavar="GAMES",
                        help="only this many self-play games of round 1, then their fits, and print core-seconds a game")
    parser.add_argument("--sample", type=float, default=0.05, help="chance of keeping the positions at each turn")
    parser.add_argument("--compare", type=int, default=1500, help="pairings head to head and crowd battles a round (PvPoke: half)")
    parser.add_argument("--confirm", action="store_true", help="play the best round against E_0 again on a fresh seed")
    parser.add_argument("--confirm-pairings", type=int, default=2000)
    parser.add_argument("--chunk", type=int, default=10, help="games saved together")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--field", choices=("standard", "pvpoke", "mixed"), default="mixed")
    parser.add_argument("--seed", type=int, default=3901, help="self-play; measuring uses seed + 1, confirming seed + 2")
    args = parser.parse_args()
    low_priority()
    folder = ROOT / "runs" / args.run
    log_path = folder / "rounds.json"
    rounds = json.loads(log_path.read_text()) if log_path.exists() else []
    if args.confirm:
        if not rounds:
            raise SystemExit(f"no rounds in {log_path}")
        best = max(rounds, key=lambda e: e["versus"]["head_to_head"][0])
        label = (f"round {best['round']}, the best head to head against E_0" if best["versus"]["head_to_head"][0] > 0.5
                 else f"round {best['round']}: no round was above 50% head to head; the best one anyway")
        print(f"confirming {label}", flush=True)
        out = versus(f"{args.run}-confirm", best["versus"]["candidate"], args.confirm_pairings, args.seed + 2, args)
        (folder / "confirm.json").write_text(json.dumps({"round": best["round"], "label": label, **out}, indent=1) + "\n")
        return
    check_run(folder, args)
    if args.timing:
        args.games = args.timing
    q_path, eval_path = START_Q, START_EVAL
    if rounds:
        q_path, eval_path = folder / f"round_{rounds[-1]['round']}" / "q.npz", folder / f"round_{rounds[-1]['round']}" / "eval.npz"
    for r in range(len(rounds) + 1, (1 if args.timing else args.rounds) + 1):
        t0 = time.time()
        here = folder / f"round_{r}"
        data = selfplay(here, q_path, eval_path, args.seed * 100 + r, args)
        if (here / "fit.json").exists():
            report = json.loads((here / "fit.json").read_text())
        else:
            report = fit(here, data, q_path, eval_path, args.seed + r)
        if args.timing:
            timing(data, args)
            return
        candidate = f"samples={WEBSITE['samples']},q={rel(here / 'q.npz')},eval={rel(here / 'eval.npz')}"
        out = versus(f"{args.run}-versus", candidate, args.compare, args.seed + 1, args)
        h, hm = out["head_to_head"]
        print(f"round {r}: head to head against E_0 {100 * h:.1f}% ± {100 * hm:.1f}; " + "; ".join(
            f"{kind} {100 * out[kind]['change'][0]:+.1f} ± {100 * out[kind]['change'][1]:.1f} points" for kind in ("crowd", "pvpoke")),
            flush=True)
        rounds.append({"round": r, "networks_from": [rel(q_path), rel(eval_path)], "self_play_seed": args.seed * 100 + r,
                       "core_seconds_a_game": float(data["game_cpu"].mean()), "fit": report, "versus": out,
                       "minutes": round((time.time() - t0) / 60, 1)})
        log_path.write_text(json.dumps(rounds, indent=1) + "\n")
        q_path, eval_path = here / "q.npz", here / "eval.npz"
    print(f"\nrounds: {rel(log_path)}; next: --confirm")


if __name__ == "__main__":
    main()
