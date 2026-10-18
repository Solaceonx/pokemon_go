"""What the web page calls, inside Pyodide: battles between two given teams, both sides the trained bot.

The page asks for a few battles at a time for each lead against each lead and adds them up as they come, so the
table fills in and sharpens while the visitor watches (the same play as pogo.lineup.win_chance).
"""
import json
import random
from pathlib import Path

from pogo.agents import varied_settings
from pogo.battle import DRAW, Battle
from pogo.gamedata import GameData
from pogo.learner import Learner, QNet
from pogo.roster import builds

HERE = Path(__file__).resolve().parent
_state = {}


def setup() -> str:
    gd = GameData()
    _state.update(gd=gd, pool=gd.meta(50), net=QNet.load(str(HERE / "runs" / "general-decide" / "q.npz")), owned=builds(gd))
    return json.dumps({"ok": True})


def run(job: str) -> str:
    """job: {"mine": [3 ids, lead first], "theirs": [...], "owned": bool, "n": battles, "seed": int} -> points won."""
    j = json.loads(job)
    s = _state
    gd, pool, net = s["gd"], s["pool"], s["net"]
    mine = [(s["owned"].get(sid) if j["owned"] else None) or gd.default(sid) for sid in j["mine"]]
    theirs = [gd.default(sid) for sid in j["theirs"]]
    rng = random.Random(j["seed"])
    points = 0.0
    for _ in range(j["n"]):
        ours = Learner(q=net, margin=rng.choice((0.02, 0.05)), **varied_settings(rng, pool))
        foes = Learner(q=net, margin=rng.choice((0.02, 0.05)), **varied_settings(rng, pool))
        winner = Battle(mine, theirs, ours, foes, seed=rng.getrandbits(32)).run()
        points += 1.0 if winner == 0 else 0.5 if winner == DRAW else 0.0
    return json.dumps({"points": points, "n": j["n"]})
