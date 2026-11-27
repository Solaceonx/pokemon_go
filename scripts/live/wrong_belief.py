"""How long the live player's belief about which of ours is out was wrong, from a replay with POGO_DEBUG_ACTIVE=1
the screen's evidence (our header's name, else the type icons read in the last second) against `active`, sustained
over consecutive checks. wrong_belief.py REPLAY_LOG..."""
import json, sys
canon = lambda s: "".join(ch for ch in (s or "").upper() if ch.isalpha())
for path in sys.argv[1:]:
    rows = [json.loads(l) for l in open(path) if l.strip()]
    team = next((r["team"] for r in rows if r["kind"] == "team"), [])
    names = [canon(m[0]) for m in team]
    spans, start, last_t = [], None, None
    for r in rows:
        if r["kind"] != "dbg_active":
            continue
        h = canon(r.get("header"))
        ev = next((j for j, n in enumerate(names) if len(h) >= 4 and (n in h or h in n)), None)
        ts = r.get("types_seen")
        if ev is None and ts and r["t"] - ts[1] < 1.0:
            ev = ts[0]
        act = next((j for j, n in enumerate(names) if n == canon(r["active"])), None)
        wrong = ev is not None and act is not None and ev != act
        if wrong and start is None:
            start = r["t"]
        if not wrong and start is not None:
            spans.append((round(start, 1), round(r["t"] - start, 1))); start = None
    if start is not None:
        spans.append((round(start, 1), round(rows[-1]["t"] - start, 1)))
    long = [s for s in spans if s[1] >= 1.0]
    print(f"{path.split('/')[-1][:15]} wrong-belief spans of 1 s or more: {long}  total {sum(d for _, d in long):.1f} s")
