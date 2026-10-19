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
    mid_swap  in an ongoing matchup, within two of their fast moves of a charge: stay / either bench

A network is then trained to predict, from what the player can see, the chance
of winning after each option (with --score margin: how decisively each option
goes on to win or lose, from the winner's health and shields left; see
pogo.arena.decisive). The Learner follows the Planner except where the
network rates another option clearly higher. Each round uses the previous
round's Learner to generate the positions and to play them out. At the end the
result is tested on fresh battles against the Planner piloting the same teams.

One core, low priority. Files go to runs/general-decide/ or runs/<team>-decide/.
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

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pogo.agents import Planner, varied, varied_settings  # noqa: E402
from pogo.arena import decisive, field_results, low_priority, mean_and_margin  # noqa: E402
from pogo.battle import DRAW, Battle  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.learner import N_FEATURES, N_FORMS, N_KNOWN, Q_HEADS, Learner, QNet  # noqa: E402
from pogo.pvpoke_ai import PvpokeAI  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NAN = float("nan")


class PvpokeOpponent(PvpokeAI):
    """PvPoke's AI as a training opponent. Play-outs need clone(); PvpokeAI keys its matchup
    cache on the battle's Pokémon objects, so a copy rebuilds it on first use anyway and a
    fresh instance behaves the same as a deep copy."""

    def clone(self):
        return PvpokeOpponent()


_EVALUATOR = {}


def play_out(snapshot, head: str, option: int, score: str = "result", horizon: int = 0, side: int = 0,
             reseed: int | None = None) -> float:
    """Continue the frozen battle with one choice forced. 1 if we go on to win, 0 if we lose; with score
    "margin", how decisively (pogo.arena.decisive: any win above any loss, and by how much). With a horizon,
    stop after that many turns and let the engine's evaluation (runs/eval/eval.npz) judge the position reached.
    With side 1 the choice is the opponent's, and the result is scored for them. With reseed, the battle's and both
    players' dice are set afresh from it (the same for every option of a decision), for another play-out."""
    battle, me, them = snapshot
    pilot = (me if side == 0 else them).clone()
    pilot.force(head, option)
    played = battle.clone(pilot, them.clone()) if side == 0 else battle.clone(me.clone(), pilot)
    if reseed is not None:
        played.rng.seed(reseed)
        for j, agent in enumerate(played.agents):
            if hasattr(agent, "rng"):
                agent.rng.seed(reseed * 3 + j + 1)
    if horizon:
        for _ in range(horizon):
            if played.winner is not None:
                break
            played.step()
        if played.winner is None:
            if "eval" not in _EVALUATOR:
                from pogo.evaluation import Evaluator
                _EVALUATOR["eval"] = Evaluator.load(ROOT / "runs" / "eval" / "eval.npz")
            return _EVALUATOR["eval"](played.views[side])
        winner = played.winner
    else:
        winner = played.run()
    if score == "margin":
        return decisive(played, side)
    return 1.0 if winner == side else 0.5 if winner == DRAW else 0.0


def options_for(head: str, mask: tuple) -> list[int]:
    if head == "throw":
        return [0, 3, 4] + [k for k in (1, 2) if mask[k]]
    return [k for k in range(Q_HEADS[head]) if mask[k]]


def collect(team, pool, q, margin: float, crowd, seconds: float, seed: int, draw, throw_share: float = 0.1,
            pvpoke_share: float = 0.0, mid_swap: bool = True, score: str = "result", horizon: int = 0,
            wide: bool = False, both_sides: float = 0.0, forms: bool = False, playouts: int = 1):
    """Play battles; at each decision (a sample of the throw decisions), play out every option.

    With pvpoke_share, that share of battles is one against one versus PvPoke's AI. The port is
    faithful only inside a matchup and never switches, so these battles are 1v1 and only give
    shield and throw decisions; there is no switching for the learner to exploit.

    With both_sides, that share of battles is the learner against itself, and both players' decisions are
    played out and kept, each scored from its own side.

    With playouts above 1, each option is played out that many times (the first as always, the others with fresh
    dice shared by all options of the decision) and the results averaged: steadier targets, fewer examples.
    """
    rng = random.Random(seed)
    data = {head: ([], []) for head in Q_HEADS}
    battles, pvpoke_battles, stop = 0, 0, time.time() + seconds
    while time.time() < stop:
        log: list = []
        their_log = None
        if pvpoke_share and rng.random() < pvpoke_share:
            me, them = Learner(q=q, margin=margin, log=log, mid_swap=mid_swap, wide=wide, forms=forms, seed=rng.getrandbits(32)), PvpokeOpponent()
            battle = Battle(rng.sample(pool, 1), rng.sample(pool, 1), me, them, seed=rng.getrandbits(32))
            pvpoke_battles += 1
        elif both_sides and rng.random() < both_sides:
            their_log = []
            me = Learner(q=q, margin=margin, log=log, mid_swap=mid_swap, wide=wide, forms=forms, seed=rng.getrandbits(32))
            them = Learner(q=q, margin=margin, log=their_log, mid_swap=mid_swap, wide=wide, forms=forms, seed=rng.getrandbits(32))
            battle = Battle(team or draw(rng), draw(rng), me, them, seed=rng.getrandbits(32))
        else:
            me, them = Learner(q=q, margin=margin, log=log, mid_swap=mid_swap, wide=wide, forms=forms, seed=rng.getrandbits(32)), crowd(rng)
            battle = Battle(team or draw(rng), draw(rng), me, them, seed=rng.getrandbits(32))
        logs = [log] if their_log is None else [log, their_log]  # whose decisions this battle teaches
        while battle.winner is None:
            snapshot = (battle.clone(None, None), me.clone(), them.clone())
            seen = [len(lg) for lg in logs]
            battle.step()
            for side, lg in enumerate(logs):
                for head, x, mask, _ in lg[seen[side]:]:
                    if head == "throw" and rng.random() >= throw_share:
                        continue
                    y = [NAN] * Q_HEADS[head]
                    dice = [None] + [rng.getrandbits(31) for _ in range(playouts - 1)]
                    for k in options_for(head, mask):
                        y[k] = sum(play_out(snapshot, head, k, score, horizon, side, d) for d in dice) / len(dice)
                    data[head][0].append(x)
                    data[head][1].append(y)
        battles += 1
    inputs = N_FEATURES + (N_KNOWN if wide else 0) + (N_FORMS if forms else 0)
    return {head: (np.array(x).reshape(-1, inputs), np.array(y).reshape(-1, Q_HEADS[head]))
            for head, (x, y) in data.items()}, battles, pvpoke_battles


def sample_examples(data, count: int, seed: int):
    """Keep exactly count decision examples, sampled uniformly across all heads.

    Use the same count each round in ablations: equal wall time alone gives different
    amounts of training data when an extra decision needs more play-outs.
    """
    total = sum(len(x) for x, _ in data.values())
    if total < count:
        raise ValueError(f"collected {total} examples, fewer than the requested {count}; increase --minutes")
    selected = np.sort(np.random.default_rng(seed).choice(total, count, replace=False))
    sampled, offset = {}, 0
    for head, (x, y) in data.items():
        rows = selected[(selected >= offset) & (selected < offset + len(x))] - offset
        sampled[head] = x[rows], y[rows]
        offset += len(x)
    return sampled


def world(config: dict):
    """The pool, our team, the source of teams and the source of opponents, from plain settings.

    Kept separate so that worker processes can rebuild the same world for themselves.
    """
    gd = GameData()
    pool = gd.meta(50)
    team = [gd.default(sid) for sid in config["team"]] if config["team"] else None
    if config.get("field") == "mixed":  # teams as people bring them (pogo.teamshape.mixed_field), form-changers included
        from pogo.teamshape import mixed_field
        pool, draw = mixed_field(gd)
    elif config["teams"]:
        from pogo.teamlist import drawer
        draw = drawer(gd, pool, config["teams"])
    else:
        draw = lambda rng: rng.sample(pool, 3)  # noqa: E731
    rivals = [QNet.load(path) for path in config["opponents"]]
    target = QNet.load(config["exploit"]) if config["exploit"] else None

    def crowd(rng):
        """An opponent: a variation of the Planner, and half the time one playing with our learned decisions."""
        if target is not None:
            return Learner(q=target, margin=0.02, seed=rng.getrandbits(32))  # always the bot being exploited
        settings = varied_settings(rng, pool)
        if rivals and rng.random() < 0.5:
            return Learner(q=rng.choice(rivals), margin=rng.choice((0.02, 0.05, 0.1)), **settings)
        return Planner(**settings)

    return gd, pool, team, draw, crowd


def collect_job(job):
    """One worker's share of a round of collecting."""
    config, q_params, margin, seconds, seed = job
    low_priority()
    _, pool, team, draw, crowd = world(config)
    return collect(team, pool, QNet(q_params) if q_params else None, margin, crowd, seconds, seed, draw,
                   pvpoke_share=config.get("pvpoke_share", 0.0), mid_swap=config["mid_swap"],
                   score=config.get("score", "result"), horizon=config.get("horizon", 0), wide=config.get("wide", False),
                   both_sides=config.get("both_sides", 0.0), forms=config.get("forms", False),
                   playouts=config.get("playouts", 1))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--team", nargs=3, metavar="SPECIES", help="train for this team only; the first one named leads")
    parser.add_argument("--also-test", nargs=3, metavar="SPECIES", help="after training, also test on this team")
    parser.add_argument("--opponents", nargs="+", metavar="FILE", default=[],
                        help="learned models (q.npz) that half the opponents should play with")
    parser.add_argument("--exploit", metavar="FILE",
                        help="train an exploiter: every opponent is the bot with this learned model (q.npz), margin 0.02")
    parser.add_argument("--teams", metavar="FILE", help="draw half of all teams from this list (data/teams.json) instead of at random")
    parser.add_argument("--resume", action="store_true", help="carry on from the model and examples already in the run folder")
    parser.add_argument("--run", help="name of the run folder under runs/")
    parser.add_argument("--minutes", type=float, default=30, help="time spent generating examples, over all rounds")
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--no-mid-swap", action="store_true", help="train the four original heads only (controlled ablation)")
    parser.add_argument("--examples-per-round", type=int,
                        help="fit on exactly this many fresh decision examples per round, sampled after collection; fail if too few")
    parser.add_argument("--workers", type=int, default=1,
                        help="processes generating examples at once; each uses one core, so 4 gives four times the examples in the same time")
    parser.add_argument("--val-battles", type=int, default=1000, help="battles used to choose how readily to overrule the Planner")
    parser.add_argument("--final-battles", type=int, default=3000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--score", choices=("result", "margin"), default="result",
                        help="what a play-out is worth: the result (win 1, draw 0.5, loss 0), or margin: how decisively it was won or lost")
    parser.add_argument("--horizon", type=int, default=0,
                        help="play each option only this many turns ahead and judge the rest with the engine's evaluation (runs/eval/eval.npz); 0 plays to the end")
    parser.add_argument("--pvpoke-share", type=float, default=0.0,
                        help="share of example battles played 1v1 against PvPoke's AI (shield and throw decisions only)")
    parser.add_argument("--wide", action="store_true",
                        help="the networks also see their Pokémon seen off the field and our one-on-ones against them (pogo.learner.known_foes)")
    parser.add_argument("--hidden", type=int, default=48, help="hidden units in each network")
    parser.add_argument("--both-sides", type=float, default=0.0, metavar="SHARE",
                        help="share of example battles played by the learner against itself, keeping both players' decisions")
    parser.add_argument("--forms", action="store_true",
                        help="the networks also see the form-changing state of both Pokémon in play (pogo.learner.form_state)")
    parser.add_argument("--playouts", type=int, default=1, help="play-outs per option, averaged")
    parser.add_argument("--field", choices=("usual", "mixed"), default="usual",
                        help="teams: the usual draw (--teams or random threes), or the mixed field (overrides --teams)")
    parser.add_argument("--start", metavar="FILE",
                        help="a model to pilot the first round (widened with zero weights to the new inputs if needed); "
                             "every round still fits a new network on all examples")
    args = parser.parse_args()
    if args.examples_per_round is not None and args.examples_per_round <= 0:
        parser.error("--examples-per-round must be positive")
    if args.minutes <= 0 or args.rounds <= 0 or args.workers <= 0:
        parser.error("--minutes, --rounds and --workers must be positive")

    low_priority()
    config = {"team": args.team, "teams": args.teams, "opponents": args.opponents, "exploit": args.exploit,
              "pvpoke_share": args.pvpoke_share, "mid_swap": not args.no_mid_swap, "score": args.score,
              "horizon": args.horizon, "wide": args.wide, "both_sides": args.both_sides, "forms": args.forms,
              "playouts": args.playouts, "field": args.field}
    gd, pool, team, draw, crowd = world(config)
    folder = ROOT / "runs" / (args.run or (("-".join(args.team) if team else "general") + "-decide"))
    folder.mkdir(parents=True, exist_ok=True)
    rivals, target = args.opponents, args.exploit
    old_crowd = lambda rng: varied(rng, pool)  # noqa: E731

    print("team: " + (", ".join(b.name for b in team) if team else "any (random threes from the top 50)"))
    print("teams: " + (f"half from {args.teams}, half random" if args.teams else "random threes"))
    if target:
        print(f"opponents: always the bot using {args.exploit} (this run trains an exploiter)")
    else:
        print("opponents: variations of the Planner" + (f", half of them using learned decisions from {len(rivals)} model(s)" if rivals else ""))
    print(f"field: {args.field}; form inputs: {args.forms}; play-outs per option: {args.playouts}", flush=True)
    print(f"workers: {args.workers}; play-outs scored by: {args.score}"
          + (f", judged by the evaluation after {args.horizon} turns" if args.horizon else ""), flush=True)
    print(f"mid-matchup swap: {config['mid_swap']}; examples per round: {args.examples_per_round or 'all'}", flush=True)

    def versus_planner(q, margin, battles, seed, on_team, against=None):
        pilots = []
        against = against or crowd

        def pilot():
            pilots.append(Learner(q=q, margin=margin, mid_swap=config["mid_swap"]))
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
    inputs = N_FEATURES + (N_KNOWN if args.wide else 0) + (N_FORMS if args.forms else 0)
    stored = {head: (np.zeros((0, inputs)), np.zeros((0, n))) for head, n in Q_HEADS.items()}
    if args.start and not args.resume:
        q = QNet.load(args.start)
        if q.wide != args.wide:
            parser.error("--start model and --wide disagree")
        if max(ps[0].shape[0] for ps in q.params.values()) < inputs:
            q = q.widened(inputs)
        margin = 0.02
        print(f"first round piloted by {args.start} (margin {margin})", flush=True)
    if args.resume and (folder / "q.npz").exists():
        q = QNet.load(folder / "q.npz")
        margin = float((folder / "margin.txt").read_text()) if (folder / "margin.txt").exists() else margin
        if (folder / "examples.npz").exists():  # not kept in git; without it, start collecting afresh from the saved model
            saved = np.load(folder / "examples.npz")
            stored.update({head: (saved[f"{head}_x"], saved[f"{head}_y"])
                           for head in Q_HEADS if f"{head}_x" in saved})
        if any(x.shape[1] != inputs for x, _ in stored.values()) or (q.wide and not args.wide) or (q.forms and not args.forms):
            parser.error("the saved model or examples were made with a different --wide or --forms setting")
        # A narrower saved model may pilot the first round of a --wide run: it reads the inputs it knows.
        if args.no_mid_swap:
            q.params.pop("mid_swap", None)
            stored["mid_swap"] = (np.zeros((0, inputs)), np.zeros((0, Q_HEADS["mid_swap"])))
        print(f"resuming with {sum(len(x) for x, _ in stored.values())} examples already collected", flush=True)
        args.seed += 1000 + sum(len(x) for x, _ in stored.values()) % 1000  # so new battles differ from the earlier ones
    receipt = {"arguments": vars(args), "rounds": []}
    for round_no in range(1, args.rounds + 1):
        t0 = time.time()
        seconds = 60 * args.minutes / args.rounds
        if args.workers > 1:
            jobs = [(config, q.params if q else None, margin, seconds, args.seed + round_no + 1000 * w) for w in range(args.workers)]
            with multiprocessing.get_context("spawn").Pool(args.workers) as workers:
                parts = workers.map(collect_job, jobs)
            fresh = {head: (np.vstack([part[0][head][0] for part in parts]), np.vstack([part[0][head][1] for part in parts]))
                     for head in Q_HEADS}
            battles = sum(part[1] for part in parts)
            pvpoke_battles = sum(part[2] for part in parts)
        else:
            fresh, battles, pvpoke_battles = collect(team, pool, q, margin, crowd, seconds, args.seed + round_no, draw,
                                                     pvpoke_share=args.pvpoke_share, mid_swap=config["mid_swap"], score=args.score,
                                                     horizon=args.horizon, wide=args.wide, both_sides=args.both_sides)
        collected = {head: len(x) for head, (x, _) in fresh.items()}
        collection_seconds = time.time() - t0
        if args.examples_per_round is not None:
            fresh = sample_examples(fresh, args.examples_per_round, args.seed + 10000 + round_no)
        for head in Q_HEADS:
            stored[head] = (np.vstack([stored[head][0], fresh[head][0]]), np.vstack([stored[head][1], fresh[head][1]]))
        np.savez_compressed(folder / "examples.npz", **{f"{h}_{k}": a for h, xy in stored.items() for k, a in zip("xy", xy)})
        receipt["rounds"].append({"round": round_no, "battles": battles, "pvpoke_battles": pvpoke_battles, "collection_seconds": collection_seconds,
                                  "collected": collected, "retained": {h: len(x) for h, (x, _) in fresh.items()},
                                  "cumulative": {h: len(x) for h, (x, _) in stored.items()}})
        (folder / "training.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print("collected this round: " + ", ".join(f"{n} {h}" for h, n in collected.items()), flush=True)
        print(f"\nround {round_no}: {battles} battles ({pvpoke_battles} of them 1v1 against PvPoke) in {(time.time() - t0) / 60:.1f} min; examples so far: "
              + ", ".join(f"{len(stored[h][0])} {h}" for h in Q_HEADS), flush=True)
        q = QNet(seed=args.seed, hidden=args.hidden, inputs=inputs)
        # A missing head must fall back to the Planner, never use random untrained weights.
        q.params = {h: ps for h, ps in q.params.items() if len(stored[h][0])}
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
    if rivals or target:
        print("\nthe same test against the old crowd (Planner variations only), as a fixed yardstick")
        show("yardstick", *versus_planner(q, margin, args.final_battles, args.seed + 999, team, against=old_crowd))
    if args.also_test:
        other = [gd.default(sid) for sid in args.also_test]
        print(f"\nthe same model piloting {', '.join(b.name for b in other)}, {args.final_battles} fresh battles")
        show("also", *versus_planner(q, margin, args.final_battles, args.seed + 998, other))
    print(f"files: runs/{folder.name}/q.npz, margin.txt, examples.npz")


if __name__ == "__main__":
    main()
