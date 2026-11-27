# Running the phone bot from a new session (the owner's Mac)

For an agent with none of the earlier conversations: everything needed to play GO Battle League or Team Leader
battles on the Android phone the way the 2026-11-24/25 sessions did. The background is in `docs/android_play.md`
(how the screen is read, the minigame, the tools) and `docs/status.md` (every result).

## Rules first

- **The owner's say-so for every live session.** Automating the game breaks Niantic's terms; never send a tap to a
  live account unless the owner asked for it in this conversation (AGENTS.md).
- **Taps:** never Manage Items, the shop, paid passes, power-ups, evolve or transfer (`run_gbl.NEVER` refuses
  screens with those words). Collecting a set's rewards is allowed when the owner says so; an encounter needs Poké
  Balls, so ask.
- **Trainer names stay out of git and logs.** Accounts are called `owner`, `spare`, `third` (`data/accounts/*.json`;
  names only in the git-ignored `data/accounts/trainers.local.json`).
- **Fix before playing.** The owner prefers the open problems investigated and fixed over more sets to "test" a
  fix. After any change to `scripts/live/play_android.py`, dry-run it on a recorded battle (below) before a live one.
- **The owner is an expert player.** Ask before inventing a strategy rule; their calls are in `docs/status.md`
  ("Strategy guidance from the project owner") and in the comments of `play_android.py`.
- **Keep the Mac cool:** `nice`, no forgotten background jobs, at most three workers.
- **Git on this Mac:** prefix git with `DEVELOPER_DIR=/Library/Developer/CommandLineTools` (otherwise it fails).

## Where the code is

The live player's newest fixes are on branch **`ultra-league`** (not yet merged into `main`): work from a worktree
of it, e.g. `.worktrees/ultra-league`. Results go in `docs/status.md` on `main`.

## Set-up (once per Mac)

1. **Python for the phone tools:** `python3 -m venv .session_scratch/livevenv && .session_scratch/livevenv/bin/pip
   install -r requirements-live.txt` (Python 3.14 was used; the simulator alone needs only numpy). On 2026-11-25 the
   working one was `.session_scratch/2026-11-22_ultra-league/livevenv/bin/python`.
2. **scrcpy 5.0.1:** the release folder with its `adb` and `scrcpy-server` (from the Genymobile/scrcpy GitHub
   release); point `POGO_SCRCPY_DIR` at it. On 2026-11-25: `.session_scratch/2026-11-22_ultra-league/scrcpy501`.
3. **The phone:** `adb devices` must list it. The screen positions were measured on the moto g stylus 5G (2024),
   serial `ZY22JPBNMW`, 1080 x 2400 (`pogo/android_screen.py`); other phones need them measured again. The game must
   be open on the map (or the battle menu) with the account the owner named; the owner logs accounts in and out.
   The phone's AutoGrind overlay (the owner's own app, `~/Projects/autogrind`) should be paused first.

Below, `PY` is the venv's python and `SC` the scrcpy folder; run from the worktree's root.

## Commands

- **A ranked set** (five battles; stops at the daily limit, rewards to collect, or a screen it does not know):
  `POGO_SCRCPY_DIR=$SC nice $PY scripts/live/run_gbl.py --serial ZY22JPBNMW --max-battles 5 --wins 5 --cp 1500
  --account third --party-key main --media <folder for recordings> > <log> 2>&1`. Ultra League: `--cp 2500` and the
  account's UL party key; the parties are in `data/accounts/<account>.json`.
- **Team Leader training** (no rating at stake): `scripts/live/train_loop.py --serial ZY22JPBNMW --battles 3
  --account third --party-key main --media <folder>`; add `--practise EARTHQUAKE --stay` to throw one move again and
  again (to test a minigame stroke).
- **Marco's lab engine instead of today's** (opt-in, the owner's trial from 2026-11-26): put `POGO_LAB=P` in front
  of `run_gbl.py`, `train_loop.py` or `replay.py` (`P` is `play_android.LAB_P`; any `scripts/engine_versus.py` spec
  works). The battle log's start row then says `engine: lab:P`. Unset, today's engine plays.
- **A cup's field for the engines** (opt-in, measured 2026-11-26: no gain): `POGO_FIELD=data/fields/mega_catch_cup.json`
  makes both engines imagine their unseen Pokémon from the Mega Catch Cup opponents we met (and their real teams)
  instead of the open top 50; `scripts/live/cup_field.py` builds such a file from the logs, `scripts/cup_versus.py`
  measures it. Unset, as before.
- **The owner's shield call for the battle under way:** write `runs/live/override.json` as
  `{"shield": {"thievul": true}}` (shield at every prompt while it is out; `false`: never); delete it after.
- **After each set:** `nice $PY scripts/live/set_review.py runs/live/<stamp>.jsonl ...` (results, rules fired, likely
  mistakes); `scripts/live/win_chances.py` (the engine's own odds through each battle); `scripts/live/grade_each.py
  <media folder> <logs>` (each minigame's rating). Then look at each loss: is it the engine's (strategy, shields) or
  ours (reading, counting, tapping, timing)? The owner wants that split.
- **At the end of each day, store the battles** (on `main`; task 45): in a checkout of `main`,
  `python3 scripts/live/live_record.py --from <this worktree>/runs/live`, add what went wrong in each loss to
  `games/live/notes.json`, `nice python3 scripts/live/odds.py`, `python3 -m unittest tests.test_live_records`, commit
  and push to `main`.
- **Then the battle page** (unlisted: solaceonx.github.io/bot-battles-7924a775.html; not linked from the site,
  `noindex`, but the site's repo is public): here, `nice $PY scripts/live/battle_review.py --out <main checkout>/games/live`
  (reviews the battles not yet reviewed, about 5 s each, 3 workers); in the `main` checkout commit the new `review.json`
  files and `python3 scripts/live/battle_page.py <site clone>/bot-battles-7924a775.html`; in a fresh clone of the site
  (`git clone --depth 1 git@github.com:Solaceonx/solaceonx.github.io.git`; the owner's `~/Projects/site` has its own
  unpushed work, leave it) commit only that page and push. Engine changes go into `data/engine_history.json` on `main`.
- **Dry run before going live:** `scripts/live/replay.py <stamp> <media folder> data/team_third.json` replays a
  recorded battle through the current player; `scripts/live/engine_view.py <stamp> <t> 6 2` asks the engine again at
  time t of a logged battle.
- **The loop the owner asked for:** play sets until the daily limit; after each, review, fix only clear bugs (with a
  test in `tests/` and a dry run), collect the rewards, then the next set. Write each set into `docs/status.md`.
- **Team GO Rocket grunts:** not built yet. The brief, with what carries over and what is new, is task 49 in
  `docs/tasks.md` on `main`.

## Teams on the accounts (2026-11-25)

- `owner`: party `mcc` Clodsire / Thievul / Snorlax (`data/team_owner_mcc.json`); Ultra League `data/team_owner_ul.json`.
- `spare`: Jellicent / Vigoroth / Stunfisk (`data/alt_team.json`).
- `third`: Clodsire / Thievul / Snorlax with their real IVs (`data/team_third.json`).
