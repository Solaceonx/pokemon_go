#!/usr/bin/env python3
"""One minigame pattern for a type, learnt on the icon sightings of every move of it (task 40). Moves of one type
share a pattern (2026-11-08: Foul Play's covered 96% of Dark Pulse's held-out icons, Dark Pulse's own 93%; Mud
Bomb's covered Bulldoze's 73%, Bulldoze's own 72%), so their minigames are pooled.

    python3 scripts/live/learn_type_pattern.py TYPE SIGHTINGS.json [SIGHTINGS.json ...] [--out FILE]

Each SIGHTINGS file is [(minigame, seconds after Get Ready!, x, y, r)] (scratch icon_map.py). Half the minigames are
held out to score the pattern (the share of their sightings the stroke's path passes over, against the sweep alone);
the pattern written is learnt on all of them.
"""
import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import learn_choreography as lc  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("type")
ap.add_argument("sightings", nargs="+")
ap.add_argument("--out")
ap.add_argument("--share", type=float, default=0.35)
a = ap.parse_args()
s, moves = [], []
for f in a.sightings:
    rows = [tuple(x) for x in json.load(open(f))]
    s += rows
    moves.append(Path(f).stem.replace("icons_", ""))
games = sorted({x[0] for x in s})
random.Random(0).shuffle(games)
held = set(games[:len(games) // 2])
train, test = [x for x in s if x[0] not in held], [x for x in s if x[0] in held]
pattern = lc.learn(train, a.share)
print(f"{a.type} ({', '.join(moves)}): {len(games)} minigames; on {len(held)} held out, sightings passed over: "
      f"sweep alone {lc.coverage(lc.simulate([], a.type), test):.0%}, learnt path {lc.coverage(lc.simulate(pattern, a.type), test):.0%}")
full = lc.learn(s, a.share)
if a.out:
    Path(a.out).write_text(json.dumps({"type": a.type, "moves": moves, "minigames": len(games), "icons": full},
                                      indent=1), encoding="utf-8")
    print("written", a.out, len(full), "icons")
