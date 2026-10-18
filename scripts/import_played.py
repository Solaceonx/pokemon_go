#!/usr/bin/env python3
"""Bring games played on the website (solaceonx.github.io/pokemon_go_pvpbot/play.html) into games/played/.

    python3 scripts/import_played.py pvpbot-games-NAME-DATE.json [...]

The page's "Download my games" button writes such a file. Each game goes to games/played/<started>-<player>.json,
in the format scripts/play.py saves, with the player's notes kept, and a line is added to results.jsonl; games
already there are skipped. Then `python3 scripts/losses.py --played` replays the ones the bot lost.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAVED = ROOT / "games" / "played"


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    SAVED.mkdir(parents=True, exist_ok=True)
    added = skipped = 0
    for path in sys.argv[1:]:
        data = json.loads(Path(path).read_text())
        for game in data if isinstance(data, list) else [data]:
            who = re.sub(r"[^A-Za-z0-9_-]", "", game.get("player") or "web") or "web"
            out = SAVED / f"{game['started']}-{who}.json"
            if out.exists():
                skipped += 1
                continue
            game.setdefault("source", "website")
            out.write_text(json.dumps(game, indent=1) + "\n")
            with (SAVED / "results.jsonl").open("a") as tally:
                tally.write(json.dumps({k: game.get(k) for k in ("started", "bot", "result", "mine", "theirs", "turns", "player")}) + "\n")
            added += 1
    print(f"added {added} games to {SAVED.relative_to(ROOT)}, skipped {skipped} already there")


if __name__ == "__main__":
    main()
