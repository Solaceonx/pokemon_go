# Engine lab: creator tactics (2026-11-24)

Built on `lab-tactics`, without commits or changes to shipped models or website settings.
These are experiments for the coordinator's screen, not evidence for adoption.

## Keys and exact behavior

- `finish_safe=1`: Learner's finishing-fast shortcut now asks `_doomed(view, fast.turns)`.
  If doomed, it reaches the ordinary throw head, including the engine search. It does not
  force a charged move over that search. Safe fast finishes and no-energy positions keep
  their existing behavior. The rebuilt Henry example (Empoleon 62 HP / 48 energy,
  Diggersby 4 HP / 100 energy, Mud Shot one turn from landing) gives FAST for both defaults
  and Hydro Cannon for both opt-in players; website performs one throw search instead of zero.
- `bait_mix=p`: after a charged move has been selected, both moves must be affordable,
  have unequal costs, and the defender must have a shield. The dearer move must hit at
  least 1.3 times harder; the cheaper must not knock out. Draw cheaper with probability p,
  dearer otherwise. Holds and switches are untouched. This takes precedence over the
  charged-move selection from any earlier search/mixing rule; simultaneous-search advice
  is not mixed a second time. `p=0` means always dearer; omit the key or use `off` to disable.
  A stable private `_mix_rng`, derived without advancing search dice, is cloned independently.
  `bait_opportunities` and `baits_thrown` count mixed final throw choices, not all energy-ready
  turns or completed hits (CMP can cancel a chosen throw). The printout labels this denominator.
  A replaced search probability is excluded from the existing P(chosen) diagnostic.
- `shield_two=a,shield_one=b`: independent nonnegative margins on the trained shield
  head, selected by our remaining shields. Either omitted/`off` value inherits
  `shield_margin`, which itself retains its old default. `shield_toward` and the last-Pokemon
  rule remain in force. PolicyPlayer's bot/anchor margin also uses this helper.
  These keys do not override a people-shield network or a searched shield head.
- `swap_after_throw=1`: only after a completed search chooses a voluntary SWITCH after
  turn zero, from the `swap` or `mid_swap` head. This includes new matchups later in the
  battle: the shipped q has no `mid_swap` head, so restricting this to that head would make
  the requested website candidate inert. Rulebook sacrifice/rescue/catch switches, turn-zero
  switches, replacements, fallback-only searches and simultaneous switch-matrix choices
  are excluded. Require an affordable charged move and an opponent that survives one
  fast hit. With shields up, an affordable move must threaten an unshielded KO; with
  shields down, its damage must exceed one fast hit. Choose the cheapest affordable KO,
  otherwise the hardest affordable hit (cheapest breaks a tie). Apply bait mixing if enabled.
  Clear the remembered matchup so the next action can reconsider switching; suppress this
  override for that next action. No switch is forced. Count as `swap_after_throws`.
- `--people N`: baseline and each candidate face the same human-style PeopleLike opponent
  on the same teams and dice, with paired differences and ordinary activity counts.
  `opponents=people` uses that same factory inside imagined battles. PeopleLike moved
  to `pogo/lab/people.py`, and the creator exam re-exports it. Factory draw order and the
  shield network are unchanged; cloning now copies its private shield RNG independently.

The four bot-relevant keys work for `bot,...` as well as `website,...`; swap-after-throw
is engine-only. The bot parser also accepts the existing `shield_margin`/`shield_toward`.
As with task 41, our rollout bot retains its defaults: these controls affect the real
player's own decisions, not every imagined continuation. `opponents=people` is the explicit
exception for the imagined opposing player. Engine-versus counting is now
`per-battle-v4-tactics`; use a fresh tag rather than resuming an older counting version.

## Code and regression checks

Changed:

- `pogo/learner.py`: constructor/clone, `_head_margin`, `_decide`, `_pick_move`,
  `_choose_move`, `_bait_action`.
- `pogo/engine.py`: constructor, `_imagined_opponent`, `_act`, `_decide`, `replace`.
- `pogo/lab/mixed.py`: `private_rng`, `bait_pair`.
- `pogo/lab/policy.py`: shared margin in `PolicyPlayer._decide`.
- `pogo/lab/engines.py`: `ModelledEngine._imagined_opponent` retains an explicit people
  style even when an `opp_q`/`opp_policy` is supplied (those models apply only to bot style).
- New `pogo/lab/tactics.py`: spec parsing and `before_swap`.
- New `pogo/lab/people.py`: shared PeopleLike and factory.
- `scripts/engine_versus.py`: small parse/pilot hooks, people jobs/CLI, counters/printout.
- `scripts/lab/creator_exam.py`: imports the shared opponent.
- New `tests/test_lab_tactics.py`: 16 tests; targeted run passed in 8.337 seconds.

Final full discovery: **485 tests, 0 failures, 3 expected OCR errors, 7 skips**, 58.417 seconds
(`tests-final.out`, after the modelled-opponent integration check; earlier full run in `tests.out`).
The missing package is `rapidocr_onnxruntime`; nothing was installed.
Both before and after: **108 of 108 PvPoke battles reproduced exactly**.
All three pre-mixed frozen game digests match, both without keys (the existing suite)
and with `finish_safe=0,bait_mix=off,shield_two=off,shield_one=off,swap_after_throw=0`.
Tests cover real Henry search, unchanged safe fast finishes, bait eligibility/extremes/
seeded frequency/clone/process replay, hold/switch preservation, counters, shield-state
margins and last Pokemon, searched swap gates/reconsideration, and paired people factories.

Sandbox caveat: the first plain baseline discovery ran 469 tests and reported 19 errors:
3 OCR errors plus 16 temporary-directory access errors. Pointing TEMP/TMP inside the
worktree still gave those errors. Python 3.13's `mkdir(mode=0o700)` creates a private ACL
that this Windows sandbox cannot use. Final full discovery used a process-local wrapper
changing only that mkdir mode to 0o777 (inherited ACLs), with temporary directories under
`runs/lab-tactics/tmp`; no tests were skipped/edited to hide an error and no system settings
changed. Full tracebacks are in `tests.out`; the initial failed baseline is retained.

Reproduce that full discovery in this sandbox with the repository venv, OMP_NUM_THREADS=1,
`-X utf8`, and this Python harness:

```python
import os, tempfile, unittest
from pathlib import Path
tempfile.tempdir = str(Path('runs/lab-tactics/tmp').resolve())
real_mkdir = os.mkdir
def inherited_mkdir(path, mode=0o777, *, dir_fd=None):
    return real_mkdir(path, 0o777 if mode == 0o700 else mode, dir_fd=dir_fd)
os.mkdir = inherited_mkdir
unittest.TextTestRunner().run(unittest.defaultTestLoader.discover('tests'))
```

## Shield-rate count and candidate selection

`scripts/lab/bot_habits.py`, bot against bot, one process. Each output starts with the
exact command. These are shield habits, not win-rate comparisons. The script's printed
95% margins treat prompts as observations; within-battle dependence is not corrected.

Selection: 200 battles each, seed 5400. Non-final-Pokemon shield prompts only:

| Margins (two / one) | Total | With two | With one | First charged move faced |
|---|---|---|---|---|
| Default .02 / .02 | 34% ± 3 (302/898) | 32% ± 4 (179/559) | 36% ± 5 (123/339) | 24% ± 6 (49/200) |
| .05 / 0 | 35% ± 3 (309/886) | 35% ± 4 (181/518) | 35% ± 5 (128/368) | 29% ± 6 (58/200) |
| .1 / 0 | 36% ± 3 (317/883) | 40% ± 4 (185/468) | 32% ± 4 (132/415) | 36% ± 7 (72/200) |

Picked **.05 / 0**, the closer total-rate match, before checking fresh seed 5402.
The .1 alternative moved first shields more but also raised total use more; it is not
in the proposed screen. Fresh check: 400 battles per spec, 11 seconds each:

| Margins | Total, excluding last Pokemon | With two | With one | First charged move faced |
|---|---|---|---|---|
| Default | 34% ± 2 (607/1810) | 32% ± 3 (361/1130) | 36% ± 4 (246/680) | 27% ± 4 (108/400) |
| .05 / 0 | 34% ± 2 (624/1851) | 35% ± 3 (369/1042) | 32% ± 3 (255/809) | 30% ± 5 (122/400) |

All prompts including last Pokemon: baseline 754/1957, candidate 766/1993.
This supports the rate-matching guess, not a demonstrated strength gain or a precise
estimate of the website engine's shield rate.

## Smoke measurements

### Engine-versus

`smoke.out` contains the exact command and all activity/timing output. One worker, one
NumPy thread, mixed field, seed 5403; 2 H2H pairings both ways, 2 crowd, 2 people, 2
PvPoke and 1 reader pairing per candidate, with shared baseline field battles.
All six candidates completed: **80 actual battles in 434.2 seconds**, exit 0.
Small per-battle results/counts are retained in `smoke-scores.json`.

The script's 95% normal margins are printed below. At n=2 they may be zero or exceed
0..100%; this is execution coverage, not statistical precision. Reader has one pairing,
so its margin is unavailable. H2H and reader pairings each average two games.

| Website setting | H2H | Crowd | People | PvPoke | Reader (no margin) |
|---|---|---|---|---|---|
| Default | — | 50 ± 98 | 50 ± 98 | 50 ± 98 | 50 |
| finish_safe=1 | 50 ± 0 | 50 ± 98 | 50 ± 98 | 50 ± 98 | 50 |
| bait_mix=0.4 | 50 ± 98 | 50 ± 98 | 50 ± 98 | 50 ± 98 | 100 |
| shield_two=0.05,shield_one=0 | 75 ± 49 | 50 ± 98 | 50 ± 98 | 100 ± 0 | 100 |
| swap_after_throw=1 | 50 ± 0 | 50 ± 98 | 50 ± 98 | 50 ± 98 | 50 |
| All four | 100 ± 0 | 50 ± 98 | 50 ± 98 | 100 ± 0 | 100 |
| opponents=people | 75 ± 49 | 100 ± 0 | 100 ± 0 | 50 ± 98 | 50 |

Scores are percentages. Paired changes on the baseline: the shield candidate and all-four
combination gain +50 ± 98 points against PvPoke; imagined people gains +50 ± 98 against
crowd and people; every other non-reader field difference is +0 ± 0. Bait, shield and
all-four gain +50 reader points, but no reader margin is estimable from one pairing.
No measured improvement is established.

Across 12 battles per candidate, bait-only chose cheap **9/19** times (47% ± 22 using a
simple prompt-level normal margin); all-four **10/20** (50% ± 22). The swap override fired
once in all-four's PvPoke games and zero times in the standalone candidate's tiny sample.
The unit tests exercise both search heads, the shielding gates, fallback exclusion and
the fresh next decision; a larger screen must measure how often this conservative rule fires.

Search median / p99 / maximum in milliseconds, in candidate order: 109/554/641,
125/547/672, 156/609/672, 109/606/672, 156/530/594, 125/400/766.
These runs lift website deadlines; they are not the league's live timing measure.

### Creator exam (people judge)

Both exact requested commands completed without decision errors, using default engine
seed 1: `creator-finish-safe.out` (12 seconds) and `creator-bait-mix.out` (11 seconds).
Each covers 60 positions from 27 records: 24 holds, 12 shields, 11 switches, 13 throws.
They reuse 100-play-out values per action, value seed 1; no thrown move required added energy.

The existing website answer cache had **3 asks** per position, while each new candidate
had 1. Retaining this initial output as a record, not a controlled comparison: website
near-best was 70.0% ± 11.7; finish_safe 75.0% ± 11.0, value change on website +0.4 ± 0.7
points; bait_mix 71.7% ± 11.5, value change -0.2 ± 0.9 points. These initial differences
mix unequal answer samples.

Reran both commands with **`--seed 5404`**, one ask for every engine, same 60 positions
and value cache. New baseline and candidate caches are separate from the older seed-1
answers. Finish run took 22 seconds including a fresh baseline; bait run took 11 seconds
and reused that same one-ask baseline. Both exit 0, no decision errors.

| Engine | Agreement | Near best | Value change on website, points | Near-best change, points |
|---|---|---|---|---|
| website | 43.3% ± 12.6 | 76.7% ± 10.8 | — | — |
| finish_safe=1 | 41.7% ± 12.6 | 73.3% ± 11.3 | +0.2 ± 1.7 | -3.3 ± 6.5 |
| bait_mix=0.4 | 43.3% ± 12.6 | 75.0% ± 11.0 | +0.3 ± 1.8 | -1.7 ± 5.7 |

Signs here are candidate minus website; the script prints website minus candidate because
the requested candidate comes first on its command line. Full per-kind outputs are in
`creator-*-fresh.out`. The exam seeds each engine from its spec string, so search dice
are not identical across specs even with the same `--seed`. Positions and action-value
tables are paired; a difference in a switch answer need not come from the new tactic.
These smokes establish no gain. The Henry unit fixture directly isolates the finishing bug.
This judge continues with our bot and cannot measure real human reads.

## Coordinator run

`runs/lab-tactics-league.cmd` is exactly one cmd.exe line: website reference, four
individual tactics plus their combination, screen preset, **8 workers**, seed **5401**,
tag **tactics-screen**, measures **h2h,crowd,pvpoke,reader,predict,timing,endgame,creator**,
appending to `runs/lab-tactics-league.out`. It is written for the coordinator, not executed.
The combination is a test candidate; it includes the lower-confidence swap rule to expose
interactions. No tactic is promoted by these smoke results.

The screen includes about 20,960 simulated battles (5,000 H2H, 6,000 crowd, 3,000 PvPoke,
6,000 read/plain probe battles, 600 timing, 360 predictability), plus repeated position
queries, 318 endgames per spec and the creator exam. Scaling the 80-battle smoke gives
434.2 / 80 × 20,960 / 8 / 3,600 = **3.95 hours** for the battle portion. Allow roughly
**4–6 hours on 8 workers**, more if the shared PC is busy; this is a planning estimate,
not a measured full-screen runtime. The command was not launched.

Open questions: do gains survive a fresh screen/confirmation seed and both team fields;
does bait mixing resist the reader beyond one pairing; does the swap override fire often
enough or discard useful stored energy; and are the live timing budgets met? The requested
league command has no people measure (league does not expose one), so a larger `--people`
engine-versus run remains a useful separate follow-up if the screen selects a candidate.
