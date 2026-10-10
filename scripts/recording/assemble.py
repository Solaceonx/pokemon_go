"""Turn the frame readings and the announcement text of one recording into looks for the tracker."""
import bisect, collections, difflib, json, re, statistics, sys
from pathlib import Path
readings, text_path, out = sys.argv[1], sys.argv[2], Path(sys.argv[3])
def option(name, default):  # e.g. --every 4 keeps one frame in four, to try lower frame rates on a full reading
    return type(default)(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default
import gzip
lines = lambda path: (gzip.open(path, "rt") if str(path).endswith(".gz") else open(path))
rows = [json.loads(l) for l in lines(readings)][::option("--every", 1)]
texts = [json.loads(l) for l in lines(text_path)][::option("--text-every", 1)]
if "--middle-only" in sys.argv:  # to try doing without the lower text band
    for s in texts: s["text"] = [x for x in s["text"] if x[0] == "middle"]
FPS = 1.0 / statistics.median(b["t"] - a["t"] for a, b in zip(rows, rows[1:1000]))
SIXTH, HALF = max(3, round(FPS / 6)), max(4, round(FPS / 2))  # frames in a sixth of a second and in half a second
gm = json.load(open("data/gamemaster.json"))
species = sorted({p["speciesName"].split(" (")[0] for p in gm["pokemon"]})
moves = sorted({m["name"] for m in gm["moves"]})
KNOWN = {  # movesets we have been told; any other Pokémon of ours gets the usual moves until it shows otherwise
    "Melmetal": {"fast": "Thunder Shock", "charged": ["Double Iron Bash", "Dynamic Punch"]},
    "Altaria": {"fast": "Dragon Breath", "charged": ["Sky Attack", "Flamethrower"]},
}
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
T0 = round(next(r["t"] for r in rows if r["mh"] is not None and r["oh"] is not None) + 0.7, 1)

# events from the announcement text
gos, seqs, prompts, seq, words = [], [], [], None, []
for s in texts:
    items = [t for _, t in s["text"]]; joined = canon(" ".join(items)); t = s["t"]
    words.append((t, [w for w, part in (("super", "supere"), ("weak", "notve")) if part in joined]))
    for item in items:
        m = re.match(r"^\W*[Gg][Oo0]\W*\s*([A-Za-z][A-Za-z ]{3,})", item)
        if m:
            name = nearest(m.group(1), species)
            if name and not any(g[1] == name and t - g[0] < 8 for g in gos): gos.append((t, name))
    if "switchinanewpok" in joined: prompts.append(t)
    start = "mine" if "getready" in joined else "theirs" if "ackincoming" in joined else None
    if start and (seq is None or t - seq["start"] > 9):
        seq = {"side": start, "start": t, "move": None, "user": None, "blocked": False}; seqs.append(seq)
    m = re.search(r"([a-z]{4,})used([a-z]+)", joined)
    if m and not (seq and t - seq["start"] < 14):
        # "X used Y!" with no cue read before it (the cue can sit under other text): the cue comes about 7 s
        # earlier. Whose move it was is settled from the name below, or failing that from a shield going.
        user = nearest(m.group(1), species)
        if user:
            seq = {"side": None, "start": t - 7.2, "move": None, "user": None, "blocked": False, "late": True}; seqs.append(seq)
    if m and seq and t - seq["start"] < 14:
        seq["user"] = seq["user"] or nearest(m.group(1), species)
        seq["move"] = seq["move"] or nearest(m.group(2), moves, 0.8)
    if "blocked" in joined and seq and t - seq["start"] < 15: seq["blocked"] = True
for q in seqs:
    # A charged move is decided about 8.5 s after its cue and lands at about 9.5 s; fighting resumes at 10 s.
    q["resume"] = next((t for t in bar_times if t >= q["start"] + 9.5), rows[-1]["t"])
    if q["user"] and (q["user"] in OURS) != (q["user"] in THEIRS):  # the cue says whose move it is; the name confirms
        q["side"] = "mine" if q["user"] in OURS else "theirs"
    if q["side"] is None:  # no cue and both teams have that Pokémon: we only block their moves, so guess from that
        q["side"] = "theirs"
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
ENTER = 0.2  # a Pokémon is on the field and attacking this long after its "Go, X!" is first read
field = {"mine": [], "theirs": []}
for t, name in gos:
    side = "mine" if name in OURS else "theirs"
    if name in OURS and name in THEIRS:
        # Both teams have one: it came out on the side whose header changes to that name.
        def shown(key):
            after = [nearest(r[key]["sp"], species) for r in rows if t + 0.5 <= r["t"] <= t + 8 and r[key]["sp"]]
            return bool(after) and collections.Counter(after).most_common(1)[0][0] == name
        was = {k: (field[k][-1]["name"] if field[k] else None) for k in field}
        if was["mine"] == name: side = "theirs"
        elif was["theirs"] == name: side = "mine"
        elif shown("o") and not shown("m"): side = "theirs"
    key = "m" if side == "mine" else "o"
    faint = False
    if field[side]:
        before, after = header_left(key, t - 12, t - 1), header_left(key, t + 1, t + 6)
        last = [r[key + "h"] for r in rows if t - 8 <= r["t"] < t and r[key + "h"] is not None]
        # The counter of Pokémon left falls when one faints; the next to come out on that side is its replacement.
        earlier, now = left_at(key, field[side][-1]["t"] + 3), left_at(key, t + 6)
        faint = (earlier is not None and now is not None and now < earlier) \
            or (before is not None and after is not None and after < before) or (bool(last) and statistics.median(last[-10:]) < 0.08) \
            or (side == "mine" and any(0 <= t - p < 4 for p in prompts))
    field[side].append({"t": t + ENTER, "name": name, "faint": faint})

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
    changes = [f["t"] - ENTER for f in field[side]]
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
            fell = [when - 0.5 for when, _ in left_shown[key][1:] if when - 0.5 <= f["t"] - ENTER]
            waits.append((fell[-1] if fell else f["t"] - 2.8, f["t"] - 0.5))
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
        shields[side] = min([shields[side], 2 - blocked[side]] + shown[-1:])
    look.update(my_shields=shields["mine"], foe_shields=shields["theirs"], my_left=left["mine"], foe_left=left["theirs"])
    if "my_hp" in look or "foe_hp" in look or "my_charged" in look or "foe_charged" in look or not looks:
        since = T0 + looks[-1]["t"] if looks else t
        stood = sum(max(0.0, min(t, b) - max(since, a)) for a, b in waits)
        if stood > 0: look["paused"] = round(stood, 2)
        looks.append(look)
last = [q for k, q in enumerate(seqs) if k not in emitted]
if last and last[-1]["side"] == "mine":  # the battle ended on our charged move: the result screen stands in for the last look
    looks.append({"t": round(end - T0, 2), "my_charged": last[-1]["move"] or "left", "foe_hp": 0.0, "foe_left": left["theirs"] - 1,
                  "note": "from the result screen, not a fighting frame"})

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
    "end": rel(end), "result": next((r["result"] for r in rows if r.get("result")), None),
    "field": {side: [{"t": rel(f["t"] - ENTER), "name": f["name"], "faint": f["faint"]} for f in field[side]] for side in field},
    "charged": [{"t": rel(q["start"]), "side": q["side"], "move": q["move"], "blocked": q["blocked"]} for q in seqs],
    "left": {side: [[rel(when - 0.5), v] for when, v in left_shown[key]] for side, key in (("mine", "m"), ("theirs", "o"))},
    "steps": {side: [[rel(t), size] for t, size in level_steps[side]] for side in level_steps},
}) + "\n")
