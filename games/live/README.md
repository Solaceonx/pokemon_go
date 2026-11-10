# Live battles on the phone, as game records

Every battle the bot played on the phone (task 40) from 2026-11-07 on: GO Battle League and training against the Team
Leaders. Accounts are named by key (`spare`, `owner`), never by trainer name. One folder per battle, named by its
stamp (the PC's local time when its log was opened):

- `game.json`: the record, schema `game-record-v1` with `variant: "live-log"`, `variant_version: 2`
  (`docs/game_record.md`, "The live-log variant"). Teams (ours with level and IVs where known), every charged move
  with the energy and health believed at the look before it, shields, switches, faints, the result (win, loss, draw
  or fragment), the bot's version, the league, season and rank, the player's own faults (`bot`) and the analysis
  (`notes`).
- `game.txt`: the same as a play-by-play.
- `log.jsonl` (league battles): the raw log the record is built from, one line per event: every tap, every look
  given to the tracker, every engine decision, throws and minigames. A training battle's log is
  `runs/live/<STAMP>.jsonl`.

Beside the folders:

| File | What | Made by |
|---|---|---|
| `index.json` | every folder: mode, result, their team, what went wrong, and for a league battle its line-up odds | `live_record.py` (from the records, `notes.json`, `odds.json`) |
| `notes.json` | the analysis of each battle: `went_wrong`, `fixed`, and where it settled them `result`, `fragment_of`, `their_team`. The one place for it | by hand, after each battle is looked into |
| `context.json` | for battles whose log does not say them (before task 45): account, team, league and season, and how each is known | once, from the runner's logs |
| `our_teams.json` | our teams by key (`spare/main`, `spare/melmetal`, `owner/main`): CP on the party screen, level and IVs from the owner | by hand |
| `odds.json` | each league battle's line-up odds and how they were worked out | `odds.py` |

```bash
python3 scripts/live/live_record.py                # every record again, and index.json
python3 scripts/live/live_record.py 20261108-105348
nice python3 scripts/live/odds.py                  # odds for league battles not done yet
python3 scripts/live/battle_tables.py              # the tables in docs/live_battles_*.md, from notes.json
python3 -m unittest tests.test_live_records        # the checks
```

The recordings (`battle-<STAMP>.h264` and `.mp4` with `.times`, and the minigame frames) are on the owner's PC, not
in git. The bot's own code (`scripts/live/play_android.py`, `run_gbl.py`, `train_loop.py`, `pogo/android*.py`) is on
the `task40-android` branch.
