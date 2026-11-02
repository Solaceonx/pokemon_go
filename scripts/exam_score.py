#!/usr/bin/env python3
"""Score the exam (docs/benchmarking.md): each version of the bot and the play-out judge against one person's answers.

    python3 scripts/exam_score.py runs/exam/owner-answers.json [--tag exam-1] [--detail]

A file holds {position id: answer} or, as the website's store keeps it, a record with `answers`. The positions were chosen
where versions disagree, so these rates are for comparing versions and say nothing of how often a version is right in play.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSIONS = ("rulebook", "trained", "engine", "matching")


def share(hits: list) -> str:
    if not hits:
        return "-"
    n, p = len(hits), sum(hits) / len(hits)
    return f"{sum(hits)}/{n} ({100 * p:.0f}% ± {196 * math.sqrt(max(p * (1 - p), 0.25 / n) / n):.0f})"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("answers")
    parser.add_argument("--tag", default="exam-1")
    parser.add_argument("--detail", action="store_true")
    args = parser.parse_args()
    saved = json.loads(Path(args.answers).read_text())
    answers = saved.get("answers", saved)
    key = json.loads((ROOT / "runs" / "exam" / f"{args.tag}-key.json").read_text())
    positions = {p["id"]: p for p in json.loads((ROOT / "data" / "exam" / f"{args.tag}.json").read_text())}
    first = [k for k in key if k["group"] != "repeat" and answers.get(k["id"], {}).get("choice")]
    print(f"{len(first)} positions answered, {sum(answers[k['id']]['confidence'] == 'sure' for k in first)} of them sure")

    print("\nConsistency: the same position again, later, with the options reordered")
    for k in key:
        if k["group"] == "repeat" and k["id"] in answers and k["repeat_of"] in answers:
            a, b = answers[k["repeat_of"]], answers[k["id"]]
            print(f"  {k['repeat_of']} / {k['id']}: {a['choice']} ({a['confidence']}), {b['choice']} ({b['confidence']}): {'same' if a['choice'] == b['choice'] else 'DIFFERENT'}")

    def row(label, items):
        print(f"  {label:24s}" + "".join(f"{share([k['picks'][v] == answers[k['id']]['choice'] for k in items]):>18s}" for v in VERSIONS))

    print("\nHow often each version plays the person's answer\n  " + " " * 24 + "".join(f"{v:>18s}" for v in VERSIONS))
    row("all", first)
    row("sure only", [k for k in first if answers[k["id"]]["confidence"] == "sure"])
    for kind in ("throw", "switch", "shield", "replace"):
        row(kind, [k for k in first if k["kind"] == kind])
    for group in ("disagree", "flagged", "control"):
        row(group, [k for k in first if k["group"] == group])

    def side(a, b, items):
        split = [k for k in items if k["picks"][a] != k["picks"][b]]
        wa = sum(k["picks"][a] == answers[k["id"]]["choice"] for k in split)
        wb = sum(k["picks"][b] == answers[k["id"]]["choice"] for k in split)
        print(f"  {a} against {b}: differ on {len(split)}; the person sides with {a} {wa}, {b} {wb}, neither {len(split) - wa - wb}")

    print("\nWhere two versions differ")
    side("engine", "matching", first)
    side("engine", "trained", first)
    side("trained", "rulebook", first)

    print("\nThe play-out judge against the person")
    best = [k for k in first if max(k["judge"], key=k["judge"].get) == answers[k["id"]]["choice"]]
    print(f"  the judge's top choice is the person's: {share([k in best for k in first])}")
    close = [k for k in first if k["judge"].get(answers[k["id"]]["choice"], 0) >= max(k["judge"].values()) - 0.1]
    print(f"  the person's choice is within 10 points of the judge's top: {share([k in close for k in first])}")
    far = [k for k in first if k["judge"].get(answers[k["id"]]["choice"], 0) <= max(k["judge"].values()) - 0.25]
    print(f"  the judge calls the person's choice a blunder (25 points or more): {len(far)}, of them sure: {sum(answers[k['id']]['confidence'] == 'sure' for k in far)}")
    for label, items in (("flagged as a costly mistake of the bot", [k for k in first if k["group"] == "flagged"]),):
        print(f"  {label}: the person sides with the judge's top on {share([max(k['judge'], key=k['judge'].get) == answers[k['id']]['choice'] for k in items])}; with what was played on {share([k['played'] == answers[k['id']]['choice'] for k in items])}")
    mine = [k for k in first if k["side"] == 0]
    print(f"\nThe person's own games, in calm against what was played at speed: {share([k['played'] == answers[k['id']]['choice'] for k in mine])}")
    print(f"The Hydro Cannon positions: " + "; ".join(f"{k['id']}: {answers[k['id']]['choice']}, played {k['played']}, {k['picks']}" for k in first if k["hydro"]))

    if args.detail:
        print("\nSure answers no version plays, or the judge calls a blunder")
        for k in first:
            a = answers[k["id"]]
            if a["confidence"] != "sure":
                continue
            none = all(k["picks"][v] != a["choice"] for v in VERSIONS)
            value = k["judge"].get(a["choice"], 0)
            if none or value <= max(k["judge"].values()) - 0.25:
                p = positions[k["id"]]
                you, foe = p["you"]["active"], p["foe"]["active"]
                print(f"  {k['id']} {k['group']} {k['kind']}: {you['name']} {you['hp']}/{you['hp_max']} {you['energy']}e v {foe['name']} {foe['hp']}/{foe['hp_max']} {foe['energy']}e, shields {p['you']['shields']}-{p['foe']['shields']}: "
                      f"answer {a['choice']}, played {k['played']}, versions {sorted(set(k['picks'].values()))}, judge { {x: round(y, 2) for x, y in k['judge'].items()} }" + (f"; note: {a['note']}" if a["note"] else ""))


if __name__ == "__main__":
    main()
