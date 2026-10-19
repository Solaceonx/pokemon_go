#!/usr/bin/env python3
"""The trained bot on top of one rulebook against the bot on top of another (task 30).

    python3 scripts/bot_on_rules.py "<rule settings>" [pairings] [crowd] [workers] [seed] ["<other rule settings>"]

Rule settings are in rule_trial.py's form ("switch_margin=0.06,hold_cost=0.9,..."); the other side uses the standard
rules unless a second settings string is given. Prints head to head (each pair of teams both ways, margin over chunks of
50 pairings) and both bots against the crowd on the same battles, with the paired difference.
"""
import math
import multiprocessing
import random
import sys

from pathlib import Path

ROOT = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, ROOT)

from pogo.agents import varied  # noqa: E402
from pogo.arena import compare, field_results, low_priority  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.learner import Learner, QNet  # noqa: E402
from pogo.teamlist import drawer  # noqa: E402

_s = {}


def setup(settings, other=None):
    low_priority()
    gd = GameData()
    pool = gd.meta(50)
    _s.update(pool=pool, draw=drawer(gd, pool), q=QNet.load(f"{ROOT}/runs/general-decide/q.npz"), settings=settings, other=other or {})


def bot(evolved, seed):
    extra = _s["settings"] if evolved else _s["other"]
    return Learner(q=_s["q"], margin=0.02, seed=seed, **extra)


def h2h(job):
    seed, n = job
    r = random.Random(seed)
    res = compare(lambda: bot(True, r.getrandbits(30)), lambda: bot(False, r.getrandbits(30)), _s["pool"], pairings=n, seed=seed)
    return res.score, n


def crowd(job):
    seed, n = job
    out = []
    for evolved in (True, False):
        r = random.Random(seed + 1)
        out.append(field_results(None, _s["pool"], lambda: bot(evolved, r.getrandbits(30)),
                                 lambda rng: varied(rng, _s["pool"]), n, seed, draw=_s["draw"]))
    return out


def mm(v):
    n = len(v)
    m = sum(v) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in v) / (n - 1))
    return 100 * m, 196 * sd / math.sqrt(n)


def main():
    settings = eval(f"dict({sys.argv[1]})")  # noqa: S307 - our own command line
    other = eval(f"dict({sys.argv[6]})") if len(sys.argv) > 6 else {}  # the opposing bot's rules; standard if absent
    pairings = int(sys.argv[2]) if len(sys.argv) > 2 else 4000
    battles = int(sys.argv[3]) if len(sys.argv) > 3 else 4000
    workers = int(sys.argv[4]) if len(sys.argv) > 4 else 3
    seed = int(sys.argv[5]) if len(sys.argv) > 5 else 3030
    chunk = 50
    with multiprocessing.get_context("spawn").Pool(workers, initializer=setup, initargs=(settings, other)) as pool:
        heads = pool.map(h2h, [(seed * 1000 + k, chunk) for k in range(pairings // chunk)])
        fields = pool.map(crowd, [(seed * 7000 + k, chunk) for k in range(battles // chunk)])
    chunk_scores = [s for s, _ in heads]
    print(f"bot on the first rules vs bot on the second (standard if not given), head to head ({pairings} pairings both ways): "
          "%.1f%% ± %.1f (margin over chunks of 50 pairings)" % mm(chunk_scores))
    evolved = [x for e, _ in fields for x in e]
    standard = [x for _, s in fields for x in s]
    print("against the crowd (%d battles, same battles): evolved %.1f%% ± %.1f, standard %.1f%% ± %.1f" % ((battles,) + mm(evolved) + mm(standard)))
    print("paired difference: %+.1f ± %.1f points" % mm([a - b for a, b in zip(evolved, standard)]))


if __name__ == "__main__":
    main()
