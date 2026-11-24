#!/usr/bin/env python3
"""How the creators and their opponents throw and shield, and how predictable they are (engine lab, 2026-11-24).

    python -X utf8 scripts/lab/creator_habits.py [--all] [--save runs/lab-creators/habits.json]

Reads every charged move in task 46's creator records (games/creators/<channel>/<game>/), both sides: the creator's
throws at their opponent and the opponent's throws at the creator. For each throw: the thrower's energy (the
tracker's ledger, not read from the screen), both moves' costs, the defender's shields, health, Pokémon left, how
much of the defender's health the move takes (our damage formula on the tracker's builds) and whether it shielded.
By default only the 29 records that pass every check; --all reads the 84.

Prints shield rates by situation, the bait share (cheaper move while the dearer one was affordable and the defender
had a shield), spare energy at throws, and how predictable the shield and bait calls are: the entropy of the call
given a coarse description of the situation, and how often the majority call of the same situation in the other
records (leave one record out) copies it. A rule-follower scores near 100% on situations it repeats; a player who
mixes scores near the larger of the two shares. What the description leaves out (their read of the energy, the
teams, the score) also looks like mixing, so these are upper bounds on how random they are.
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from advise import mon_from  # noqa: E402
from pogo.battle import damage  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402

CREATORS = ROOT / "games" / "creators"


def lines(folder: Path, name: str) -> list:
    path = folder / name
    if not path.exists():
        path = folder / (name + ".gz")
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def records(passed_only: bool = True) -> list[Path]:
    out = []
    for folder in sorted(CREATORS.glob("*/*/")):
        verdict = folder / "verdict.json"
        if not verdict.exists() or not (folder / "states.jsonl.gz").exists():
            continue
        if passed_only and json.loads(verdict.read_text(encoding="utf-8"))["verdict"] != "pass":
            continue
        out.append(folder)
    return out


def hit_of(gd, thrower: dict, move_id: str, target: dict) -> tuple[int | None, int]:
    """Damage of `move_id` from `thrower` into `target` (tracker records), and the target's health before it."""
    try:
        user, victim = mon_from(gd, thrower), mon_from(gd, target)
        move = gd.moves[move_id]
    except Exception:  # noqa: BLE001 - a move or form the game data does not know
        return None, target["hp"]
    return damage(user, move, victim), target["hp"]


def throws(gd, folder: Path) -> list[dict]:
    """Every charged move in one record, from either side, with the situation just before it."""
    states, looks = lines(folder, "states.jsonl"), lines(folder, "observations.jsonl")
    if len(states) != len(looks):
        return []
    events = lines(folder, "events.jsonl")
    foe_throws = {round(e["t"], 2): e for e in events if e["event"] == "foe_charged"}
    out = []
    faced = Counter()  # throws faced so far by each side
    for k in range(1, len(looks)):
        prev, look, now = states[k - 1], looks[k], states[k]
        for side, flag in (("opponent", "foe_charged"), ("creator", "my_charged")):
            if not look.get(flag) and look.get(flag) != 0:
                continue
            thr_key, def_key = ("opponent", "me") if side == "opponent" else ("me", "opponent")
            thr, dfn = prev[thr_key], prev[def_key]
            if thr["active"] is None or dfn["active"] is None:
                continue
            tp, dp = thr["pokemon"][thr["active"]], dfn["pokemon"][dfn["active"]]
            costs = {m["id"]: m["energy"] for m in tp["charged_moves"]}
            if side == "opponent":
                ev = foe_throws.get(round(look["t"], 2), {})
                move = ev.get("move")
                low, high = ev.get("energy_before") or tp.get("energy_range") or (tp["energy"], tp["energy"])
                energy = (low + high) / 2
            else:
                thrown = look["my_charged"]
                names = [m["name"] for m in tp["charged_moves"]]
                if isinstance(thrown, int):
                    move = tp["charged_moves"][thrown]["id"] if thrown < len(names) else None
                else:
                    move = tp["charged_moves"][names.index(thrown)]["id"] if thrown in names else None
                energy = tp["energy"]
            if move is None:
                continue
            cost = costs.get(move)
            if cost is None and move in gd.moves:
                cost = gd.moves[move].energy
            others = [c for m, c in costs.items() if m != move]
            dear = max([cost or 0, *others])
            cheap = min([cost or 0, *others])
            dmg, hp = hit_of(gd, tp, move, dp)
            alt = [hit_of(gd, tp, m, dp)[0] for m in costs if m != move]
            alt = max([a for a in alt if a is not None], default=None)
            shields_before = dfn["shields"]
            shielded = now[def_key]["shields"] < shields_before
            faced[def_key] += 1
            out.append({
                "game": folder.name, "channel": folder.parent.name, "t": look["t"], "side": side,
                "thrower": tp["species"], "defender": dp["species"], "move": move, "cost": cost,
                "energy": energy, "spare": None if cost is None else energy - cost,
                "two_costs": len(set([cost, *others])) > 1 and bool(others),
                "both_ready": bool(others) and cost is not None and energy >= dear and cheap < dear,
                "cheaper": cost is not None and bool(others) and cost < max(others),
                "def_shields": shields_before, "thr_shields": thr["shields"], "shielded": shielded,
                "def_hp_share": hp / max(1, dp["hp_max"]), "hit": None if dmg is None else dmg / max(1, hp),
                "ko": None if dmg is None else dmg >= hp,
                "alt_hit": None if alt is None else alt / max(1, hp), "def_left": dfn["left"], "thr_left": thr["left"],
                "faced": faced[def_key],
            })
    return out


def hit_bucket(r: dict) -> str:
    if r["hit"] is None:
        return "?"
    if r["ko"]:
        return "ko"
    return "small" if r["hit"] < 0.3 else "mid" if r["hit"] < 0.6 else "big"


def shield_bucket(r: dict) -> tuple:
    return (r["def_shields"], hit_bucket(r), min(r["def_left"], 2), r["thr_shields"] > 0)


def bait_bucket(r: dict) -> tuple:
    return (r["def_shields"], r["thr_shields"] > 0, min(r["def_left"], 2), r["def_hp_share"] > 0.6)


def entropy(p: float) -> float:
    return 0.0 if p <= 0 or p >= 1 else -(p * math.log2(p) + (1 - p) * math.log2(1 - p))


def predictability(rows: list[dict], bucket, answer) -> dict:
    """Base rate, entropy of the call given the bucket (plug-in, buckets of 5+), and leave-one-record-out copying by
    the majority call of the same bucket in the other records (ties and unseen buckets: the overall majority)."""
    n = len(rows)
    if not n:
        return {"n": 0}
    yes = sum(answer(r) for r in rows)
    base = yes / n
    groups = defaultdict(list)
    for r in rows:
        groups[bucket(r)].append(r)
    h, covered = 0.0, 0
    for g in groups.values():
        if len(g) >= 5:
            h += len(g) * entropy(sum(answer(r) for r in g) / len(g))
            covered += len(g)
    copied = 0
    for r in rows:
        others = [o for o in groups[bucket(r)] if o["game"] != r["game"]]
        k = sum(answer(o) for o in others)
        guess = (k * 2 > len(others)) if others and k * 2 != len(others) else base >= 0.5
        copied += guess == answer(r)
    mixed = [g for g in groups.values() if len(g) >= 4]
    return {"n": n, "rate": round(base, 3), "entropy_bits": round(entropy(base), 3),
            "entropy_given_bucket_bits": round(h / covered, 3) if covered else None, "covered": covered,
            "copy_by_bucket_loro": round(copied / n, 3), "copy_never": round(max(base, 1 - base), 3),
            "buckets_4plus": len(mixed),
            "buckets_4plus_mixed_20_80": sum(0.2 <= sum(answer(r) for r in g) / len(g) <= 0.8 for g in mixed)}


def repeats(rows: list[dict], answer) -> dict:
    """Same defender, thrower, move, defender shields and Pokémon left, in different records: same call?"""
    groups = defaultdict(list)
    for r in rows:
        groups[(r["side"], r["defender"], r["thrower"], r["move"], r["def_shields"], min(r["def_left"], 2))].append(r)
    pairs = same = 0
    multi = 0
    for g in groups.values():
        if len({r["game"] for r in g}) < 2:
            continue
        multi += 1
        for i in range(len(g)):
            for j in range(i + 1, len(g)):
                if g[i]["game"] != g[j]["game"]:
                    pairs += 1
                    same += answer(g[i]) == answer(g[j])
    return {"situations_repeated": multi, "pairs": pairs, "same_call": round(same / pairs, 3) if pairs else None}


def pct(k: int, n: int) -> str:
    if not n:
        return "-"
    p = k / n
    return f"{100 * p:.0f}% ± {100 * 1.96 * math.sqrt(p * (1 - p) / n):.0f} ({k}/{n})"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--all", action="store_true", help="all 84 records, not only the 29 that pass every check")
    parser.add_argument("--save", help="write every throw to this JSON file")
    args = parser.parse_args()
    gd = GameData()
    rows = [r for f in records(not args.all) for r in throws(gd, f)]
    print(f"{len(rows)} charged moves in {len({r['game'] for r in rows})} records")
    who = {"creators": [r for r in rows if r["side"] == "creator"],
           "their opponents": [r for r in rows if r["side"] == "opponent"]}
    # shields: the defender is the other side
    print("\nShield calls (the defender had a shield):")
    for name, side in (("creators", "opponent"), ("their opponents", "creator")):
        prompts = [r for r in rows if r["side"] == side and r["def_shields"] > 0]
        not_last = [r for r in prompts if r["def_left"] > 1]
        print(f"  {name}: shielded {pct(sum(r['shielded'] for r in prompts), len(prompts))}; "
              f"not their last Pokémon {pct(sum(r['shielded'] for r in not_last), len(not_last))}")
        for label, cond in (("with 2 shields", lambda r: r["def_shields"] == 2),
                            ("with 1 shield", lambda r: r["def_shields"] == 1),
                            ("first charged move faced", lambda r: r["faced"] == 1),
                            ("hit < 30% of health", lambda r: hit_bucket(r) == "small"),
                            ("hit 30-60%", lambda r: hit_bucket(r) == "mid"),
                            ("hit 60%+, no knock-out", lambda r: hit_bucket(r) == "big"),
                            ("would knock out", lambda r: hit_bucket(r) == "ko"),
                            ("the cheaper of two moves", lambda r: r["cheaper"]),
                            ("a bait (cheaper, dearer affordable)", lambda r: r["both_ready"] and r["cheaper"]),
                            ("thrower has no shields", lambda r: r["thr_shields"] == 0)):
            sub = [r for r in not_last if cond(r)]
            print(f"    {label:38} {pct(sum(r['shielded'] for r in sub), len(sub))}")
        pred = predictability(not_last, shield_bucket, lambda r: r["shielded"])
        rep = repeats(not_last, lambda r: r["shielded"])
        print(f"    predictability: {pred}")
        print(f"    repeated situations: {rep}")
    print("\nThrows (by the thrower):")
    for name, sub in who.items():
        spare = sorted(r["spare"] for r in sub if r["spare"] is not None)
        if spare:
            q = lambda p: spare[min(len(spare) - 1, int(p * len(spare)))]  # noqa: E731
            print(f"  {name}: {len(sub)} throws; spare energy at the throw: median {q(0.5):.0f}, quartiles "
                  f"{q(0.25):.0f} to {q(0.75):.0f}; 20+ spare {pct(sum(s >= 20 for s in spare), len(spare))}")
        chances = [r for r in sub if r["both_ready"]]  # two costs, energy for the dearer: a free choice
        bait = [r for r in chances if r["def_shields"] > 0]
        k = sum(r["cheaper"] for r in bait)
        print(f"    both moves affordable, defender has a shield: cheaper move {pct(k, len(bait))}")
        no_sh = [r for r in chances if r["def_shields"] == 0]
        print(f"    both moves affordable, defender has no shield: cheaper move "
              f"{pct(sum(r['cheaper'] for r in no_sh), len(no_sh))}")
        real = [r for r in bait if r["alt_hit"] is not None and r["hit"] is not None]
        def hits(r):  # (cheaper move's share, dearer move's share)
            return (r["hit"], r["alt_hit"]) if r["cheaper"] else (r["alt_hit"], r["hit"])
        real = [r for r in real if hits(r)[1] >= 1.3 * hits(r)[0] and hits(r)[0] < 1]  # the dearer is the threat
        print(f"    of those where the dearer move hits 1.3x+ harder and the cheaper does not knock out: cheaper "
              f"(a real bait) {pct(sum(r['cheaper'] for r in real), len(real))}")
        print(f"    bait predictability: {predictability(bait, bait_bucket, lambda r: r['cheaper'])}")
    # switches: right after one's own charged move (its animation is about 10 s of clock), and early lead switches
    for name, mine in (("creators", True), ("their opponents", False)):
        total = after = lead = games = 0
        for folder in records(not args.all):
            events = lines(folder, "events.jsonl")
            games += 1
            throws_at = [e["t"] for e in events if e["event"] == ("my_charged" if mine else "foe_charged")]
            switches = [e["t"] for e in events if e["event"] == ("my_switch" if mine else "foe_switch") and e["t"] > 0]
            lead += any(t <= 12 for t in switches)
            for t in switches:
                total += 1
                after += any(0 <= t - u <= 12 for u in throws_at)
        print(f"  switches by {name}: {total} in {games} records; lead switched in the first 12 s in "
              f"{pct(lead, games)} of records; within 12 s of clock (about 2 s of play) after their own charged move: "
              f"{pct(after, total)}")
    if args.save:
        Path(args.save).parent.mkdir(parents=True, exist_ok=True)
        with open(args.save, "w", encoding="utf-8", newline="\n") as f:
            json.dump(rows, f, indent=0)
            f.write("\n")


if __name__ == "__main__":
    main()
