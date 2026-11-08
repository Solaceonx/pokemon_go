# Live battles on the phone, as game records

Every battle the bot played on the owner's spare account (task 40), 2026-11-07 and 2026-11-08: GO Battle League
and training against the Team Leaders. One folder per battle, named by its stamp:

- `game.json`: the record, schema `game-record-v1` with `variant: "live-log"` (the format of the recorded-game
  pipeline, `docs/game_record.md` on the `game-record-and-charged-damage` branch; the differences are listed at the
  top of `scripts/live/live_record.py`). Teams, every charged move with the energy and health believed at the look
  before it, shields, switches, faints, the result, the player's own faults (`bot`) and the analysis (`notes`).
- `game.txt`: the same as a play-by-play.

`index.json` lists them all with result, their team and what went wrong. `notes.json` holds the analysis of each
league battle of 2026-11-08 (also in `docs/live_battles_2026-11-08.md`, with what is still open).

Built from the player's logs, `runs/live/<STAMP>.jsonl`, which have every tap, look and decision:

```bash
python3 scripts/live/live_record.py            # all of them again
python3 scripts/live/live_record.py 20261108-105348
```

The recordings (`battle-<STAMP>.h264` and `.mp4` with `.times`, and the minigame frames) are on the owner's PC, not
in git: about 9 GB.
