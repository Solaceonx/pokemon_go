#!/usr/bin/env python3
"""The bot against real players' decisions, from tracked battles.

    python3 scripts/real_decisions.py games/<tracked game> [more ...] [--games 100] [--bot learner|planner]

For every decision the player on our side of a recording made (whether to throw a charged move or keep
fast-moving, which move, whether to shield, whether to switch), the position just before is rebuilt from the
tracker's state and the bot is asked what it would do. Where the two differ, the position is played on
--games times each way with the same dice: first the player's choice, then the bot's, both continued by the
bot against the varied crowd, with what cannot be known (their unseen Pokémon, their exact energy) drawn as
scripts/advise.py does. The difference in win share says which choice was likely better, as far as the
simulator and its opponents can tell.

Decisions counted:
- throw: a look in which the player could afford a charged move (by the tracker and, when not thrown, by the
  buttons too): thrown (which one) or held;
- shield: they threw at the player while the player had a shield: shielded or not;
- switch: the first look of each new matchup with the player's switch ready, and every switch the player made.
"""
from __future__ import annotations

import argparse
import gzip
import json
import random
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from advise import rebuild  # noqa: E402
from pogo.agents import Planner, varied  # noqa: E402
from pogo.battle import CHARGED, DRAW, FAST, SWITCH  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.learner import Learner, QNet  # noqa: E402

MODEL = ROOT / "runs" / "general-decide" / "q.npz"


def lines(folder: Path, name: str) -> list:
    path = folder / name
    if not path.exists():
        path = folder / (name + ".gz")
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


class Forced:
    """A player whose first action, or first shield answer, is fixed; the rest is left to `inner`."""

    def __init__(self, inner, action=None, shield=None):
        self.inner, self.action, self.answer = inner, action, shield
        for hook in ("saw_throw", "saw_shield"):
            if hasattr(inner, hook):
                setattr(self, hook, getattr(inner, hook))

    def act(self, view):
        if self.action is not None:
            action, self.action = self.action, None
            if action in view.legal():
                return action
        return self.inner.act(view)

    def shield(self, view, energy, *move):
        if self.answer is not None:
            answer, self.answer = self.answer, None
            return answer
        return self.inner.shield(view, energy)

    def replace(self, view):
        return self.inner.replace(view)


def decisions(folder: Path) -> list[dict]:
    """The player's decisions in one tracked game, each with the state just before it."""
    states, looks = lines(folder, "states.jsonl"), lines(folder, "observations.jsonl")
    if len(states) != len(looks):
        raise ValueError(f"{folder.name}: {len(looks)} looks but {len(states)} states (rejected looks?)")
    events = lines(folder, "events.jsonl")
    switches = {round(e["t"], 2): e["to"] for e in events if e["event"] == "my_switch"}
    foe_throws = {round(e["t"], 2): e for e in events if e["event"] == "foe_charged"}
    out, judged = [], set()
    for k in range(1, len(looks)):
        prev, look, now = states[k - 1], looks[k], states[k]
        me, foe = prev["me"], prev["opponent"]
        if foe["active"] is None or me["active"] is None:
            continue
        mine, theirs = me["pokemon"][me["active"]], foe["pokemon"][foe["active"]]
        if mine["fainted"] or theirs["fainted"] or now["me"]["left"] < me["left"]:
            continue
        same = now["me"]["active"] == me["active"] and now["opponent"]["active"] == foe["active"]
        where = {"game": folder.name, "t": look["t"], "state": prev, "mine": mine["species"], "theirs": theirs["species"]}
        if look.get("foe_charged"):
            if me["shields"] > 0 and same:
                thrown = foe_throws.get(round(look["t"], 2), {})
                move = thrown.get("move")
                low, high = thrown.get("energy_before") or theirs["energy_range"]
                out.append({**where, "kind": "shield", "human": now["me"]["shields"] < me["shields"],
                            "move": move, "energy": (low + high) // 2})
            continue
        t = round(look["t"], 2)
        if t in switches:
            slot = next((j for j, p in enumerate(me["pokemon"]) if p["species"] == switches[t]), None)
            if slot is not None and me["switch_ready_in"] == 0:
                out.append({**where, "kind": "switch", "human": SWITCH[slot]})
            continue
        if me["switch_ready_in"] == 0 and (me["active"], foe["active"]) not in judged and same:
            judged.add((me["active"], foe["active"]))
            if any(not p["fainted"] for j, p in enumerate(me["pokemon"]) if j != me["active"]):
                out.append({**where, "kind": "switch", "human": FAST})  # stayed in
        costs = [m["energy"] for m in mine["charged_moves"]]
        if not same or not costs or mine["energy"] < min(costs):
            continue
        if look.get("my_charged") is not None:
            names = [m["name"] for m in mine["charged_moves"]]
            thrown = look["my_charged"]
            k_thrown = thrown if isinstance(thrown, int) else names.index(thrown) if thrown in names else None
            if k_thrown is not None:
                out.append({**where, "kind": "throw", "human": CHARGED[k_thrown]})
        elif look.get("my_energy") is not None and look["my_energy"] >= min(costs):
            out.append({**where, "kind": "throw", "human": FAST})
    return out


def bot_choice(gd, d: dict, make_bot, pool, rng) -> int | bool:
    bot = make_bot(rng.getrandbits(32))
    battle = rebuild(gd, d["state"], pool, rng, bot, varied(rng, pool))
    view = battle.views[0]
    if d["kind"] == "shield":
        return bool(bot.shield(view, d["energy"]))
    return bot.act(view)


def play_on(gd, d: dict, first, make_bot, pool, seed: int) -> float:
    """Win share of one continuation from this decision with our first choice fixed to `first`."""
    rng = random.Random(seed)
    bot = make_bot(rng.getrandbits(32))
    foe_pilot = varied(rng, pool)
    if d["kind"] == "shield":
        ours = Forced(bot, shield=first)
        battle = rebuild(gd, d["state"], pool, rng, ours, foe_pilot)
        foe = battle.sides[1].mon
        names = [m.id for m in foe.build.charged]
        k = names.index(d["move"]) if d["move"] in names else 0
        foe.energy = max(foe.energy, foe.build.charged[k].energy)
        battle.sides[1].busy = 0
        battle.agents[1] = Forced(foe_pilot, action=CHARGED[k])
    else:
        battle = rebuild(gd, d["state"], pool, rng, Forced(bot, action=first), foe_pilot)
    winner = battle.run()
    return 1.0 if winner == 0 else 0.5 if winner == DRAW else 0.0


def describe(d: dict, choice) -> str:
    if d["kind"] == "shield":
        return "shield" if choice else "no shield"
    me = d["state"]["me"]
    p = me["pokemon"][me["active"]]
    if choice == FAST:
        return "hold" if d["kind"] == "throw" else "stay"
    if choice in CHARGED:
        return ("throw " + p["charged_moves"][choice - CHARGED[0]]["name"]) if d["kind"] == "throw" else "stay"
    return "switch to " + me["pokemon"][choice - SWITCH[0]]["name"]


def same_kind(d: dict, choice) -> object:
    """Choices compared at the level of the decision: for a switch decision, staying and attacking are one."""
    if d["kind"] == "switch":
        return choice if choice in SWITCH else "stay"
    return choice


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folders", nargs="+")
    parser.add_argument("--games", type=int, default=100, help="continuations each way at a disagreement")
    parser.add_argument("--bot", choices=("learner", "planner"), default="learner")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--save", help="write every decision and its scores to this JSON file")
    args = parser.parse_args()
    if all(f.endswith(".json") for f in args.folders):  # results saved earlier with --save: just sum them up
        summary([r for f in args.folders for r in json.loads(Path(f).read_text())])
        return
    gd = GameData()
    pool = gd.meta(50)
    if args.bot == "learner":
        net = QNet.load(str(MODEL))
        make_bot = lambda seed: Learner(q=net, margin=0.02, seed=seed)  # noqa: E731
    else:
        make_bot = lambda seed: Planner(seed=seed)  # noqa: E731
    rng = random.Random(args.seed)
    rows = []
    for folder in map(Path, args.folders):
        for d in decisions(folder):
            bot = bot_choice(gd, d, make_bot, pool, rng)
            agree = same_kind(d, bot) == same_kind(d, d["human"])
            row = {k: d[k] for k in ("game", "t", "kind", "mine", "theirs")}
            row.update(human=describe(d, d["human"]), bot=describe(d, bot), agree=agree)
            if not agree:
                seeds = [rng.getrandbits(32) for _ in range(args.games)]
                theirs = [play_on(gd, d, d["human"], make_bot, pool, s) for s in seeds]
                ours = [play_on(gd, d, bot, make_bot, pool, s) for s in seeds]
                row.update(human_wins=round(statistics.mean(theirs), 3), bot_wins=round(statistics.mean(ours), 3))
            rows.append(row)
            print(f"{row['game'][-24:]:>24} {row['t']:6.1f}s {row['kind']:6} {row['mine']:>14} v {row['theirs']:<14} "
                  f"player: {row['human']:<24} bot: {row['bot']:<24}"
                  + ("" if agree else f" win share {row['human_wins']:.2f} player, {row['bot_wins']:.2f} bot"), flush=True)
    if args.save:
        Path(args.save).write_text(json.dumps(rows, indent=1) + "\n")
    print()
    summary(rows)


def summary(rows: list[dict]) -> None:
    counts = defaultdict(Counter)
    for r in rows:
        counts[r["kind"]]["decisions"] += 1
        counts[r["kind"]]["agree"] += r["agree"]
    for kind, c in counts.items():
        differ = [r for r in rows if r["kind"] == kind and not r["agree"]]
        line = f"{kind}: {c['decisions']} decisions, bot agrees with the player on {100 * c['agree'] / max(c['decisions'], 1):.0f}%"
        if differ:
            gaps = [r["bot_wins"] - r["human_wins"] for r in differ]
            spread = statistics.stdev(gaps) if len(gaps) > 1 else 0.0
            line += (f"; where they differ ({len(differ)}), the bot's choice wins {100 * statistics.mean(gaps):+.1f} ± "
                     f"{100 * 1.96 * spread / len(gaps) ** 0.5:.1f} points more often; bot better in "
                     f"{sum(g > 0.02 for g in gaps)}, player better in {sum(g < -0.02 for g in gaps)}")
        print(line)


if __name__ == "__main__":
    main()
