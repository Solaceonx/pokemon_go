#!/usr/bin/env python3
"""The battle page: one plain, unlisted HTML page about the bot's live league battles, built from the records.

    python3 scripts/live/battle_page.py OUT.html

Three parts, all from games/live/ (task 45's records, scripts/live/live_record.py) and data/engine_history.json:
1. The engine: which engine played each league battle (the log's start row, else the bot's commit against the commits
   in engine_history.json's `versions`), its record and our mean accuracy; then the changes tested, from the file.
2. The teams we have met, by league: each team (the Pokémon seen), how often, our record against it, the highest rank
   we met it at, and a weight that puts low ranks last: rank 20 and up counts 1, below that rank / 20 (rank 10: 0.5).
   A battle whose rank was not read takes the account's last reading before it; none yet: 0.5.
3. A review of each battle for both sides (scripts/live/battle_review.py on `ultra-league` writes review.json beside
   each record): accuracy, mistakes, blunders and the worst moment.
No trainer names: the records hold none (tests/test_live_records.py checks). Standard library only.
"""
from __future__ import annotations

import html
import json
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GAMES = ROOT / "games" / "live"
PT = timezone(timedelta(hours=-8))
LEAGUES = {"Great League Edition": "Mega Catch Cup (Great League)", "Great League: Mega": "Great League: Mega Edition",
           "Great League: Mega Edition": "Great League: Mega Edition", "Ultra League": "Ultra League"}
STYLE = """body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;max-width:1100px;margin:24px auto;
padding:0 16px;color:#222;background:#fff;line-height:1.4;font-size:15px}h1{font-size:22px}h2{font-size:18px;
margin-top:32px;border-bottom:1px solid #ddd}h3{font-size:15px}table{border-collapse:collapse;font-size:13px;margin:8px 0}
td,th{border:1px solid #ccc;padding:3px 6px;text-align:left;vertical-align:top}th{background:#f4f4f4}
.wrap{overflow-x:auto}.n{text-align:right}p.small{font-size:13px;color:#555}"""


def esc(x) -> str:
    return html.escape("" if x is None else str(x))


def table(head: list, rows: list, numeric: set = frozenset()) -> str:
    h = "".join(f"<th>{esc(c)}</th>" for c in head)
    body = "".join("<tr>" + "".join(f'<td{" class=n" if i in numeric else ""}>{c}</td>' for i, c in enumerate(r)) + "</tr>"
                   for r in rows)
    return f'<div class="wrap"><table><tr>{h}</tr>{body}</table></div>'


def ancestor(a: str, c: str, cache: dict) -> bool:
    if (a, c) not in cache:
        r = subprocess.run(["git", "merge-base", "--is-ancestor", a, c], cwd=ROOT, capture_output=True)
        cache[(a, c)] = r.returncode == 0
    return cache[(a, c)]


def engine_label(rec: dict, start: dict, versions: list, cache: dict) -> str:
    eng = start.get("engine")
    if isinstance(eng, str) and eng.startswith("lab:"):
        lab = eng[4:]
        return next((v["label"] for v in versions if v.get("lab") == lab), f"Lab engine {lab}")
    commit = ((rec["source"].get("bot") or {}).get("commit")) or start.get("commit")
    if eng == "":
        return "Website engine (POGO_ENGINE empty)"
    for v in versions:
        if v.get("lab") or not v.get("commit"):
            continue
        if commit and ancestor(v["commit"], commit, cache):
            return v["label"]
    return versions[-1]["label"]


def odds() -> dict:
    """Each league battle's chance before it began (scripts/live/odds.py): {stamp: {"chance", "margin", ...}}."""
    path = GAMES / "odds.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def load() -> list:
    out = []
    for path in sorted(GAMES.glob("2*/game.json")):
        rec = json.loads(path.read_text(encoding="utf-8"))
        if rec["source"]["mode"] != "league" or (rec["result"] or {}).get("value") == "fragment":
            continue
        log = path.parent / "log.jsonl"
        start = {}
        if log.exists():
            with log.open(encoding="utf-8") as f:
                for line in f:
                    r = json.loads(line)
                    if r.get("kind") == "start":
                        start = r
                        break
        review = path.parent / "review.json"
        out.append({"stamp": path.parent.name, "rec": rec, "start": start,
                    "review": json.loads(review.read_text(encoding="utf-8")) if review.exists() else None})
    return out


def when(b: dict) -> datetime:
    s = b["rec"]["source"].get("started_utc")
    if s:
        return datetime.fromisoformat(s).astimezone(PT)
    return datetime.strptime(b["stamp"], "%Y%m%d-%H%M%S").replace(tzinfo=PT)


def ranks(battles: list) -> None:
    """Each battle's rank: read before it, else the account's last reading before it (carried)."""
    last = {}
    for b in sorted(battles, key=when):
        st = b["rec"].get("standing") or b["start"].get("standing") or {}
        acct = b["rec"]["source"].get("account")
        if isinstance(st, dict) and st.get("rank"):
            last[acct] = st
            b["rank"], b["rank_from"] = st["rank"], "read"
        elif acct in last:
            b["rank"], b["rank_from"] = last[acct]["rank"], "carried"
        else:
            b["rank"], b["rank_from"] = None, None


def weight(rank) -> float:
    if rank is None:
        return 0.5
    return 1.0 if rank >= 20 else max(0.05, rank / 20)


def result(b: dict) -> str:
    return (b["rec"]["result"] or {}).get("value") or "?"


def names(side: list) -> str:
    return " / ".join(m.get("name") or m["species"] for m in side)


def pct(w: int, n: int) -> str:
    return f"{100 * w / n:.0f}%" if n else ""


def worst(side: dict | None) -> str:
    d = (side or {}).get("worst")
    if not d:
        return ""
    win = ", ".join(f"{k} {v}%" for k, v in d["win"].items())
    return esc(f"{d['t']:.0f} s, {d['kind']}: {d['chosen']} (gave up {d['lost']:.0f}; {win})")


def build() -> str:
    hist = json.loads((ROOT / "data" / "engine_history.json").read_text(encoding="utf-8"))
    battles = load()
    chances = odds()
    for b in battles:
        o = chances.get(b["stamp"]) or {}
        b["chance"] = o.get("chance")
    ranks(battles)
    cache: dict = {}
    for b in battles:
        b["engine"] = engine_label(b["rec"], b["start"], hist["versions"], cache)
        b["league"] = LEAGUES.get(b["rec"]["source"].get("league"), "League not read")
    battles.sort(key=when)
    wins = sum(result(b) == "win" for b in battles)
    losses = sum(result(b) == "loss" for b in battles)
    reviewed = [b for b in battles if b["review"]]
    now = datetime.now(PT).strftime("%Y-%m-%d %H:%M PT")
    parts = [f"<h1>Pokémon GO bot: league battles</h1><p>Updated {now}. {len(battles)} GO Battle League battles played "
             f"by the bot on the phone since {when(battles[0]):%Y-%m-%d}: {wins} won, {losses} lost. Built from the "
             f"battle records by <code>scripts/live/battle_page.py</code>.</p>"]

    # 1. the engine
    current = hist.get("now") or battles[-1]["engine"]
    by_eng = defaultdict(list)
    for b in battles:
        by_eng[b["engine"]].append(b)
    rows = []
    for label in [v["label"] for v in hist["versions"]]:
        bs = by_eng.get(label, [])
        if not bs:
            continue
        w, l = sum(result(b) == "win" for b in bs), sum(result(b) == "loss" for b in bs)
        acc = [b["review"]["sides"]["mine"]["accuracy"] for b in bs if b["review"] and b["review"]["sides"]["mine"]["accuracy"] is not None]
        rows.append([esc(label), f"{when(bs[0]):%m-%d} to {when(bs[-1]):%m-%d}", len(bs), w, l, pct(w, w + l),
                     f"{sum(acc) / len(acc):.1f}" if acc else ""])
    parts.append(f"<h2>1. The engine</h2><p>On the phone now: <b>{esc(current)}</b> (the last set: {esc(battles[-1]["engine"])}).</p><h3>Live record by engine</h3>"
                 + table(["Engine", "Dates", "Battles", "Won", "Lost", "Win %", "Our accuracy"], rows, {2, 3, 4, 5, 6})
                 + "<p class=small>Opponents get stronger as the accounts climb, so later engines met harder players.</p>"
                 + "<h3>Changes tested in the simulator</h3>"
                 + table(["Date", "Change", "Result (95% margins)", "Kept"],
                         [[esc(c["date"]), esc(c["change"]), esc(c["result"]), esc(c["kept"])] for c in hist["changes"]]))

    # 2. teams met
    parts.append("<h2>2. Teams we have met</h2><p>Their Pokémon as seen in each battle (a battle that ended before "
                 "the third came out lists two). Weight puts low ranks last: a battle at rank 20 or above counts 1, below "
                 "that rank ÷ 20 (rank 10 counts 0.5); a battle whose rank was not read takes the account's last reading "
                 "(no reading yet: 0.5).</p>")
    for league in sorted({b["league"] for b in battles}, key=lambda x: -sum(b["league"] == x for b in battles)):
        bs = [b for b in battles if b["league"] == league]
        teams, species = defaultdict(list), defaultdict(list)
        for b in bs:
            theirs = b["rec"]["teams"]["theirs"]
            teams[" / ".join(sorted(m.get("name") or m["species"] for m in theirs))].append(b)
            for m in theirs:
                species[m.get("name") or m["species"]].append(b)

        def rows_of(groups):
            out = []
            for key, gb in groups.items():
                w = sum(result(b) == "win" for b in gb)
                l = sum(result(b) == "loss" for b in gb)
                rk = [b["rank"] for b in gb if b["rank"]]
                out.append((sum(weight(b["rank"]) for b in gb), [esc(key), len(gb), f"{sum(weight(b['rank']) for b in gb):.2f}",
                            f"{w}-{l}", max(rk) if rk else "", f"{when(gb[-1]):%m-%d}"]))
            return [r for _, r in sorted(out, key=lambda x: (-x[0], x[1][0]))]
        parts.append(f"<h3>{esc(league)}: {len(bs)} battles</h3><details><summary>Teams ({len(teams)})</summary>"
                     + table(["Their team", "Met", "Weight", "Our W-L", "Highest rank", "Last met"], rows_of(teams), {1, 2, 4})
                     + f"</details><details><summary>Pokémon ({len(species)})</summary>"
                     + table(["Pokémon", "Met", "Weight", "Our W-L", "Highest rank", "Last met"], rows_of(species), {1, 2, 4})
                     + "</details>")

    # 3. reviews
    parts.append("<h2>3. Battle reviews, both sides</h2><p>Every throw, shield and voluntary switch either side made "
                 "is played on to the end of the battle against the other choices it had (24 times each, the trained bot "
                 "playing both sides with varied habits, the same dice for every choice) and scored by the win chance it "
                 "gave up against the best choice, counted only beyond the 95% margin. Accuracy uses a chess site's curve: "
                 "nothing given up is 100, 10 points about 62, 20 points about 39; a side's accuracy is the mean over its "
                 "decisions. Blunder: 20 points or more given up; mistake: 10 to 20. Both teams are judged as known at the "
                 "battle's end, so the review knows what neither player knew at the time. Not yet scored: holding energy "
                 "and replacements after a faint (the opponent's holds cannot be seen). An estimated rating per side will "
                 "follow once we have rated battles to calibrate it.</p>")
    if reviewed:
        srows = []
        for league in sorted({b["league"] for b in reviewed}):
            bs = [b for b in reviewed if b["league"] == league]
            m = [b["review"]["sides"]["mine"] for b in bs]
            t = [b["review"]["sides"]["theirs"] for b in bs]
            def mean(xs):
                acc = [x["accuracy"] for x in xs if x["accuracy"] is not None]
                return f"{sum(acc) / len(acc):.1f}" if acc else ""
            srows.append([esc(league), len(bs), mean(m), mean(t), f"{sum(x['blunder'] for x in m) / len(bs):.2f}",
                          f"{sum(x['blunder'] for x in t) / len(bs):.2f}"])
        parts.append(table(["League", "Battles reviewed", "Our accuracy", "Their accuracy", "Our blunders a battle",
                            "Their blunders a battle"], srows, {1, 2, 3, 4, 5}))
    erows = []
    for league in sorted({b["league"] for b in battles}):
        bs = [b for b in battles if b["league"] == league and b["chance"] is not None and result(b) in ("win", "loss", "draw")]
        if bs:
            exp = sum(b["chance"] for b in bs)
            won = sum(result(b) == "win" for b in bs) + 0.5 * sum(result(b) == "draw" for b in bs)
            erows.append([esc(league), len(bs), f"{exp:.1f}", f"{won:g}", f"{won - exp:+.1f}"])
    parts.append("<h3>Wins expected from the line-ups</h3><p>Each battle's chance before it began: our team against "
                 "theirs as seen (a Pokémon not seen filled at random from PvPoke's Great League ranks 101 to 400), "
                 "300 battles of two equally good bots (<code>scripts/live/odds.py</code>). Above the expected: we "
                 "played better than the bots, or met weaker players; below: the reverse.</p>"
                 + table(["League", "Battles with odds", "Wins expected", "Wins", "Difference"], erows, {1, 2, 3, 4}))
    rows = []
    for b in sorted(battles, key=when, reverse=True):
        rv = b["review"] or {}
        m, t = (rv.get("sides") or {}).get("mine") or {}, (rv.get("sides") or {}).get("theirs") or {}
        rows.append([f"{when(b):%m-%d %H:%M}", esc(b["league"]), esc(b["rec"]["source"].get("account")),
                     esc(b["rank"] if b["rank"] else ""), esc(names(b["rec"]["teams"]["theirs"])), esc(result(b)),
                     esc(f"{100 * b['chance']:.0f}%" if b["chance"] is not None else ""),
                     esc(m.get("accuracy", "")), esc(t.get("accuracy", "")),
                     esc(f"{m.get('blunder', '')}/{t.get('blunder', '')}" if rv else ""), worst(m), worst(t)])
    parts.append(table(["Date (PT)", "League", "Account", "Rank", "Their team", "Result", "Chance before", "Our accuracy",
                        "Their accuracy", "Blunders (ours/theirs)", "Our worst moment", "Their worst moment"], rows, {3, 6, 7, 8}))
    # 4. the creators' battles (scripts/lab/creator_accuracy.py on ultra-league, copied to data/creator_accuracy.json)
    ca = ROOT / "data" / "creator_accuracy.json"
    if ca.exists():
        acc = json.loads(ca.read_text(encoding="utf-8"))
        label = {"player": "The creators (all three)", "website": "Today's website engine", "bot": "The trained bot alone"}
        parts.append("<h2>4. The creators' battles</h2><p>The same accuracy, on the "
                     f"{acc['decisions']} checked decisions of three strong players' recorded battles (reis2occasion, "
                     "HomeSliceHenry, ItsAXN; the creator exam, <code>scripts/lab/creator_exam.py</code>): every legal "
                     "choice at each decision played to the end 100 times, our bot continuing for them, against two kinds "
                     f"of opponent; a loss under {acc['noise']:g} points counts as none. Our engines are scored on the "
                     "same decisions. <b>The judge is our own simulator and bot, which favour bot-like choices:</b> that "
                     "the engines score above the creators here says the creators often choose what our bot would not, "
                     "not that the engines play better; the creators win far more against people. Not comparable with "
                     "section 3's numbers (24 play-outs there, both teams as known at the end).</p>")
        for opp, tab in acc["tables"].items():
            order = ["player"] + sorted(k for k in tab if k not in ("player", "website", "bot")) + ["website", "bot"]
            rows = []
            for who in order:
                if who not in tab:
                    continue
                t = tab[who]
                cell = lambda k: f"{t[k]['accuracy']:.1f}" if k in t else ""
                rows.append([esc(label.get(who, who)), f"{t['all']['accuracy']:.1f} ± {t['all']['margin']:.1f}", t["all"]["n"],
                             cell("switch"), cell("shield"), cell("throw"), cell("hold")])
            parts.append(f"<h3>Judged against {'people-like' if opp == 'people' else 'the bot crowd as'} opponents</h3>"
                         + table(["Player", "Accuracy (all)", "Decisions", "Switch", "Shield", "Throw", "Hold"], rows,
                                 {1, 2, 3, 4, 5, 6}))
    return ("<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content=\"width=device-width,"
            "initial-scale=1\"><meta name=robots content=\"noindex,nofollow\"><title>Bot battles</title>"
            f"<style>{STYLE}</style></head><body>" + "".join(parts) + "</body></html>\n")


if __name__ == "__main__":
    out = Path(sys.argv[1])
    out.write_text(build(), encoding="utf-8")
    print(f"wrote {out}")
