#!/usr/bin/env python3
"""Self-play improvement loop for the engine's evaluation (docs/tasks.md, task 31; the AlphaZero idea).

    python3 scripts/selfplay_eval.py --run selfplay-1 [--rounds 5] [--games 20000] [--compare 1000] [--workers 64]

Each round:
1. The current engine (confirmed settings, habits shifted a little on each side) plays itself on teams drawn half from
   the good-team list and half at random. At random moments both players' positions are kept, each with how that battle
   ended for that player (pogo.arena.decisive), as scripts/train_eval.py does for the trained bot's battles.
2. A new evaluation is fitted on every round's positions so far (a tenth of the games held out whole, to report how
   well each evaluation predicts them).
3. The engine with the new evaluation plays the engine with the current one head to head, and both play the crowd
   (scripts/engine_versus.py), on fresh battles.
4. The new evaluation is adopted when it wins head to head beyond the margin and is not worse against the crowd beyond
   the margin; otherwise the round is recorded and the loop stops.

Everything is saved in runs/selfplay/<run>/ (positions per round, each evaluation, rounds.json) and the run resumes.
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
from pogo.agents import varied_settings  # noqa: E402
from pogo.arena import decisive, low_priority, mean_and_margin  # noqa: E402
from pogo.battle import Battle  # noqa: E402
from pogo.engine import Engine  # noqa: E402
from pogo.evaluation import Evaluator  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.learner import QNet  # noqa: E402
from pogo.teamlist import drawer  # noqa: E402
from pogo.value import ValueModel, log_loss  # noqa: E402

START = ROOT / "runs" / "eval" / "eval.npz"


def games(task) -> dict:
    """Engine against engine; positions from both sides with each battle's end for that side."""
    eval_path, seed, count, sample = task
    low_priority()
    gd = GameData()
    pool = gd.meta(50)
    draw = drawer(gd, pool)
    net = QNet.load(str(ROOT / "runs" / "general-decide" / "q.npz"))
    model = Evaluator.load(eval_path).model
    rng = random.Random(seed)
    xs, ys, game_ids = [], [], []
    for n in range(count):
        # A fresh evaluation cache for each player and for the recorder in every game: the cache is keyed by team slot
        # and opposing species, not by our team, so sharing it lets one game or player change another's features.
        features = Evaluator()
        players = [Engine(Evaluator(model), pool, rollout="bot", samples=4, edge=0.03, q=net, margin=0.02,
                          **varied_settings(rng, pool))
                   for _ in range(2)]
        battle = Battle(draw(rng), draw(rng), *players, seed=rng.getrandbits(32))
        seen = []
        while battle.winner is None:
            if rng.random() < sample:
                for side in (0, 1):
                    view = battle.views[side]
                    if view.me.mon.hp > 0 and view.foe.hp > 0:
                        seen.append((side, features.features(view)))
            battle.step()
        for side, x in seen:
            xs.append(x)
            ys.append(decisive(battle, side))
            game_ids.append(seed * 100_000 + n)
    return {"x": np.array(xs, dtype=np.float32), "y": np.array(ys), "game": np.array(game_ids)}


def main() -> None:
    import engine_versus
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", required=True)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--games", type=int, default=20000, help="engine games per round")
    parser.add_argument("--sample", type=float, default=0.05, help="chance of keeping the positions at each turn")
    parser.add_argument("--compare", type=int, default=1000, help="pairings head to head, and crowd battles, per round")
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 4)
    parser.add_argument("--seed", type=int, default=4001)
    args = parser.parse_args()
    folder = ROOT / "runs" / "selfplay" / args.run
    folder.mkdir(parents=True, exist_ok=True)
    log_path = folder / "rounds.json"
    rounds = json.loads(log_path.read_text()) if log_path.exists() else []
    current = Path(rounds[-1]["adopted_eval"]) if rounds else START
    for r in range(len(rounds) + 1, args.rounds + 1):
        t0 = time.time()
        data_path = folder / f"positions_{r}.npz"
        if not data_path.exists():
            per = 20
            tasks = [(str(current), args.seed * 1000 + r * 100_000 + k, min(per, args.games - k * per), args.sample)
                     for k in range(-(-args.games // per))]
            parts = []
            with multiprocessing.get_context("spawn").Pool(args.workers) as pool:
                for done, part in enumerate(pool.imap_unordered(games, tasks), start=1):
                    parts.append(part)
                    if done % max(1, len(tasks) // 10) == 0:
                        print(f"  round {r}: {done * per} of {args.games} games, {(time.time() - t0) / 60:.0f} min", flush=True)
            np.savez_compressed(data_path, **{k: np.concatenate([p[k] for p in parts]) for k in ("x", "y", "game")})
        data = [np.load(folder / f"positions_{k}.npz") for k in range(1, r + 1)]
        x = np.concatenate([d["x"] for d in data]).astype(np.float64)
        y = np.concatenate([d["y"] for d in data])
        game = np.concatenate([d["game"] for d in data])
        held = (game % 10) == 0
        model = ValueModel.train(x[~held], y[~held], hidden=(64, 32), epochs=30, seed=args.seed + r)
        new_path = folder / f"eval_{r}.npz"
        model.save(new_path)
        old = Evaluator.load(current)
        loss_new = log_loss(model.predict(x[held]), y[held])
        loss_old = log_loss(old.many(x[held]), y[held])
        print(f"round {r}: {len(y)} positions; held-out log loss {loss_new:.4f} new against {loss_old:.4f} current", flush=True)
        tag = f"selfplay-{args.run}-round-{r}"
        sys.argv = ["engine_versus", "--tag", tag, "--baseline", f"eval={current}", "--candidates", f"eval={new_path}",
                    "--pairings", str(args.compare), "--crowd", str(args.compare), "--pvpoke", "0",
                    "--workers", str(args.workers), "--seed", str(args.seed + 17 * r)]
        engine_versus.main()
        saved = json.loads((ROOT / "runs" / "engine_versus" / f"{tag}.json").read_text())["results"]
        h2h = list(saved["h2h"][f"eval={new_path}"].values())
        crowd_new = [saved["crowd"][f"eval={new_path}"][k] for k in sorted(saved["crowd"][f"eval={new_path}"], key=int)]
        crowd_old = [saved["crowd"][f"eval={current}"][k] for k in sorted(saved["crowd"][f"eval={current}"], key=int)]
        h, hm = mean_and_margin(h2h)
        d, dm = mean_and_margin([a - b for a, b in zip(crowd_new, crowd_old)])
        adopt = h - hm > 0.5 and d + dm > 0
        rounds.append({"round": r, "positions": int(len(y)), "loss_new": loss_new, "loss_current": loss_old,
                       "head_to_head": [h, hm], "crowd_difference": [d, dm], "adopted": adopt,
                       "adopted_eval": str(new_path if adopt else current), "minutes": round((time.time() - t0) / 60, 1)})
        log_path.write_text(json.dumps(rounds, indent=1) + "\n")
        print(f"round {r}: head to head {100 * h:.1f}% ± {100 * hm:.1f}, crowd {100 * d:+.1f} ± {100 * dm:.1f}: "
              f"{'adopted' if adopt else 'not adopted; stopping'}", flush=True)
        if not adopt:
            break
        current = new_path
    print(f"\nrounds: {log_path.relative_to(ROOT)}; best evaluation: {current}")


if __name__ == "__main__":
    main()
