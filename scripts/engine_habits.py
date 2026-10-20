#!/usr/bin/env python3
"""Where the engine (pogo.engine) disagrees with the trained bot, and in what situations: candidate rules.

    python3 scripts/engine_habits.py [--battles 200] [--workers 2] [--save runs/engine_habits.json] [--spots] [--rules]
    python3 scripts/engine_habits.py --from-saved --spots --rules      report on decisions already recorded

The engine plays the usual crowd. At every decision it searches, the situation is recorded with the trained bot's
pick and the engine's, and the look-ahead's worth of each option. The report tabulates, for each kind of decision,
how often the engine overrode the bot and in which direction, split by the things a rule could test: shields on
each side, energy against the move costs, the opponent's energy against theirs, health, and the matchup's outlook.
--spots lists the conditions under which the engine most often overrules the bot one way; --rules scores simple
rules ("in this situation always do X") by the look-ahead's own worths, the test a candidate rule must pass first.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pogo.agents import varied  # noqa: E402
from pogo.arena import low_priority  # noqa: E402
from pogo.battle import Battle, damage  # noqa: E402
from pogo.engine import Engine  # noqa: E402
from pogo.evaluation import Evaluator  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.learner import Learner, QNet  # noqa: E402
from pogo.teamlist import drawer  # noqa: E402


class Recorder(Engine):
    """The engine, writing down each searched decision."""

    def _decide(self, head, view, mask, planner_choice, foe_energy=None):
        if head in self.forced or head not in self.heads or getattr(self, "notes", None) is None:
            return super()._decide(head, view, mask, planner_choice, foe_energy)
        options = [k for k in range(len(mask)) if mask[k]]
        pick = Learner._decide(self, head, view, mask, planner_choice, foe_energy)
        if len(options) < 2:
            return pick
        seeds = [self.rng.getrandbits(32) for _ in range(self.samples)]
        worth = {k: sum(self._look(view, head, k, s) for s in seeds) / len(seeds) for k in options}
        best = max(options, key=lambda k: (worth[k], k == pick))
        choice = best if worth[best] - worth[pick] > self.edge else pick
        self.notes.append(situation(self, view, head, pick, choice, worth))
        return choice


def situation(agent, view, head, pick, choice, worth) -> dict:
    me, mon, foe = view.me, view.me.mon, view.foe
    costs = [m.energy for m in mon.build.charged]
    foe_costs = [m.energy for m in foe.build.charged]
    hits = [damage(mon, m, foe) for m in mon.build.charged]
    foe_hits = [damage(foe, m, mon) for m in foe.build.charged]
    fast, foe_fast = damage(mon, mon.build.fast, foe), damage(foe, foe.build.fast, mon)
    bench = [j for j in range(3) if j != me.active]
    # Options named by what they do: for a throw, the cheaper or dearer move (by energy, then by damage).
    kinds = {}
    if head == "throw":
        order = sorted(range(len(costs)), key=lambda k: (costs[k], -hits[k]))
        kinds = {0: "hold", **{k + 1: ("cheap" if k == order[0] else "dear") for k in range(len(costs))}}
        if len(costs) == 1:
            kinds[1] = "only"
    return {
        "head": head, "pick": pick, "choice": choice, "kinds": {str(k): v for k, v in kinds.items()},
        "worth": {str(k): round(v, 4) for k, v in worth.items()},
        "my_shields": me.shields, "foe_shields": view.foe_shields,
        "my_hp": round(max(mon.hp, 0) / mon.build.hp, 3), "foe_hp": round(max(foe.hp, 0) / foe.build.hp, 3),
        "my_energy": mon.energy, "cheap": min(costs) if costs else None, "dear": max(costs) if costs else None,
        "foe_energy": foe.energy, "foe_cheap": min(foe_costs) if foe_costs else None,
        "foe_ready": bool(foe_costs) and foe.energy >= min(foe_costs),
        "foe_ready_soon": bool(foe_costs) and foe.energy + 2 * foe.build.fast.energy_gain >= min(foe_costs),
        "lethal": any(h >= foe.hp for h, c in zip(hits, costs) if mon.energy >= c),
        "foe_lethal": any(h >= mon.hp for h, c in zip(foe_hits, foe_costs) if foe.energy >= c),
        "fasts_to_kill": -(-max(foe.hp, 0) // max(fast, 1)), "foe_fasts_to_kill": -(-max(mon.hp, 0) // max(foe_fast, 1)),
        "my_fast_turns": mon.build.fast.turns, "foe_fast_turns": foe.build.fast.turns,
        "doomed_soon": mon.hp > 0 and agent._doomed(view, 2 * foe.build.fast.turns),
        "outlook": round(agent._outlook(view, me.active), 3) if mon.hp > 0 else None,
        "bench_outlook": [round(agent._outlook(view, j), 3) if me.team[j].hp > 0 else None for j in bench],
        "bench_energy": [me.team[j].energy for j in bench],
        "my_left": me.left(), "foe_left": view.foe_left, "foe_seen": len(view.foe_shown),
        "my_switch_ready": me.switch_wait == 0, "foe_locked": view.foe_switch_wait > 0,
        "turn": view.turn,
    }


def play(task) -> list:
    seed, count = task
    low_priority()
    gd = GameData()
    pool = gd.meta(50)
    draw = drawer(gd, pool)
    net = QNet.load(str(ROOT / "runs" / "general-decide" / "q.npz"))
    ev = Evaluator.load(ROOT / "runs" / "eval" / "eval.npz")
    rng = random.Random(seed)
    notes = []
    for _ in range(count):
        # a fresh evaluation cache per engine, the weights shared (task 27's fix)
        engine = Recorder(Evaluator(ev.model), pool, rollout="bot", samples=4, edge=0.03, q=net, margin=0.02, seed=rng.getrandbits(32))
        engine.notes = notes
        Battle(draw(rng), draw(rng), engine, varied(rng, pool), seed=rng.getrandbits(32)).run()
    return notes


def name(row: dict, k: int) -> str:
    """An option by what it does: for a throw the cheaper or dearer move; for a swap whether the Pokémon brought
    in is the bench's better or worse one-on-one against what is in front of it."""
    head = row["head"]
    if head == "throw":
        return row["kinds"].get(str(k), str(k))
    if head != "replace" and k == 0:
        return "stay"
    slot = k if head == "replace" else k - 1
    mine, other = row["bench_outlook"][slot], row["bench_outlook"][1 - slot]
    which = "better" if other is None or (mine is not None and mine >= other) else "worse"
    return f"bring the {which}" if head == "replace" else f"switch to the {which}"


def report(notes: list) -> None:
    by_head = defaultdict(list)
    for n in notes:
        by_head[n["head"]].append(n)
    for head, rows in by_head.items():
        changed = [r for r in rows if r["choice"] != r["pick"]]
        print(f"\n== {head}: {len(rows)} searched, engine overrode the bot in {len(changed)} ({100 * len(changed) / len(rows):.0f}%)")
        print("   direction: " + ", ".join(f"{a} -> {b} {n}"
                                         for (a, b), n in Counter((name(r, r["pick"]), name(r, r["choice"])) for r in changed).most_common(6)))
        splits = {
            "their shields": lambda r: r["foe_shields"],
            "our shields": lambda r: r["my_shields"],
            "they have a move ready": lambda r: r["foe_ready"],
            "our move would knock them out": lambda r: r["lethal"],
            "our health": lambda r: "under 1/3" if r["my_hp"] < 1 / 3 else "1/3 to 2/3" if r["my_hp"] < 2 / 3 else "over 2/3",
            "matchup outlook": lambda r: "losing" if (r["outlook"] or 0) < -0.15 else "even" if (r["outlook"] or 0) < 0.15 else "winning",
            "their switch locked": lambda r: r["foe_locked"],
            "Pokémon left, ours v theirs": lambda r: f"{r['my_left']} v {r['foe_left']}",
        }
        if head == "throw":
            splits["energy for the dearer move too"] = lambda r: r["dear"] is not None and r["my_energy"] >= r["dear"]
        for label, key in splits.items():
            cells = defaultdict(lambda: [0, Counter()])
            for r in rows:
                cell = cells[key(r)]
                cell[0] += 1
                if r["choice"] != r["pick"]:
                    cell[1][(name(r, r["pick"]), name(r, r["choice"]))] += 1
            parts = []
            for value, (n, moves) in sorted(cells.items(), key=lambda kv: str(kv[0])):
                if n < 30:
                    continue
                top = ", ".join(f"{a}->{b} {100 * c / n:.0f}%" for (a, b), c in moves.most_common(2))
                parts.append(f"{value}: {n} [{top or 'agrees'}]")
            print(f"   {label}: " + " | ".join(parts))


def conditions(r: dict) -> dict:
    """Yes/no facts about a decision that a hand-written rule could test."""
    best_bench = max((o for o in r["bench_outlook"] if o is not None), default=None)
    c = {
        f"their shields {r['foe_shields']}": True, f"our shields {r['my_shields']}": True,
        "they have a move ready": r["foe_ready"], "they will have a move within two fast moves": r["foe_ready_soon"],
        "ours knocks them out": r["lethal"], "theirs knocks us out": r["foe_lethal"],
        "we are knocked out within two of their fast moves": r["doomed_soon"],
        "their fast moves alone finish us in 2 or fewer": r["foe_fasts_to_kill"] <= 2,
        "our fast moves alone finish them in 2 or fewer": r["fasts_to_kill"] <= 2,
        "our health under 1/3": r["my_hp"] < 1 / 3, "our health over 2/3": r["my_hp"] > 2 / 3,
        "their health under 1/3": r["foe_hp"] < 1 / 3, "their health over 2/3": r["foe_hp"] > 2 / 3,
        "losing the matchup": (r["outlook"] or 0) < -0.15, "winning the matchup": (r["outlook"] or 0) > 0.15,
        "a bench Pokémon beats staying by 0.3": best_bench is not None and r["outlook"] is not None and best_bench - r["outlook"] > 0.3,
        "their switch is locked": r["foe_locked"], "our switch is ready": r["my_switch_ready"],
        "more Pokémon left than them": r["my_left"] > r["foe_left"], "fewer Pokémon left than them": r["my_left"] < r["foe_left"],
        "last Pokémon each": r["my_left"] == 1 and r["foe_left"] == 1,
        "first two minutes": r["turn"] < 240,
    }
    if r["head"] == "throw":
        c["energy for the dearer move"] = r["dear"] is not None and r["my_energy"] >= r["dear"]
        c["energy for two of the cheaper"] = r["cheap"] is not None and r["my_energy"] >= 2 * r["cheap"]
    return {k: v for k, v in c.items() if v}


def candidates(notes: list, least: int = 150, top: int = 12) -> None:
    """The spots, defined by one or two conditions, where the engine most often overrules the bot's pick one way."""
    from itertools import combinations
    groups = defaultdict(list)
    for r in notes:
        groups[r["head"], name(r, r["pick"])].append((r, sorted(conditions(r))))
    for (head, pick), rows in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        if len(rows) < least:
            continue
        cells = defaultdict(lambda: [0, Counter(), 0.0])
        for r, facts in rows:
            keys = [()] + [(f,) for f in facts] + list(combinations(facts, 2))
            new = name(r, r["choice"])
            gain = r["worth"][str(r["choice"])] - r["worth"][str(r["pick"])]
            for k in keys:
                cell = cells[k]
                cell[0] += 1
                if new != pick:
                    cell[1][new] += 1
                    cell[2] += gain
        base_n, base_moves, _ = cells[()]
        print(f"\n== {head}, the bot picks {pick}: {base_n} times, engine overrules "
              + ", ".join(f"to {b} {100 * c / base_n:.0f}%" for b, c in base_moves.most_common()))
        ranked = []
        for k, (n, moves, gain) in cells.items():
            if not k or n < least:
                continue
            for b, c in moves.items():
                ranked.append((c / n, n, k, b, gain / max(sum(moves.values()), 1)))
        ranked.sort(reverse=True)
        shown = []
        for rate, n, k, b, gain in ranked:
            # Skip a pair that says no more than one of its conditions already shown.
            if any(set(prev) <= set(k) and b == pb and rate < prate + 0.08 for prate, prev, pb in shown):
                continue
            shown.append((rate, k, b))
            print(f"   {100 * rate:3.0f}% to {b} (n {n}, mean gain when overruled {gain:+.3f}): " + " & ".join(k))
            if len(shown) >= top:
                break


def worths(r: dict) -> dict:
    """Each kind of option the decision offered, with the look-ahead's worth of it minus that of the bot's pick."""
    out = {}
    for k in r["worth"]:
        out.setdefault(name(r, int(k)), r["worth"][k] - r["worth"][str(r["pick"])])
    return out


def blanket(notes: list, least: int = 300, top: int = 5) -> None:
    """Rules of the form "when these one or two conditions hold, always do X", each scored by the look-ahead:
    the mean, over every decision where the conditions hold, of X's worth minus the bot's pick's (zero where the
    bot picked X anyway). A rule worth adding would score clearly above zero."""
    from itertools import combinations
    cells = defaultdict(lambda: [0, 0.0, 0.0])
    for r in notes:
        facts = sorted(conditions(r))
        keys = [()] + [(f,) for f in facts] + list(combinations(facts, 2))
        for kind, gain in worths(r).items():
            for key in keys:
                cell = cells[r["head"], kind, key]
                cell[0] += 1
                cell[1] += gain
                cell[2] += gain * gain
    for head in ("throw", "swap", "replace"):
        for kind in sorted({k for h, k, _ in cells if h == head}):
            rows = []
            for (h, k, key), (n, total, squares) in cells.items():
                if h == head and k == kind and n >= least:
                    mean = total / n
                    rows.append((mean, 2 * (max(squares / n - mean * mean, 0) / n) ** 0.5, n, key))
            rows.sort(key=lambda z: -z[0])
            everywhere = next((z for z in rows if z[3] == ()), None)
            print(f"\n== {head}: always {kind!r}" + (f"; everywhere {everywhere[0]:+.4f} ± {everywhere[1]:.4f}" if everywhere else ""))
            for mean, margin, n, key in rows[:top]:
                print(f"   {mean:+.4f} ± {margin:.4f}  (n {n})  " + " & ".join(key))


def numbers(r: dict) -> dict:
    """What a rule with thresholds could test, as numbers."""
    bench = [o for o in r["bench_outlook"] if o is not None]
    outlook = r["outlook"] if r["outlook"] is not None else 0.0
    return {
        "our shields": r["my_shields"], "their shields": r["foe_shields"], "our health": r["my_hp"], "their health": r["foe_hp"],
        "our energy over the cheaper move": r["my_energy"] - r["cheap"] if r["cheap"] is not None else -100,
        "our energy over the dearer move": r["my_energy"] - r["dear"] if r["dear"] is not None else -100,
        "their energy over their cheaper move": r["foe_energy"] - r["foe_cheap"] if r["foe_cheap"] is not None else -100,
        "our fast moves to finish them": r["fasts_to_kill"], "their fast moves to finish us": r["foe_fasts_to_kill"],
        "our fast move's turns": r["my_fast_turns"], "their fast move's turns": r["foe_fast_turns"],
        "ours knocks them out": r["lethal"], "theirs knocks us out": r["foe_lethal"], "knocked out soon": r["doomed_soon"],
        "outlook": outlook, "best bench outlook over staying": max(bench) - outlook if bench else -2,
        "Pokémon left, ours": r["my_left"], "Pokémon left, theirs": r["foe_left"], "Pokémon left, ours minus theirs": r["my_left"] - r["foe_left"],
        "their switch locked": r["foe_locked"], "turn": r["turn"], "their Pokémon seen": r["foe_seen"],
    }


def thresholds(notes: list, depth: int = 3, least: int = 250) -> None:
    """The best rule with up to `depth` threshold conditions for always doing X, searched for on the first half of
    the decisions and then scored on the second half, which it has not seen."""
    import numpy as np
    keys = list(numbers(notes[0]))
    half = len(notes) // 2

    def table(rows, head, kind):
        x, y = [], []
        for r in rows:
            gains = worths(r)
            if r["head"] == head and kind in gains:
                x.append([float(v) for v in numbers(r).values()])
                y.append(gains[kind])
        return np.array(x), np.array(y)

    def t(y):
        return y.mean() / (y.std() / len(y) ** 0.5 + 1e-9) if len(y) > 1 else 0.0

    def search(x, y, depth, path):
        best = (t(y), path)
        if depth == 0:
            return best
        tried = []
        for j in range(len(keys)):
            values = np.unique(x[:, j])
            cuts = values if len(values) < 12 else np.unique(np.quantile(x[:, j], np.linspace(0.05, 0.95, 19)))
            for c in cuts:
                for side, mask in (("<=", x[:, j] <= c), (">", x[:, j] > c)):
                    if least <= mask.sum() < len(y):
                        tried.append((t(y[mask]), j, side, c, mask))
        tried.sort(key=lambda z: -z[0])
        for _, j, side, c, mask in tried[:4]:
            found = search(x[mask], y[mask], depth - 1, path + [(j, side, c)])
            if found[0] > best[0]:
                best = found
        return best

    print(f"\nrules with up to {depth} thresholds, found on {half} decisions and scored on the other {len(notes) - half}")
    for head, kinds in (("throw", ("hold", "cheap", "dear")), ("swap", ("stay", "switch to the better", "switch to the worse")),
                        ("replace", ("bring the better", "bring the worse"))):
        for kind in kinds:
            xa, ya = table(notes[:half], head, kind)
            xb, yb = table(notes[half:], head, kind)
            if len(ya) < 4 * least:
                continue
            _, path = search(xa, ya, depth, [])
            found = np.ones(len(xa), bool)
            mask = np.ones(len(xb), bool)
            for j, side, c in path:
                found &= xa[:, j] <= c if side == "<=" else xa[:, j] > c
                mask &= xb[:, j] <= c if side == "<=" else xb[:, j] > c
            held = yb[mask]
            when = " & ".join(f"{keys[j]} {side} {c:g}" for j, side, c in path) or "always"
            print(f"   {head}, always {kind}: {ya[found].mean():+.4f} where found, {held.mean():+.4f} ± "
                  f"{2 * held.std() / max(len(held), 1) ** 0.5:.4f} on unseen decisions (n {len(held)}); when {when}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--battles", type=int, default=200)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--seed", type=int, default=91)
    parser.add_argument("--save", default=str(ROOT / "runs" / "engine_habits.json"))
    parser.add_argument("--from-saved", action="store_true", help="only report on the saved decisions")
    parser.add_argument("--spots", action="store_true", help="also list the spots where the engine most often overrules")
    parser.add_argument("--rules", action="store_true", help="also score simple rules by the look-ahead's worths")
    args = parser.parse_args()
    if args.from_saved:
        notes = json.loads(Path(args.save).read_text())
    else:
        per = -(-args.battles // args.workers)
        with multiprocessing.get_context("spawn").Pool(args.workers) as pool:
            parts = pool.map(play, [(args.seed * 1000 + w, per) for w in range(args.workers)])
        notes = [n for part in parts for n in part]
        Path(args.save).write_text(json.dumps(notes) + "\n")
    print(f"{len(notes)} searched decisions")
    report(notes)
    if args.spots:
        candidates(notes)
    if args.rules:
        blanket(notes)
        thresholds(notes)


if __name__ == "__main__":
    main()
