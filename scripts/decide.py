#!/usr/bin/env python3
"""Learn the bot's judgement calls one decision at a time, unattended.

    python3 scripts/decide.py --minutes 60                                   one model for any team
    python3 scripts/decide.py --team melmetal jellicent altaria --minutes 30   a model for one team

At decisions met in ordinary play, the battle is frozen and played out once for
each option, dice and all else equal:

    shield    shield / do not shield
    throw     first charged move / second / hold for one, four or ten more fast moves
    swap      at a new matchup with the switch ready: stay / bring in either of the others
    replace   after a faint: which of the others to send in

A network is then trained to predict, from what the player can see, the chance
of winning after each option. The Learner follows the Planner except where the
network rates another option clearly higher. Each round uses the previous
round's Learner to generate the positions and to play them out. At the end the
result is tested on fresh battles against the Planner piloting the same teams.

One core, low priority. Files go to runs/general-decide/ or runs/<team>-decide/.
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import time
from pathlib import Path

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pogo.agents import Planner, varied, varied_settings  # noqa: E402
from pogo.arena import field_results, mean_and_margin  # noqa: E402
from pogo.battle import DRAW, Battle  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.learner import N_FEATURES, Q_HEADS, Learner, QNet  # noqa: E402
from pogo.pvpoke_ai import PvpokeAI  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NAN = float("nan")


class PvpokeOpponent(PvpokeAI):
    """PvPoke's AI as a training opponent. Play-outs need clone(); PvpokeAI keys its matchup
    cache on the battle's Pokémon objects, so a copy rebuilds it on first use anyway and a
    fresh instance behaves the same as a deep copy."""

    def clone(self):
        return PvpokeOpponent()


def play_out(snapshot, head: str, option: int) -> float:
    """Continue the frozen battle with one choice forced. 1 if we go on to win, 0 if we lose."""
    battle, me, them = snapshot
    pilot = me.clone()
    pilot.force(head, option)
    winner = battle.clone(pilot, them.clone()).run()
    return 1.0 if winner == 0 else 0.5 if winner == DRAW else 0.0


def options_for(head: str, mask: tuple) -> list[int]:
    if head == "throw":
        return [0, 3, 4] + [k for k in (1, 2) if mask[k]]
    return [k for k in range(Q_HEADS[head]) if mask[k]]


def collect(team, pool, q, margin: float, crowd, seconds: float, seed: int, draw, throw_share: float = 0.1,
            pvpoke_share: float = 0.0):
    """Play battles; at each decision (a sample of the throw decisions), play out every option.

    With pvpoke_share, that share of battles is one against one versus PvPoke's AI. The port is
    faithful only inside a matchup and never switches, so these battles are 1v1 and only give
    shield and throw decisions; there is no switching for the learner to exploit.
    """
    rng = random.Random(seed)
    data = {head: ([], []) for head in Q_HEADS}
    battles, pvpoke_battles, stop = 0, 0, time.time() + seconds
    while time.time() < stop:
        log: list = []
        if pvpoke_share and rng.random() < pvpoke_share:
            me, them = Learner(q=q, margin=margin, log=log, seed=rng.getrandbits(32)), PvpokeOpponent()
            battle = Battle(rng.sample(pool, 1), rng.sample(pool, 1), me, them, seed=rng.getrandbits(32))
            pvpoke_battles += 1
        else:
            me, them = Learner(q=q, margin=margin, log=log, seed=rng.getrandbits(32)), crowd(rng)
            battle = Battle(team or draw(rng), draw(rng), me, them, seed=rng.getrandbits(32))
        while battle.winner is None:
            # No action, hit, shield or replacement can occur before either fast
            # move finishes, so there is no decision to snapshot on this turn.
            if battle.sides[0].busy > 1 and battle.sides[1].busy > 1:
                battle.step()
                continue
            snapshot = (battle.clone(None, None), me.clone(), them.clone())
            seen = len(log)
            battle.step()
            for head, x, mask, _ in log[seen:]:
                if head == "throw" and rng.random() >= throw_share:
                    continue
                y = [NAN] * Q_HEADS[head]
                for k in options_for(head, mask):
                    y[k] = play_out(snapshot, head, k)
                data[head][0].append(x)
                data[head][1].append(y)
        battles += 1
    return {head: (np.array(x).reshape(-1, N_FEATURES), np.array(y).reshape(-1, Q_HEADS[head]))
            for head, (x, y) in data.items()}, battles, pvpoke_battles


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--team", nargs=3, metavar="SPECIES", help="train for this team only; the first one named leads")
    parser.add_argument("--also-test", nargs=3, metavar="SPECIES", help="after training, also test on this team")
    parser.add_argument("--opponents", nargs="+", metavar="FILE", default=[],
                        help="learned models (q.npz) that half the opponents should play with")
    parser.add_argument("--teams", metavar="FILE", help="draw half of all teams from this list (data/teams.json) instead of at random")
    parser.add_argument("--resume", action="store_true", help="carry on from the model and examples already in the run folder")
    parser.add_argument("--run", help="name of the run folder under runs/")
    parser.add_argument("--minutes", type=float, default=30, help="time spent generating examples, over all rounds")
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--val-battles", type=int, default=1000, help="battles used to choose how readily to overrule the Planner")
    parser.add_argument("--final-battles", type=int, default=3000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--pvpoke-share", type=float, default=0.0,
                        help="share of example battles played 1v1 against PvPoke's AI (shield and throw decisions only)")
    args = parser.parse_args()

    os.nice(10)
    gd = GameData()
    pool = gd.meta(50)
    team = [gd.default(sid) for sid in args.team] if args.team else None
    folder = ROOT / "runs" / (args.run or (("-".join(args.team) if team else "general") + "-decide"))
    folder.mkdir(parents=True, exist_ok=True)
    if args.teams:
        from pogo.teamlist import drawer
        draw = drawer(gd, pool, args.teams)
    else:
        draw = lambda rng: rng.sample(pool, 3)  # noqa: E731
    rivals = [QNet.load(path) for path in args.opponents]
    old_crowd = lambda rng: varied(rng, pool)  # noqa: E731

    def crowd(rng):
        """An opponent: a variation of the Planner, and half the time one playing with our learned decisions."""
        settings = varied_settings(rng, pool)
        if rivals and rng.random() < 0.5:
            return Learner(q=rng.choice(rivals), margin=rng.choice((0.02, 0.05, 0.1)), **settings)
        return Planner(**settings)

    print("team: " + (", ".join(b.name for b in team) if team else "any (random threes from the top 50)"))
    print("teams: " + (f"half from {args.teams}, half random" if args.teams else "random threes"))
    print("opponents: variations of the Planner" + (f", half of them using learned decisions from {len(rivals)} model(s)" if rivals else ""), flush=True)

    def versus_planner(q, margin, battles, seed, on_team, against=None):
        pilots = []
        against = against or crowd

        def pilot():
            pilots.append(Learner(q=q, margin=margin))
            return pilots[-1]

        learned = field_results(on_team, pool, pilot, against, battles, seed, draw)
        planned = field_results(on_team, pool, Planner, against, battles, seed, draw)
        overruled: dict = {}
        for p in pilots:
            for (head, _, _), n in p.departures.items():
                overruled[head] = overruled.get(head, 0) + n / battles
        return learned, planned, overruled

    def show(label, learned, planned, overruled):
        for name, values in (("with learned decisions", learned), ("Planner, same teams", planned)):
            mean, spread = mean_and_margin(values)
            print(f"  {name:24s} {100 * mean:.1f}% ± {100 * spread:.1f}")
        gain, spread = mean_and_margin([a - b for a, b in zip(learned, planned)])
        print(f"  difference               {100 * gain:+.1f} ± {100 * spread:.1f} points (same battles for both); overruled the Planner per battle: "
              + ", ".join(f"{h} {n:.2f}" for h, n in sorted(overruled.items())), flush=True)

    q, margin = None, 0.03
    stored = {head: (np.zeros((0, N_FEATURES)), np.zeros((0, n))) for head, n in Q_HEADS.items()}
    if args.resume and (folder / "q.npz").exists():
        q = QNet.load(folder / "q.npz")
        margin = float((folder / "margin.txt").read_text()) if (folder / "margin.txt").exists() else margin
        if (folder / "examples.npz").exists():  # not kept in git; without it, start collecting afresh from the saved model
            saved = np.load(folder / "examples.npz")
            stored = {head: (saved[f"{head}_x"], saved[f"{head}_y"]) for head in Q_HEADS}
        print(f"resuming with {sum(len(x) for x, _ in stored.values())} examples already collected", flush=True)
        args.seed += 1000 + sum(len(x) for x, _ in stored.values()) % 1000  # so new battles differ from the earlier ones
    for round_no in range(1, args.rounds + 1):
        t0 = time.time()
        fresh, battles, pvpoke_battles = collect(team, pool, q, margin, crowd, 60 * args.minutes / args.rounds,
                                                 args.seed + round_no, draw, pvpoke_share=args.pvpoke_share)
        for head in Q_HEADS:
            stored[head] = (np.vstack([stored[head][0], fresh[head][0]]), np.vstack([stored[head][1], fresh[head][1]]))
        np.savez_compressed(folder / "examples.npz", **{f"{h}_{k}": a for h, xy in stored.items() for k, a in zip("xy", xy)})
        print(f"\nround {round_no}: {battles} battles ({pvpoke_battles} of them 1v1 against PvPoke) in "
              f"{(time.time() - t0) / 60:.1f} min; examples so far: "
              + ", ".join(f"{len(stored[h][0])} {h}" for h in Q_HEADS), flush=True)
        q = QNet(seed=args.seed)
        for head, (x, y) in stored.items():
            if len(x):
                print(f"  {head}: average result by option " + " ".join(f"{100 * r:.1f}%" for r in np.nanmean(y, axis=0)))
                q.fit(head, x, y, seed=args.seed)
        q.save(folder / "q.npz")
        best = None
        for candidate in (0.02, 0.05, 0.1):
            learned, planned, overruled = versus_planner(q, candidate, args.val_battles, args.seed + 50 + round_no, team)
            gain, spread = mean_and_margin([a - b for a, b in zip(learned, planned)])
            print(f"  overrule when ahead by {candidate}: {100 * gain:+.1f} ± {100 * spread:.1f} points against the Planner", flush=True)
            if best is None or gain > best[0]:
                best = (gain, candidate)
        margin = best[1]
    (folder / "margin.txt").write_text(f"{margin}\n")

    print(f"\nfinal test on {args.final_battles} fresh battles, overruling when ahead by {margin}")
    show("final", *versus_planner(q, margin, args.final_battles, args.seed + 999, team))
    if rivals:
        print("\nthe same test against the old crowd (Planner variations only), as a fixed yardstick")
        show("yardstick", *versus_planner(q, margin, args.final_battles, args.seed + 999, team, against=old_crowd))
    if args.also_test:
        other = [gd.default(sid) for sid in args.also_test]
        print(f"\nthe same model piloting {', '.join(b.name for b in other)}, {args.final_battles} fresh battles")
        show("also", *versus_planner(q, margin, args.final_battles, args.seed + 998, other))
    print(f"files: runs/{folder.name}/q.npz, margin.txt, examples.npz")


if __name__ == "__main__":
    main()
