#!/usr/bin/env python3
"""Engine lab: decisions of the search engines judged by play-outs with both real teams known (pogo/lab/tree.py).

    python scripts/lab/search_positions.py --positions [--seeds 6] [--playouts 300]
    python scripts/lab/search_positions.py --review 20 [--workers 2] [--playouts 200] [--seed 2431]
        [--variants "fix_stay=1" "fix_stay=1,depth=3,root=sh" ...]

--positions: hand positions (the Tinkaton lead against the owner's Quagsire, status.md task 43; the Rage Fist throw of
2026-10-28, rebuilt from runs/bot_losses_web.out with the benched Pokémon's health guessed). Each engine variant
searches the position with several seeds of its own; the "truth" plays each option to the end `--playouts` times with
both real teams and the trained bot on both sides (the diagnosis status.md used).

--review: games of the website engine against itself on the mixed field. At every searched throw or swap decision of
side 0 each variant searches the same position from the same random state (the website engine's choice is the one
played); where any variant chooses differently, every option is played to the end with both real teams, the trained
bot on both sides and the same dice for every option. Each variant's choice is scored by those play-outs: mean
decisiveness (pogo.arena.decisive) and win rate of what it chose, paired against the website engine's choice over the
reviewed decisions, with 95% margins. The play-outs are the trained bot's games, which is what the flat engine assumes
too, but they know the hidden team and play to the end.
"""
from __future__ import annotations

import argparse
import math
import multiprocessing
import os
import random
import sys
import time
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_v] = "1"

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from pogo.arena import decisive, low_priority, mean_and_margin  # noqa: E402
from pogo.battle import CHARGED, FAST, SWITCH, Battle, Mon  # noqa: E402
from pogo.engine import _First  # noqa: E402
from pogo.evaluation import Evaluator  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.lab import setting  # noqa: E402
from pogo.lab.tree import Search, TreeEngine, _Stay  # noqa: E402
from pogo.learner import Learner, QNet  # noqa: E402
from pogo.realtime import WEBSITE  # noqa: E402

NO_LIMIT = {k: 1e9 for k in ("turn_ms", "unforeseen_ms", "after_charged_ms", "after_faint_ms", "replace_ms", "start_ms")}
VARIANTS = ("fix_stay=1", "fix_stay=1,root=sh", "fix_stay=1,depth=3", "fix_stay=1,depth=3,root=sh",
            "fix_stay=1,depth=3,root=sh,adversary=1")
_state: dict = {}


def attrs(spec: str) -> dict:
    out = {}
    for part in filter(None, (p.strip() for p in spec.split(","))):
        key, value = part.split("=", 1)
        out[key] = setting(key, value)
    return out


def load() -> None:
    if _state:
        return
    gd = GameData()
    _state.update(gd=gd, pool=gd.meta(50), net=QNet.load(str(ROOT / "runs" / "general-decide" / "q.npz")),
                  ev=Evaluator.load(ROOT / "runs" / "eval" / "eval.npz").model)


def website(seed: int, cls=TreeEngine, **kw) -> TreeEngine:
    s = _state
    settings = {k: v for k, v in WEBSITE.items() if k != "margin"}
    return cls(Evaluator(s["ev"]), s["pool"], q=s["net"], margin=WEBSITE["margin"], seed=seed, **settings,
               **NO_LIMIT, **kw)


def bot(seed: int) -> Learner:
    return Learner(q=_state["net"], margin=WEBSITE["margin"], seed=seed)


def first_player(head: str, option: int, active: int, player):
    others = [j for j in range(3) if j != active]
    if head == "throw":
        return _First(player, FAST if option == 0 else CHARGED[option - 1])
    if option == 0:
        return _Stay(player)
    return _First(player, SWITCH[others[option - 1]])


def truth(snapshot: Battle, head: str, options: list, playouts: int, seed: int) -> dict:
    """Each option played to the end from the real position, both real teams, the trained bot on both sides, the same
    dice for every option: {option: (mean decisiveness, win rate, per-play-out decisiveness)}."""
    out = {}
    active = snapshot.sides[0].active
    for k in options:
        values, wins = [], 0
        for j in range(playouts):
            rng = random.Random(seed * 7919 + j)
            us, them = bot(rng.getrandbits(32)), bot(rng.getrandbits(32))
            if head == "throw":  # an ongoing matchup: both have judged it already, as in the game
                us._judged = (active, snapshot.sides[1].mon.build.uid)
                them._judged = (snapshot.sides[1].active, snapshot.sides[0].mon.build.uid)
            twin = snapshot.clone(first_player(head, k, active, us), them)
            twin.rng = random.Random(rng.getrandbits(32))
            winner = twin.run()
            values.append(decisive(twin, 0))
            wins += 1.0 if winner == 0 else 0.5 if winner == -1 else 0.0
        out[k] = (sum(values) / playouts, wins / playouts, values)
    return out


class Review(TreeEngine):
    """The website engine (it plays its own choice), searching each throw and swap decision again as every variant."""

    variants: list = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.reviews: list = []

    def _halving(self, view, head, options, pick, logits):
        state, mixed = self.rng.getstate(), self._mix_rng.getstate()
        played = after = None
        found = {}
        for name, change in [("website", {})] + self.variants:
            self.rng.setstate(state)
            self._mix_rng.setstate(mixed)
            saved = {k: getattr(self, k) for k in change}
            for k, v in change.items():
                setattr(self, k, v)
            self._search = Search(self.depth, self.c_puct, self.k0, self.prior_temp, self.tree_heads, self.closed)
            start = time.process_time()
            try:
                result = super()._halving(view, head, options, pick, logits)
            finally:
                for k, v in saved.items():
                    setattr(self, k, v)
            found[name] = (result[0] if result[0] is not None else pick, 1000 * (time.process_time() - start), result[1])
            if played is None:
                played, after = result, (self.rng.getstate(), self._mix_rng.getstate())
        self.rng.setstate(after[0])
        self._mix_rng.setstate(after[1])
        if head in ("throw", "swap", "mid_swap"):
            self.reviews.append(dict(turn=view.turn, head=head, options=options, pick=pick, found=found,
                                     snapshot=view._battle.clone(None, None)))
        return played


def review_job(task):
    game, seed, variants, playouts = task
    low_priority()
    load()
    from pogo.teamshape import mixed_field
    _, draw = mixed_field(_state["gd"])
    rng = random.Random(seed * 1_000_003 + game)
    a, b = draw(rng), draw(rng)
    Review.variants = [(v, attrs(v)) for v in variants]
    me = website(rng.getrandbits(32), cls=Review)
    Battle(a, b, me, website(rng.getrandbits(32)), seed=rng.getrandbits(32)).run()
    rows = []
    for n, r in enumerate(me.reviews):
        choices = {name: f[0] for name, f in r["found"].items()}
        row = dict(game=game, turn=r["turn"], head=r["head"], options=r["options"], pick=r["pick"], choices=choices,
                   ms={name: f[1] for name, f in r["found"].items()},
                   worth={name: f[2] for name, f in r["found"].items()},
                   mon=r["snapshot"].sides[0].mon.build.name, foe=r["snapshot"].sides[1].mon.build.name)
        if len(set(choices.values())) > 1:
            t = truth(r["snapshot"], r["head"], sorted(set(choices.values())), playouts, seed * 100_003 + game * 1009 + n)
            row["truth"] = {k: (v[0], v[1]) for k, v in t.items()}
            row["paired"] = {name: t[c][2] for name, c in choices.items()}
        rows.append(row)
    return game, rows


def option_name(head: str, option: int, snapshot_mon=None) -> str:
    if head == "throw":
        return ("fast", "charged 1", "charged 2")[option]
    return "stay" if option == 0 else f"switch {option}"


def review(args) -> None:
    """Games are reviewed in parallel; each game's rows are appended to --save (JSON lines) as it finishes, a run with
    the same file skips the games already in it, and the summary covers every game in the file."""
    import json
    names = ["website"] + list(args.variants)
    done = set()
    if args.save and args.save.exists():
        for line in args.save.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row["seed"] != args.seed or row["variants"] != names or row["playouts"] != args.playouts:
                raise SystemExit(f"{args.save} holds another review (seed, variants or play-outs); use another file")
            done.add(row["game"])
    tasks = [(g, args.seed, args.variants, args.playouts) for g in range(args.review) if g not in done]
    if tasks:
        with multiprocessing.get_context("spawn").Pool(min(args.workers, len(tasks))) as pool:
            for game, part in pool.imap_unordered(review_job, tasks):
                if args.save:
                    args.save.parent.mkdir(parents=True, exist_ok=True)
                    with args.save.open("a", encoding="utf-8", newline="\n") as f:
                        for row in part or [dict(game=game, turn=None)]:
                            row = {k: v for k, v in row.items() if k != "paired"}
                            if "truth" in row:
                                row["truth"] = {str(k): v for k, v in row["truth"].items()}
                            f.write(json.dumps(dict(row, seed=args.seed, variants=names, playouts=args.playouts)) + "\n")
                print(f"  reviewed a game: {len(part)} decisions", flush=True)
    if args.save:
        rows = [json.loads(line) for line in args.save.read_text(encoding="utf-8").splitlines()]
        rows = [r for r in rows if r.get("turn") is not None and r["game"] < args.review]
    else:
        raise SystemExit("--review needs --save")
    games = len({r["game"] for r in rows})
    judged = [r for r in rows if "truth" in r]
    print(f"\n{len(rows)} searched throw/swap decisions in {games} games (seed {args.seed}); {len(judged)} where some "
          f"variant chose differently, each option played out {args.playouts} times with both real teams, the trained "
          f"bot on both sides\n")
    print(f"{'variant':45} | differs | better / worse | decisiveness gained per judged decision | wins gained | ms median / 99th")
    import numpy as np

    def value(r, name, i):
        return r["truth"][str(r["choices"][name])][i]

    for name in names:
        diffs = [value(r, name, 0) - value(r, "website", 0) for r in judged]
        wins = [value(r, name, 1) - value(r, "website", 1) for r in judged]
        differs = sum(r["choices"][name] != r["choices"]["website"] for r in rows)
        better, worse = sum(d > 0.01 for d in diffs), sum(d < -0.01 for d in diffs)
        ms = np.array([r["ms"][name] for r in rows])
        if len(diffs) > 1:
            m, h = mean_and_margin(diffs)
            w, hw = mean_and_margin(wins)
            gained = f"{100 * m:+.2f} ± {100 * h:.2f}"
            won = f"{100 * w:+.2f} ± {100 * hw:.2f}"
        else:
            gained = won = "n/a"
        print(f"{name:45} | {differs:7d} | {better:6d} / {worse:5d} | {gained:39} | {won:13} | "
              f"{np.median(ms):.0f} / {np.percentile(ms, 99):.0f}")
    print("\ndecisions where variants disagree (truth: decisiveness / win rate of each option played out):")
    for r in sorted(judged, key=lambda r: (r["game"], r["turn"])):
        truths = ", ".join(f"{option_name(r['head'], int(k))} {v[0]:.3f}/{100 * v[1]:.0f}%"
                           for k, v in sorted(r["truth"].items()))
        picks = " ".join(f"[{n}: {option_name(r['head'], c)}]" for n, c in r["choices"].items())
        print(f"  game {r['game']} turn {r['turn']} {r['head']} {r['mon']} v {r['foe']}: bot's pick "
              f"{option_name(r['head'], r['pick'])}; {picks}; truth {truths}")


# hand positions

def team(gd, entries) -> list:
    out = []
    for species, hp_share, energy in entries:
        build = gd.default(species)
        out.append(Mon(build, max(1, round(hp_share * build.hp)), energy))
    return out


def positions(gd) -> list:
    """(name, our team, their team, our active, their active, shields, turn, their Pokémon shown, the decision, notes)."""
    return [
        ("Tinkaton lead against the owner's Quagsire (website game 2026-11-04, status.md task 43)",
         team(gd, [("tinkaton", 1, 0), ("florges", 1, 0), ("rillaboom", 1, 0)]),
         team(gd, [("quagsire", 1, 0), ("sableye_shadow", 1, 0), ("corviknight_shadow", 1, 0)]),
         0, 0, (2, 2), 0, [0], "swap",
         "status.md: the engine rated stay 54%, Florges 37%, Rillaboom 38%; bot both sides with both real teams, 300 "
         "games each: Florges 77% ± 5, stay 27% ± 5, Rillaboom 21% ± 5"),
        ("Annihilape's Rage Fist into Altaria (website game 2026-10-28 14:19, turn 179; bench health guessed)",
         team(gd, [("annihilape_shadow", 0.64, 72), ("tinkaton", 1.0, 0), ("carbink", 0.38, 45)]),
         team(gd, [("melmetal", 1.0, 0), ("altaria", 0.89, 36), ("jellicent", 0.14, 62)]),
         0, 1, (0, 1), 179, [0, 2, 1], "throw",
         "runs/bot_losses_web.out: chose Rage Fist (21%), Ice Punch wins 96% (replayed with the real game's state); "
         "here Tinkaton 100%, Carbink 38%, Melmetal 100% and Jellicent 14% are guesses"),
    ]


def setup_battle(ours, theirs, active, foe_active, shields, turn, shown, agents):
    battle = Battle([m.copy() for m in ours], [m.copy() for m in theirs], *agents, seed=1, shields=shields)
    battle.sides[0].active, battle.sides[1].active = active, foe_active
    battle.sides[0].shown = [active]
    battle.sides[1].shown = list(shown)
    battle.turn = turn
    return battle


def hand(args) -> None:
    load()
    gd = _state["gd"]
    names = ["website"] + list(args.variants)
    for title, ours, theirs, active, foe_active, shields, turn, shown, head, notes in positions(gd):
        print(f"\n== {title}\n   {notes}")
        snap = setup_battle(ours, theirs, active, foe_active, shields, turn, shown, (None, None))
        options = [0, 1, 2]
        if head == "throw":
            mon = snap.sides[0].mon
            options = [0] + [k + 1 for k, m in enumerate(mon.build.charged) if mon.energy >= m.energy]
        t = truth(snap, head, options, args.playouts, 4301)
        print("   truth (both real teams, trained bot both sides, to the end): " + ", ".join(
            f"{option_name(head, k)} {v[0]:.3f} / {100 * v[1]:.0f}% won" for k, v in t.items()))
        for name in names:
            counts, worth, ms = {}, {}, []
            for s in range(args.seeds):
                change = attrs(name) if name != "website" else {}
                e = website(1000 + s, **change)
                e.record = []
                battle = setup_battle(ours, theirs, active, foe_active, shields, turn, shown, (e, bot(7)))
                if head != "swap":  # mid-battle: the matchup was judged when it began, and stood at the last decision
                    e._judged = (active, battle.sides[1].mon.build.uid)
                    e._last_pair, e._last_foe_free = e._judged, True
                start = time.process_time()
                e.act(battle.views[0])
                ms.append(1000 * (time.process_time() - start))
                rec = [r for r in e.record if r["head"] == head]
                if not rec:
                    continue
                r = rec[0]
                counts[r["choice"]] = counts.get(r["choice"], 0) + 1
                for k, v in r["worth"].items():
                    worth.setdefault(k, []).append(v)
            print(f"   {name:42} chose " + ", ".join(f"{option_name(head, k)} x{n}" for k, n in sorted(counts.items()))
                  + "; worth " + ", ".join(f"{option_name(head, k)} {sum(v) / len(v):.3f}" for k, v in sorted(worth.items()))
                  + f"; {sum(ms) / len(ms):.0f} ms")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--positions", action="store_true")
    parser.add_argument("--review", type=int, default=0, help="games to review")
    parser.add_argument("--variants", nargs="+", default=list(VARIANTS), help="lab settings on top of the website engine")
    parser.add_argument("--seeds", type=int, default=6, help="engine seeds per hand position")
    parser.add_argument("--playouts", type=int, default=200)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--seed", type=int, default=2431)
    parser.add_argument("--save", type=Path)
    args = parser.parse_args()
    if args.positions:
        hand(args)
    if args.review:
        review(args)


if __name__ == "__main__":
    main()
