#!/usr/bin/env python3
"""Play the bot yourself, in the simulator, in a browser.

    python3 scripts/play.py                     your team from data/owner_team.json against the trained bot
    python3 scripts/play.py --team medicham azumarill registeel --bot planner
    python3 scripts/play.py --foe tinkaton corviknight mandibuzz --port 8765

Then open http://localhost:8765 (it opens by itself). The battle runs on the same engine as every simulation
here, 1.5 times slower than the real game unless --slow says otherwise: half-second turns, fast moves
landing on their last turn, charged moves taking 10 s off the clock. You attack with your fast move all the time, as if holding the screen, and choose charged
moves, switches and shields; a charged move always counts as fully charged (no swiping). The opponent's
energy is not shown, as on the phone.

Opponents: --bot learner (default, the trained bot), engine (the trained bot with a look-ahead at its judgement
calls, pogo.engine; needs runs/eval/eval.npz), planner (the hand-written rules) or crowd (a varied Planner, as in
training). Without --foe, each battle draws a team the way the simulations do (half
from data/teams.json, half random from the top 50).

Every battle is saved to games/played/: the teams, every turn, every choice on both sides and the result,
with a running tally in games/played/results.jsonl, so games against people can be studied like the rest.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pogo.agents import Planner, varied  # noqa: E402
from pogo.battle import CHARGED, DRAW, FAST, MAX_TURNS, SWITCH, Battle  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.learner import Learner, QNet  # noqa: E402
from pogo.arena import decisive  # noqa: E402
from pogo.lineup import win_chance  # noqa: E402
from pogo.realtime import RealTime  # noqa: E402
from pogo.evaluation import Evaluator  # noqa: E402
from pogo.teamlist import drawer  # noqa: E402

TURN = 0.5  # game seconds a turn takes (the clock on screen counts these)
PAGE = Path(__file__).resolve().parent / "play" / "index.html"
SAVED = ROOT / "games" / "played"
MODEL = ROOT / "runs" / "general-decide" / "q.npz"
EVALUATION = ROOT / "runs" / "eval" / "eval.npz"  # the engine's evaluation (scripts/train_eval.py); without it, the plain count


# teams

def owner_builds(gd: GameData) -> dict:
    """The owner's Pokémon by species name, built with their real moves, IVs and level."""
    builds = {}
    for name in ("owner_team.json", "owner_roster.json"):
        path = ROOT / "data" / name
        if not path.exists():
            continue
        for entry in json.loads(path.read_text())["pokemon"]:
            sid = next((k for k, v in gd.species.items() if v["speciesName"] == entry["species"]), None)
            if sid is None or entry["species"] in builds:
                continue
            by_name = {m.name: m.id for m in gd.moves.values()}
            if not entry.get("fast") or not entry.get("charged") or any(m not in by_name for m in [entry["fast"], *entry["charged"]]):
                builds[entry["species"]] = gd.default(sid, allow_forms=True)
                continue
            moves = [by_name[entry["fast"]], *(by_name[m] for m in entry["charged"])]
            ivs, level = tuple(entry["ivs"]) if entry.get("ivs") else None, None
            if ivs and entry.get("cp"):
                levels = [1 + i / 2 for i in range(100)]
                level = min(levels, key=lambda lv: (abs(gd.cp_at(sid, lv, ivs) - entry["cp"]), -lv))
            builds[entry["species"]] = gd.build(sid, moves, level=level, ivs=ivs, allow_forms=True)
    return builds


def species_build(gd: GameData, text: str, owned: dict):
    """A Pokémon by name or id: the owner's own build if they have one, otherwise the usual one."""
    for name, build in owned.items():
        if text.lower() in (name.lower(), build.species_id):
            return build
    by_name = {v["speciesName"].lower(): k for k, v in gd.species.items()}
    sid = text if text in gd.species else by_name.get(text.lower().replace("_", " "))
    if sid is None:
        raise SystemExit(f"unknown Pokémon {text!r}")
    return gd.default(sid, allow_forms=True)


def sprite(gd: GameData, build) -> dict:
    """Names for sprite sites: Pokémon Showdown's ("ninetales-alola", "deoxys-defense"), and the National Dex
    number as a fallback."""
    regional = {"alolan": "alola", "galarian": "galar", "hisuian": "hisui", "paldean": "paldea", "female": "f"}
    plain = {"shadow", "altered", "incarnate", "standard", "average", "male", "normal", "land", "aria", "ordinary"}
    base, *rest = build.species_id.split("_")
    form = "".join(regional.get(w, w) for w in rest if w not in plain)
    return {"showdown": base + (f"-{form}" if form else ""), "dex": gd.species[build.species_id]["dex"],
            "shadow": build.species_id.endswith("_shadow")}


def describe(build) -> list:
    """A Pokémon as saved with a game: species, moves (fast first), level and IVs."""
    return [build.species_id, [build.fast.id, *(m.id for m in build.charged)], build.level, list(build.ivs)]


# the human player

class Human:
    """The person at the browser. Fast moves unless told otherwise; shields and replacements are asked for."""

    # Not told which charged move is coming, as on the phone (and as the bot is not told ours).

    def __init__(self, game: Game):
        self.game = game

    def act(self, view) -> int:
        wanted = self.game.take()
        return wanted if wanted is not None and wanted in view.legal() else FAST

    def shield(self, view, energy: int, move=None) -> bool:
        if view.me.shields == 0:
            return False
        return bool(self.game.ask("shield", 6.0, False))

    def replace(self, view) -> int:
        bench = view.me.bench()
        return self.game.ask("replace", 12.0, bench[0], options=bench) if len(bench) > 1 else bench[0]


class Game:
    def __init__(self, gd: GameData, mine: list, theirs: list, bot, bot_name: str, charged_pause: float, slow: float = 1.5,
                 my_charged_pause: float = 4.0, countdown: float = 3.0, evaluator: Evaluator | None = None,
                 eval_bar: bool = False, bot_seed: int | None = None):
        self.gd, self.bot_name, self.charged_pause, self.my_charged_pause = gd, bot_name, charged_pause, my_charged_pause
        self.real_turn = TURN * slow  # real seconds a turn takes: slower than the game by `slow`
        self.human = Human(self)
        # Seeds are saved with the game, so it can be replayed exactly (scripts/losses.py --played).
        self.seed, self.bot_seed = random.getrandbits(32), bot_seed
        self.battle = Battle(mine, theirs, self.human, bot, seed=self.seed, record=True)
        self.queued = None
        self.prompt, self.answer, self.answered = None, None, threading.Event()
        self.choices = []  # (turn, side, what) for the saved record
        self.started, self.finished, self.stopped = time.time(), None, False
        self.pause_until = 0.0
        self.countdown = countdown
        self.begins = None  # set when the page first looks: 3, 2, 1 from then before the first turn
        self.evaluator, self.eval_bar = evaluator, eval_bar
        self.evals = []  # (game seconds, evaluation from our side) each turn, for the review after the battle
        self.thread = threading.Thread(target=self.run, daemon=True)
        # The line-up's win chance (pogo.lineup), worked out when the battle is over so it cannot slow the turns.
        self.teams = [list(mine), list(theirs)]
        self.lineup, self.lineup_net, self.pool = None, None, None

    # from the page

    def queue(self, action: int) -> None:
        self.queued = action

    def take(self):
        action, self.queued = self.queued, None
        if action is not None:
            self.choices.append((self.battle.turn, 0, action))
        return action

    def ask(self, kind: str, seconds: float, default, **details):
        self.answered.clear()
        self.prompt = {"kind": kind, "until": time.time() + seconds, **details}
        self.answered.wait(seconds)
        value = self.answer if self.answered.is_set() else default
        self.prompt, self.answer = None, None
        self.choices.append((self.battle.turn, 0, f"{kind}:{value}"))
        return value

    def reply(self, value) -> None:
        if self.prompt:
            if self.prompt["kind"] == "replace" and value not in self.prompt["options"]:
                return
            self.answer = value
            self.answered.set()

    # the clock

    def run(self) -> None:
        battle = self.battle
        while (self.begins is None or time.time() < self.begins) and not self.stopped:
            time.sleep(0.05)
        while battle.winner is None and not self.stopped:
            started = time.time()
            seen = len(battle.log)
            if self.evaluator and battle.sides[0].mon.hp > 0 and battle.sides[1].mon.hp > 0:
                self.evals.append((round(battle.turn * TURN, 1), round(self.evaluator(battle.views[0]), 3)))
            battle.step()
            if battle.winner is not None:
                break
            # A charged move holds the screen: longer for ours, so there is time to see it and choose what next.
            # The hold starts once the move has landed, so time spent on the shield prompt does not use it up and
            # a second charged move straight after cannot arrive before the first one's outcome has been seen.
            throwers = {side for _, side, text in battle.log[seen:] if " throws " in text}
            hold = max([self.my_charged_pause] * (0 in throwers) + [self.charged_pause] * (1 in throwers), default=0.0)
            if hold:
                self.pause_until = time.time() + hold
                time.sleep(hold)
            else:
                time.sleep(max(0.0, self.real_turn - (time.time() - started)))
        if battle.winner is not None and self.lineup_net is not None:
            chance, margin = win_chance(self.lineup_net, self.pool, *self.teams, battles=200, seed=self.seed)
            self.lineup = [round(chance, 3), round(margin, 3)]
        self.finished = time.time()
        if battle.winner is not None:
            self.evals.append((round(battle.turn * TURN, 1), round(decisive(battle, 0), 3)))
            self.save()

    def save(self) -> None:
        battle = self.battle
        SAVED.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime(self.started))
        result = {DRAW: "draw", 0: "win", 1: "loss"}[battle.winner]
        record = {"started": stamp, "bot": self.bot_name, "result": result, "turns": battle.turn,
                  "mine": [m.build.species_id for m in battle.sides[0].team],
                  "theirs": [m.build.species_id for m in battle.sides[1].team],
                  "log": battle.log, "my_choices": self.choices, "evaluation": self.evals,
                  "decisiveness": round(decisive(battle, 0), 3), "lineup_win_chance": self.lineup}
        record.update(seed=self.seed, bot_seed=self.bot_seed, teams=[[describe(m.build) for m in side.team] for side in battle.sides])
        rows = getattr(battle.agents[1], "rows", None)
        if rows:  # the real-time engine's searches: what came before, kind, ms allowed, ms taken, wait, cut, fell back
            record["bot_searches"] = [[c, k, round(b), round(s, 1), round(w, 1), cut, fell] for c, k, b, s, w, cut, fell in rows]
        (SAVED / f"{stamp}.json").write_text(json.dumps(record, indent=1) + "\n")
        with (SAVED / "results.jsonl").open("a") as out:
            out.write(json.dumps({k: record[k] for k in ("started", "bot", "result", "mine", "theirs", "turns")}) + "\n")

    def review(self) -> dict:
        """After the battle: how the evaluation went, and the moments it swung most, with what happened then."""
        points = self.evals
        swings = []
        for (t0, e0), (t1, e1) in zip(points, points[1:]):
            happened = [(side, re.sub(r" -?\d+/\d+hp \d+e", "", text)) for turn, side, text in self.battle.log
                        if t0 <= turn * TURN < t1 + 0.01 and ("throws" in text or "sends in" in text or "faints" in text)]
            if happened:
                swings.append({"t": t0, "change": round(e1 - e0, 3),
                               "what": "; ".join(("You: " if side == 0 else "Bot: ") + text for side, text in happened[:3])})
        swings.sort(key=lambda s: -abs(s["change"]))
        return {"points": points, "swings": sorted(swings[:5], key=lambda s: s["t"]), "lineup": self.lineup,
                "learned": bool(self.evaluator and self.evaluator.model is not None)}

    # to the page

    def state(self) -> dict:
        if self.begins is None:
            self.begins = time.time() + self.countdown  # someone is watching: start counting down
        battle, gd = self.battle, self.gd
        me, foe = battle.sides

        def mon(m, own: bool) -> dict:
            out = {"name": m.build.name, "species": m.build.species_id, "types": list(m.build.types),
                   "cp": m.build.cp, "hp": max(m.hp, 0), "hp_max": m.build.hp, "sprite": sprite(gd, m.build)}
            if own:
                out.update(energy=m.energy, fast={"name": m.build.fast.name, "type": m.build.fast.type},
                           charged=[{"name": c.name, "type": c.type, "energy": c.energy} for c in m.build.charged])
            return out

        prompt = dict(self.prompt) if self.prompt else None
        if prompt:
            prompt["seconds"] = round(max(0.0, prompt.pop("until") - time.time()), 1)
        return {
            "clock": round(max(0, MAX_TURNS - battle.turn) * TURN, 1),
            "winner": None if battle.winner is None else {DRAW: "draw", 0: "win", 1: "loss"}[battle.winner],
            "charging": time.time() < self.pause_until,
            "countdown": round(max(0.0, self.begins - time.time()), 1) if self.begins else self.countdown,
            "prompt": prompt, "bot": self.bot_name,
            "me": {"active": me.active, "shields": me.shields, "switch_wait": round(me.switch_wait * TURN),
                   "team": [mon(m, True) for m in me.team]},
            "foe": {"active": mon(foe.mon, False), "shields": foe.shields, "left": foe.left(),
                    "seen": [foe.team[j].build.name for j in foe.shown]},
            # Without the health and energy the engine's log adds ("Florges 110/110hp 0e"): the phone shows neither.
            "log": [{"turn": t, "side": s, "text": re.sub(r" -?\d+/\d+hp \d+e", "", x)} for t, s, x in (battle.log or [])[-8:]],
            "eval": self.evals[-1][1] if self.eval_bar and self.evals else None,
            "review": self.review() if battle.winner is not None and self.finished else None,
        }


# the web side

class Server:
    def __init__(self, args):
        self.gd = GameData()
        self.args = args
        self.owned = owner_builds(self.gd)
        self.pool = self.gd.meta(50)
        self.draw = drawer(self.gd, self.pool)
        self.net = QNet.load(str(MODEL)) if args.bot in ("learner", "engine") else None
        self.lineup_net = QNet.load(str(MODEL)) if MODEL.exists() else None
        self.evaluator = Evaluator.load(EVALUATION) if EVALUATION.exists() else Evaluator()
        self.rng = random.Random()
        self.game = None
        self.new()

    def counter(self, mine):
        """With --counters, a team that should beat ours, from scripts/counters.py's list for our team."""
        if not self.args.counters:
            return None
        path = ROOT / "data" / "counters" / ("-".join(b.species_id for b in mine) + ".json")
        if not path.exists():
            print(f"no list of counters for this team yet; make it with: python3 scripts/counters.py "
                  f"{' '.join(b.species_id for b in mine)}")
            return None
        teams = json.loads(path.read_text())["teams"]
        if not teams:
            return None
        pick = self.rng.choice(teams)
        print(f"the bot brings {' / '.join(pick['team'])}: it should win {100 * pick['win_chance']:.0f}% (bot against bot)")
        return [self.gd.default(sid) for sid in pick["team"]]

    def team(self, names):
        return [species_build(self.gd, n, self.owned) for n in names]

    def new(self) -> None:
        if self.game:
            self.game.stopped = True
            self.game.answered.set()
        # The review and the bot each need their own cache for this game's team.
        self.evaluator = Evaluator(self.evaluator.model)
        mine = self.team(self.args.team) if self.args.team else list(self.owned.values())[:3]
        theirs = self.team(self.args.foe) if self.args.foe else self.counter(mine) or self.draw(self.rng)
        bot_seed = random.getrandbits(30)
        # Share model weights across games, but keep the bot's and display's matchup caches separate.
        if self.args.bot == "learner":
            bot = Learner(q=self.net, margin=0.02, seed=bot_seed)
        elif self.args.bot == "engine":
            # The trained bot with a look-ahead at its judgement calls (pogo.engine), as tested in scripts/engine_trial.py,
            # with a deadline on every search on the wall clock (pogo.realtime). Here the search runs inside the game's
            # own turn, so none may take longer than a turn; in simulation none comes near that.
            bot = RealTime(Evaluator(self.evaluator.model), self.pool, rollout="bot", samples=32, edge=0.03, q=self.net, margin=0.02,
                           turn_ms=1000 * TURN * self.args.slow, after_charged_ms=1000 * self.args.charged_pause,
                           cap_ms=1000 * TURN * self.args.slow - 50, clock=time.perf_counter, seed=bot_seed)
        elif self.args.bot == "crowd":
            bot = varied(self.rng, self.pool)
        else:
            bot = Planner(seed=bot_seed)
        self.game = Game(self.gd, mine, theirs, bot, self.args.bot, self.args.charged_pause, self.args.slow,
                         self.args.my_charged_pause, evaluator=Evaluator(self.evaluator.model),
                         eval_bar=self.args.eval_bar, bot_seed=bot_seed)
        self.game.lineup_net, self.game.pool = self.lineup_net, self.pool
        self.game.thread.start()

    def tally(self) -> dict:
        path = SAVED / "results.jsonl"
        rows = [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []
        return {k: sum(r["result"] == k for r in rows) for k in ("win", "loss", "draw")}

    def handler(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def send(self, body: bytes, kind: str = "application/json", code: int = 200):
                self.send_response(code)
                self.send_header("Content-Type", kind)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path in ("/", "/index.html"):
                    self.send(PAGE.read_bytes(), "text/html; charset=utf-8")
                elif self.path == "/api/state":
                    state = server.game.state()
                    state["tally"] = server.tally()
                    self.send(json.dumps(state).encode())
                else:
                    self.send(b"{}", code=404)

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                game = server.game
                if self.path == "/api/act":
                    what = body.get("a", "")
                    if what in ("c0", "c1"):
                        game.queue(CHARGED[int(what[1])])
                    elif what in ("s0", "s1", "s2"):
                        game.queue(SWITCH[int(what[1])])
                elif self.path == "/api/answer":
                    game.reply(body.get("value"))
                elif self.path == "/api/new":
                    server.new()
                self.send(b"{}")

        return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--team", nargs=3, help="your three, lead first (default: the first three in data/owner_team.json)")
    parser.add_argument("--foe", nargs=3, help="the bot's three (default: drawn as in the simulations)")
    parser.add_argument("--bot", choices=("learner", "engine", "planner", "crowd"), default="learner")
    parser.add_argument("--counters", action="store_true",
                        help="the bot brings a team that should beat yours (from scripts/counters.py)")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--charged-pause", type=float, default=2.0,
                        help="real seconds the bot's charged move holds the screen (the game takes about 10; the clock still loses 10)")
    parser.add_argument("--my-charged-pause", type=float, default=4.0, help="the same for yours")
    parser.add_argument("--slow", type=float, default=1.5,
                        help="how much slower than the real game a turn runs (1 is the game's own half-second; default 1.5)")
    parser.add_argument("--eval-bar", action="store_true",
                        help="show the engine's evaluation during the battle, as chess sites do (more than the phone shows)")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    server = Server(args)
    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), server.handler())
    url = f"http://localhost:{args.port}"
    print(f"playing against the {args.bot} at {url} (Ctrl-C to stop); battles are saved to {SAVED}")
    if not args.no_browser:
        threading.Timer(0.5, webbrowser.open, (url,)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
