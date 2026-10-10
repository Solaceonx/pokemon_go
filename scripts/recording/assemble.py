"""Turn the frame readings and the announcement text of one recording into looks for the tracker."""
import collections, difflib, json, re, statistics, sys
from pathlib import Path
readings, text_path, out = sys.argv[1], sys.argv[2], Path(sys.argv[3])
rows = [json.loads(l) for l in open(readings)]
texts = [json.loads(l) for l in open(text_path)]
gm = json.load(open("data/gamemaster.json"))
species = sorted({p["speciesName"].split(" (")[0] for p in gm["pokemon"]})
moves = sorted({m["name"] for m in gm["moves"]})
OURS = ["Melmetal", "Altaria", "Jellicent"]
T0 = 24.7
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
bar_times = [r["t"] for r in rows if r["mh"] is not None or r["oh"] is not None]

# events from the announcement text
gos, seqs, prompts, seq = [], [], [], None
for s in texts:
    items = [t for _, t in s["text"]]; joined = canon(" ".join(items)); t = s["t"]
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
    if m and seq and t - seq["start"] < 14:
        seq["user"] = seq["user"] or nearest(m.group(1), species)
        seq["move"] = seq["move"] or nearest(m.group(2), moves, 0.8)
    if "blocked" in joined and seq and t - seq["start"] < 15: seq["blocked"] = True
for q in seqs:
    # A charged move is decided about 8.5 s after its cue and lands at about 9.5 s; fighting resumes at 10 s.
    q["resume"] = next((t for t in bar_times if t >= q["start"] + 9.5), rows[-1]["t"])
    if q["user"]: q["side"] = "mine" if q["user"] in OURS else "theirs"
end = next((r["t"] for r in rows if r["phase"] == "result" or r["result"]), rows[-1]["t"])

# who is on the field, and whether each change was a faint
def header_left(side, a, b):
    vals = [r[side]["left"] for r in rows if a <= r["t"] <= b and r[side]["left"] is not None]
    return statistics.mode(vals) if vals else None
field = {"mine": [], "theirs": []}
for t, name in gos:
    side = "mine" if name in OURS else "theirs"; key = "m" if side == "mine" else "o"
    faint = False
    if field[side]:
        before, after = header_left(key, t - 12, t - 1), header_left(key, t + 1, t + 6)
        last = [r[key + "h"] for r in rows if t - 8 <= r["t"] < t and r[key + "h"] is not None]
        faint = (before is not None and after is not None and after < before) or (bool(last) and statistics.median(last[-10:]) < 0.08) \
            or (side == "mine" and any(0 <= t - p < 4 for p in prompts))
    field[side].append({"t": t + 0.8, "name": name, "faint": faint})

def header_shields(key):
    """The header's shield counter, once it has shown the same number for half a second."""
    out, value, run = [], None, 0
    for r in rows:
        v = r[key]["sh"]
        if v is None: continue
        value, run = (value, run + 1) if v == value else (v, 1)
        if run == 30: out.append((r["t"], v))
    return out
header = {"mine": header_shields("m"), "theirs": header_shields("o")}
blocked = {"mine": 0, "theirs": 0}
looks, left, shields, emitted = [], {"mine": 3, "theirs": 3}, {"mine": 2, "theirs": 2}, set()
seen_hp, risen, dropped = {}, {"mine": 0, "theirs": 0}, {"mine": 0, "theirs": 0}
current = {"mine": None, "theirs": None}
n_bins = int((end - T0) * 2)
for b in range(n_bins + 1):
    t = T0 + 0.5 * b
    if any(q["start"] <= t < q["resume"] for q in seqs): continue
    look = {"t": round(t - T0, 2)}
    for side, prefix in (("mine", "my"), ("theirs", "foe")):
        on = [f for f in field[side] if f["t"] <= t]
        if on and on[-1] is not current[side]:
            if on[-1]["faint"]: left[side] -= 1
            current[side] = on[-1]
        if current[side]: look[f"{prefix}_species"] = current[side]["name"]
        key = "mh" if side == "mine" else "oh"
        vals = [r[key] for r in rows if t - 0.5 < r["t"] <= t and r[key] is not None]
        value = commonest(vals) if len(vals) >= 5 else None
        name = current[side]["name"] if current[side] else None
        if value is not None and name:
            before = seen_hp.get((side, name))
            if before is not None and value > before + 2.5 / W and risen[side] < 4:  # health cannot rise: a misread
                risen[side] += 1; dropped[side] += 1; value = None
            else:
                risen[side] = 0; seen_hp[side, name] = value
        if value is not None: look[f"{prefix}_hp"] = round(value, 4)
    for k, q in enumerate(seqs):
        if k not in emitted and q["resume"] <= t:
            emitted.add(k)
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
        looks.append(look)
last = [q for k, q in enumerate(seqs) if k not in emitted]
if last and last[-1]["side"] == "mine":  # the battle ended on our charged move: the result screen stands in for the last look
    looks.append({"t": round(end - T0, 2), "my_charged": last[-1]["move"] or "left", "foe_hp": 0.0, "foe_left": left["theirs"] - 1,
                  "note": "from the result screen, not a fighting frame"})

out.mkdir(parents=True, exist_ok=True)
team = {"pokemon": [{"species": "Melmetal", "fast": "Thunder Shock", "charged": ["Double Iron Bash", "Dynamic Punch"]},
                    {"species": "Altaria", "fast": "Dragon Breath", "charged": ["Sky Attack", "Flamethrower"]},
                    {"species": "Jellicent"}]}
(out / "team.json").write_text(json.dumps(team, indent=2) + "\n")
(out / "observations.jsonl").write_text("".join(json.dumps(l) + "\n" for l in looks))
print(f"{len(looks)} looks over {end - T0:.0f}s of battle; readings set aside because health rose: ours {dropped['mine']}, theirs {dropped['theirs']}")
print("charged moves: " + "; ".join(f"{q['start'] - T0:.0f}s {q['user'] or q['side']} {q['move'] or '?'}{' (blocked)' if q['blocked'] else ''}, {q['resume'] - q['start']:.1f}s" for q in seqs))
for side in ("mine", "theirs"):
    print(f"{side}: " + ", ".join(f"{f['t'] - T0:.0f}s {f['name']}{' (after a faint)' if f['faint'] else ''}" for f in field[side]))
