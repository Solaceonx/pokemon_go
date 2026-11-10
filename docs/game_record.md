# The game record: one readable file per tracked battle

A tracked battle is spread over many files (`scripts/recording/README.md`): what the pixels said, the looks,
the timeline, the tracker's events and a full state after every look. Each answers a different question, and
none of them reads as a game. `scripts/recording/game_record.py` puts them together into two files in the
game's folder:

The recording builder and the task45 live-log v2 builder are included in this
import branch. The original implementations came from
`game-record-and-charged-damage` and `task45-live-records`, respectively.
`games/catalog.json` indexes both without counting camera views as distinct games.

| File | For | What it is |
|---|---|---|
| `game.json` | programs | the record described below, schema `game-record-v1` |
| `game.txt` | people | the same as a play-by-play |

```bash
python3 scripts/recording/game_record.py games/lyxia-2026-10-10      # one game
python3 scripts/recording/game_record.py --all                       # every tracked game under games/
python3 scripts/recording/game_record.py games/lyxia-2026-10-10 --print
```

It reads only what `assemble.py`, `track.py` and `verdict.py` already wrote (plain or `.gz`), plus
`source.json` for public footage. Nothing is read from the video and nothing is tracked again: after changing
the assembly or the tracker, re-run them and then this. It needs only the standard library.

## Three rules the record keeps

1. **Every value says how we know it.** `known_from` is `team_sheet` (we were told), `seen` (the screen showed
   it), `inferred` (worked out from what the screen showed: hit sizes and rhythm, effectiveness words, the only
   legal option) or `guessed` (the usual choice for the species, not confirmed). Energy is never seen for the
   opponent: it is a range from the count, with the most the clock allows beside it.
2. **The actions are what happened on screen; the state is the tracker's picture.** An action's time is when it
   started on screen (a charged move at its cue, "Get Ready!" or "Attack incoming!"). The `state` beside it is
   what the tracker believed at the first look after it, and is not corrected afterwards: if the tracker later
   works out a different fast move, earlier states keep the old count. The team list at the top is the final
   belief.
3. **Doubt is carried, not dropped.** A charged move thrown with less energy than it costs by our count, health
   changes the rules could not explain, a missing result screen and a clip that starts mid-battle are all kept
   in the record, at the action they concern.

`mine` is the player whose screen it is: the owner in their own recordings, the camera's player in public
footage. `theirs` is the other player.

## game.json

```json
{
  "schema": "game-record-v1",
  "game": "lyxia-2026-10-10",
  "source": {"kind": "own_recording"},
  "result": {"value": "win", "from": "result screen", "left": {"mine": 1, "theirs": 0}},
  "seconds": 157.63,
  "fighting_turns": 107,
  "checks": {"verdict": "pass", "failed": [], "notes": [], "unexplained_health_changes": 4},
  "teams": {"mine": [...], "theirs": [...], "theirs_unseen": 0},
  "summary": {"charged": {"mine": 5, "theirs": 5}, "shielded": {"mine": 2, "theirs": 1}, ...},
  "actions": [...],
  "deductions": [...],
  "built_from": ["events.jsonl", "state.json", "states.jsonl", "timeline.json", "track.json", "verdict.json"]
}
```

**`source`.** `{"kind": "own_recording"}`, or for public footage `{"kind": "public_footage", "url", "view",
"match_id", "clip_seconds": [start, end], "incomplete_start", "incomplete_end", "dataset_role"}`.

**`result`.** `value` is `win`, `loss`, `draw` or null, from `mine`'s side. `from` is `result screen`, `who had
Pokémon left` (no result screen was read, but exactly one side was out) or `unknown`.

**`teams`.** One entry per Pokémon in the order it appeared:

```json
{"species": "oinkologne", "name": "Oinkologne", "known_from": "seen", "cp": 1496, "cp_from": "assumed",
 "stats_assumed": true, "fainted": true, "hp_share_at_end": 0.0,
 "fast_move": {"id": "MUD_SLAP", "name": "Mud Slap", "turns": 3, "energy_gain": 10, "known_from": "inferred"},
 "charged_moves": [{"id": "BODY_SLAM", "name": "Body Slam", "energy": 40, "known_from": "seen", "times_used": 1},
                   {"id": "TRAILBLAZE", "name": "Trailblaze", "energy": 45, "known_from": "guessed", "times_used": 0}],
 "other_charged_moves": {"Trailblaze": 0.6, "Dig": 0.4}}
```

For the opponent, `fast_move.odds` gives the chance of each fast move while it is not worked out, and
`other_charged_moves` the chance of each move not yet seen being one of its two.

**`actions`**, in the order they happened. Every action has `kind`, `t` (seconds from the start of the fight,
the same clock as the looks), `fighting_turn` (the tracker's count of half-second turns, which stops during
charged moves) and `state`.

| kind | Other fields |
|---|---|
| `start` | `mine`, `theirs` (the leads), `incomplete_start` |
| `fighting` | `until`, `turns`, and for each side `pokemon`, `fast_move`, `fast_move_known_from`, `fast_moves_if_no_pause` (turns divided by the move's length: the rhythm count, an upper bound), `hits_seen` (steps seen on the other side's bar: a lower bound, since small hits and hidden bars are missed); `unexplained_health_changes`, `my_energy_corrected` when there were any |
| `charged` | `side`, `pokemon`, `move`, `move_id`, `move_known_from`, `cost`, `energy_before` (ours a number; theirs `[low, high]` with `energy_ceiling`), `energy_short_by` if our count says it could not be paid, `target`, `shielded`, `target_hp_before`, `target_hp_after`, `target_hp_max`, `target_bar_read`, `expected_damage` (the rules' damage on this target, 1 if shielded), `resolved_t` (the first look after it), `cue` (false when no cue was read and the time is the look's) |
| `switch` | `side`, `from`, `to` |
| `faint` | `side`, `pokemon`, `next` (the time is when the replacement came out) |
| `end` | `result`, `result_from`, `left` |

**`target_bar_read: false`: the first look after the move did not read the target's bar.** That happened to 2 of
the 6 unshielded charged moves in the owner's first recording, and to about four in ten in public clips. Since
2026-11-04 the tracker then takes the damage off by the rules (`status.md`, "Charged-move damage when the bar is not
read"), and `game.txt` shows `-> 19% (bar not read; by the rules)`. Games tracked before that left the health as it
was until a later look read the bar; for them `target_hp_after` equals `target_hp_before` and `game.txt` shows
`-> ? (bar not read; the move does ~40%)`.

`state` is `{"mine": {...}, "theirs": {...}}`, each with `active`, `hp`, `hp_max`, `hp_share`, `energy`,
`shields` and `left`; theirs also has `energy_ceiling`, and its `energy` is a `[low, high]` range. For the
opponent `hp_max` comes from typical stats for the species, so `hp_share` is the number to trust.

**`deductions`**: what the tracker worked out, with `t`, `side`, `pokemon`, `what` (`fast move`, `charged move`
or `team member`), `value`, `how` and `ruled_out`. A deduction can be replaced by a later one (Quagsire's fast
move went from Water Gun to Mud Shot in one public clip); the last one stands and matches `teams`.

## game.txt

The start of the owner's first recording:

```
lyxia-2026-10-10 . own recording . WIN (result screen) . 2:37.6, 107 fighting turns
Checks: pass

Mine
  Melmetal     CP 1500   Thunder Shock | Double Iron Bash, Dynamic Punch  [fainted]
  Altaria      CP 1499   Dragon Breath | Sky Attack, Flamethrower  [fainted]
  Jellicent    CP 1499?  Hex? | Surf, Shadow Ball?

Theirs
  Cramorant    CP 1498?  Peck* | Dive, Fly?  [fainted]
  Oinkologne   CP 1496?  Mud Slap* | Body Slam, Trailblaze?  [fainted]
  Talonflame   CP 1500?  Incinerate* | Flame Charge, Fly?  [fainted]
  plain = seen or told   * = worked out from the screen   ? = assumed, not confirmed

   0:00.0  Start: Melmetal vs Cramorant
   0:00.0  fight to 0:01.5, 3 turns: Melmetal ~1 Thunder Shock (2 seen); Cramorant ~1 Peck* (1 seen)
   0:01.5  They switch Cramorant -> Oinkologne
   0:01.5  fight to 0:05.6, 8 turns: Melmetal ~4 Thunder Shock (0 seen); Oinkologne ~2 Mud Slap* (3 seen)  [2 unexplained health change(s)]
   0:05.6  We throw Dynamic Punch (Melmetal, 45 of 45 energy) -> Oinkologne 91% -> 19%
   0:16.0  We switch Melmetal -> Altaria
   0:16.0  fight to 0:20.6, 9 turns: Altaria ~9 Dragon Breath (6 seen); Oinkologne ~3 Mud Slap* (4 seen)
   0:18.5  . worked out: their Oinkologne has Mud Slap (every other fast move ruled out by effectiveness words or energy; ruled out Tackle, Take Down)
   0:20.6  They throw Body Slam (Oinkologne, 40 of 40 energy, clock allows 70) -> Altaria shielded
```

`~4 Thunder Shock (0 seen)` is the rhythm count against the steps actually seen on the bar; a big gap there,
or `unexplained health change(s)`, marks a stretch to look at in the video. Moments of one turn or less with no
hits seen are left out of `game.txt` (they stay in `game.json`).

## What it is not

- **Not ground truth.** It is the tracker's account, as good as the reader and the tracker. `checks` says how
  far it held together; `docs/reserved_state_evaluation.md` says how far it agrees with the other player's
  screen.
- **Not the website's saved games.** `games/played/*.json` are replayed from their seeds and choices; a
  recording has neither, so this record carries what happened instead.

## The live-log variant (`variant: "live-log"`, `variant_version: 2`)

The battles the bot played itself on the phone (task 40) are recorded from its own log, not from a recording:
`games/live/<STAMP>/game.json` and `game.txt`, built by `scripts/live/live_record.py`. A GO Battle League battle's raw
log is beside its record, `games/live/<STAMP>/log.jsonl` (one line per event: every tap, every look given to the
tracker, every engine decision, throws and minigames); a Team Leader battle's stays in `runs/live/<STAMP>.jsonl`.
`games/live/index.json` lists every folder. Nothing is read from the video, and no trainer name (ours or theirs)
is kept.

What differs from a record of a recording:
- `mine` is the bot. Our team is as the bot was told it (`known_from: "team_sheet"`), with `cp` as computed, and
  `cp_on_screen`, `level` and `ivs` ([attack, defence, stamina]) from `games/live/our_teams.json` by the team's key
  (null until the owner gives them).
- A charged move's time is when the bot saw it start (Get Ready!, its minigame's icons, or its prompt). Ours carry
  the minigame's swipe (`icons_chased`, the looks on which an icon was chased); theirs whether we shielded.
- `state` is what the live tracker believed at the look just before the action, as logged: their energy is the
  tracker's `[low, high]`; our energy is the buttons' reading when there was one (`energy_from: "buttons"`), else
  the count.
- `bot` counts what the player itself did wrong or doubted, from its log: throws not taken, decisions dropped,
  tracker and engine errors, and so on.
- `notes` is the analysis of the battle, from `games/live/notes.json`: `went_wrong`, `fixed`, and where the
  analysis settled it, `result`, `fragment_of`, `their_team`. notes.json is the one place for it:
  `index.json`'s `went_wrong` and the tables in `docs/live_battles_*.md` are made from it
  (`scripts/live/battle_tables.py`; `--check` says whether they are up to date).

Version 2 (task 45) adds:

| Field | What | Null when |
|---|---|---|
| `result.value` | one of `win`, `loss`, `draw`, `fragment`; a fragment's `result.fragment_of` names the battle it is the start of; `result.from` says how it is known (the result screen, or the analysis in notes.json) | never, for a league battle |
| `source.started_utc` | the start as UTC ISO text, beside `source.epoch`; `source.started_from` says how: the epoch, or for the first battles (2026-11-07, no epoch logged) the log's name, the PC's local time (UTC−08:00) a few seconds before the start | never |
| `source.account`, `source.team` | the account (`spare`, `owner`: keys, not trainer names) and the team's key in `our_teams.json` | |
| `source.league`, `source.season` | as read on screen (the league card the runner tapped, the season card) | not read for that battle |
| `source.bot` | `commit` (the git commit the bot ran) and `dirty` (whether its working tree had uncommitted changes) | battles before 2026-11-08 evening |
| `source.context_from` | for older battles whose log does not carry the four fields above: how each is known (`games/live/context.json`) | the log carries them |
| `standing.before`, `standing.after` | rank and rating on the GO Battle League screen before and after the battle | not read (the older battles; rating shows only from rank 20) |

`index.json` also carries each league battle's `odds`: our chance from the line-ups alone (`scripts/live/odds.py`,
kept in `games/live/odds.json`). `tests/test_live_records.py` checks every league record against this section.

### Additional evidence sidecars

`scripts/live/import_evidence.py` attaches audited observations in each existing
game's folder without replacing `game.json`, `game.txt` or a differing source log.
`enrichment.json` records input-log and package hashes. It points to compressed
logged readings, optional fresh pixel readings, summaries and review flags.
`live/index.json` links this manifest as `evidence`. The sidecars are additional,
unverified evidence, not corrected historical states. The canonical record's
`built_from` remains its source log. A differing existing package is an explicit
conflict. The importer may record training context from the explicit log field
or a dated training recording collection in `context.json`; it does not classify
a league opponent as training merely because that species is used by a Team Leader.

Raw logs and hash-covered evidence packages have Git text conversion disabled in
`.gitattributes`. Their original bytes, including line endings, must survive a
Windows or Unix checkout so source/package hashes and lossless re-import remain
valid. Ordinary readable game summaries remain text files.
