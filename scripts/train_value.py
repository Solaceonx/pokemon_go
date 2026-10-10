#!/usr/bin/env python3
"""Learn what a position is worth from self-play, and save the model to models/value.npz.

    python3 scripts/train_value.py                 generate positions, train, report
    python3 scripts/train_value.py --battles 2000  fewer base battles (faster, noisier)
    python3 scripts/train_value.py --reuse         retrain on the positions already saved

A position here is one side's remaining Pokémon, shields and switch timer at the
moment an opposing Pokémon faints, facing opponents it has not seen. Each one is
labelled by playing it out against fresh random opponents.
"""
from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pogo.agents import Planner, duel, expert, position_features  # noqa: E402
from pogo.battle import DRAW, Battle, Mon  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.value import ValueModel, log_loss  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
POSITIONS = ROOT / "data" / "value_positions.npz"
MODEL = ROOT / "models" / "value.npz"


def collect(pool, battles: int, seed: int, playouts: int = 2):
    """Positions from self-play, each played out against fresh opponents to see who wins."""
    rng = random.Random(seed)
    players = [Planner, lambda: expert(pool)]
    xs, ys = [], []
    for _ in range(battles):
        battle = Battle(rng.sample(pool, 3), rng.sample(pool, 3), rng.choice(players)(), rng.choice(players)(),
                        seed=rng.getrandbits(32))
        while battle.winner is None:
            before = [side.left() for side in battle.sides]
            battle.step()
            for loser in (0, 1):
                me, them = battle.sides[1 - loser], battle.sides[loser]
                if battle.winner is not None or them.left() == before[loser] or me.mon.hp <= 0:
                    continue
                for k in range(playouts):
                    # First playout keeps the real count and shields; later ones vary them for coverage.
                    unseen = them.left() if k == 0 else rng.choice((1, 2))
                    foe_shields = them.shields if k == 0 else rng.choice((0, 1, 2))
                    foes = sorted((Mon(b) for b in rng.sample(pool, unseen)),
                                  key=lambda foe: duel(foe, me.mon, foe_shields, me.shields), reverse=True)
                    mine = [me.mon.copy()] + [m.copy() for j, m in enumerate(me.team) if j != me.active and m.hp > 0]
                    rest = Battle(mine, foes, Planner(), rng.choice(players)(), seed=rng.getrandbits(32),
                                  shields=(me.shields, foe_shields), switch_wait=(me.switch_wait, 0))
                    rest.turn = battle.turn
                    winner = rest.run()
                    xs.append(position_features(me.team, me.active, me.shields, me.switch_wait,
                                                unseen, foe_shields, battle.turn, pool))
                    ys.append(1.0 if winner == 0 else 0.5 if winner == DRAW else 0.0)
    return np.array(xs), np.array(ys)


def tally_guess(x: np.ndarray) -> np.ndarray:
    """The hand-set rule the model replaces: health plus 0.35 per shield, mine minus theirs."""
    mine = x[:, 1] + x[:, 5] + x[:, 9] + 0.35 * 2 * x[:, 12]
    theirs = 2 * x[:, 14] + 0.35 * 2 * x[:, 15]
    return mine - theirs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--battles", type=int, default=6000)
    parser.add_argument("--reuse", action="store_true", help="skip generation and use the saved positions")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    if args.reuse:
        saved = np.load(POSITIONS)
        x, y = saved["x"], saved["y"]
    else:
        pool = GameData().meta(50)
        t0 = time.perf_counter()
        x, y = collect(pool, args.battles, args.seed)
        np.savez_compressed(POSITIONS, x=x, y=y)
        print(f"{len(x)} positions from {args.battles} battles in {time.perf_counter() - t0:.0f}s")

    rng = np.random.default_rng(args.seed)
    order = rng.permutation(len(x))
    cut = len(x) // 10
    test, train = order[:cut], order[cut:]
    t0 = time.perf_counter()
    model = ValueModel.train(x[train], y[train], seed=args.seed)
    model.save(MODEL)
    print(f"trained on {len(train)} positions in {time.perf_counter() - t0:.0f}s; saved {MODEL.relative_to(ROOT)}")

    # How well does each predict the held-out positions?
    p = model.predict(x[test])
    base = np.full(len(test), y[train].mean())
    tally = tally_guess(x[test])
    scale = np.linspace(0.2, 6, 30)
    best = min(scale, key=lambda s: log_loss(1 / (1 + np.exp(-s * tally_guess(x[train]))), y[train]))
    p_tally = 1 / (1 + np.exp(-best * tally))
    decided = y[test] != 0.5
    print(f"\nheld-out positions: {len(test)}; this side wins {100 * y[test].mean():.0f}% of them")
    print(f"{'':28s}{'log loss':>10s}{'picks the winner':>18s}")
    for label, guess in (("always the average", base), ("health-and-shields tally", p_tally), ("trained model", p)):
        right = ((guess > 0.5) == (y[test] > 0.5))[decided].mean()
        print(f"{label:28s}{log_loss(guess, y[test]):10.3f}{100 * right:17.1f}%")


if __name__ == "__main__":
    main()
