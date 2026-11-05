#!/usr/bin/env python3
"""The owner's website games for task 42 (opponents fitted to people), with no names: runs/people/owner_games.jsonl.

    python3 scripts/export_people.py [--tag exam-1]

Run on the owner's Mac, where games/played/ is. One line per game: the teams, the dice, both sides' decisions (the
owner's `my_choices`, the bot's `log`) and the result, enough to replay every position exactly as
scripts/exam_positions.py does. Notes, reviews, timings, player names and file-name suffixes are left out; only the
owner's games are kept (no player name, or the owner's own). `held_out` lists the decisions the exam asks about
(side, turn, kind): never fit on them, since the exam judges the fit and the owner answered many of them as played.
Each game is replayed before it is written; one that does not replay exactly is left out and reported.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
from pogo.battle import Battle  # noqa: E402
from pogo.review import Logged, Replay  # noqa: E402

OWNER = ("", "solaceonx")
KEEP = ("bot", "seed", "teams", "my_choices", "log", "result", "turns")


def replays(record: dict, gd) -> bool:
    teams = [[gd.build(sid, mv, level=level, ivs=tuple(ivs)) for sid, mv, level, ivs in t] for t in record["teams"]]
    battle = Battle(teams[0], teams[1], Replay(record["my_choices"]), Logged(record["log"]), seed=record["seed"], record=True)
    battle.run()
    return [list(e) for e in battle.log] == [list(e) for e in record["log"]]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tag", default="exam-1")
    args = parser.parse_args()
    from pogo.gamedata import GameData
    gd = GameData()
    key = json.loads((ROOT / "runs" / "exam" / f"{args.tag}-key.json").read_text())
    held: dict = {}
    for k in key:
        held.setdefault(k["game"], []).append([k["side"], k["turn"], k["kind"]])
    out, skipped = [], []
    for path in sorted(glob.glob(str(ROOT / "games" / "played" / "*.json"))):
        try:
            record = json.loads(Path(path).read_text())
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(record, dict) or record.get("source") != "website" or "my_choices" not in record:
            continue
        if record.get("player", "").lower() not in OWNER:
            continue
        stem = Path(path).stem
        game = stem[:19]  # the date and time; the suffix can be a name
        if not replays(record, gd):
            skipped.append(game)
            continue
        out.append({"game": game, **{k: record[k] for k in KEEP if k in record},
                    "held_out": sorted(held.get(stem, []))})
    folder = ROOT / "runs" / "people"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "owner_games.jsonl").write_text("".join(json.dumps(g, separators=(",", ":")) + "\n" for g in out))
    decisions = sum(len(g["my_choices"]) for g in out)
    print(f"{len(out)} games, {decisions} of the owner's decisions, "
          f"{sum(len(g['held_out']) for g in out)} exam decisions held out; written to runs/people/owner_games.jsonl")
    if skipped:
        print(f"left out, not replaying exactly: {skipped}")


if __name__ == "__main__":
    main()
