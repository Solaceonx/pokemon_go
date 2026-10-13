#!/usr/bin/env python3
"""When the opponent has just switched (and so cannot switch again) and our switch is ready: how often the
trained bot and the engine bring in a counter, by how the matchup stands and how much better the counter is.

    python3 scripts/punish_count.py [BATTLES]     default 300, against the crowd

The owner's complaint was that the bot does not punish with harder counters. Outlooks are the Planner's
one-on-one estimates (-1 to +1); only the pilot's own decisions count, not those inside the engine's look-ahead.
"""
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pogo.agents import varied  # noqa: E402
from pogo.battle import Battle  # noqa: E402
from pogo.engine import Engine  # noqa: E402
from pogo.evaluation import Evaluator  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.learner import Learner, QNet  # noqa: E402
from pogo.teamlist import drawer  # noqa: E402

battles = int(sys.argv[1]) if len(sys.argv) > 1 else 300
gd = GameData()
pool = gd.meta(50)
draw = drawer(gd, pool)
net = QNet.load(str(ROOT / "runs" / "general-decide" / "q.npz"))
ev = Evaluator.load(ROOT / "runs" / "eval" / "eval.npz")
for name, make in (("trained bot", lambda s: Learner(q=net, margin=0.02, seed=s)),
                   ("engine", lambda s: Engine(ev, pool, rollout="bot", samples=4, edge=0.03, q=net, margin=0.02, seed=s))):
    rows = []
    def spy(self, view, _orig=Learner._swap_choice):
        # Only the pilot's own decisions, not those of the players inside the engine's look-ahead.
        locked = view.foe_switch_wait > 0 and view.me.bench() and getattr(self, "counted", False)
        if locked:
            stay = self._outlook(view, view.me.active)
            best = max(view.me.bench(), key=lambda j: self._outlook(view, j))
            gain = self._outlook(view, best) - stay
        choice = _orig(self, view)
        if locked:
            rows.append((stay, gain, choice))
        return choice
    saved = Learner._swap_choice
    Learner._swap_choice = spy
    rng = random.Random(3)
    for i in range(battles):
        pilot = make(i)
        pilot.counted = True
        Battle(draw(rng), draw(rng), pilot, varied(rng, pool), seed=i).run()
    Learner._swap_choice = saved
    def share(sel):
        r = [x for x in rows if sel(x)]
        return f"{sum(x[2] is not None for x in r)} of {len(r)}"
    print(f"{name}: opponent just switched, our switch ready: {len(rows)} times")
    print(f"  losing, a counter 0.3+ better on the bench: switched {share(lambda x: x[0] < 0 and x[1] >= 0.3)}")
    print(f"  losing, counter better by under 0.3: switched {share(lambda x: x[0] < 0 and x[1] < 0.3)}")
    print(f"  even or ahead, a counter 0.3+ better: switched {share(lambda x: x[0] >= 0 and x[1] >= 0.3)}")
    print(f"  ahead, counter better by under 0.3: switched {share(lambda x: x[0] >= 0 and x[1] < 0.3)}", flush=True)
