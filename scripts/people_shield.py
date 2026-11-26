#!/usr/bin/env python3
"""Fit the shield calls of good players (pogo.people_shield) on task 46's creator records.

    python3 scripts/people_shield.py CREATORS_DIR [--out runs/people-shield]

CREATORS_DIR holds <channel>/<record>/game.json (games/creators on the task 46 branch). Every charged move thrown
at a side with a shield up is a decision, the creators' and their opponents' alike, our last Pokémon left out.
Damage comes from the record's species and moves at default stats. Prints the battle-wise cross-validated copy
rate (records kept whole in one fold) and writes shield.npz and report.json.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pogo.battle import Mon, damage  # noqa: E402
from pogo.gamedata import GameData  # noqa: E402
from pogo.people_shield import FEATURES, describe, fit  # noqa: E402


def decisions(root: str, gd: GameData) -> list[dict]:
    rows = []
    for f in sorted(glob.glob(f"{root}/*/*/game.json")):
        g = json.loads(Path(f).read_text(encoding="utf-8"))
        if g["source"].get("incomplete_start"):
            continue
        team = {s: {p["name"]: p for p in g["teams"][s]} for s in ("mine", "theirs")}
        for a in g["actions"]:
            if a["kind"] != "charged" or a.get("shielded") is None or not a.get("state"):
                continue
            att = a["side"]
            dfn = "theirs" if att == "mine" else "mine"
            st_d, st_a = a["state"][dfn], a["state"][att]
            before = st_d["shields"] + (1 if a["shielded"] else 0)
            if before < 1 or st_d["left"] <= 1 or not a.get("target_hp_before") or not a.get("target_hp_max"):
                continue
            pa, pd = team[att].get(a["pokemon"]), team[dfn].get(a.get("target"))
            if not pa or not pd:
                continue
            try:
                ba = gd.build(pa["species"], [pa["fast_move"]["id"], *[m["id"] for m in pa["charged_moves"]]])
                bd = gd.build(pd["species"], [pd["fast_move"]["id"], *[m["id"] for m in pd["charged_moves"]]])
            except (KeyError, ValueError, TypeError):
                continue
            ma, md = Mon(ba), Mon(bd)
            hits = [(m.energy, damage(ma, m, md)) for m in ba.charged]
            x = describe(a["target_hp_before"], a["target_hp_max"], hits, before, st_a["shields"], st_d["left"],
                         st_a["left"])
            rows.append({"record": Path(f).parent.name, "creator": dfn == "mine", "x": x, "y": int(a["shielded"])})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("creators")
    ap.add_argument("--out", default=str(ROOT / "runs" / "people-shield"))
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--repeats", type=int, default=5)
    args = ap.parse_args()
    rows = decisions(args.creators, GameData())
    x = np.array([r["x"] for r in rows])
    y = np.array([r["y"] for r in rows])
    records = sorted({r["record"] for r in rows})
    copy = []
    for rep in range(args.repeats):
        rng = np.random.default_rng(rep)
        fold = dict(zip(rng.permutation(records), np.arange(len(records)) % args.folds))
        p = np.zeros(len(y))
        for k in range(args.folds):
            test = np.array([fold[r["record"]] == k for r in rows])
            p[test] = fit(x[~test], y[~test], seed=rep).probabilities(x[test])
        copy.append(float(((p > 0.5) == y).mean()))
    model = fit(x, y)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    model.save(out / "shield.npz")
    report = {"decisions": len(rows), "records": len(records), "creators'": int(sum(r["creator"] for r in rows)),
              "shield_rate": round(float(y.mean()), 3), "copy_rate_cv": round(float(np.mean(copy)), 3),
              "copy_rate_cv_sd": round(float(np.std(copy)), 3), "never_shield": round(float(1 - y.mean()), 3),
              "features": list(FEATURES), "fitted_shield_rate": round(float((model.probabilities(x) > 0.5).mean()), 3)}
    (out / "report.json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
