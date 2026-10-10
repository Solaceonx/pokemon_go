#!/usr/bin/env python3
"""Train the Learner by self-play, unattended, then test it.

    python3 scripts/selfplay.py --team melmetal jellicent altaria --minutes 60
        train a strategy for that team (first one named leads), then test it

    python3 scripts/selfplay.py --minutes 30
        train one general strategy on random teams

Run the same command again and it resumes. Each run keeps its files in
runs/<name>/ (the team's names, or "default").

Stage 1, once: the Learner's networks are fitted to imitate the Planner.
Stage 2: the Learner plays batches of battles against the Planner, a crowd of
variations on the Planner, and its own best version, and its networks are nudged towards the choices
made in battles that went better than expected. Every few rounds it is tested on
a fixed set of battles and the best version so far is kept. Training stops when
the time is up, or when --patience tests in a row bring no new best.
Stage 3: the best version is tested on fresh battles.

It runs at low priority on one core and saves after every round, so it can be
stopped with Ctrl-C at any time.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sys
import time
from pathlib import Path

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")  # the networks are tiny; extra threads only heat the machine

import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pogo.agents import Planner, varied  # noqa: E402
from pogo import arena  # noqa: E402
from pogo.arena import compare  # noqa: E402
from pogo.battle import DRAW, Battle  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.learner import HEADS, Learner, Policy, batches  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TEST_SEED = 12345  # the same test battles every time, so scores can be compared between rounds


def imitate(policy: Policy, pool, team, battles: int, seed: int) -> None:
    """Fit the networks to the Planner's own choices and print how often each one now agrees with it."""
    rng = random.Random(seed)
    log: list = []
    for _ in range(battles):
        mine = team or rng.sample(pool, 3)
        Battle(mine, rng.sample(pool, 3), Learner(log=log), Learner(log=log), seed=rng.getrandbits(32)).run()
    order = np.random.default_rng(seed)
    for head, (x, mask, action, weight) in batches(log).items():
        for _ in range(40):
            rows = order.permutation(len(x))
            for start in range(0, len(x), 256):
                pick = rows[start:start + 256]
                policy.step(head, x[pick], mask[pick], action[pick], weight[pick], rate=2e-3)
        p, _ = policy.probabilities(head, x, mask)
        print(f"  {head:8s} {len(x):7d} decisions, agrees with the Planner on {100 * (p.argmax(axis=1) == action).mean():.0f}%")


def play_round(policy: Policy, opponents: dict, pool, team, battles: int, rng: random.Random):
    """A batch of battles for the Learner. Returns its decisions weighted by how the battle went, and its scores."""
    games = []
    names = list(opponents)
    for _ in range(battles):
        name = rng.choice(names)
        log: list = []
        me, them = Learner(policy=policy, log=log), opponents[name]()
        mine, theirs = team or rng.sample(pool, 3), rng.sample(pool, 3)
        first = rng.random() < 0.5
        sides = (mine, theirs, me, them) if first else (theirs, mine, them, me)
        winner = Battle(*sides, seed=rng.getrandbits(32)).run()
        result = 0.0 if winner == DRAW else 1.0 if (winner == 0) == first else -1.0
        games.append((name, result, log))
    expected = {name: float(np.mean([r for n, r, _ in games if n == name] or [0.0])) for name in names}
    rows = [(*decision, result - expected[name]) for name, result, log in games for decision in log]
    return rows, {name: 0.5 + 0.5 * expected[name] for name in names}


def field_results(team, pool, make_pilot, battles: int, seed: int) -> np.ndarray:
    """This team and pilot against random threes, each piloted by a different variation of our own player."""
    return np.array(arena.field_results(team, pool, make_pilot, lambda rng: varied(rng, pool), battles, seed))


def spread(values: np.ndarray) -> float:
    return 1.96 * float(values.std(ddof=1)) / np.sqrt(len(values))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--team", nargs=3, metavar="SPECIES", help="train for this team; the first one named leads")
    parser.add_argument("--minutes", type=float, default=20, help="stop training after this long")
    parser.add_argument("--patience", type=int, default=12, help="stop after this many tests in a row with no new best (0 = never)")
    parser.add_argument("--run", help="name of the run folder under runs/ (default: the team's names, or 'default')")
    parser.add_argument("--battles", type=int, default=400, help="battles per round")
    parser.add_argument("--test-every", type=int, default=5, help="rounds between tests")
    parser.add_argument("--test-battles", type=int, default=800, help="battles per test")
    parser.add_argument("--final-battles", type=int, default=3000, help="fresh battles for the final test")
    parser.add_argument("--rate", type=float, default=3e-4, help="learning rate")
    parser.add_argument("--explore", type=float, default=0.01, help="reward for keeping options open (entropy bonus)")
    parser.add_argument("--imitation-battles", type=int, default=3000)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    os.nice(10)
    start = time.time()
    gd = GameData()
    pool = gd.meta(50)
    team = None
    if args.team:
        unknown = [sid for sid in args.team if sid not in gd.species]
        if unknown:
            sys.exit(f"unknown species id: {', '.join(unknown)}")
        team = [gd.default(sid) for sid in args.team]
    folder = ROOT / "runs" / (args.run or ("-".join(args.team) if team else "default"))
    folder.mkdir(parents=True, exist_ok=True)
    state_file, log_file = folder / "state.json", folder / "log.csv"

    def test(policy: Policy) -> tuple[float, float]:
        if team:
            points = field_results(team, pool, lambda: Learner(policy=policy, greedy=True), args.test_battles, TEST_SEED)
            return float(points.mean()), spread(points)
        result = compare(lambda: Learner(policy=policy, greedy=True), Planner, pool, pairings=args.test_battles // 2, seed=TEST_SEED)
        return result.score, result.margin

    if team:
        print("team: " + ", ".join(f"{b.name} ({b.fast.name} / {' / '.join(m.name for m in b.charged)})" for b in team))
        print("scores are this team's win share against random threes from the top 50, each piloted by a variation of our own player")
    else:
        print("scores are the Learner's win share against the Planner, both on random teams")

    if state_file.exists():
        state = json.loads(state_file.read_text())
        policy, best = Policy.load(folder / "latest.npz"), Policy.load(folder / "best.npz")
        print(f"resuming {folder.name}: round {state['round']}, {state['battles']} battles so far, best test score {100 * state['best']:.1f}%")
    else:
        state = {"round": 0, "battles": 0, "stale": 0}
        if team:
            points = field_results(team, pool, Planner, args.test_battles, TEST_SEED)
            state["planner"] = float(points.mean())
            print(f"the Planner piloting this team scores {100 * state['planner']:.1f}% ± {100 * spread(points):.1f} on the test battles")
        print(f"stage 1: imitating the Planner over {args.imitation_battles} battles")
        policy = Policy(seed=args.seed)
        imitate(policy, pool, team, args.imitation_battles, args.seed)
        state["best"], margin = test(policy)
        print(f"  after imitation the Learner scores {100 * state['best']:.1f}% ± {100 * margin:.1f}")
        best = policy.copy()
        policy.save(folder / "latest.npz")
        best.save(folder / "best.npz")
        with log_file.open("w", newline="") as f:
            csv.writer(f).writerow(["round", "battles", "vs_planner", "vs_varied", "vs_self", "test", "test_margin",
                                    *[f"entropy_{h}" for h in HEADS]])
            csv.writer(f).writerow([0, 0, "", "", "", f"{state['best']:.4f}", f"{margin:.4f}", *[""] * len(HEADS)])
        state_file.write_text(json.dumps(state))

    print(f"stage 2: self-play for up to {args.minutes:g} minutes ({args.battles} battles a round)")
    rng = random.Random(args.seed + 1000 * state["round"] + 1)
    why = "time is up"
    try:
        while time.time() - start < 60 * args.minutes:
            opponents = {"planner": Planner, "varied": lambda: varied(rng, pool), "self": lambda: Learner(policy=best, greedy=True)}
            rows, scores = play_round(policy, opponents, pool, team, args.battles, rng)
            entropy = {head: "" for head in HEADS}
            for head, (x, mask, action, weight) in batches(rows).items():
                entropy[head] = f"{policy.step(head, x, mask, action, weight, args.rate, args.explore):.3f}"
            state["round"] += 1
            state["battles"] += args.battles
            tested = ("", "")
            if state["round"] % args.test_every == 0:
                score, margin = test(policy)
                tested = (f"{score:.4f}", f"{margin:.4f}")
                note = ""
                if score > state["best"]:
                    state["best"], state["stale"], best = score, 0, policy.copy()
                    best.save(folder / "best.npz")
                    note = "  <- new best"
                else:
                    state["stale"] = state.get("stale", 0) + 1
                    if score < state["best"] - 0.05:
                        policy = best.copy()  # it has drifted somewhere worse; go back to the best version
                        note = "  (reset to best)"
                print(f"  round {state['round']:4d}  {state['battles']:7d} battles  in training: "
                      + " ".join(f"{k} {100 * v:.0f}%" for k, v in scores.items())
                      + f"  | test {100 * score:.1f}% ± {100 * margin:.1f}{note}", flush=True)
            policy.save(folder / "latest.npz")
            state_file.write_text(json.dumps(state))
            with log_file.open("a", newline="") as f:
                csv.writer(f).writerow([state["round"], state["battles"], *[f"{scores[k]:.3f}" for k in ("planner", "varied", "self")],
                                        *tested, *[entropy[h] for h in HEADS]])
            if args.patience and state.get("stale", 0) >= args.patience:
                why = f"no new best in {args.patience} tests"
                break
    except KeyboardInterrupt:
        why = "stopped by hand"
    print(f"training ended: {why}. {state['battles']} battles in total.")

    print(f"\nstage 3: testing the best version on {args.final_battles} fresh battles")
    fresh = args.seed + 777
    if team:
        learned = field_results(team, pool, lambda: Learner(policy=best, greedy=True), args.final_battles, fresh)
        planned = field_results(team, pool, Planner, args.final_battles, fresh)
        gain = learned - planned
        print(f"  trained strategy   {100 * learned.mean():.1f}% ± {100 * spread(learned):.1f}")
        print(f"  Planner, same team {100 * planned.mean():.1f}% ± {100 * spread(planned):.1f}")
        print(f"  difference         {100 * gain.mean():+.1f} ± {100 * spread(gain):.1f} points (same battles for both)")
        print("  trained strategy by lead:")
        for k in range(3):
            order = [team[k]] + [b for j, b in enumerate(team) if j != k]
            points = field_results(order, pool, lambda: Learner(policy=best, greedy=True), args.final_battles // 3, fresh + 1 + k)
            print(f"    {order[0].name:12s} {100 * points.mean():.1f}% ± {100 * spread(points):.1f}")
    else:
        print("  " + str(compare(lambda: Learner(policy=best, greedy=True), Planner, pool, pairings=args.final_battles // 2, seed=fresh)))
    print(f"files: runs/{folder.name}/best.npz (best policy), latest.npz, log.csv")


if __name__ == "__main__":
    main()
