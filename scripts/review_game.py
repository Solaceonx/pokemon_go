#!/usr/bin/env python3
"""After a game: each player's decisions judged, the costly ones marked, and a score per player (pogo/review.py).

    python3 scripts/review_game.py GAME.json [GAME.json ...] [--workers 3] [--limit 30]

GAME.json is a game as the website saves it (games/played/, brought in by scripts/import_played.py). Both players
are reviewed the same way: every throw, shield call, switch and replacement (and every knock-out left unthrown) is
played out each other way with the trained bot on both sides from there, and the drop in win chance from the best
choice is the decision's cost (blunder 25 points or more, mistake 15, inaccuracy 8). Each player's accuracy is 100
when no decision gave away win chance, on Lichess's curve (8 points lost -> 70, 15 -> 50, 25 -> 32), the mean of the
plain and harmonic means over the decisions looked at. With several games, each player's average follows.

The judge is the trained bot itself, so the score says how close a player came to what the bot's play-outs prefer,
with the full teams known; on the owner's exam of real positions, strong players agreed with its top pick no more
often than chance. One game is a few dozen decisions, so a single score is noisy; a set of games says more.
"""
from __future__ import annotations

import os

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import argparse  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
from multiprocessing import Pool  # noqa: E402
from pathlib import Path  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pogo import review  # noqa: E402

TURN = 0.5  # seconds per turn
WHO = ("person", "bot")
_w: dict = {}


def _init() -> None:
    from pogo.arena import low_priority
    from pogo.gamedata import GameData
    from pogo.learner import QNet
    low_priority()
    gd = GameData()
    _w.update(gd=gd, pool=gd.meta(50), net=QNet.load(str(ROOT / "runs" / "general-decide" / "q.npz")), games={})


def _game(path: str, side: int, limit: int) -> dict:
    key = (path, side)
    if key not in _w["games"]:
        _w["games"][key] = review.decisions(json.loads(Path(path).read_text()), _w["gd"], limit=limit, side=side)
    return _w["games"][key]


def _count(job) -> tuple:
    path, side, limit = job
    return path, side, len(_game(path, side, limit)["items"])


def _judge(job) -> tuple:
    path, side, limit, i = job
    game = _game(path, side, limit)
    item = game["items"][i]
    return path, side, i, review.judge(game, item, _w["net"], _w["pool"], seed=item[1])


def clock(turn: int) -> str:
    left = max(0, 240 - turn * TURN)
    return f"{int(left // 60)}:{int(left % 60):02d}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("games", nargs="+")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--limit", type=int, default=30, help="decisions looked at per player and game")
    args = parser.parse_args()
    paths = [str(Path(p)) for p in args.games]
    old = [p for p in paths if not {"teams", "my_choices", "log", "seed"} <= json.loads(Path(p).read_text()).keys()]
    if old:
        print(f"{len(old)} games saved before the website kept the full record cannot be replayed: {', '.join(Path(p).name for p in old)}")
        paths = [p for p in paths if p not in old]
    with Pool(args.workers, _init) as runner:
        counts = {(p, s): n for p, s, n in runner.map(_count, [(p, s, args.limit) for p in paths for s in (0, 1)])}
        jobs = [(p, s, args.limit, i) for (p, s), n in counts.items() for i in range(n)]
        judged: dict = {}
        for p, s, i, out in runner.imap_unordered(_judge, jobs):
            judged.setdefault((p, s), {})[i] = out
    totals: dict = {0: [], 1: []}
    for p in paths:
        record = json.loads(Path(p).read_text())
        result = {"win": "won", "loss": "lost", "draw": "drew"}.get(record["result"], record["result"])
        print(f"\n{Path(p).name}: the person {result} against the {record.get('bot', 'bot')}")
        for s in (0, 1):
            if not counts[(p, s)]:
                print(f"  {WHO[s]}: the game does not replay exactly, so it cannot be reviewed")
                continue
            rows = [judged[(p, s)][i] for i in sorted(judged[(p, s)])]
            score = review.accuracy(rows)
            totals[s].append(score)
            marks = ", ".join(f"{score[name]} {name}{'s' if score[name] > 1 else ''}" for _, name in review.LABELS if score[name])
            print(f"  {WHO[s]}: accuracy {score['accuracy']:.0f} over {score['decisions']} decisions "
                  f"({marks or 'nothing marked'}; the marked costs add up to {100 * score['given_away']:.0f} points of win chance)")
            for r in rows:
                if r["label"]:
                    print(f"    {review.MARKS[r['label']]:2s} {clock(r['turn'])} {r['mon']} v {r['foe']}: {r['did']} "
                          f"(wins {100 * r['mine']:.0f}%); to {r['better']} wins {100 * r['best']:.0f}%")
    if len(paths) > 1:
        print()
        for s in (0, 1):
            scored = [t for t in totals[s] if t["accuracy"] is not None]
            if scored:
                print(f"{WHO[s]}: mean accuracy {sum(t['accuracy'] for t in scored) / len(scored):.1f} over {len(scored)} games, "
                      f"marked costs {100 * sum(t['given_away'] for t in scored) / len(scored):.0f} points per game")


if __name__ == "__main__":
    main()
