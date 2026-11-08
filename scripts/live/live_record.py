#!/usr/bin/env python3
"""One game record per battle the bot played on the phone (task 40), in the format of the recorded-game pipeline
(schema game-record-v1, docs/game_record.md on the game-record-and-charged-damage branch), built from the live
player's log.

    python3 scripts/live/live_record.py                 every log in runs/live/
    python3 scripts/live/live_record.py STAMP [STAMP ...]

For each runs/live/<STAMP>.jsonl (scripts/live/play_android.py) it writes games/live/<STAMP>/game.json and game.txt,
and games/live/index.json listing them all. Nothing is read from the video. Notes on what went wrong, from the
analysis of each battle, come from games/live/notes.json ({stamp: {"went_wrong": ..., "fixed": ...}}).

What differs from a record of a recording (`variant: "live-log"`):
- `mine` is the bot; our team is as the bot was told it (`team_sheet`).
- A charged move's time is when the bot saw it start (Get Ready!, its minigame's icons, or its prompt); ours carry
  the minigame's swipe (`icons_chased`), theirs whether we shielded.
- `state` is what the live tracker believed at the look just before the action, as logged: their energy is the
  tracker's `[low, high]`, our energy the buttons' reading when there was one (`energy_from: "buttons"`), else the
  count.
- `bot` lists what the player itself did wrong or doubted, counted from its log: throws not taken, decisions
  dropped, tracker and engine errors, and so on.
Standard library only.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOGS = ROOT / "runs" / "live"
OUT = ROOT / "games" / "live"
SCHEMA = "game-record-v1"
# the Team Leaders' teams in training (Blanche, Candela, Spark): a battle against one is training, the rest league
LEADERS = {"sneasel", "sealeo", "plusle", "electrode", "combusken", "flareon", "uxie", "muk"}
# events in the log that say the player went wrong or was unsure
BOT_EVENTS = ("throw_not_taken", "throw_beaten", "throw_cancelled", "throw_fainted", "queued_dropped",
              "switch_not_taken", "decision_dropped", "active_corrected", "move_corrected", "tracker_error",
              "engine_error", "armed", "armed_fired", "armed_expired", "armed_replaced", "throw_before_fainting",
              "throw_before_theirs", "waiting_for_better", "shield_override", "fainted_unprompted",
              "their_charged_unprompted", "minigame_seen", "no_fight")


def load_names():
    """Display names and move costs from the game data, if it is here."""
    try:
        sys.path.insert(0, str(ROOT))
        from pogo.gamedata import GameData
        gd = GameData()
        return ({k: v["speciesName"] for k, v in gd.species.items()},
                {k: (m.name, m.energy, m.turns, m.energy_gain) for k, m in gd.moves.items()})
    except Exception:  # noqa: BLE001
        return {}, {}


SPECIES, MOVES = load_names()


def sname(sid):
    return SPECIES.get(sid, sid) if sid else None


def mname(mid):
    return MOVES.get(mid, (mid,))[0] if mid else None


def base(sid):
    """The screen name a species shows under: its forms share one (Arcanine, Hisuian Arcanine)."""
    return (sname(sid) or "").split(" (")[0]


def num(x):
    return int(x) if isinstance(x, str) and x.isdigit() else x


class Battle:
    def __init__(self, stamp: str, rows: list[dict]):
        self.stamp, self.rows = stamp, rows
        self.looks = [r for r in rows if r["kind"] == "look"]

    def look_before(self, t):
        best = None
        for lk in self.looks:
            if lk["t"] > t:
                break
            best = lk
        return best

    def state(self, t):
        lk = self.look_before(t)
        if lk is None:
            return None
        o, foe = lk["obs"], lk.get("foe") or []
        mine = {"active": o.get("my_species"), "hp_share": o.get("my_hp"), "shields": num(o.get("my_shields")),
                "left": num(o.get("my_left"))}
        if o.get("my_energy") is not None:
            mine["energy"], mine["energy_from"] = round(o["my_energy"]), "buttons"
        else:
            mine["energy"], mine["energy_from"] = lk.get("counted"), "count"
        theirs = {"active": foe[0] if foe else o.get("foe_species"), "hp_share": o.get("foe_hp"),
                  "shields": num(o.get("foe_shields")), "left": num(o.get("foe_left")),
                  "energy": [foe[1], foe[2]] if len(foe) >= 3 else None,
                  "fast_move": foe[3] if len(foe) >= 4 else None}
        return {"look_t": lk["t"], "mine": mine, "theirs": theirs}

    def record(self, notes: dict | None) -> dict:
        rows = self.rows
        team_row = next((r for r in rows if r["kind"] == "team"), None)
        end = next((r for r in rows if r["kind"] == "end"), None)
        start = next((r for r in rows if r["kind"] == "start"), None)
        mine_team = []
        for sid, fast, charged, cp in (team_row or {}).get("team", []):
            mine_team.append({"species": sid, "name": sname(sid), "known_from": "team_sheet", "cp": cp,
                              "fast_move": {"id": fast, "name": mname(fast), "known_from": "team_sheet"},
                              "charged_moves": [{"id": c, "name": mname(c), "energy": MOVES.get(c, (0, None))[1],
                                                 "known_from": "team_sheet", "times_used": 0} for c in charged],
                              "fainted": False})
        by_id = {p["species"]: p for p in mine_team}
        # their team, in order of first appearance; the last thing the tracker believed of each. A form the tracker
        # worked out later (Hisuian Arcanine, first taken for the regular one) is the same Pokémon: the last form stands.
        final = {}
        for lk in self.looks:
            sid = (lk.get("foe") or [None])[0] or lk["obs"].get("foe_species")
            if sid:
                final[base(sid)] = sid
        self.final = final
        theirs, order = {}, []
        for lk in self.looks:
            foe = lk.get("foe")
            sid = (foe or [None])[0] or lk["obs"].get("foe_species")
            if not sid:
                continue
            sid = final.get(base(sid), sid)
            if sid not in theirs:
                order.append(sid)
                theirs[sid] = {"species": sid, "name": sname(sid), "known_from": "seen", "charged_moves": {},
                               "fast_move": None, "fainted": False}
            if foe and len(foe) >= 5:
                theirs[sid]["fast_move"] = {"id": foe[3], "name": mname(foe[3]),
                                            "known_from": {"inferred": "inferred", "guessed": "guessed"}.get(foe[4], foe[4])}
        actions, active_foe = [], None
        if self.looks:
            o = self.looks[0]["obs"]
            first_foe = next((lk["obs"].get("foe_species") for lk in self.looks if lk["obs"].get("foe_species")), None)
            actions.append({"kind": "start", "t": 0.0, "mine": o.get("my_species"), "theirs": first_foe})
        prompts = []  # their throws we were asked to shield: (t, shielded)
        last_named = -99.0
        foe_left = None
        prev_foe = None
        for r in rows:
            k, t = r["kind"], r["t"]
            if k == "look":
                o = r["obs"]
                sid = (r.get("foe") or [None])[0] or o.get("foe_species")
                sid = self.final.get(base(sid), sid) if sid else sid
                fl = num(o.get("foe_left"))
                if prev_foe and sid and sid != prev_foe:
                    fainted = fl is not None and foe_left is not None and fl < foe_left
                    if fainted:
                        theirs.get(prev_foe, {})["fainted"] = True
                    actions.append({"kind": "faint" if fainted else "switch", "t": t, "side": "theirs",
                                    "pokemon" if fainted else "from": prev_foe, "next" if fainted else "to": sid,
                                    "known_from": "seen", "state": self.state(t)})
                if sid:
                    prev_foe = sid
                if fl is not None:
                    foe_left = fl if foe_left is None else min(foe_left, fl)
            elif k == "throw_started":
                lk = self.look_before(t)
                sid = lk["obs"].get("my_species") if lk else None
                move = r["move"]
                if sid in by_id:
                    for c in by_id[sid]["charged_moves"]:
                        if c["id"] == move:
                            c["times_used"] += 1
                actions.append({"kind": "charged", "side": "mine", "t": r.get("cue_t", t), "pokemon": sid,
                                "move": mname(move), "move_id": move, "cost": MOVES.get(move, (0, None))[1],
                                "seen_by": "queued" if r.get("queued") else ("icons" if r.get("by") else "Get Ready!"),
                                "seconds_after_tap": r.get("after_tap_s"), "state": self.state(t)})
            elif k == "minigame":
                for a in reversed(actions):
                    if a["kind"] == "charged" and a["side"] == "mine" and a.get("move_id") == r["move"]:
                        a["icons_chased"] = r.get("icons_seen")
                        break
            elif k == "shield_prompt":
                prompts.append((t, bool(r.get("shield"))))
                actions.append({"kind": "charged", "side": "theirs", "t": t, "pokemon": prev_foe, "move": None,
                                "move_id": None, "move_known_from": None, "shielded": bool(r.get("shield")),
                                "seen_by": "shield prompt", "their_energy_believed": r.get("foe_energy"),
                                "state": self.state(t)})
            elif k in ("their_charged_named", "their_charged_unprompted"):
                move = r.get("move")
                recent = [a for a in actions if a["kind"] == "charged" and a["side"] == "theirs" and t - a["t"] < 12.0]
                new = False
                if k == "their_charged_named" and (r.get("prompted") or r.get("counted_already")) and recent:
                    a = recent[-1]  # the words of a throw already noted at its prompt
                    if a["move_id"] is None:
                        a["move_id"], a["move"], a["move_known_from"] = move, mname(move), "seen"
                        a["cost"] = MOVES.get(move, (0, None))[1]
                        new = True
                elif k == "their_charged_named" and t - last_named < 3.0:
                    pass
                else:
                    new = True
                    actions.append({"kind": "charged", "side": "theirs", "t": t, "pokemon": prev_foe,
                                    "move": mname(move), "move_id": move, "cost": MOVES.get(move, (0, None))[1] if move else None,
                                    "move_known_from": "seen" if move else None, "shielded": False,
                                    "seen_by": "words" if move else "pause", "state": self.state(t)})
                if move:
                    last_named = t
                if move and new:
                    if prev_foe in theirs:
                        cm = theirs[prev_foe]["charged_moves"]
                        cm[move] = cm.get(move, 0) + 1
            elif k == "switch_seen":
                lk = self.look_before(t - (r.get("after_tap_s") or 0) - 0.05)
                actions.append({"kind": "switch", "side": "mine", "t": t, "from": lk["obs"].get("my_species") if lk else None,
                                "to": next((p["species"] for p in mine_team if p["name"] == r.get("to")), r.get("to")),
                                "seconds_after_tap": r.get("after_tap_s"), "state": self.state(t)})
            elif k in ("replace", "fainted_unprompted"):
                lk = self.look_before(t)
                was = lk["obs"].get("my_species") if lk else None
                if was in by_id:
                    by_id[was]["fainted"] = True
                nxt = r.get("to") or r.get("now")
                actions.append({"kind": "faint", "side": "mine", "t": t, "pokemon": was,
                                "next": next((p["species"] for p in mine_team if p["name"] == nxt), nxt),
                                "state": self.state(t)})
        # their charged moves named (count of each) into the team list
        for sid, p in theirs.items():
            p["charged_moves"] = [{"id": m, "name": mname(m), "energy": MOVES.get(m, (0, None))[1], "known_from": "seen",
                                   "times_used": n} for m, n in p["charged_moves"].items()]
        result = end.get("result") if end else None
        if end:
            actions.append({"kind": "end", "t": end["t"], "result": result, "result_from": "result screen"})
        actions.sort(key=lambda a: a["t"])
        foes_final = (end or {}).get("foes") or order
        mode = "training" if set(foes_final) & LEADERS else "league"
        bot = Counter(r["kind"] for r in rows if r["kind"] in BOT_EVENTS)
        charged = Counter(a["side"] for a in actions if a["kind"] == "charged")
        rec = {
            "schema": SCHEMA, "variant": "live-log", "game": f"live-{self.stamp}",
            "source": {"kind": "live_bot", "mode": mode, "device": "android phone (the owner's spare account)",
                       "log": f"runs/live/{self.stamp}.jsonl",
                       "recording": f"battle-{self.stamp}.h264 / .mp4 with .times (not in git)",
                       "epoch": (start or {}).get("epoch")},
            "result": {"value": result, "from": "result screen" if end else "unknown"},
            "seconds": end["t"] if end else (rows[-1]["t"] if rows else 0),
            "teams": {"mine": mine_team, "theirs": [theirs[s] for s in order if s in theirs]},
            "summary": {"charged": {"mine": charged.get("mine", 0), "theirs": charged.get("theirs", 0)},
                        "we_shielded": sum(1 for _, s in prompts if s), "shield_prompts": len(prompts),
                        "fast_taps": sum(1 for r in rows if r["kind"] == "tap" and r.get("note") == "fast move"),
                        "looks": len(self.looks)},
            "bot": dict(bot),
            "notes": notes,
            "actions": actions,
            "built_from": [f"runs/live/{self.stamp}.jsonl"],
        }
        return rec


def text(rec: dict) -> str:
    res = (rec["result"]["value"] or "no result").upper()
    out = [f"{rec['game']} . {rec['source']['mode']} . {res} . {rec['seconds']:.0f} s"]
    if rec.get("notes"):
        out.append(f"What went wrong: {rec['notes'].get('went_wrong') or '-'}")
        if rec["notes"].get("fixed"):
            out.append(f"Fixed: {rec['notes']['fixed']}")
    out.append("")
    for side in ("mine", "theirs"):
        out.append("Mine" if side == "mine" else "Theirs")
        for p in rec["teams"][side]:
            fm = p.get("fast_move") or {}
            mark = {"inferred": "*", "guessed": "?"}.get(fm.get("known_from"), "")
            cms = ", ".join(f"{c['name']} x{c['times_used']}" for c in p["charged_moves"])
            out.append(f"  {p['name'] or p['species']:14s} {fm.get('name') or '?'}{mark} | {cms}"
                       f"{'  [fainted]' if p.get('fainted') else ''}")
    s = rec["summary"]
    out.append(f"\nCharged moves: ours {s['charged']['mine']}, theirs {s['charged']['theirs']}; shield prompts {s['shield_prompts']}, "
               f"shielded {s['we_shielded']}; fast taps {s['fast_taps']}")
    if rec["bot"]:
        out.append("Player events: " + ", ".join(f"{k} {v}" for k, v in sorted(rec["bot"].items())))
    out.append("")
    for a in rec["actions"]:
        st = a.get("state") or {}
        m, th = st.get("mine") or {}, st.get("theirs") or {}

        def hp(x):
            return f"{round(100 * x)}%" if isinstance(x, (int, float)) else "?"
        if a["kind"] == "start":
            line = f"start: {sname(a['mine'])} v {sname(a['theirs'])}"
        elif a["kind"] == "charged" and a["side"] == "mine":
            line = (f"ours   {sname(a['pokemon'])} {a['move']} (cost {a['cost']}; energy {m.get('energy')} by "
                    f"{m.get('energy_from')}; theirs believed {th.get('energy')})"
                    f"{'' if a.get('icons_chased') is None else ', swipe chased icons ' + str(a['icons_chased'])}"
                    f"{', seen ' + a['seen_by'] if a.get('seen_by') != 'Get Ready!' else ''}")
        elif a["kind"] == "charged":
            line = (f"theirs {sname(a['pokemon'])} {a['move'] or '(move not named)'}"
                    f" ({'we shielded' if a.get('shielded') else 'not shielded'}; their energy believed "
                    f"{a.get('their_energy_believed') or th.get('energy')}; our health {hp(m.get('hp_share'))})")
        elif a["kind"] == "switch":
            line = f"{a['side']:6s} switch {sname(a['from'])} -> {sname(a['to'])}"
        elif a["kind"] == "faint":
            line = f"{a['side']:6s} {sname(a['pokemon'])} fainted -> {sname(a['next'])}"
        else:
            line = f"end: {a.get('result')}"
        out.append(f"{a['t']:7.1f}  {line}")
    return "\n".join(out) + "\n"


def main(argv):
    notes = {}
    notes_path = OUT / "notes.json"
    if notes_path.exists():
        notes = json.loads(notes_path.read_text(encoding="utf-8"))
    stamps = argv or sorted(p.stem for p in LOGS.glob("2026*.jsonl") if not p.stem.startswith("runner"))
    index = []
    for stamp in stamps:
        path = LOGS / f"{stamp}.jsonl"
        rows = [json.loads(l) for l in path.open(encoding="utf-8") if l.strip()]
        if not any(r["kind"] == "look" for r in rows):
            continue  # no battle in it (the runner stopped before one began)
        rec = Battle(stamp, rows).record(notes.get(stamp))
        folder = OUT / stamp
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "game.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")
        (folder / "game.txt").write_text(text(rec), encoding="utf-8")
        index.append({"stamp": stamp, "mode": rec["source"]["mode"], "result": rec["result"]["value"],
                      "theirs": [p["species"] for p in rec["teams"]["theirs"]],
                      "went_wrong": (rec["notes"] or {}).get("went_wrong"), "game": f"games/live/{stamp}/game.json"})
    if not argv:
        (OUT / "index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    print(f"{len(index)} games written to {OUT}")


if __name__ == "__main__":
    main(sys.argv[1:])
