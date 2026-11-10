# Stored games

`catalog.json` indexes the canonical `game-record-v1` files and their readable
play-by-play files. Rebuild it with `python scripts/index_games.py`; `--check`
verifies it without writing.

As imported on 2026-11-09:

| Collection | Records | What the number means |
|---|---:|---|
| Live league | 100 | 99 completed games (60 wins, 39 losses), plus one fragment linked to its game |
| Live training | 138 | 135 logged wins and three unresolved results; these are not league games |
| Public tracked footage | 43 | Player views, grouped by 29 match IDs; camera views are not separate games |
| Personal tracked footage | 6 | Recording segments; some can overlap |
| All canonical records | 287 | A file count, **not 287 distinct games** |

For live games, use `live/index.json` and one folder per timestamp. Each folder
contains `game.json` and `game.txt`. A league record's source is `log.jsonl`
beside it; training sources stay under `runs/live/`. The detailed format is
[`docs/game_record.md`](../docs/game_record.md).

The 207 records from the additional evidence audit also contain:

- `enrichment.json`: input hash and a manifest of additional evidence files.
- `evidence.jsonl.gz`, `evidence-summary.json`, `review-flags.jsonl.gz`: timestamped
  logged observations and beliefs, plus their counts and review flags.
- For three re-read recordings, `pixels.jsonl.gz` and `pixel-summary.json`: fresh
  pixel observations, separate from the canonical record's historical beliefs.

These observations remain unverified. They do not overwrite the original record
or fill in unknown IVs, levels, rating, results or missing decision states.
The twenty reserved official VOD views remain test-only; generating readable
summaries does not retrain their reader or tracker.

Videos and frames remain outside Git. Video-only cuts without tracked game data
are not included in this catalog. `games/played` website games use a different
seed/action format; worked examples are also excluded from this real-footage index.
