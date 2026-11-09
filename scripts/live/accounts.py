#!/usr/bin/env python3
"""Which game account is on the phone, and its settings (task 40): data/accounts/<NAME>.json, with
data/accounts/current.txt naming the one signed in now. When the owner swaps accounts:

    python3 scripts/live/accounts.py use owner           the account now on the phone (a key, or a trainer name)
    python3 scripts/live/accounts.py show                the current account's parties

Accounts are kept under neutral keys (spare, owner): trainer names stay out of the public repo. A trainer name
given to `use` is looked up in data/accounts/trainers.local.json ({trainer name: key}), which is not committed;
data/accounts/current.txt is not committed either.

An account file lists its saved parties by a short key: the team file (data/team_*.json: species, moves in button
order) and the CPs the party screen shows, in order. The party screens show nicknames, not species, so the CPs are
how a party is found there. "league" is the key of the party for GO Battle League. train_loop.py and run_gbl.py take
--account (default: the current one) and --party-key (default: the league party).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FOLDER = ROOT / "data" / "accounts"


def current() -> str:
    return (FOLDER / "current.txt").read_text(encoding="utf-8").strip()


def load(name: str | None = None) -> dict:
    path = FOLDER / f"{name or current()}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def expect_words(cps) -> str:
    """The party's CPs as the party screen reads with spaces taken out: [1496, 1499, 1492] -> CP1496CP1499CP1492."""
    return "".join(f"CP{c}" for c in cps)


def party(name: str | None = None, key: str | None = None) -> dict:
    """{"key", "team" (an absolute path), "expect", "cps", "species"} for the account's party (default: the league's)."""
    account = load(name)
    key = key or account["league"]
    p = dict(account["parties"][key])
    p["key"] = key
    p["team"] = str(ROOT / p["team"])
    p["expect"] = expect_words(p["cps"])
    return p


def main() -> None:
    if len(sys.argv) >= 3 and sys.argv[1] == "use":
        name = sys.argv[2]
        local = FOLDER / "trainers.local.json"
        if local.exists():
            name = json.loads(local.read_text(encoding="utf-8")).get(name, name)
        if not (FOLDER / f"{name}.json").exists():
            raise SystemExit(f"no data/accounts/{name}.json: write one first (see the others)")
        (FOLDER / "current.txt").write_text(name + "\n", encoding="utf-8")
    account = load()
    print(f"current account: {account['account']}")
    for key, p in account["parties"].items():
        mark = " (league)" if key == account["league"] else ""
        print(f"  {key}{mark}: {', '.join(p['species'])}  CP {p['cps']}  team {p['team']}")


if __name__ == "__main__":
    main()
