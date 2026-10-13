"""Play a recorded battle back as if it were live, and measure what is lost by not seeing the future.

    python3 scripts/recording/live_replay.py games/<recording>/raw [--battle 1] [--lag 0] [--text-delay 0] [--jobs 4]
        [--save FOLDER] [assemble options such as --public-footage --single-clip]

The offline pipeline (assemble.py, then the tracker) builds each look from the whole recording: it smooths a
health bar with frames that come after, takes back a step that later frames contradict, works out a faint from
the header several seconds later, and dates a switch from text read after it. A live bot has only what has
been seen so far.

So at every half-second t of the battle this rebuilds the looks from the readings up to t + lag only, with
each text reading arriving text-delay seconds after its frame (reading text is slow), and hands the tracker
the looks for that half-second as soon as they exist. A look that only appears once later readings are in is
lost, because the tracker cannot go back. The tracker's picture at each half-second is then set against the
offline picture of the same moment, and our energy against the charged-move buttons.

--lag is the price of waiting: the tracker's picture of time t is ready at t + lag.
The team is given to the tracker at the start, as it would be in a live game.
"""
from __future__ import annotations

import bisect, concurrent.futures, dataclasses, gzip, io, json, statistics, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import assemble as asm  # noqa: E402
import track  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.tracker import Observation, Tracker, state  # noqa: E402

FIELDS = {f.name for f in dataclasses.fields(Observation)}


def option(argv, name, default):
    return type(default)(argv[argv.index(name) + 1]) if name in argv else default


def without(argv, *names):
    """argv with the named options (and their values) taken out."""
    out, skip = [], False
    for a in argv:
        if skip:
            skip = False
        elif a in names:
            skip = True
        else:
            out.append(a)
    return out


def load(raw: Path):
    name = "readings-refined.jsonl.gz" if (raw / "readings-refined.jsonl.gz").exists() else "readings.jsonl.gz"
    rows = [json.loads(l) for l in gzip.open(raw / name, "rt", encoding="utf-8")]
    texts = [json.loads(l) for l in gzip.open(raw / "text.jsonl.gz", "rt", encoding="utf-8")]
    return rows, texts


class Feed:
    """The tracker, fed one look at a time the way track.py feeds it."""

    def __init__(self, gd: GameData, team: dict):
        self.gd = gd
        builds, known = track.load_team(gd, team)
        self.tracker = Tracker(gd, builds, moves_known=known)
        self.tracker._file = io.StringIO()  # its events, kept in memory
        self.states, self.rejected = [], 0

    def give(self, look: dict) -> None:
        look = {k: v for k, v in look.items() if k != "note"}
        try:
            for key in ("my_species", "foe_species"):
                if look.get(key):
                    look[key] = track.species_id(self.gd, look[key])
            if look.get("foe_move"):
                try:
                    look["foe_move"] = track.move_id(self.gd, look["foe_move"])
                except ValueError:
                    del look["foe_move"]
            if look.get("my_charged") is not None:
                look["my_charged"] = track.charged_index(self.gd, self.tracker, look, 0)
            obs = Observation(**{k: v for k, v in look.items() if k in FIELDS})
            if obs.t < self.tracker.t:
                raise ValueError("time goes backwards")
            self.tracker.update(obs)
        except (ValueError, TypeError, KeyError):
            self.rejected += 1
            return
        self.states.append(state(self.tracker))


_shared = {}


def _init(rows, texts, argv, span):
    _shared.update(rows=rows, texts=texts, argv=argv, span=span)


def prefix(cutoff_and_delay):
    """The looks built from what had been seen by `cutoff`, text arriving `delay` seconds late."""
    cutoff, delay = cutoff_and_delay
    rows = [r for r in _shared["rows"] if r["t"] <= cutoff]
    texts = [s for s in _shared["texts"] if s["t"] + delay <= cutoff]
    argv = _shared["argv"] + ["--text-delay", str(delay)]
    done = asm.assemble([dict(r) for r in rows], texts, argv, span=(_shared["span"][0], cutoff), now=cutoff)
    return done["looks"], done["waits"], done["timeline"]["field"]["theirs"]


def replay(raw: Path, argv: list, lag: float, delay: float, jobs: int, gd: GameData, out_for: bool = True) -> dict:
    rows, texts = load(raw)
    full = asm.assemble([dict(r) for r in rows], texts, without(argv, "--buttons-stop", "--buttons-hold"))
    origin, span, end = full["origin"], full["span"], full["end"]
    offline = Feed(gd, full["team"])
    for look in full["looks"]:
        offline.give(look)
    steps = [origin + 0.5 * k for k in range(int((end - origin) * 2) + 2)]
    rows = [r for r in rows if span[0] <= r["t"] <= span[1]]
    texts = [s for s in texts if span[0] <= s["t"] <= span[1]]
    started = time.time()
    with concurrent.futures.ProcessPoolExecutor(jobs, initializer=_init, initargs=(rows, texts, argv, span)) as pool:
        built = list(pool.map(prefix, [(t + lag, delay) for t in steps], chunksize=4))
    live, fed = Feed(gd, full["team"]), []
    shown = None  # their Pokémon on the last look given
    for t, (looks, waits, theirs) in zip(steps, built):
        rel = round(t - origin, 2)
        for look in looks:
            if (fed and look["t"] <= fed[-1]["t"]) or look["t"] > rel:
                continue
            look = dict(look)
            # How long the fight stood still since the last look that was really given, by what is known now.
            since = origin + fed[-1]["t"] if fed else origin + look["t"]
            stood = sum(max(0.0, min(origin + look["t"], b) - max(since, a)) for a, b in waits)
            look.pop("paused", None)
            if abs(stood) > 0.01:
                look["paused"] = round(stood, 2)
            if out_for and look.get("foe_species") and shown and look["foe_species"] != shown:
                # The first look to show their new Pokémon: say how long ago it really came out.
                came = [f["t"] for f in theirs if f["name"] == look["foe_species"] and f["t"] <= look["t"]]
                if came and look["t"] - came[-1] >= 0.25:
                    look["foe_out_for"] = round(look["t"] - came[-1], 2)
            shown = look.get("foe_species") or shown
            fed.append(look)
            live.give(look)
    return {"offline": offline, "live": live, "full": full, "fed": fed, "seconds": time.time() - started}


def compare(offline: Feed, live: Feed, full_looks: list) -> dict:
    """The live picture at each half-second against the offline one, and our energy against the buttons."""
    live_t = [s["t"] for s in live.states]
    buttons = {l["t"]: l["my_energy"] for l in full_looks if "my_energy" in l}
    tally = {}

    def count(key, ok):
        n, good = tally.get(key, (0, 0))
        tally[key] = (n + 1, good + bool(ok))

    for s in offline.states:
        k = bisect.bisect_right(live_t, s["t"]) - 1
        if k < 0:
            continue
        l = live.states[k]
        for who in ("me", "opponent"):
            a, b = s[who], l[who]
            if a["active"] is None:
                continue
            pa = a["pokemon"][a["active"]]
            pb = b["pokemon"][b["active"]] if b["active"] is not None else None
            same = pb is not None and pa["species"] == pb["species"]
            count(f"{who}: who is out", same)
            count(f"{who}: shields", a["shields"] == b["shields"])
            count(f"{who}: Pokémon left", a["left"] == b["left"])
            if same:
                count(f"{who}: health within 3%", abs(pa["hp_share"] - pb["hp_share"]) <= 0.03)
                gain = max(pa["fast_move"]["energy_gain"], 1)
                count(f"{who}: energy within one fast move", abs(pa["energy"] - pb["energy"]) <= gain + 0.5)
        if s["t"] in buttons and live.states[k]["me"]["active"] is not None:
            for name, st in (("offline", s), ("live", live.states[k])):
                me = st["me"]["pokemon"][st["me"]["active"]]
                count(f"our energy within 5 of the buttons, {name}", abs(me["energy"] - buttons[s["t"]]) <= 5)
    return tally


KINDS = ("my_charged", "foe_charged", "my_switch", "foe_switch", "my_faint", "foe_faint")


def events(feed: Feed) -> list:
    lines = feed.tracker._file.getvalue().splitlines()
    return [e for e in map(json.loads, lines) if e["event"] in KINDS]


def event_delays(offline: Feed, live: Feed) -> dict:
    """Each switch, faint and charged move: did the live tracker see it, and how much later (or earlier)?"""
    out = {}
    spare = events(live)
    for e in events(offline):
        match = min((x for x in spare if x["event"] == e["event"] and abs(x["t"] - e["t"]) <= 12),
                    key=lambda x: abs(x["t"] - e["t"]), default=None)
        row = out.setdefault(e["event"], {"offline": 0, "found": 0, "late": [], "extra": 0})
        row["offline"] += 1
        if match:
            spare.remove(match)
            row["found"] += 1
            row["late"].append(round(match["t"] - e["t"], 2))
    for x in spare:
        out.setdefault(x["event"], {"offline": 0, "found": 0, "late": [], "extra": 0})["extra"] += 1
    return out


def main() -> int:
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    raw = Path(argv[0])
    lag, delay, jobs = option(argv, "--lag", 0.0), option(argv, "--text-delay", 0.0), option(argv, "--jobs", 4)
    out_for = "--no-out-for" not in argv  # without: a change of their Pokémon counts from the look that shows it
    save = option(argv, "--save", "")
    passed = [a for a in without(argv[1:], "--lag", "--text-delay", "--jobs", "--save") if a != "--no-out-for"]
    gd = GameData()
    done = replay(raw, passed, lag, delay, jobs, gd, out_for)
    tally = compare(done["offline"], done["live"], done["full"]["looks"])
    print(f"{raw.parent.name}: lag {lag} s, text {delay} s late; {len(done['fed'])} looks given live "
          f"({done['live'].rejected} rejected) against {len(done['full']['looks'])} offline; {done['seconds']:.0f} s")
    for key, (n, good) in tally.items():
        print(f"  {key}: {100 * good / n:.1f}% of {n}")
    delays = event_delays(done["offline"], done["live"])
    for kind, row in delays.items():
        late = row["late"]
        print(f"  {kind}: {row['found']} of {row['offline']} seen live" + (f", {row['extra']} extra" if row["extra"] else "")
              + (f"; time live minus offline: median {statistics.median(late):+.1f} s, from {min(late):+.1f} to {max(late):+.1f}" if late else ""))
    if save:
        # FOLDER/live and FOLDER/offline each hold looks, states and the timeline, as a tracked game folder does.
        out = Path(save)
        for name, looks, feed in (("live", done["fed"], done["live"]), ("offline", done["full"]["looks"], done["offline"])):
            (out / name).mkdir(parents=True, exist_ok=True)
            (out / name / "observations.jsonl").write_text("".join(json.dumps(l) + "\n" for l in looks))
            (out / name / "states.jsonl").write_text("".join(json.dumps(s) + "\n" for s in feed.states))
            (out / name / "team.json").write_text(json.dumps(done["full"]["team"], indent=2) + "\n")
            (out / name / "timeline.json").write_text(json.dumps(done["full"]["timeline"]) + "\n")
        (out / "tally.json").write_text(json.dumps({"lag": lag, "text_delay": delay, "tally": tally, "events": delays}, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
