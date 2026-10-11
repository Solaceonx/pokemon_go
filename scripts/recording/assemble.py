"""Turn the frame readings and the announcement text of one recording into looks for the tracker."""
import bisect, collections, difflib, json, re, statistics, sys
from pathlib import Path
readings, text_path, out = sys.argv[1], sys.argv[2], Path(sys.argv[3])
def option(name, default):  # e.g. --every 4 keeps one frame in four, to try lower frame rates on a full reading
    return type(default)(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default
import gzip
lines = lambda path: (gzip.open(path, "rt", encoding="utf-8") if str(path).endswith(".gz") else open(path, encoding="utf-8"))
rows = [json.loads(l) for l in lines(readings)][::option("--every", 1)]
texts = [json.loads(l) for l in lines(text_path)][::option("--text-every", 1)]
if "--middle-only" in sys.argv:  # to try doing without the lower text band
    for s in texts: s["text"] = [x for x in s["text"] if x[0] == "middle"]
FPS = 1.0 / statistics.median(b["t"] - a["t"] for a, b in zip(rows, rows[1:1000]))
SIXTH, HALF = max(3, round(FPS / 6)), max(4, round(FPS / 2))  # frames in a sixth of a second and in half a second
gm = json.load(open("data/gamemaster.json"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pogo.gamedata import GameData
gd = GameData()
species = sorted({p["speciesName"].split(" (")[0] for p in gm["pokemon"]})
moves = sorted({m["name"] for m in gm["moves"]})
KNOWN = {  # movesets we have been told; any other Pokémon of ours gets the usual moves until it shows otherwise
    "Melmetal": {"fast": "Thunder Shock", "charged": ["Double Iron Bash", "Dynamic Punch"]},
    "Altaria": {"fast": "Dragon Breath", "charged": ["Sky Attack", "Flamethrower"]},
}
PUBLIC = "--public-footage" in sys.argv
if PUBLIC:
    KNOWN = {}  # The recorder owner's team sheet does not describe a public VOD.
canon = lambda s: re.sub(r"[^a-z]", "", s.lower())
def nearest(word, options, cutoff=0.72):
    table = {}
    for o in sorted(options, key=len, reverse=True): table[canon(o)] = o  # "Surf" wins over "Surf+"
    hit = difflib.get_close_matches(canon(word), list(table), n=1, cutoff=cutoff)
    return table[hit[0]] if hit else None

def health(side):
    seg, w = side["seg"], side["w"]
    if not seg or not w: return None
    return round(seg[0][1] if seg[0][0] == "cyan" else sum(p for _, p in seg)) / w
W = 138
def commonest(vals):
    """Hit flashes move a reading by a few pixels and now and then to nothing or to full: keep what most frames agree on."""
    px = collections.Counter(round(v * W) for v in vals)
    best, _ = max(px.items(), key=lambda kv: (kv[1] + px.get(kv[0] - 1, 0) + px.get(kv[0] + 1, 0), -kv[0]))
    near = px[best] + px.get(best - 1, 0) + px.get(best + 1, 0)
    return best / W if near >= 0.4 * len(vals) else None
for r in rows: r["mh"], r["oh"] = health(r["m"]), health(r["o"])
# A recording can hold several battles. One starts when both bars appear after 25 s without any, and ends at
# its result screen or, failing that, at the last frame with a bar before the next such gap.
battles, last_bar, current = [], None, None
for r in rows:
    bar, both = r["mh"] is not None or r["oh"] is not None, r["mh"] is not None and r["oh"] is not None
    if current and bar and last_bar is not None and r["t"] - last_bar > 25:
        current = None  # a long gap: that battle was over at the last bar
    if current is None and both and (not battles or r["t"] - battles[-1]["end"] > 8):
        current = {"start": r["t"], "end": r["t"]}; battles.append(current)
    if current:
        if r.get("result") or r["phase"] == "result":
            current["end"] = r["t"]; current = None
        elif bar:
            current["end"] = r["t"]
    if bar: last_bar = r["t"]
battles = [b for b in battles if b["end"] - b["start"] > 20]
if "--single-clip" in sys.argv and any(r["mh"] is not None or r["oh"] is not None for r in rows):
    # VOD intake already supplies one match candidate. Read its complete tail:
    # an announced move or result can arrive after the last health bar vanished.
    battles = [{"start": rows[0]["t"], "end": rows[-1]["t"]}]
if "--count" in sys.argv:
    print(len(battles)); sys.exit(0)
which = option("--battle", 1)
if not 1 <= which <= len(battles):
    sys.exit(f"no battle {which} in this recording ({len(battles)} found)")
span = (battles[which - 1]["start"] - 6.0, battles[which - 1]["end"] + 0.5)
rows = [r for r in rows if span[0] <= r["t"] <= span[1]]
texts = [s for s in texts if span[0] <= s["t"] <= span[1]]
bar_times = [r["t"] for r in rows if r["mh"] is not None or r["oh"] is not None]
# Our Pokémon are the names the header shows on our side; the fight starts when both bars are first on screen.
named = collections.Counter(nearest(r["m"]["sp"], species) for r in rows if r["m"]["sp"])
OURS = [name for name, n in named.most_common() if name and n >= 3][:3]  # the header is read every second or two
theirs_named = collections.Counter(nearest(r["o"]["sp"], species) for r in rows if r["o"]["sp"])
THEIRS = [name for name, n in theirs_named.most_common() if name and n >= 3][:3]
# The bars are on screen for about a second before the first fast moves begin.
first_both = next((r["t"] for r in rows if r["mh"] is not None and r["oh"] is not None), bar_times[0])
T0 = round(first_both + 0.7, 1)

# events from the announcement text
gos, seqs, prompts, seq, words = [], [], [], None, []
for s in texts:
    items = [t for _, t in s["text"]]; joined = canon(" ".join(items)); t = s["t"]
    words.append((t, [w for w, part in (("super", "supere"), ("weak", "notve")) if part in joined]))
    for item in items:
        m = re.match(r"^\W*[Gg][Oo0]\W*\s*([A-Za-z][A-Za-z ]{3,})", item)
        if m:
            name = nearest(m.group(1), species)
            if name and not any(g[1] == name and t - g[0] < 3 for g in gos): gos.append((t, name))
    if "switchinanewpok" in joined: prompts.append(t)
    start = "mine" if "getready" in joined else "theirs" if "ackincoming" in joined else None
    if start and (seq is None or t - seq["start"] > 9):
        seq = {"side": start, "start": t, "move": None, "user": None, "blocked": False}; seqs.append(seq)
    # Broadcast logos can cover the actor prefix while leaving "used MOVE"
    # readable. An earlier charge cue still establishes the thrower's side.
    announcement = next((canon(item) for item in items if "used" in canon(item)), joined) if PUBLIC else joined
    m = re.search(r"([a-z]*)used([a-z]+)" if PUBLIC else r"([a-z]{4,})used([a-z]+)", announcement)
    if m and not (seq and t - seq["start"] < 14):
        # "X used Y!" with no cue read before it (the cue can sit under other text): the cue comes about 7 s
        # earlier. Whose move it was is settled from the name below, or failing that from a shield going.
        user = nearest(m.group(1), OURS + THEIRS) or nearest(m.group(1), species)
        if user:
            seq = {"side": None, "start": t - 7.2, "move": None, "user": None, "blocked": False, "late": True}; seqs.append(seq)
    if m and seq and t - seq["start"] < 14:
        seq["user"] = seq["user"] or nearest(m.group(1), OURS + THEIRS) or nearest(m.group(1), species)
        move_text = m.group(2).replace("lron", "iron") if PUBLIC else m.group(2)
        seq["move"] = seq["move"] or nearest(move_text, moves, 0.8)
    # "BLOCKED!" comes at the end of a move; one still on screen as the next cue appears belongs to the last move.
    if "blocked" in joined and seq and 6 < t - seq["start"] < 15: seq["blocked"] = True
    # NICE! GREAT! EXCELLENT! are the charging game, which only the thrower's own screen shows: our move.
    if seq and t - seq["start"] < 9 and any(canon(x) in ("nice", "great", "excellent") for x in items): seq["ours"] = True
for q in seqs:
    # A charged move is decided about 8.5 s after its cue and lands at about 9.5 s; fighting resumes at 10 s.
    q["resume"] = next((t for t in bar_times if t >= q["start"] + 9.5), rows[-1]["t"])
    # Whose move: the cue says ("Get Ready!" is ours, "Attack incoming!" theirs). Without a cue, the charging
    # game marks ours; failing that the name, if only one team has that Pokémon.
    if q["side"] is None:
        q["side"] = "mine" if q.get("ours") else "theirs"
        if not q.get("ours") and q["user"] and (q["user"] in OURS) != (q["user"] in THEIRS):
            q["side"] = "mine" if q["user"] in OURS else "theirs"
for q, after in zip(seqs, seqs[1:]):
    q["resume"] = min(q["resume"], after["start"])  # two charged moves back to back: the bars do not come back between
end = next((r["t"] for r in rows if r["phase"] == "result" or r["result"]), rows[-1]["t"])

# who is on the field, and whether each change was a faint
def header_left(side, a, b):
    vals = [r[side]["left"] for r in rows if a <= r["t"] <= b and r[side]["left"] is not None]
    return statistics.mode(vals) if vals else None
def steady(key, what):
    """A header counter, once it has shown the same number for half a second: (time, value) at each change."""
    out, value, run = [], None, 0
    for r in rows:
        v = r[key][what]
        if v is None: continue
        value, run = (value, run + 1) if v == value else (v, 1)
        if run == HALF: out.append((r["t"], v))
    return out
left_shown = {"m": steady("m", "left"), "o": steady("o", "left")}
def left_at(key, t):
    seen = [v for when, v in left_shown[key] if when <= t]
    return seen[-1] if seen else None
ENTER = 0.2  # a replacement for a fainted Pokémon is attacking this long after its "Go, X!" is first read
# A switch takes effect before the text says so. Measured from our own energy on the buttons: Jellicent had its
# first fast move in 0.7 s before "Go, Jellicent!" was read, and Altaria stopped gaining 1.5 s before "Go, Melmetal!".
SWAPPED = -1.0
def header_stints(key):
    """Stretches over which the header on one side showed the same name: [first seen, last seen, name]."""
    runs = []
    for r in rows:
        name = nearest(r[key]["sp"], species) if r[key]["sp"] else None
        if not name: continue
        if runs and runs[-1][2] == name: runs[-1][1] = r["t"]; runs[-1][3] += 1
        else: runs.append([r["t"], r["t"], name, 1])
    # one odd reading inside a run of another name is a misread
    runs = [x for i, x in enumerate(runs) if not (x[3] == 1 and 0 < i < len(runs) - 1 and runs[i - 1][2] == runs[i + 1][2])]
    joined_up = []
    for x in runs:
        if joined_up and joined_up[-1][2] == x[2]: joined_up[-1][1] = x[1]
        else: joined_up.append(x[:3])
    return joined_up
def entered(side, key, t, name, first):
    """One Pokémon coming out on one side at time t (when its "Go, X!" was read)."""
    faint = False
    if not first:
        before, after = header_left(key, t - 12, t - 1), header_left(key, t + 1, t + 6)
        last = [r[key + "h"] for r in rows if t - 8 <= r["t"] < t and r[key + "h"] is not None]
        # The counter of Pokémon left falls when one faints; the next to come out on that side is its replacement.
        earlier, now = left_at(key, field[side][-1]["t"] + 3), left_at(key, t + 6)
        faint = (earlier is not None and now is not None and now < earlier) \
            or (before is not None and after is not None and after < before) or (bool(last) and statistics.median(last[-10:]) < 0.08) \
            or (side == "mine" and any(0 <= t - p < 4 for p in prompts))
    field[side].append({"t": t + (ENTER if faint or first else SWAPPED), "name": name, "faint": faint, "read": t})
field = {"mine": [], "theirs": []}
stints = {"mine": header_stints("m"), "theirs": header_stints("o")}
if stints["mine"] and stints["theirs"]:
    # Who is out comes from the name in each side's header, which also settles it when both teams have the same
    # Pokémon. The header is read every second or two, so the moment comes from the matching "Go, X!".
    changes = sorted((x[0], side, i) for side in stints for i, x in enumerate(stints[side]))
    used = set()
    for seen, side, i in changes:
        name = stints[side][i][2]
        earliest = stints[side][i - 1][1] - 1.5 if i else seen - 8.0
        said = [k for k, (t, n) in enumerate(gos) if n == name and k not in used and earliest <= t <= seen + 0.5]
        if said: used.add(said[0])
        entered(side, "m" if side == "mine" else "o", gos[said[0]][0] if said else seen - 0.5, name, first=i == 0)
else:
    for t, name in gos:  # no header to go by: the names alone
        side = "mine" if name in OURS else "theirs"
        if name in OURS and name in THEIRS:
            was = {k: (field[k][-1]["name"] if field[k] else None) for k in field}
            if was["mine"] == name: side = "theirs"
        entered(side, "m" if side == "mine" else "o", t, name, first=not field[side])

def header_shields(key):
    """The header's shield counter, once it has shown the same number for half a second."""
    out, value, run = [], None, 0
    for r in rows:
        v = r[key]["sh"]
        if v is None: continue
        value, run = (value, run + 1) if v == value else (v, 1)
        if run == HALF: out.append((r["t"], v))
    return out
header = {"mine": header_shields("m"), "theirs": header_shields("o")}
blocked = {"mine": 0, "theirs": 0}
def follow(side):
    """Follow one health bar frame by frame: the level it sits at, and each step down with its time and size.

    Hit flashes move single frames by a few pixels, so the level is the median of the last ten frames, and a
    step counts once that median has fallen by two pixels or more. Health cannot rise, so a higher level is
    believed only just after a change of Pokémon on that side."""
    key = "mh" if side == "mine" else "oh"
    changes = [min(f["t"], f["read"]) for f in field[side]]
    times, values, steps, recent, level = [], [], [], collections.deque(maxlen=SIXTH), None
    longer = collections.deque(maxlen=HALF)
    for r in rows:
        if r[key] is None: continue
        t = r["t"]
        if level is not None and level <= W - 6 and r[key] * W >= W - 1 and not any(0 <= t - c <= 6 for c in changes):
            continue  # a bar that was lower cannot be full again: an attack animation is covering it
        if recent and t - recent[-1][0] > 1.0: recent.clear(); longer.clear()  # the bar was away: start afresh
        recent.append((t, round(r[key] * W))); longer.append(recent[-1][1])
        if len(recent) < max(2, round(0.6 * SIXTH)): continue
        middle = statistics.median_low(v for _, v in recent)
        if level is None or (middle > level + 2 and any(0 <= t - c <= 6 for c in changes)):
            level = middle
        elif len(longer) == HALF and sorted(longer)[round(0.1 * HALF)] > level + 2:
            # Half a second of readings all above the level: the level came from a misread. Take the step back.
            wrong = statistics.median_low(longer) - level
            level += wrong
            while steps and wrong > 0:
                taken = min(wrong, steps[-1][1]); steps[-1][1] -= taken; wrong -= taken
                if steps[-1][1] <= 0: steps.pop()
            values[-HALF:] = [max(v, level) for v in values[-HALF:]]
        elif middle <= level - 2:
            when = next(tt for tt, v in recent if v <= level - 1)
            if steps and when - steps[-1][0] < 0.3: steps[-1][1] += level - middle  # one hit, still draining
            else: steps.append([when, level - middle])
            level = middle
        times.append(t); values.append(level)
    return times, values, steps
level_times, level_values, level_steps = {}, {}, {}
for side in ("mine", "theirs"):
    level_times[side], level_values[side], level_steps[side] = follow(side)
# After a faint nobody can attack until the replacement is out: from the counter falling to the "Go, X!".
waits = []
for side, key in (("mine", "m"), ("theirs", "o")):
    for f in field[side]:
        if f["faint"]:
            fell = [when - 0.5 for when, _ in left_shown[key][1:] if when - 0.5 <= f["read"]]
            waits.append((fell[-1] if fell else f["t"] - 2.8, f["t"] - 0.5))
# Our charged-move buttons, when the reading has them. They are on screen exactly while the fight is running:
# they go the moment either side starts a charged move or a Pokémon faints, and come back when fighting resumes.
both_on = lambda r: bool(r.get("b") and r["b"]["l"][1] and r["b"]["r"][1])
live = []
if sum(map(both_on, rows)) / FPS > max(5.0, 0.04 * (end - T0)):  # seen for long enough to be the real thing
    flags, reach, run = [(r["t"], both_on(r)) for r in rows], max(1, round(FPS / 7)), None
    for i, (t, _) in enumerate(flags):
        near = [f for _, f in flags[max(0, i - reach):i + reach + 1]]
        if sum(near) * 2 > len(near):
            run = [t, t] if run is None else [run[0], t]
        elif run is not None:
            live.append(run); run = None
    if run: live.append(run)
    joined_up = []
    for a, b in (x for x in live if x[1] - x[0] > 0.3):
        if joined_up and a - joined_up[-1][1] < 0.4: joined_up[-1][1] = b  # a flicker, or the frame of a switch
        else: joined_up.append([a, b])
    live = joined_up
def away(a, b):
    """Seconds between a and b with the buttons off screen, counted only once they have first been seen."""
    if not live or b <= live[0][0]: return 0.0
    a = max(a, live[0][0])
    return max(0.0, (b - a) - sum(max(0.0, min(b, y) - max(a, x)) for x, y in live))
# The buttons are away for each charged move, each wait for a replacement and, briefly, each switch of ours.
# They are not used as the fight's clock: they come back about half a second after fighting resumes and go a
# second early when we tap a charged move, and counting only the time they are on screen leaves the opponent
# short of energy for moves they threw. They are used for the one thing the text times badly: how long nobody
# attacks after a faint. A wait runs from the buttons going (or from the end of a charged move that caused the
# faint) to half a second before they come back.
if live:
    waits = []
    for (_, gone), (back, _) in zip(live, live[1:] + [[end + 0.5, end + 0.5]]):
        cues = sorted((q for q in seqs if gone - 0.5 <= q["start"] <= back), key=lambda q: q["start"])
        if not any(gone - 1.0 <= when - 0.5 <= back for key in ("m", "o") for when, _ in left_shown[key][1:]):
            continue  # nobody fainted in this gap
        start = cues[-1]["start"] + 10.0 if cues else gone
        if back - 0.5 > start + 0.3: waits.append((start, back - 0.5))

# Our energy, straight from the buttons. Each shows energy / cost as the filled share of its height, and starts
# again from empty for the second helping once the first is full. Two buttons with different costs pin it down.
def our_moves(name):
    if PUBLIC:
        # Read labels from this Pokémon's own stint. Never substitute PvPoke's
        # default charged costs when the footage did not show the move names.
        labels = collections.Counter(tuple(r.get("cm", [])) for r in rows
                                     if r["m"].get("sp") == name and len(r.get("cm", [])) == 2
                                     and all(r["cm"]))
        if not labels:
            return []
        pair = labels.most_common(1)[0][0]
        found = [next((m for m in gd.moves.values() if m.name == n), None) for n in pair]
        return found if all(found) else []
    known = KNOWN.get(name, {}).get("charged")
    if known:
        return [next(m for m in gd.moves.values() if m.name == n) for n in known]
    sid = next((k for k, v in gd.species.items() if v["speciesName"] == name), None)
    return list(gd.default(sid, allow_forms=True).charged) if sid else []
def readings_of(f, cost):
    if 0.09 < f < 0.91: return [f * cost, cost + f * cost]
    return None
def energy_now(fl, fr, cl, cr, was):
    a, b = readings_of(fl, cl), readings_of(fr, cr)
    if a and b:
        x, y = min(((x, y) for x in a for y in b), key=lambda xy: abs(xy[0] - xy[1]))
        return (x + y) / 2 if abs(x - y) <= 5 else None
    one, cost, other_f, other_cost = (a, cl, fr, cr) if a else (b, cr, fl, cl) if b else (None, 0, 0, 0)
    if not one: return None
    if other_f >= 0.91:  # the other is full: at least nine tenths of its cost
        fits = [x for x in one if x >= 0.9 * other_cost - 2]
    else:  # the other is empty: under a tenth of its cost, or just past a full helping
        fits = [x for x in one if x < 0.12 * other_cost + 2 or other_cost - 2 <= x <= 1.12 * other_cost + 2]
    fits = [x for x in fits if x <= 102]
    return min(fits, key=lambda x: abs(x - was)) if fits else None
button_energy = []  # (time, energy) for frames where it could be read
if live:
    flipped, votes = {}, collections.defaultdict(lambda: [0, 0])
    stints = [(f["t"], nxt["t"] if nxt else end, f["name"]) for f, nxt in zip(field["mine"], field["mine"][1:] + [None])]
    def active(t): return next((name for a, b, name in stints if a <= t < b), None)
    for r in rows:  # which button is which move: the pairing whose two readings agree
        name = active(r["t"])
        moves_ = our_moves(name) if name else []
        if len(moves_) == 2 and both_on(r) and 0.12 < r["b"]["l"][0] < 0.88 and 0.12 < r["b"]["r"][0] < 0.88 and moves_[0].energy != moves_[1].energy:
            fl, fr = r["b"]["l"][0], r["b"]["r"][0]
            straight = abs(fl * moves_[0].energy - fr * moves_[1].energy); crossed = abs(fl * moves_[1].energy - fr * moves_[0].energy)
            if abs(straight - crossed) > 1.5: votes[name][straight > crossed] += 1
    was = 0.0
    for r in rows:
        name = active(r["t"])
        moves_ = our_moves(name) if name else []
        if len(moves_) != 2 or not both_on(r): continue
        cl, cr = (moves_[1].energy, moves_[0].energy) if votes[name][1] > votes[name][0] else (moves_[0].energy, moves_[1].energy)
        e = energy_now(r["b"]["l"][0], r["b"]["r"][0], cl, cr, was)
        if e is not None:
            was = min(100.0, e); button_energy.append((r["t"], was))
energy_times = [t for t, _ in button_energy]
looks, left, shields, emitted = [], {"mine": 3, "theirs": 3}, {"mine": 2, "theirs": 2}, set()
current = {"mine": None, "theirs": None}
n_bins = int((end - T0) * 2)
for b in range(n_bins + 1):
    t = T0 + 0.5 * b
    due = [k for k, q in enumerate(seqs) if k not in emitted and q["resume"] <= t][:1]
    inside = any(q["start"] <= t < q["resume"] for q in seqs)
    if inside and not due: continue
    look = {"t": round(t - T0, 2)}
    # A look that reports a charged move shows the two Pokémon that were out when it was thrown; a change
    # made straight after it is left for the next look.
    as_of = seqs[due[0]]["start"] if due else t
    for side, prefix in (("mine", "my"), ("theirs", "foe")):
        on = [f for f in field[side] if f["t"] <= as_of]
        fresh = not any(as_of < f["t"] <= t for f in field[side])  # the bar still belongs to that Pokémon
        if on and on[-1] is not current[side]:
            if on[-1]["faint"]: left[side] -= 1
            current[side] = on[-1]
        if current[side]: look[f"{prefix}_species"] = current[side]["name"]
        at = bisect.bisect_right(level_times[side], t) - 1
        if not inside and fresh and at >= 0 and t - level_times[side][at] <= 0.5:  # the bar was on screen in this half-second
            look[f"{prefix}_hp"] = round(level_values[side][at] / W, 4)
    shown = [w for when, w in words if t - 0.5 < when <= t]
    if shown and not inside: look["effects"] = sorted({x for w in shown for x in w})
    for k in due:
        if True:
            q = seqs[k]; emitted.add(k)
            if q["side"] == "mine":
                look["my_charged"] = q["move"] or "left"
                if q["blocked"]: blocked["theirs"] += 1
            else:
                look["foe_charged"] = True
                if q["move"]: look["foe_move"] = q["move"]
                if q["blocked"]: blocked["mine"] += 1
    for side in shields:  # the counter in the header, or failing that the "BLOCKED!" announcements
        shown = [v for when, v in header[side] if when <= t]
        shields[side] = max(0, min([shields[side], 2 - blocked[side]] + shown[-1:]))
    look.update(my_shields=shields["mine"], foe_shields=shields["theirs"], my_left=left["mine"], foe_left=left["theirs"])
    if PUBLIC:
        # A counter decrease can happen without a subsequent replacement
        # announcement. Public footage supplies the actual remaining count.
        for side, key, prefix in (("mine", "m", "my"), ("theirs", "o", "foe")):
            seen = left_at(key, t)
            if seen is not None:
                left[side] = seen
                look[prefix + "_left"] = seen
    if "my_hp" in look or "foe_hp" in look or "my_charged" in look or "foe_charged" in look or not looks:
        since = T0 + looks[-1]["t"] if looks else t
        stood = sum(max(0.0, min(t, b) - max(since, a)) for a, b in waits)
        if stood > 0: look["paused"] = round(stood, 2)
        lo, hi = bisect.bisect_right(energy_times, t - 0.5), bisect.bisect_right(energy_times, t)
        if hi > lo and "my_charged" not in look and not inside:
            # The fill glides up after each hit and jumps about while it does; the last few frames are the settled ones.
            look["my_energy"] = round(statistics.median(e for _, e in button_energy[max(lo, hi - 3):hi]), 1)
        looks.append(look)
last = [q for k, q in enumerate(seqs) if k not in emitted]
result = next((r["result"] for r in rows if r.get("result")), None)
if PUBLIC:
    # A final named announcement proves an attack, not a knockout. Public
    # footage can end during the animation or show a concession. Keep the
    # visible attack without inventing zero HP or a lost party marker.
    for q in last:
        if not q["move"]:
            continue
        look = {"t": round(end - T0, 2), "note": "final attack announcement; damage and remaining count unreadable"}
        if q["side"] == "mine":
            look["my_charged"] = q["move"]
        else:
            look.update(foe_charged=True, foe_move=q["move"])
        looks.append(look)
elif last and last[-1]["side"] == "mine":  # the battle ended on our charged move: the result screen stands in for the last look
    looks.append({"t": round(end - T0, 2), "my_charged": last[-1]["move"] or "left", "foe_hp": 0.0, "foe_left": left["theirs"] - 1,
                  "note": "from the result screen, not a fighting frame"})
elif result == "win":  # the last knock-out was a fast move, with no replacement to announce it
    looks.append({"t": round(end - T0, 2), "foe_hp": 0.0, "foe_left": left["theirs"] - 1, "note": "from the result screen"})
elif result == "loss":
    looks.append({"t": round(end - T0, 2), "my_hp": 0.0, "my_left": left["mine"] - 1, "note": "from the result screen"})
out.mkdir(parents=True, exist_ok=True)
order = list(dict.fromkeys([f["name"] for f in field["mine"]] + OURS))  # in the order they came out
team = {"pokemon": [{"species": name, **KNOWN.get(name, {})} for name in order[:3]]}
(out / "team.json").write_text(json.dumps(team, indent=2) + "\n")
(out / "observations.jsonl").write_text("".join(json.dumps(l) + "\n" for l in looks))
print(f"battle {which} of {len(battles)}; fight starts {T0}s into the recording; ours: {', '.join(order[:3])}; {len(looks)} looks over {end - T0:.0f}s of battle")
def on_field(side, t):
    on = [f for f in field[side] if f["t"] <= t]
    return on[-1]["name"] if on else "?"
print("fast-move steps seen in the health bars (size in pixels of 138: how many; gap to the next step in turns: how many)")
for side, other in (("mine", "theirs"), ("theirs", "mine")):
    groups = collections.defaultdict(lambda: [collections.Counter(), collections.Counter()])
    quiet = [s for s in level_steps[side] if not any(q["start"] <= s[0] < q["resume"] + 0.7 for q in seqs)]
    for (t, size), nxt in zip(quiet, quiet[1:] + [None]):
        pair = f"{on_field(other, t)} hitting {on_field(side, t)}"
        groups[pair][0][size] += 1
        if nxt and nxt[0] - t < 3.2 and on_field(other, nxt[0]) == on_field(other, t) and on_field(side, nxt[0]) == on_field(side, t) \
                and not any(t < q["start"] < nxt[0] for q in seqs):
            groups[pair][1][round((nxt[0] - t) / 0.5)] += 1
    for pair, (sizes, gaps) in groups.items():
        print(f"  {pair}: {sum(sizes.values())} steps; size " + " ".join(f"{k}:{v}" for k, v in sorted(sizes.items()))
              + "; gap " + " ".join(f"{k}:{v}" for k, v in sorted(gaps.items())))
print("charged moves: " + "; ".join(f"{q['start'] - T0:.0f}s {q['user'] or q['side']} {q['move'] or '?'}{' (blocked)' if q['blocked'] else ''}, {q['resume'] - q['start']:.1f}s" for q in seqs))
for side in ("mine", "theirs"):
    print(f"{side}: " + ", ".join(f"{f['t'] - T0:.0f}s {f['name']}{' (after a faint)' if f['faint'] else ''}" for f in field[side]))

# The bare timeline, in seconds since the fight started, for scripts that reason about timing (rhythm.py).
rel = lambda t: round(t - T0, 2)
(out / "timeline.json").write_text(json.dumps({
    "clip_origin_seconds": T0, "public_footage": PUBLIC,
    "end": rel(end), "result": next((r["result"] for r in rows if r.get("result")), None),
    "field": {side: [{"t": rel(f["t"]), "name": f["name"], "faint": f["faint"]} for f in field[side]] for side in field},
    "charged": [{"t": rel(q["start"]), "side": q["side"], "move": q["move"], "blocked": q["blocked"]} for q in seqs],
    "left": {side: [[rel(when - 0.5), v] for when, v in left_shown[key]] for side, key in (("mine", "m"), ("theirs", "o"))},
    "steps": {side: [[rel(t), size] for t, size in level_steps[side]] for side in level_steps},
    "buttons_on": [[rel(a), rel(b)] for a, b in live], "waits": [[rel(a), rel(b)] for a, b in waits],
}) + "\n")
