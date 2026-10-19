#!/usr/bin/env python3
"""Play one match-up thousands of times and see which ways of playing it win (the owner: "playing out a game a ton
of times to really see all the best ways to win").

    python3 scripts/best_lines.py melmetal altaria jellicent [--vs SP SP SP ...] [--pvpoke 5] [--battles 3000]

Our team (the owner's builds where they have them, lead first) against each opposing team: by default the --pvpoke
most-played teams in PvPoke's data (data/pvpoke_training_1500.json), or those given with --vs (three names each).
Our side is the trained bot, except that at its judgement calls it sometimes picks another legal option at random
(shields, swaps, replacements: a third of the time; charged-move timing: a tenth), so the battles cover many ways of
playing. Their side is the trained bot with shifted habits, as in every measurement. Each battle is summed up as a line:

  lead      what our lead did: stayed until it fainted or the battle was decided, or swapped (at once, or later) to whom
  shields   our first three shield calls in order (S shielded, N took it)
  first     the first charged move our lead threw
  back      whom we sent in after the first faint

For each, the win share of every choice seen (with its 95% margin), then the best whole lines seen often enough.
Lines are what happened, not plans: a line that wins may also be one the opponent let happen. The bot's own score
without random choices is given first, on its own battles, as the yardstick. Writes runs/best_lines/<team>.json.
"""
from __future__ import annotations

import argparse
import collections
import json
import multiprocessing
import os
import random
import sys
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_v] = "1"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pogo.agents import varied_settings  # noqa: E402
from pogo.arena import low_priority, mean_and_margin  # noqa: E402
from pogo.battle import DRAW, Battle  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.learner import Learner, QNet  # noqa: E402
from pogo.roster import builds  # noqa: E402

RATES = {"shield": 1 / 3, "swap": 1 / 3, "mid_swap": 1 / 3, "replace": 1 / 3, "throw": 0.1}
_s: dict = {}


class Explorer(Learner):
    """The trained bot, sometimes choosing at random at its judgement calls; notes every such call."""

    def __init__(self, explore: bool, rng: random.Random, **kw):
        super().__init__(**kw)
        self.explore, self.dice, self.calls = explore, rng, []

    def clone(self):
        twin = super().clone()
        twin.explore, twin.dice, twin.calls = False, random.Random(0), []
        return twin

    def _decide(self, head, view, mask, planner_choice, foe_energy=None):
        if self.explore and head not in self.forced and self.dice.random() < RATES.get(head, 0.0):
            planner_choice()  # its bookkeeping, as when it decides for itself
            choice = self.dice.choice([k for k in range(len(mask)) if mask[k]])
        else:
            choice = super()._decide(head, view, mask, planner_choice, foe_energy)
        self.calls.append((view.turn, head, choice, view.me.active, view.me.mon.hp > 0))
        return choice


def setup(team):
    low_priority()
    gd = GameData()
    owned = builds(gd)
    _s.update(gd=gd, mine=[owned.get(sp) or gd.default(sp) for sp in team], pool=gd.meta(50),
              net=QNet.load(str(ROOT / "runs" / "general-decide" / "q.npz")))


def line_of(battle, me: Explorer) -> dict:
    gd, team = _s["gd"], battle.sides[0].team
    name = lambda m: m.build.name  # noqa: E731
    lead, slot_names = "stayed", [name(m) for m in team]
    for k, (turn, head, choice, active, alive) in enumerate(me.calls):
        if active != 0:
            break
        if head in ("swap", "mid_swap") and choice and alive:
            others = [j for j in range(3) if j != 0]
            first = not any(h in ("swap", "mid_swap", "throw") for _, h, _, _, _ in me.calls[:k])
            lead = f"swapped {'at once' if first else 'later'} to {slot_names[others[choice - 1]]}"
            break
    shields = "".join("S" if c else "N" for _, h, c, _, _ in me.calls if h == "shield")[:3] or "-"
    first = next((text.split(" throws ")[1].split(":")[0] for _, side, text in battle.log
                  if side == 0 and " throws " in text and text.startswith(team[0].build.name)), "none")
    faint = next((k for k, (_, side, text) in enumerate(battle.log) if side == 0 and text.endswith("faints")), None)
    back = "none" if faint is None else next((text[len("sends in "):].rsplit(" ", 2)[0] for _, side, text in battle.log[faint:]
                                              if side == 0 and text.startswith("sends in")), "none")
    return {"lead": lead, "shields": shields, "first": first, "back": back}


def job(task):
    theirs_ids, start, count, seed, explore = task
    s = _s
    gd = s["gd"]
    theirs = [gd.default(sp) for sp in theirs_ids]
    out = []
    for n in range(start, start + count):
        rng = random.Random(seed * 1_000_003 + n)
        me = Explorer(explore, random.Random(rng.getrandbits(32)), q=s["net"], margin=0.02, seed=rng.getrandbits(32))
        foe = Learner(q=s["net"], margin=rng.choice((0.02, 0.05)), **varied_settings(rng, s["pool"]))
        battle = Battle(s["mine"], theirs, me, foe, seed=rng.getrandbits(32))
        battle.log = []
        winner = battle.run()
        points = 1.0 if winner == 0 else 0.5 if winner == DRAW else 0.0
        out.append((points, line_of(battle, me) if explore else None))
    return out


def summary(rows, key, least):
    groups = collections.defaultdict(list)
    for points, line in rows:
        groups[line[key] if isinstance(key, str) else tuple(line[k] for k in key)].append(points)
    ranked = []
    for value, pts in groups.items():
        if len(pts) >= least:
            m, h = mean_and_margin(pts)
            ranked.append((m, h, len(pts), value))
    return sorted(ranked, reverse=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("team", nargs=3)
    parser.add_argument("--vs", nargs="+", default=[], help="opposing teams, three names each")
    parser.add_argument("--pvpoke", type=int, default=5, help="without --vs: this many of PvPoke's most-played teams")
    parser.add_argument("--battles", type=int, default=3000)
    parser.add_argument("--baseline", type=int, default=600)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--seed", type=int, default=91)
    args = parser.parse_args()
    gd = GameData()
    known = {e["speciesId"] for e in gd.rankings(1500)}
    if args.vs:
        teams = [args.vs[k:k + 3] for k in range(0, len(args.vs), 3)]
    else:
        listed = json.loads((ROOT / "data" / "pvpoke_training_1500.json").read_text())["usage"]["teams"]
        teams = [t["team"] for t in sorted(listed, key=lambda t: -t["games"]) if all(sp in known for sp in t["team"])][:args.pvpoke]
    name = lambda sp: gd.species[sp]["speciesName"]  # noqa: E731
    report = {"team": args.team, "opponents": []}
    with multiprocessing.get_context("spawn").Pool(args.workers, initializer=setup, initargs=(args.team,)) as pool:
        for i, theirs in enumerate(teams):
            seed = args.seed + 100 * i

            def run(count, explore, seed=seed, theirs=theirs):
                per = -(-count // (4 * args.workers))
                tasks = [(theirs, k, min(per, count - k), seed + (0 if explore else 50), explore) for k in range(0, count, per)]
                return [r for part in pool.map(job, tasks) for r in part]

            base = run(args.baseline, False)
            rows = run(args.battles, True)
            m, h = mean_and_margin([p for p, _ in base])
            print(f"\n{' / '.join(map(name, args.team))} against {' / '.join(map(name, theirs))}: the bot alone wins "
                  f"{100 * m:.0f}% ± {100 * h:.0f} ({len(base)} battles); {len(rows)} battles with random choices mixed in", flush=True)
            entry = {"theirs": theirs, "bot": [m, h], "features": {}, "lines": []}
            for key, label in (("lead", "our lead"), ("shields", "first three shield calls"), ("first", "lead's first charged move"),
                               ("back", "sent in after the first faint")):
                ranked = summary(rows, key, 40)
                entry["features"][key] = [[v, round(m, 3), round(h, 3), n] for m, h, n, v in ranked]
                print(f"  {label}: " + "; ".join(f"{v} {100 * m:.0f}% ± {100 * h:.0f} ({n})" for m, h, n, v in ranked[:6]))
            best = summary(rows, ("lead", "shields", "first", "back"), 25)
            entry["lines"] = [[list(v), round(m, 3), round(h, 3), n] for m, h, n, v in best[:10]]
            print("  best whole lines (lead | shields | first charged move | sent in after the first faint):")
            for m, h, n, v in best[:5]:
                print(f"    {100 * m:3.0f}% ± {100 * h:.0f} ({n:3d})  {' | '.join(v)}")
            report["opponents"].append(entry)
    out = ROOT / "runs" / "best_lines" / f"{'-'.join(args.team)}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1) + "\n")
    print(f"\nwritten: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
