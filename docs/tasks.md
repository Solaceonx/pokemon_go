# Tasks

Open work on the bot, each brief self-contained. Read `AGENTS.md` first (setup, rules, how to claim a
task), then `docs/status.md` for every result so far. To take a task, put your name after its title here
and push that before starting.

## Where things stand (2026-10-17)

- **The bot**: hand-written rules (`Planner`, `pogo/agents.py`) plus a learned layer that may overrule
  them at shield, throw-or-hold, swap and replacement decisions (`Learner`, `pogo/learner.py`, model
  `runs/general-decide/q.npz`, margin 0.02). The layer adds about 9 points against the crowd (+8.9 ± 1.6).
- **The owner's rules that helped are on by default**: farm until they are about to reach a move, throw
  before fainting, keep charged-move timing, counter-swap to win the switch, get into the good matchup.
  Seven more were built and gained nothing (task 18 lists them).
- **The engine** (`pogo/engine.py`) is the strongest player: at each judgement call it plays each option 20 turns
  ahead in 4 imagined battles with the trained bot on both sides, and judges the result with a learned evaluation.
  65.0% ± 1.9 head to head against the bot, but that is flattered (it imagines its opponent as exactly that bot);
  the fair figure is against the crowd: +5.4 ± 3.7 points over the bot. It now runs in real time
  (`pogo/realtime.py`): searches take 18 ms median, 126 ms worst on the owner's Mac against budgets of 300 to
  2,300 ms, so it uses a small part of the time it has (task 27). Its edge is judgement, not rules: turning its
  habits into rules or into the bot's networks did not help.
- **Tracking**: owner recordings and public footage go through `scripts/recording/` to game states;
  replayed as if live, shields / Pokémon left / who is out are 98–100% right and their energy is within
  one fast move 93% of the time.
- **Team choice**: `scripts/roster_teams.py` ranks the owner's line-ups, but the answer depends on the
  opposing team list, which is not yet self-consistent (task 21).
- **Task 26 (learning from losses)** is done: every change it found costs more in won battles than it gains in lost ones.
- **Play it and learn from it**: `python3 scripts/play.py` is a browser game against the bot (`--bot engine`
  for the real-time engine). Every game is saved with its seeds; `python3 scripts/losses.py --played` then
  finds the bot's decisions that lost its games against you; `--counters` gives the bot a team that should beat
  yours (`scripts/counters.py`). `python3 scripts/lineup_site.py` opens a page
  (localhost:8767) for the win chance of any two teams, every lead against every lead. Both are also online at
  solaceonx.github.io/pokemon_go_pvpbot (built by `scripts/build_pvpbot_site.py`; games played there come back
  through `scripts/import_played.py`).

## Open tasks

| # | Task | Needs |
|---|---|---|
| **41** | **Shield calls the way strong players make them: how far the trained bot may overrule the rulebook's shield call** — Marco; measured 2026-11-04, no gain against bots; merged 2026-11-05 as a record; exam screen 2026-11-05: `shield_margin=0.05` better for both players on 3 picks, into exam 2 | Done; exam 2 |
| **42** | **Opponents fitted to people: the rulebook's settings fitted to human decisions, as imagined and test opponents** — for Marco after task 41; **data ready on branch `task42-export` (2026-11-05)** | Marco's machine; small data |
| **43** | **Let the engine search swaps in the middle of a matchup: today only the rulebook makes them** — Marco; measured 2026-11-04, **no gain against bots**; merged 2026-11-05 as a record; exam screen 2026-11-05: no gate helps | Done; results in `status.md` |
| **44** | **The bot and the engine for any team: train on teams from the top 300 and form-changers, and test the engine on unfamiliar teams** — for Marco after task 43 (the owner, 2026-11-05) | Marco's machine, a few hours |
| **40** | **The live loop on an Android phone from the PC: connect, calibrate, watch only, then input step by step** — for the Claude agent on the owner's PC (the owner, 2026-11-04); replaces the iPhone route of task 13 | Owner's PC, an Android phone on USB, the owner present |
| **39** | **Train the engine on its own games: the trained bot learns the engine's choices, the evaluation learns who won, three rounds** — for Marco (the owner, 2026-11-02: the medium size); built 2026-11-02 (`scripts/engine_loop.py`); done 2026-11-03 after two rounds of 10,000 games: **no gain** (round 1 48.6% ± 1.5 head to head against E_0, round 2 46.9% ± 1.5; crowd and PvPoke within the margins). Round 3 and the confirmation not run (the owner's rule: only if round 2 beat E_0 beyond its margin). Networks in `runs/engine-loop/round_N/` for the exam (`status.md`) | Done |
| **35** | **Fix the engine's look-ahead: varied imagined opponents, fair judging, keeping the switch** — Marco; done 2026-10-30: **varied imagined opponents confirmed at 32** (51.7% ± 1.2 head to head, +3.2 crowd, +8.9 PvPoke on a fresh seed); judging changes do not help and keeping the switch is worse. Not adopted: run before the nesting fix, and on the exam `matching` plays the two players' shared answer least often (`status.md`) | Done |
| **27** | **Give the engine the time it has** — Marco; done 2026-10-18: **32 imagined battles adopted** (53.4% ± 1.2 head to head, +1.7 crowd, +5.5 PvPoke on a fresh seed); a longer look-ahead does not help. Also found and fixed the shared evaluation cache in the measuring scripts | Done |
| **34** | **Readable baits: throwing and shielding them evolved against each other** (`scripts/coevolve_baits.py`, `pogo/coevo.py`) — on the owner's PC (`docs/run_elsewhere.md` section 6); Marco: do not run | Owner's PC, ~1 h |
| **33** | **Retrain the bot's networks: form inputs, two play-outs per option, mixed opponents (one job)** — to run on the owner's PC (`docs/run_elsewhere.md`); Marco: do not run | Owner's PC, ~4 h |
| 32 | Opponents as people bring them: **done 2026-10-18.** The engine's edge holds on the PvPoke field (+4.0 ± 1.6 on the crowd), no weakness against Cramorant or Mimikyu. Owner's rule: realistic but not overfit, so new measurements, team choice and books use `--field mixed` and must not lose on `--field standard`. Opening book on the mixed field: +5.2 ± 1.1 there, +1.2 ± 0.7 on the usual (the PvPoke-only book is overfit). Team choice on the mixed field, cross-checked: the owner's three are best with Jellicent leading (59.4% mixed, 71.2% usual); Vigoroth-lead winners are overfit. Answers to every arrival (`scripts/answers.py`) add nothing beyond the opening book. Open: an opening book for a Jellicent lead. | Python |
| **25** | **Let the engine search shield decisions** — Marco; measured 2026-10-18: no gain, keep off | Done; results in `status.md` |
| **28** | **Opponents in the look-ahead that are not our own bot** — Marco; measured, not adopted: outside gains but fresh head-to-head regression | Complete, 2026-10-18 |
| **29** | **Mixed choices at simultaneous moments, and plenty of randomisation** — Marco; done 2026-10-18: no confirmed gain | Done |
| **30** | **Evolve the rulebook and the engine's settings** — Marco; rulebook done 2026-10-18: **evolved rules confirmed** (54.0% ± 0.9 alone, bot on top 51.6% ± 0.8), **made the default 2026-10-19 (owner)**; the crowd keeps the standard values (`STANDARD_RULES`); the engine-settings run (`engine-1`, stopped at 12 of 30 generations) found a 60-turn look-ahead that wins head to head (54.4% against the live engine) but not against the crowd or PvPoke and is too slow live: not adopted | Done |
| **31** | **Self-play improvement loop** — Marco; done 2026-10-18: round 1 predicts better but plays no better (49.2% ± 1.5); stopped | Done |
| 23 | The engine in real time: built; pauses measured from recordings and set as defaults; nothing cut on the owner's Mac. Open: search the shield and move outcomes during the 9 s a charged move plays (needed if task 27 adopts a slower setting) | Python, numpy |
| 21 | Opposing teams as good as ours, for choosing a team | Python, numpy, hours of computing |
| 24 | Live assembly without rebuilding every half-second | Python |
| 5 | Learn from the tracked games (teams, movesets, habits seen) | Python |
| 8 | Predict hidden teams from real team combinations | Python, real teams (task 5) |
| 7 | Opponent stats from CP, move priority and damage | Python |
| 16, 17, 22 | Footage: acceptance work on public VODs, the reserved official sample, whole-VOD splitting | Codex; video access |
| 15 | Train the bot on the tracker's uncertain picture | **On hold** until real-game testing |
| 13 | Live loop on the phone (iPhone Mirroring on the Mac) | Superseded by task 40 |

**Done or stopped** (details in `status.md`): 2–4 and 12 (footage to game states, by `scripts/recording/`),
6 (PvPoke's AI, `pogo/pvpoke_ai.py`), 9 (exact endgames, `pogo/endgame.py`, no significant gain),
10 (form-changing Pokémon, 132 of 132 PvPoke battles; not yet in the training pools), 11 (simulator 1.2–1.4× faster), 14 (exploiters gain nothing beyond the margin), 18 (owner's rules),
19 (retrain, adopted), 20 (mid-matchup swap head, not adopted), 26 (losses: 72% had a decisive decision in
hindsight, but no change helps once wins are counted). Task 1 (catalogue of videos) is partly
covered by `data/video_sources.csv`; task 3 (fast frame recognition for live play) waits on task 13.

## 41. Shield calls the way strong players make them — for Marco (2026-11-04; Marco's idea E)

**State.** measured 2026-11-04, no gain against bots; on the exam next (owner's Mac).

**Why.** Two strong players answered the exam (`docs/benchmarking.md`). Its clearest split is shields: on the owner's 7
shield calls the owner and the rulebook shield 6, the trained bot and the engine 1; where both players agree, 3 of the
engine's misses are hits both shield and it does not. The engine's shield calls are the trained bot's
(`Learner.shield` in `pogo/learner.py`: the rulebook's call, `Planner.shield`, overruled when the q's shield head rates the
other answer higher by the margin, 0.02; one margin serves every head). Task 25 found that letting the engine search
shields gains nothing against bots. So the question is narrower: how far should the learned head overrule the rulebook?
Its shield habit was learned against bots, which do not bait the way people do.

**Build.** A separate margin for the shield head (`shield_margin`, default the current margin, so nothing changes), and
`shield_toward=1`, under which the head may turn a "no" into a shield but never a shield into a "no". Both must reach the
trained bot inside the engine (an `Engine` keyword passed on, and keys in `scripts/engine_versus.py`), so the owner's Mac
can score the same settings on the exam with `scripts/exam_variants.py` (the answers are not in the repo). Tests: the
defaults play the same games as before.

**Candidates** (at the website's settings, 32 imagined battles): `shield_margin` 0.05, 0.1, 1 (the rulebook decides), and
`shield_toward=1`; baseline the website engine.

**Judges, all three, in this order.**
1. **Exact endgames** (`python3 scripts/bench.py score ... --rulers endgame`, the frozen `runs/bench/endgame-1.jsonl.gz`):
   points given away against exact play, on its 48 shield calls (6 from real games) reported on their own. No model
   of the opponent, so it is the independent judge, but only for late positions.
2. **Bot fields:** `engine_versus.py --field mixed`, 1,500 pairings both ways, 1,500 crowd, 750 PvPoke, against the website
   engine. A candidate must not lose beyond the margin on any of them.
3. **The exam:** the owner's Mac scores the candidates once they are pushed. Print how often each candidate shields per
   shield prompt, for comparison with the players.

**Done when** the table of all candidates on judges 1 and 2 is in `status.md` with the commands, the best on judges 1-2
is confirmed on a fresh seed (2,000 / 2,000 / 1,000), and the code is in a pull request. The owner decides after the exam
score. Expect a few hours.

## 44. The bot and the engine for any team — for Marco after task 43 (the owner, 2026-11-05)

**Why.** The owner wants the engine to play any team, not only teams from PvPoke's top 50. The trained bot's networks
were trained on top-50 teams only (`scripts/decide.py` draws from `gd.meta(50)`, no form-changers), but their inputs
are general (health, energy, damage of each move against this opponent, move costs, shields, the rulebook's pick), not
species. `scripts/any_team_test.py` (2026-11-05; `status.md` on `wide-teams`, "Does the trained bot work on any team?") played 60 random
teams, each piloted once by the trained bot and once by the rulebook with the same opponents and dice:

| Group | Trained minus rulebook |
|---|---|
| Top 50 (trained on) | +8.2 ± 1.6 points |
| Ranks 51-300 | +4.9 ± 1.5 |
| With a form-changer (Mimikyu, Morpeko, Cramorant, Aegislash) | +8.4 ± 1.6 |

So the bot keeps its edge with form-changers but loses about 40% of it on teams outside the top 50. The one-on-one
table's coverage made no difference (the shipped 50-Pokémon table against a 304-Pokémon one: -0.1 ± 1.3). The engine
has not been tested on such teams; it imagines their unseen Pokémon from its `pool` (`pogo/engine.py`, top 50 on the
website).

**Start from branch `wide-teams`** (not merged: it holds the owner's Disguise rule in `pogo/`, `scripts/wide_teams.py`,
`scripts/any_team_test.py`). Build the 304-Pokémon one-on-ones first: `python3 scripts/wide_teams.py --table-only`
(under a minute; `runs/wide-teams/matchups.json`, not in git).

**Part A: train for any team.** Give `scripts/decide.py` a `--pool N` option (default 50: nothing changes) that draws
example teams from `wide_teams.species_pool(gd, N)` (the top N, the mixed field's Pokémon, the reference teams), plus
the four form-changers when `--forms` is on, and reads the wide table. Candidates, each with the same example time as
the current model (`--minutes 60`, three workers):
1. `--pool 300`;
2. `--pool 300 --forms` (form-changers in the pool and the form inputs);
3. the better of 1 and 2 with `--start runs/general-decide/q.npz`.

Task 33's planned retrain (two play-outs per option, `--field mixed`) is a fair fourth if time allows.

**Judges for A.**
1. **Any team:** `python3 scripts/any_team_test.py --net <candidate> --seed 8` (a fresh seed). The candidate must
   raise the ranks 51-300 edge beyond the margin and lose nothing beyond the margin on the other two groups.
2. **No loss where we are now:** the candidate against the current `q.npz` on the usual bot fields, top-50 teams:
   `decide.py`'s closing test against the rulebook, and `engine_versus.py --field mixed` with the website engine on
   each network (1,500 pairings both ways, 1,500 crowd, 750 PvPoke).
3. **The exam:** the owner's Mac scores the best once pushed.

**Part B: the website engine on unfamiliar teams.** Add a `--pilot engine` choice to `any_team_test.py`: the
website engine (`pogo/realtime.py` `WEBSITE` settings, 32 imagined battles) in place of the rulebook, so the table
reads engine minus trained bot per group; 10 teams per group and 100 battles each are enough to start. Run it twice:
- with the engine's `pool` as on the website (top 50);
- with the pool widened to `species_pool(gd, 300)` plus the form-changers.

The opponents are the mixed field throughout. If the engine's edge shrinks on the 51-300 group, report whether the
wider pool brings it back, and the search time per decision (release check: p99 under 800 ms).

**Done when** the tables for A and B are in `status.md` with the commands, the best network is confirmed on a fresh
seed (2,000 / 2,000 / 1,000 on judge 2), and the code is in a pull request against `wide-teams`. The owner decides
after the exam whether the new network ships.

## 43. Let the engine search swaps in the middle of a matchup — for Marco after task 41, before 42 (the owner, 2026-11-04)

**State:** measured 2026-11-04, **no gain against bots**; on the exam next (owner's Mac).

**Why.** In a website game (2026-11-04) the engine led Tinkaton into the owner's Quagsire (Mud Shot / Mud Bomb / Stone
Edge), took a Mud Bomb, and stayed in at 50 HP with 90 energy, throwing Bulldoze; the owner asked why it did not swap to
Florges. The engine asks the swap question once, when a matchup starts (`Planner._pick_switch` returns nothing once
`_judged` holds the matchup; `Learner._swap_choice` → the "swap" head). At 4:00 it rated stay 54%, Florges 37%,
Rillaboom 38% (96 imagined battles), and that was the last time it asked. Later swaps go through
`Learner._pick_switch`, which offers the "mid_swap" head only when the network has one; the website's
`runs/general-decide/q.npz` does not (task 20 trained one, not adopted), so every mid-matchup swap is the rulebook's
sacrifice/rescue rule and the engine's `mid_swap` head is never reached. A fresh engine asked at 3:40 (Tinkaton 50 HP)
rates Florges 60%, Rillaboom 62%, stay 46%. With both real teams known and the trained bot playing both sides, a swap
to Florges at 4:00 wins 77% ± 5 and staying 27% ± 5 (300 games each). The lead call itself is mostly unknowable:
against guessed back lines the engine prefers staying even with play-outs to the end (60% against 49%), and only with
the owner's real back line and play-outs to the end does it flip (Florges 80%). The re-ask later in the matchup is
the part to fix.

**Build.** An `Engine` keyword, `mid_swap_search` (default off, so nothing changes), under which the trained bot's
mid-matchup gate opens without a learned head: `Learner._decide("mid_swap", ...)` already falls back to the rulebook's
choice when the head is missing, so the engine's search then gets the decision with the rulebook's pick as default.
Gates to try (when the swap question is asked again in an already judged matchup):
- **task 20's gate:** the switch is ready, our Pokémon can act, and they are at most two fast moves from their cheapest
  charged move;
- **after a charged move lands on us:** once per charged move;
- **both.**

Reach it from `scripts/engine_versus.py` keys and `scripts/exam_variants.py`. Tests: off plays the same games as before.

**Candidates** (website settings, 32 imagined battles): each gate, and each gate with `switch_edge` 0.05 (task 35 found
keep-the-switch settings lose against bots, while the exam rewards switching less often, so the bar for a mid-matchup
switch is part of the question). Baseline: the website engine.

**Judges.**
1. **Bot fields:** `engine_versus.py --field mixed`, 1,500 pairings both ways, 1,500 crowd, 750 PvPoke, against the
   website engine. A candidate must not lose beyond the margin on any of them.
2. **Time:** more decisions are searched, so run `scripts/release_check.py`'s timing on the best (p99 under 800 ms, cut
   short under 20%).
3. **The exam:** the owner's Mac scores the candidates once pushed. Report how often each switches mid-matchup per
   battle, beside the baseline.

**Done when** the table of candidates on judges 1 and 2 is in `status.md` with the commands, the best is confirmed on a
fresh seed (2,000 / 2,000 / 1,000), and the code is in a pull request. The owner decides after the exam score.

## 42. Opponents fitted to people — for Marco after task 41 (Marco's idea A)

**Why.** The engine plans against a copy of itself, so its gain falls as opponents get less like it (+17 against the
trained bot, −2 against PvPoke's AI, and the owner is about as far from it as PvPoke's AI; `docs/benchmarking.md`). Task 35's
mix of hand-varied styles helps against bots but not on the exam. Fitting the styles to people is the direct fix.

**Data, and its limit.** About 55 website games of human decisions, nearly all the owner's, plus the two exams. A small
model of the owner (`scripts/people_model.py`) picks the owner's move 66% of the time against the trained bot's 62% and
stops improving after about 10 games, so expect a small change at first. **The data is on branch `task42-export`
(2026-11-05); start from it:** `runs/people/owner_games.jsonl`, the owner's 35 website games with no names (538 of their
decisions), each with its teams, dice and both sides' decisions, so every position replays exactly as in
`scripts/exam_positions.py` (`scripts/export_people.py` made it and checks the replay). **Never fit on a game's
`held_out` decisions:** they are the exam's 40 positions, and the owner answered many of them as played. The two exams'
answers stay private. Task 40's live games will add real opponents' decisions; refit then.

**Fit.** The rulebook's settings (task 30's genes) chosen to play what the people played, on four fifths of the games, by
how often the rulebook's pick is theirs; scored on the held-back fifth against the rulebook, the trained bot and the
people model. **Use** it as one imagined style in the engine's mix, and alone.

**Judge** on the exam (the owner's Mac) and real games, and on the bot fields for no loss. **Never by battles against the
fitted opponent itself:** that is how `matching` looked good in simulation and ranked last with both players.

## 40. The live loop on an Android phone from the PC — for the Claude agent on the owner's PC (the owner, 2026-11-04)

**Why.** The bot's strategy has stopped improving in simulation (tasks 31, 35, 39), and the owner finds the website
engine hard to beat; what is missing now is real games. The iPhone route (task 13: iPhone Mirroring on the Mac,
`helper/phonectl.swift`, `pogo/phone.py`) passes taps, but synthetic drags are slow (about a second a stroke) and a press
that lingers reads as a long-press; the charged-move minigame needs quick, curved drags (a charged move does a quarter
to all of its damage by how well it is swiped, and every number the bot learned assumes it is swiped well). On Android
over USB, scrcpy mirrors the screen at about 35-70 ms (its own figure) and injects touches directly, drags included.
The phone plays on the owner's **second account**; the owner accepts the ban risk there (automating the game breaks
Niantic's terms). Never the owner's main account.

**Rules for this task, on top of `AGENTS.md`.**
- Installs are downloads: ask the owner first, naming each one and its source, official sources only (Android
  platform-tools from developer.android.com, scrcpy from github.com/Genymobile/scrcpy releases, Python packages from
  PyPI). The reader needs Python 3.12 (rapidocr does not install on 3.13); `scripts/recording/README.md` lists its
  packages.
- **No input to the phone until the owner says so for that step.** Test gestures only on a harmless screen: a blank
  drawing app, or Android's developer option "Pointer location", which draws every touch. Never on the home screen,
  in lists, mail or messages (on the iPhone a test drag rearranged the owner's apps). One gesture at a time; stop
  at the first surprise. In the game, the keep-out zones in `pogo/controls.py` stay (the flee button forfeits).
- Team Leader (training) battles before GO Battle League; GO Battle League only with the owner's yes.
- Recordings and frames stay out of git (no large files); results go in small text files and `docs/status.md`.

**The team.** Jellicent (Hex / Surf / Shadow Ball) and Clodsire (Poison Sting / Earthquake / Stone Edge), with Araquanid
or Mandibuzz third: the owner's choice once caught, with the real IVs. All are in the bot's matchup table
(`data/matchups.json`, 50 species; a Pokémon outside it counts every matchup as even, so do not swap in one that is
not there without measuring). Put the alt team in its own file beside `data/owner_team.json`, never over it.

**Steps.** Each one ends with its numbers in `docs/status.md`, and the next starts only with the owner's yes.

1. **Connect.** `adb devices` sees the phone; scrcpy mirrors it. Write `pogo/android.py` with the same interface as
   `pogo.phone.Phone` (`doctor`, `shot`, `tap`, `drag`, `path`, `record`, with its dry run and action cap), frames
   taken from scrcpy's video stream (`adb exec-out screencap` takes hundreds of ms a frame, too slow) and touches through
   scrcpy's control channel (`adb shell input` only as a fallback: it cannot draw fast curves). Tests with a fake device,
   no phone needed. Measure the delay from a change on the screen to the frame arriving, at the 50th and 99th percentiles.
2. **Calibrate.** The reader's regions and the touch points in `pogo/controls.py` were measured on iPhone recordings
   (1206 x 2622); the Android screen has another shape. From 2-3 of the owner's screen recordings of battles on the
   Android phone, re-measure them (`scripts/recording/contact_sheet.py`, `overlay_controls.py`), then run
   `python3 scripts/recording/run.py` on the recordings and compare its verdicts with the iPhone ones (`status.md`,
   real recordings).
3. **Watch only (no input).** The owner plays; live frames go through the reader, the tracker and the engine
   (`pogo.realtime.WEBSITE`), and every decision's choice is logged with its time. Record the screen at the same time
   so the live states can be checked against `run.py` on the recording. Measure screen-to-decision delay against the
   targets in `status.md` (99% within 500 ms, aim 215 ms in all). Done when five games are logged, with the delay
   figures and how often the live state (shields, Pokémon left, who is out, energy) matches the recording's.
4. **Input check (the owner's yes).** On "Pointer location": taps, then `path` drags at minigame speed; measure the delay
   from sending to the touch showing.
5. **The minigame (the owner's yes).** Record the owner's own swipes for each charged-move type on the team (`record`
   listens and never acts): Water (Surf), Ghost (Shadow Ball), Ground (Earthquake), Rock (Stone Edge), plus the third's.
   Ghost and Ground are not in the swipe library (`data/minigame/`) at all. Replay them in Team Leader battles and
   read the rating the game shows (Excellent, Great, Nice).
6. **Whole battles against Team Leaders (the owner's yes),** the bot choosing and sending every touch; then the owner
   decides on GO Battle League.

**Done when** steps 1-3 are done and written up, with `pogo/android.py`, its tests and the calibration in a pull request
(tests and `scripts/check_pvpoke.py` pass). Steps 4-6 follow as the owner allows.

## 39. Train the engine on its own games — for Marco (big job, the owner chose it 2026-11-02)

**Why.** The owner now finds the website engine hard to beat and wants it trained further. The engine is two
learned parts inside a look-ahead: the trained bot (`runs/general-decide/q.npz`, `pogo/learner.py`) plays both
sides of every imagined battle, and the evaluation (`runs/eval/eval.npz`) judges each one where it stops. This is the
AlphaZero loop: the engine plays itself, the trained bot learns to choose what the engine chose, the evaluation learns
who won, and the improved engine plays the next round. Task 31 tried only the evaluation half, with a 4-sample engine,
for one round (predicted better, played no better, 49.2% ± 1.5) and stopped. Untried: the trained bot learning the
engine's choices, self-play at the website's strength, and more than one round (plateaus are common in this kind
of training, so this job does not stop early). Task 31's other lesson stands: October's distillation fitted the bot
to the look-ahead's 20-turn worths, which are short-sighted, and it got worse; here the value comes from who won.

**Before.** `git pull`; start from `main` as it is (the website's networks and settings; task 35's branch is not
merged and its settings are not used). Tests and `scripts/check_pvpoke.py` pass. Use `W` = the cores you can spare.

**Each round r** (engine E_r = `pogo.realtime.WEBSITE` settings, horizon 20, no clock cuts, with networks q_r, eval_r;
E_0 is the website's engine):

1. **Self-play.** 10,000 games of E_r against E_r on the mixed field (`--field mixed`), a fresh seed each round,
   a fresh evaluation cache for each player in every game (task 27's bug). At every decision of either side save the
   trained bot's inputs and options as `scripts/decide.py` does, the engine's pick, whether it overrode the bot, and
   who won the game. Save as it goes and resume. Extending `scripts/selfplay_eval.py` (`--samples 32`) into a new
   script is the natural route; keep task 31's script reproducible.
2. **Evaluation.** Refit eval on positions from this round's games against who won, as task 31 does.
3. **Trained bot.** Refit each head of q (throw, swap, replace, shield) starting from q_r: the chosen option's output
   regresses to who won (as a win share), plus 0.3 × cross-entropy toward the engine's pick over the softmax of the
   head's outputs divided by 0.02 (the margin). These two numbers are fixed in advance, not tuned. Keep the network
   sizes, so the website speed is unchanged. Hold back a tenth of games and print fit and agreement on them.
4. **Measure** E_{r+1} (q_{r+1}, eval_{r+1}) against **E_0**, not the previous round, so the rounds read as one
   curve: `scripts/engine_versus.py` (add a `q=` path key beside the existing `eval=`), 1,500 pairings both ways,
   1,500 crowd and 750 PvPoke battles, at 32 samples, with the search-time lines.
5. Go on to the next round from the newest networks whatever the result. Three rounds.

**Since 2026-11-03** Marco's play-out caches are in `main` (same games, about 2× faster self-play; capped at 15,000 entries, which
a long PC run may raise). Pull them in only between stages, never under running workers; the games do not change.

Start with a timing run of 50 self-play games and print core-seconds a game. The estimate is about 25; if it is over
40, use 6,000 games a round and say so.

**Confirm** the round with the best head to head against E_0 (if none is above 50%, the best one anyway, labelled as
such): fresh seed, 2,000 pairings both ways, 2,000 crowd, 1,000 PvPoke, against E_0. Then `scripts/release_check.py`
on it with the candidate networks swapped in locally (do not commit the swap).

**Done when.** `status.md` has, per round: games played, fit and agreement on held-back games, and the three changes
against E_0 with margins and search times; then the confirmation, the commands as run and the core-hours used. Push
the `.out` files and each round's `q.npz` and `eval.npz` under `runs/engine-loop/round_N/` (small files). Do not change
defaults or the website: the owner decides, after the owner's side scores the candidate on the owner's exam (the exam's
key is private, so that step is not Marco's). Adoption needs head to head above 50% beyond its margin and no loss
beyond its margin against the crowd or PvPoke ("Rules for proposing a change"). Report a failure plainly.

## 35. Fix the engine's look-ahead — Marco (big job, assigned 2026-10-28)

**Why.** The engine loses website games to the owner on decisions its search makes against the trained bot's own
better pick (`status.md`, "Why the engine loses to the owner"). Two causes found: once the person's three Pokémon are
seen, its imagined battles are all the same battle (the imagined opponent is the trained bot, nothing unseen is
left to draw), so 32 "samples" are one look-ahead; and each option is judged after `horizon` *steps*, which can be
different moments of the game (throws and faints take turns), so the learned evaluation compares unlike positions.
The owner adds: in linear games, win the matchups and keep the switch (the bot sometimes sends a Pokémon in after a
faint and swaps straight out of it, spending its switch).

**Built (2026-10-28, all off by default; `tests/test_engine_options.py`).** `pogo/engine.py` settings, all usable in
`scripts/engine_versus.py` specs: `judge=steps|turn|end` (stop every look at the same game turn, `horizon` turns on,
or play it to the end, scored by `decisive`); `switch_edge=X` (a swap the search finds must beat staying by X more);
`stay_after_replace=1` (never swap out on the turn of a replacement). Existing: `opponents=mix,matching=1`
(task 28 / 2026-10-20: varied imagined opponents weighted by every decision seen).

**Run sheet.** Set `W` to the cores to spare. Each command saves as it goes; run it again to resume. Smoke test on the
owner's Mac: playing 32 looks to the end costs about 20 core-seconds a battle with single decisions up to 20 s, so the
grid uses 8 imagined battles (both sides) and only the winner is confirmed at the live 32.

```bash
# 1. Grid, mixed field (about 20-40 core-hours)
nice python3 scripts/engine_versus.py --tag look-grid --field mixed --seed 3551 --workers $W \
  --pairings 1000 --crowd 1000 --pvpoke 500 --baseline "samples=8" --candidates \
  "samples=8,judge=turn,horizon=40" "samples=8,judge=turn,horizon=80" "samples=8,judge=end" \
  "samples=8,opponents=mix,matching=1" "samples=8,opponents=mix,matching=1,judge=end" \
  "samples=8,switch_edge=0.05,stay_after_replace=1" "samples=8,switch_edge=0.1,stay_after_replace=1" \
  "samples=8,opponents=mix,matching=1,judge=end,switch_edge=0.05,stay_after_replace=1" > runs/look_grid.out 2>&1
# 2. Confirm the best one at the live 32 imagined battles on a fresh seed (about 30 core-hours); put its settings
#    after "samples=32," (for example "samples=32,opponents=mix,matching=1,judge=end")
nice python3 scripts/engine_versus.py --tag look-confirm --field mixed --seed 3552 --workers $W \
  --pairings 2000 --crowd 2000 --pvpoke 1000 --baseline "samples=32" --candidates "samples=32,BEST" > runs/look_confirm.out 2>&1
```

"Best" means the largest gain against the crowd and PvPoke's AI together whose head to head is not below 50% by
more than its margin (the opponents that matter are people, not this engine; a bot-like imagined opponent is exactly
right only against itself). If two are close, confirm both (two candidates in step 2).

**Done when.** `status.md` has both tables (head to head, crowd and PvPoke changes with margins, and the search-time
lines: median, 99th percentile, worst), and the commands as run; push `runs/look_grid.out` and
`runs/look_confirm.out` (not the json). Do not change defaults or the website: the owner decides on adoption, and
the search times must be checked in the browser first (the live budget per decision is 300-2,300 ms on the owner's
Mac, and the browser is slower than native Python).

## 33. Retrain the bot's networks — on the owner's PC (the owner, 2026-10-19: all three changes as one job; how to run it elsewhere: `docs/run_elsewhere.md`)

**Why.** The bot's networks (`runs/general-decide/q.npz`; 45 inputs, `pogo/learner.py`) were trained on the usual
pool, which never held Cramorant or Mimikyu (8.5% and 8% of team slots in PvPoke's data, status: "Team shapes, and
PvPoke's public team data"), cannot see a form-changer's state, and learn from one play-out per option, whose noise
is what limits them (status: "Is the network too small? No"). One run changes all three:

- `--forms`: six more inputs (`form_state()`): for both Pokémon in play, a form other than its starting one, a
  disguise still up, a catch in Cramorant's mouth. Zeros for everything else.
- `--playouts 2`: each option played out twice (the second with fresh dice shared by all options) and averaged:
  steadier targets, half as many examples for the time.
- `--field mixed`: teams as PvPoke's usage data has them three times in four, the usual draw otherwise.
- `--start runs/general-decide/q.npz`: the current model (widened with zero weights) pilots the first round, so the
  first positions come from a good player. Every round still fits a new network on all examples.

**Before.** Done 2026-10-19: `engine-batch` is merged into `main`, and the evolved rulebook is the default (the
owner's yes), so this run trains the networks on top of it. Pull first.

**Run** (4 workers, `nice`; about 4 h collecting, 1 h fitting and validating; saves after every round):

```bash
nice python3 scripts/decide.py --run qnet-1 --forms --playouts 2 --field mixed --both-sides 0.5 --start runs/general-decide/q.npz --minutes 240 --rounds 4 --workers 4 > runs/qnet-1.out
nice python3 scripts/compare_models.py runs/general-decide/q.npz:0.02 runs/qnet-1/q.npz:auto --field mixed --battles 4000 --workers 3 --seed 3301 > runs/qnet-1-compare-mixed.out
nice python3 scripts/compare_models.py runs/general-decide/q.npz:0.02 runs/qnet-1/q.npz:auto --field usual --battles 4000 --workers 3 --seed 3302 > runs/qnet-1-compare-usual.out
```

If the first command stops part-way, `--resume --rounds R --minutes 60*R` (R = rounds not yet done) carries on
from the saved examples.

**Adopt only if** (status: "Rules for proposing a change") on the mixed field it beats the current model against the
crowd beyond the margin and scores above 50% beyond the margin head to head, and on the usual field it loses
neither beyond its margin; then confirm the mixed comparison once more on `--seed 3303`. If adopted, keep the old
model as `runs/general-decide/q_v6.npz`, copy the new one and its margin in, and note that the engine and website
pick it up (the Learner reads the form inputs from the model's size). One job measures the three changes together;
if it fails, say so and do not split it up without the owner.

## For Marco: the engine-strength batch (assigned by the owner, 2026-10-17)

The owner's notes for Marco:
- **Prioritise using Astra agents** for this batch.
- **Use the machine fully.** The owner allows any number of workers on Marco's machine (128 GB of RAM); the
  three-worker limit in `AGENTS.md` does not apply to these tasks there. Still use `nice`, one NumPy thread per
  worker (the scripts set it), runs that save as they go and can resume, and never edit code a running job imports.

Order: 27 and 25 first (cheap and likely to pay), then 28 and 29 (what matters most against strong people),
then 30 and 31 (the big jobs; start them early in the background if cores are free). Each is independent;
combine adopted changes at the end and confirm the combination on a fresh seed.

**The code is written and smoke-tested (2026-10-17); this batch is mostly running it at scale.** All new engine
options are off by default, and with them off the engine plays exactly as before (checked game for game against
the previous code). `tests/test_engine_options.py` checks each option takes effect.

| Piece | What it is |
|---|---|
| `scripts/engine_versus.py` | Engine settings against each other (head to head, both ways), and each against the crowd, PvPoke's AI and the reader, on the same battles; search time per decision; resumes by `--tag` |
| `pogo/engine.py` options | `heads=...+shield` (task 25), `opponents=mix`, `profile=1`, `unseen=teams` (task 28), `mix=1`, `temperature` (task 29) |
| `pogo/reader.py` | The reader probe for task 29 |
| `scripts/calibrate_styles.py` | Measures each imagined opponent style's shield and bait rates, for `profile=1` (task 28) |
| `scripts/evolve_rules.py` | CMA-ES over 34 rulebook genes, or the engine's settings with `--engine`; resumes; `--final` re-scores the best (task 30) |
| `scripts/selfplay_eval.py` | The self-play evaluation loop (task 31) |

**Run sheet.** Set `W` to the number of cores to use. Each command saves as it goes; run it again to resume.

```bash
# 27: time
python3 scripts/engine_versus.py --tag time-grid --workers $W --pairings 1000 --crowd 1000 --pvpoke 500 \
  --candidates "samples=8" "samples=16" "samples=32" "horizon=30" "horizon=40" "samples=16,horizon=30" "samples=16,horizon=40" "samples=32,horizon=40"
# 25: shields
python3 scripts/engine_versus.py --tag shields --workers $W --pairings 2000 --crowd 2000 --pvpoke 1000 \
  --candidates "heads=throw+swap+mid_swap+replace+shield"
# 28: opponents (calibrate first)
python3 scripts/calibrate_styles.py --battles 4000 --workers $W
python3 scripts/engine_versus.py --tag opponents --workers $W --pairings 2000 --crowd 2000 --pvpoke 1000 \
  --candidates "opponents=mix" "opponents=mix,profile=1" "unseen=teams" "opponents=mix,profile=1,unseen=teams"
# 29: mixing and randomisation
python3 scripts/engine_versus.py --tag mixing --workers $W --pairings 2000 --crowd 2000 --pvpoke 1000 --reader 1000 \
  --candidates "mix=1" "temperature=0.01" "temperature=0.03" "mix=1,temperature=0.02"
# 30: evolution (big; start early)
python3 scripts/evolve_rules.py --run rules-1 --workers $W --generations 100 --population 32 --pairings 2000
python3 scripts/evolve_rules.py --run rules-1 --workers $W --final
python3 scripts/evolve_rules.py --run rules-bot-1 --pilot bot --workers $W --generations 60 --population 24 --pairings 1500
python3 scripts/evolve_rules.py --run engine-1 --engine --workers $W --generations 30 --population 16 --pairings 300
# 31: self-play (big)
python3 scripts/selfplay_eval.py --run selfplay-1 --workers $W --rounds 5 --games 20000 --compare 1500
```

Each comparison prints the head-to-head score against the baseline and the differences against the crowd, PvPoke's
AI and the reader, with margins. Confirm the chosen setting of each task on a fresh `--seed` (a new `--tag`) before
adopting it.

**How to measure an engine change.** The engine imagines its opponent, so beating the trained bot head to head
flatters it. For every change report, on the same battles:
1. head to head against the current engine (every pair of teams both ways round);
2. against the crowd (`varied`), the fairer figure;
3. against PvPoke's AI (`pogo.pvpoke_ai.PvpokeAI`), an outside opponent nobody here trained against;
4. time per searched decision (median, 99th percentile, worst) with `scripts/realtime_trial.py --timing`, since the
   engine must still fit the live budgets in `pogo/realtime.py` on a machine like the owner's Mac.

Use `scripts/engine_versus.py` (above), not `scripts/engine_trial.py`, which plays the engine against the trained bot
only. Margins on everything; a
setting chosen from several is confirmed on a fresh `--seed` before it is adopted; every result, including those that
did not help, goes into `docs/status.md`. Adopted settings go into `RealTime`'s defaults in `scripts/play.py` and the
website (`python3 scripts/build_pvpbot_site.py`, then the owner publishes).

## How to test a strategy rule

Every rule tried since 11 October gained nothing, so first ask the engine's look-ahead:
`python3 scripts/engine_habits.py --from-saved --rules` scores rules against 45,856 recorded decisions in a
minute (remake the recording with `--battles 2000 --workers 3`, ~20 min). A rule scoring at or below zero
there is unlikely to win. Then:

1. Add the rule to the `Planner` behind an option that defaults to off (copy `hold` or `win_switch`).
2. `python3 scripts/rule_trial.py "my_rule=True" --battles 4000`: head to head against the standard
   `Planner` (the number that matters) and against the crowd on the same battles.
3. Rerun the chosen setting on a fresh `--seed`. It counts only if ahead beyond the margin there.
4. If it counts: make it the default, give it to the crowd in `varied_settings` (~80% of opponents), run
   the tests, `check_pvpoke.py` and `speedcheck.py save`, and check the bot still helps on top with
   `python3 scripts/compare_models.py runs/general-decide/q.npz:0.02`.
5. Record it in `status.md` under "Strategy guidance from the project owner", either way.

## How to train the learned layer

```bash
python3 scripts/decide.py --run my-run --minutes 180 --rounds 3 --teams data/teams.json --both-sides 0.5 --workers 3 > runs/my-run.out
python3 scripts/compare_models.py runs/general-decide/q.npz:0.02 runs/my-run/q.npz:$(cat runs/my-run/margin.txt) --battles 4000
```

- Training freezes battles at decisions, plays out every option with the same dice, and fits a network to
  the results. Examples are what matter: a core-hour gives ~30,000 shield examples; the current model
  used ~1.3 million. Bigger networks and extra inputs did not help; `--both-sides 0.5` (the bot against
  itself, both sides learning) gave +2 points head to head; at full size (`runs/both-full`) 52.6% ± 1.2 head to
  head but level against the crowd, so not adopted.
- **Accept a new model only if** it beats the current one beyond the margin against the crowd *and* scores
  above 50% beyond the margin head to head (the second command prints both). Then copy it to
  `runs/general-decide/q.npz`, keeping the old one as `q_vN.npz`, and record the table in `status.md`.
- Long runs belong on another machine, not the owner's Mac. `examples.npz` files are not in git.

## How to choose a team

```bash
python3 scripts/roster_teams.py --rival bot --listed 0.8
```

Plays every line-up from the owner's Pokémon (`data/owner_team.json`, `data/owner_roster.json`) against
the same bot on teams mostly from `data/teams.json`, and writes `data/roster_teams.json` (~45 min, three
cores). The owner's test: between equals the game is near 50-50, so a best line-up far above that means
the opposition is wrong (the script warns above 65%). `--recheck` re-scores saved line-ups in minutes.

---

## 26. Learn from the bot's own losses — done 2026-10-16 (Marco): no change survives the balance check

**Why.** The owner's idea: go back through the battles the bot lost, find the decisions where a different
choice would have won, and look for general trends. Training already plays out alternatives, but only at
the four decisions the learned layer makes and in every battle alike. This looks only at losses and tries
*every* legal choice at each moment, including switching in the middle of a matchup, which nothing in the
bot decides by learning today.

**What exists.** `scripts/losses.py`. The bot (side 0) plays itself on teams drawn half from the good-team
list and half at random. In each battle side 0 loses, every one of its decisions is replayed with each other
legal choice (fast move, either charged move, a switch to either bench Pokémon; shield or not; whom to send
in after a faint). After the changed decision the bot plays on against a different variation of itself in
each play-out (habits shifted as in the training crowd, as strong on average), because against an identical
copy every replay comes out 0% or 100%. Choices that look 0.3 better on `--screen` play-outs are re-scored on
`--confirm` fresh ones. A decision "lost the battle" when its alternative wins at least half the time where
ours won under a quarter. It prints the share of losses one decision would have won, the kinds of decision
(what we did -> what would have won), the situations at the earliest such decision in each battle, and ten
examples in plain words; rows go to `runs/losses/swings.jsonl`. Tried on 6 battles only (2 losses), about
3.5 seconds a battle on three cores; never run in full.

```bash
python3 scripts/losses.py --battles 600 --workers 3 > runs/losses.out
```

**Do.**

1. Check it first: with the opponent left unvaried, replaying our own choice must reproduce the actual
   loss (add that as a test), and the trial's examples should look sensible.
2. Run it on at least 600 battles. Report the share of losses that one decision would have won, the kinds
   and situations, and 20 examples for the owner to judge as a player.
3. A trend in losses is not yet a mistake: the same change might throw away wins elsewhere. For each kind
   that makes up 10% or more of the earliest decisions, measure the same change in the same situation in
   won battles too (extend the script to analyse wins, for example `--all`), and keep only kinds that help
   on balance.
4. Turn each kept trend into a change and measure it the usual way: a `Planner` rule (`rule_trial.py`), or
   training weighted towards those positions, or the mid-matchup switch head from task 20 trained on them.
   Head to head on a fresh seed decides.
5. Optional: the same analysis with the engine as side 0, to see which of the bot's mistakes the engine
   already avoids.

**Done when.** `status.md` has the run's numbers, the examples, which trends held up in step 3, and each
resulting change's head-to-head score on a fresh seed, whichever way it points. Run it on a machine other
than the owner's Mac.

## 23. The engine in real time: think during its own fast moves

**Why.** The engine is the strongest player in the project (65.0% ± 1.9 head to head against the trained
bot, +5.4 ± 3.7 against the crowd; `status.md`, "The first search") but a searched decision takes 45 ms
typically and up to about 400 ms on one core, against the 10 ms the latency table allowed. That table
assumed the decision starts when it is due. It need not: while our fast move plays out there is nothing to
choose, and the position when it ends is known in advance whenever the opponent only fast-moves.
`scripts/engine_timing.py` measured this on 600 battles (`runs/engine_timing.out`): predicted from the start
of the fast move, 64% of searched decisions are known exactly in advance and 99.9 to 100% of those finish in
the time the move leaves (its turns at 500 ms, less 200 ms for seeing the screen and the tap). The rest
follow something the player sees: a charged move (the game pauses), a faint, the start, or a switch by them.

**What exists.** `pogo/engine.py`: `Engine(evaluator, pool, horizon=20, samples=4, edge=0.03,
rollout="bot", q=..., margin=0.02)` is the confirmed setting (`scripts/engine_trial.py --rollout bot
--samples 4 --edge 0.03` measures it). `imagine(view, ...)` builds a battle from what a view shows, with the
opponent's unseen Pokémon drawn from the pool. `scripts/engine_timing.py` has the prediction (`_predict`:
both sides fast-move until our move ends) and the timing. The prediction there clones the real battle, using
only what our side can see; a player must build it from its view instead (`imagine` does that).

**Do.**

1. A player (for example `pogo/anticipate.py`) that wraps the engine: when it chooses a fast move, it
   predicts the position at the end of that move and starts searching it in another process (the search
   is pure Python, so a thread would only compete for the interpreter). At the decision, if the position is
   the predicted one, it plays the answer; otherwise it searches afresh.
2. A deadline for every search. Make the search work sample by sample (each option once, then each again,
   and so on), stop when time is up, and decide on what is done; with less than one sample of every option,
   play the trained bot's own pick (about 1 ms). Keep the player's internal state (what it has judged, any
   hold it has planned) as it would be had it decided on the spot.
3. Use it in `scripts/play.py --bot engine`, and log at each decision whether the prediction held, how long
   the decision waited, and whether it fell back.

**Deliver.** The player, tests (the prediction equals what happens when the opponent only fast-moves; a tiny
deadline falls back to the bot's pick), the change to `play.py`, and a table in `status.md`.

**Done when.**
- In simulation, each searched decision given the time it would have live (the fast move's turns at 500 ms
  less 200 ms when predicted; 300 ms otherwise), measured on the machine running the test: the real-time
  engine is within the margin of the unhurried engine head to head (500 or more pairings, each both ways),
  and still ahead of the trained bot against the crowd on the same battles. Report both.
- The wait at the moment of decision (median, 99th percentile, worst), the share answered from the
  prediction and the share that fell back are reported.
- `python3 -m unittest discover tests` and `python3 scripts/check_pvpoke.py` pass.

**Optional, if time is still short:** search only the close calls. The engine changed the bot's pick at
15% of searched decisions; if those are mostly where the bot's own values for the options are close,
skipping the rest saves most of the time. `scripts/engine_habits.py` records what is needed to check.

## 27. Give the engine the time it has — Marco: evaluator-cache isolation fixed; corrected measurements running

**Why.** The engine's settings (4 imagined battles per option, 20 turns ahead) were chosen when every decision had to
be quick. Live it has 300 ms (unforeseen decisions) to 2,300 ms (during a 5-turn fast move) and uses 18 ms on the
median. 40 turns ahead was only ever tried with the cheap stand-in players inside the look-ahead (worse, `status.md`,
"The first search"), never with the trained bot inside.

**Do.**
1. Run the "27: time" command in the run sheet (the confirmed engine is the baseline). Then edge 0.01, 0.03, 0.05 at
   the best of the grid with another `--tag`.
2. The search times it prints are for Marco's machine; time the best on a machine like the owner's Mac (or scale by
   a measured speed ratio) against the budgets in `pogo/realtime.py`.

**Done when.** The table is in `status.md`; the best setting is confirmed on a fresh seed (2,000 or more pairings) and
adopted if it beats the current engine head to head beyond the margin and is not worse against the crowd or PvPoke's AI.

## 28. Opponents in the look-ahead that are not our own bot — Marco; measured 2026-10-18, not adopted: fresh head-to-head regression

**Result.** Calibrated and measured all four run-sheet settings, the stronger human-style attempt and the
v2 team prior. Fixed a shared evaluator cache that made the original harness depend on worker job order,
then reran all six. The selected mixture + profiling gained +3.4 ± 2.1 crowd points and +5.6 ± 2.6 PvPoke
points on fresh seed 280281, but scored 48.4% ± 1.3 against the current engine and failed the adoption rule.
No playing defaults changed. Human-style and v2-prior extensions added no gain beyond their margins.
Dedicated timing: median 24.41 ms (95% interval 22.69–26.02), 99th percentile 96.82 ms (91.05–101.69),
observed maximum 172.66 ms; no cuts or fallbacks in 6,974 searches. All results, including invalid exploratory
runs and the unchanged trained-bot edge, are in [status.md](status.md#task-28-mixed-look-ahead-opponents-and-listed-teams-2026-10-18)
and [the exact command log](../runs/task28/commands.txt). Final suite: 228 tests, seven skips; PvPoke 108/108.

**Why.** Inside the look-ahead every opponent is the trained bot (`Engine._look`, `rollout="bot"`). That is why the
engine wins 65% against the bot but only +5.4 points more than the bot against the crowd. People do not play like
our bot: in tracked real games players kept fast-moving where the bot would throw in 187 of 337 throw disagreements
(`status.md`, "The bot against real players' decisions"), and many use a fast move before swapping (`fast_first`).

**Do.**
Built: `opponents=mix` draws each imagined opponent from `pogo.engine.STYLES` (the bot, the bot with shifted habits,
a human-like guess, PvPoke's AI); `profile=1` weights them by how well each style's shield and bait rates fit what this
opponent has done (keeping a tenth of the starting mix); `unseen=teams` draws their unseen Pokémon from a listed team
holding everyone seen so far.

1. Run `calibrate_styles.py`, then the "28: opponents" command. A smoke run shows the guessed rates in `STYLES` are
   far off (the bot shields about a third of its chances, not 70%), so calibrate before judging `profile=1`.
2. Improve the human-like style (`pogo.engine.human_settings`, a first guess: holds longer, fast move before
   swapping) from real decisions: `runs/real_decisions/` and the owner's games in `games/played/`
   (`scripts/real_decisions.py` shows how). Say what was changed and why.
3. Try `data/teams_v2.json` weights for `unseen=teams` as well as `data/teams.json`.

**Done when.** Each part measured as above. Adopted if better against the crowd and PvPoke's AI beyond the margin
on a fresh seed and not worse head to head against the current engine beyond the margin (it may lose some of its
edge against the bot itself; report it).

## 29. Mixed choices at simultaneous moments, and plenty of randomisation: measured; no confirmed gain — Marco

**Why.** Both players choose at once, every turn. The engine always takes the single best-looking option, so a player
who reads it (when it baits, when it shields, when it throws) can exploit it. The owner wants it hard to read: mix at
the mind-game moments and randomise a lot elsewhere.

**Do.**
Built: `mix=1` solves the small game when both sides have a charged move ready (our throw options against theirs:
farm or each move ready, each cell from look-ahead play-outs with both first choices fixed) and draws our choice from
the mix; `temperature` chooses among all searched options at random weighted by worth (the trained bot's pick keeps
its `edge` as a head start). Both draw from the engine's own `_mix_rng`, seeded from its seed, so saved games replay.
`pogo/reader.py` is the probe; `engine_versus.py --reader N` plays each setting against it.

1. Run the "29: mixing" command.
2. Extend mixing to the shield decision (with task 25's `shield` head) and to switch timing when both switches are
   free; vary hold lengths within the hold rule's window. Measure each.

**Done when.** The mixed engine does better against the reader than the current engine beyond the margin, and is not
worse head to head, against the crowd or against PvPoke's AI beyond the margin, all on a fresh seed.

## 30. Evolve the rulebook and the engine's settings — Marco (big job)

**Why.** The owner's idea. The rules (`Planner`) have about 30 numeric settings (`hold_cost`, `sac_margin`,
`win_switch`, `matchup_weight`, `switch_margin`, `bad_matchup`, `farm_cost`, `shield_share`, `shield_worth`,
`expect_shield`, `expect_bait`, `belief`, `sweep_chance`, `catch_gain`, `known_edge`, `fast_first` and more; read the
constructor), each tuned on its own. Evolution can search them together and find combinations tuning one at a time
cannot. Thirty numbers suit an evolution strategy; the network's thousands of weights do not (noisy win/loss fitness).

**Do.**
Built: `scripts/evolve_rules.py` (CMA-ES in plain numpy; 34 genes: 21 numbers, 11 on/off rules, the bait and shield
styles; fitness head to head against the standard on the same pairings for the whole generation; saves every
generation; `--final` re-scores the five best on fresh pairings and prints the `rule_trial.py` command to confirm).

1. Run the four "30" commands (rules alone; the trained bot on top of each candidate, `--pilot bot`, which is what
   would be adopted; the engine's settings, `--engine`).
2. Confirm the winner with the printed `rule_trial.py` command on a new seed.
3. If the evolved rules win but the trained bot on top of them does not beat the current bot, retrain the learned
   layer on the evolved rules (`decide.py --both-sides 0.5`, full size) and compare with `compare_models.py`.
4. Optional: a league. Keep a population of evolved rule sets and learned models that play each other, breed the
   winners, keep a hall of fame of earlier champions to play against; report whether the population cycles.

**Done when.** `status.md` has the run (settings, generations, the fitness curve), the fresh-seed confirmation, and the
bot on top; rules are adopted only if they beat the current ones head to head beyond the margin on a fresh seed and
the bot on top is not worse.

## 31. Self-play improvement loop: learn the evaluation from whole engine games — Marco (big job)

**Why.** The engine judges where a 20-turn look-ahead ends with `runs/eval/eval.npz`. Teaching the bot the engine's
look-ahead worths made it worse because those worths are short-sighted (`status.md`, "Teaching the bot the engine's
judgement"). Learning the evaluation from how whole games between engines actually end fixes that, and a better
evaluation makes a better search: the AlphaZero loop.

**Do.**
Built: `scripts/selfplay_eval.py` does the loop (engine-against-engine games with shifted habits, positions with how
each game ended, a new evaluation fitted on all rounds so far with a tenth of the games held out, then
`engine_versus.py` head to head and against the crowd; adopted only if it wins beyond the margin; stops otherwise).

1. Run the "31" command. 20,000 engine games a round is a guess at what is needed; if the held-out log loss of the
   new evaluation is not better than the current one, raise `--games` before concluding.
2. Only if the evaluation improves: also train the bot's networks to pick what the engine's search picks.

**Done when.** Each adopted round beats the previous engine head to head beyond the margin on a fresh seed and is
not worse against the crowd or PvPoke's AI; `status.md` has every round, adopted or not.

## 25. Let the engine search shield decisions — Marco — measured 2026-10-18: no gain, keep off

**Result.** The full run-sheet comparison (seed 2701, 2,000 head-to-head pairings both ways, 2,000 crowd
battles and 1,000 PvPoke battles per setting) found 49.2% ± 1.3 head to head, −2.4 ± 2.2 points against
the crowd and −3.2 ± 3.0 against PvPoke. All margins are 95%. No gain, so no fresh-seed strength
confirmation or promotion. `realtime_trial.py --timing 300 --workers 3 --seed 2501` measured both settings;
with shields enabled, shield searches took 26 / 70 / 94 ms median / 99th / worst, with no cuts or fallbacks.
`RealTime` now times and bounds shield searches, and the timing script accepts `--heads`.
Full results and exact commands are in `status.md` and `runs/task25/commands.txt`.

**Built (2026-10-17):** `heads=throw+swap+mid_swap+replace+shield` (`Engine._land_their_throw`: the move drawn from
those the attacker can afford, the cheaper as often as this opponent has baited, the imagined battle starting just
after it lands). Run the "25: shields" command in the run sheet; the brief below is the original.


**Why.** The engine searches throws, swaps and replacements and leaves shields to the trained bot, because
the defender does not know which charged move is coming. Shields are among the biggest decisions in a battle
(a shield is worth about a third of a Pokémon in the project's scoring), the bot agrees with real players on
only 71% of them (`scripts/real_decisions.py`), and the choice is made during the charged-move pause, so
time is not a problem for it.

**Do.** Add "shield" to what `Engine` can search. For each move the attacker could have thrown (one if only
one is affordable; otherwise weigh both, for example by how often this opponent has thrown the cheaper one,
as the Planner's `read` guess does), imagine the battle just after the throw, shielded and unshielded, play
each 20 turns ahead with the trained bot on both sides and judge it as the engine does now. The battle has no
way to start in the middle of a charged move, so build the position just after it, as
`Planner._hit_state` in `pogo/agents.py` does.

**Done when.** `scripts/engine_trial.py --rollout bot --samples 4 --edge 0.03` with shields added to `--heads`
against the same without, 500 or more pairings both ways, and the better one rechecked on a fresh seed; both
tables in `status.md`, whichever way they point.

## 21. Opposing teams as good as ours, for choosing a team

**Why.** The owner wants to pick a line-up from their own Pokémon by simulating against the teams they
will meet. Against the current list the best line-up wins far above 50%, and the winners are counters to
the list (Stunfisk, Ninetales, Feraligatr) that drop to 49–61% against other teams, while the owner's
current three lead there (`status.md`, "The team search again"). The list (`data/teams.json`) was found
with the old `Planner`, from the top 50 only, and is heavy with Steel types. Latest: best counter still
58.3% ± 1.7 against it.

**Do.**

1. Rebuild the list so that it is self-consistent: the best teams in it should score about 50% against
   the list itself, with the trained bot piloting both sides and the top 100 as the pool. One way:
   start from the current list, find the teams that do best against it (`scripts/teams.py` has the
   quick one-on-one score for picking candidates), add them, re-weight every team by how it does
   against the current mix, and repeat until the best newcomer gains less than the margin.
2. Add the teams met in real games as they come in (the `seen` counts; task 5).
3. Rerun `scripts/roster_teams.py` against the new list and compare its order with the one against the
   old list.

**Deliver.** The new `data/teams.json` with how it was built, and the roster ranking against it.

**Done when.** The best team found anywhere in the top 100 scores under 55% against the list on fresh
battles, and the owner's ten best line-ups are reported against both lists on the same battles.

## 24. Live assembly without rebuilding every half-second

**Why.** Live, the looks are rebuilt from every reading so far at each half-second
(`assemble(rows, texts, argv, span, now=t)` in `scripts/recording/assemble.py`). That takes 3 ms early in a
battle and 150 ms by its end on one core (`status.md`, "Tracking live, replayed from recordings"), too slow
next to recognition inside a 500 ms turn.

**Do.** Make the assembly incremental: keep what earlier calls worked out and redo only what new readings
can change. Keep `assemble()` as it is for offline use; add the incremental path to
`scripts/recording/live_replay.py` behind a flag (for example `--incremental`).

**Done when.** On all 47 recordings and clips with saved readings (`games/*/raw/`), the incremental path
gives exactly the looks the rebuild gives at every half-second, so `live_replay.py` prints the same
comparison either way; the worst time per half-second update is reported, before and after; the offline
command's output is unchanged; `tests/test_live_assembly.py` covers the new path. Do not tune anything on the
reserved official clips (task 17).

## 5. Learn from the tracked games

**Why.** Our simulated opponents are variations of our own bot. Real games say what
people actually do.

**Do.** From the `events.jsonl` and `states.jsonl` of every game in `games/`, weighted by
`skill_weight`:

1. Count teams and Pokémon seen; write the counts into the `seen` field of
   `data/teams.json`, adding teams that are not there.
2. Record the moves actually used for each species where they differ from our assumed
   set; write `data/movesets_seen.json`.
3. Measure habits as rates with their sample sizes: how often a charged move is
   shielded, by shields left and by damage; how often the cheaper move is thrown when
   either could be; how often and when players switch. Write `data/habits.json`.
4. Make an opponent that plays with those rates (a new function beside `varied()` in
   `pogo/agents.py`) and measure the best bot against it.

**Deliver.** `scripts/learn_from_games.py` that produces the three data files, the new
opponent, and the measurement.

**Done when.** The script runs on `games/` end to end; each habit is reported with its
sample size and is left out if it has fewer than 30 samples; the best bot's score against
the new opponent is reported with a margin, next to its score against the old crowd.

## 8. Predict hidden teams from real team combinations

**Why.** We see their lead and nothing else. Good players do not bring random threes:
certain Pokémon come together. Knowing what usually comes with what we have seen changes
when to shield, when to switch and what to save. The owner wants the bot eventually to
guess the last Pokémon, or both hidden ones.

**Do.**

1. Build the table of real combinations. Sources, best first: teams seen in tracked
   games (task 5 fills the `seen` counts in `data/teams.json`); team lists that players
   and tournaments publish, recorded with a link and a date; and, only as a fallback
   until real data exists, the simulated list already in `data/teams.json`. Keep the
   source and the skill weight of each team so they can be weighted.
2. Write `pogo/teamguess.py`: given the opponent's Pokémon seen so far (one or two),
   return likely team-mates with probabilities. Use more than raw counts: a team seen
   once should still inform guesses for similar teams (for example by what each Pokémon
   covers). It must return something sensible for a lead never seen before.
3. Report the guess in the tracker's `state()` (an `unseen_guess` list under `opponent`).
4. Use it: let `scripts/advise.py` and the lookahead in `pogo/agents.py` draw unseen
   Pokémon from the guess instead of at random, behind a flag that defaults to off.

**Deliver.** The table with sources, `pogo/teamguess.py`, `scripts/check_teamguess.py`.

**Done when.** On real teams held out from the table, the true team-mate is in the top
five guesses more often than a guess by overall popularity, with both rates and the
number of held-out teams reported; and the bot with the flag on is measured against the
bot with it off on the same battles, where opponents' teams are drawn from the table.
Say plainly if only simulated teams were available.

## 7. Opponent stats from CP, move priority and damage

**Read first.** `scripts/ivs.py` and the "IVs" section of `status.md`: a first look found
that CP leaves 92 to 433 combinations and that fast-move clues barely narrow them. The
enumeration this task needs already exists (`GameData.spreads`, `cp_at`, `with_ivs`). The
part worth doing is charged-move damage as a clue, and predicting the damage values that
matter rather than the IVs themselves.

**Why.** We assume typical stats for the opponent. The screen gives clues to the real ones.

**Do.** Write `pogo/stats_guess.py`. Given a species and the CP shown, list every level
and IV combination that gives that CP. Narrow the list with each clue: who went first
when both threw a charged move on the same turn (higher attack goes first), the damage
of each of their fast hits on us, and the damage of our hits on them as a share of their
health bar.

**Deliver.** The module and `scripts/check_stats_guess.py`, which draws random IVs for
random Pokémon, plays simulated battles, feeds the clues in, and reports how far the
list narrows and whether the true combination is always still in it.

**Done when.** The true combination is never excluded in 1,000 simulated battles, and
the report gives the median number of combinations left after one battle.

## 10. Form-changing Pokémon in the engine

**Why.** Aegislash, Mimikyu, Cramorant and Morpeko are left out. Two of them are in the
top ten.

**Do.** Add their rules to `pogo/battle.py` from the `formChange` entries in
`data/gamemaster.json` and PvPoke's source. Produce reference battles from pvpoke.com the
way `tests/data/pvpoke_duels.txt` was made (its header gives the format; PvPoke's
`Battle`, `Pokemon` and `GameMaster` are available in the page's JavaScript console).

**Done when.** `python3 scripts/check_pvpoke.py` still prints 108 of 108, and a second
file of at least 40 battles involving these four is also reproduced exactly.

## 16, 17, 22. Footage — Codex

Public Twitch clips are read and tracked (`scripts/recording/VOD_README.md`, results in `games/twitch/`);
ten official two-screen battles are reserved for testing only and their frozen evaluation is in
`docs/reserved_state_evaluation.md`; whole VODs are split into battles automatically
(`docs/full_vod_extraction.md`). Remaining acceptance work: independent labels for faints, charged moves,
forms and energy; misses and false splits on unfamiliar recordings. Do not tune on the reserved sample.

## 15. Train the bot on the tracker's uncertain picture (on hold)

**On hold.** The owner has decided this waits until testing in real games begins. Do not
start it before then.

**Why.** The bot is trained and tested with exact information: the opponent's precise
energy, exact health, the right moves and stats. In a real game it sees the tracker's
picture instead: their energy as a range, health read off a bar, some looks missed,
their moves and stats assumed. Measured cost today: the Planner playing from a rough
camera loses about 7 points (`scripts/check_tracker.py`). The learned bot has never been
tested this way at all.

**Do.**

1. **Measure first.** Extend `scripts/check_tracker.py` to pilot with the best bot
   (`Learner` with `runs/general-decide/q.npz`), and report its score from the perfect
   camera and from the rough one. That is the baseline.
2. **Make the uncertainty visible to it.** The network's inputs (`describe()` in
   `pogo/learner.py`) carry one number for the opponent's energy. Add the low and high
   ends of the tracker's range, and whether their moves are confirmed or assumed.
3. **Train through the tracker.** Generate training positions with the bot deciding from
   the tracker's picture under flawed cameras, while each option is still played out on
   the true position. This needs the tracker and the simulated camera to be copyable
   mid-game, as `Battle.clone()` is.
4. **Make the assumptions wrong sometimes.** In training, give opponents random stats
   within what their CP allows, and a non-standard fast or charged move some of the
   time, so the bot meets cases where what it assumed is false.

**Deliver.** The changes, a model under `runs/uncertain-decide/`, and a table in
`docs/status.md`: current bot and new bot, each from the perfect camera and the rough
camera, on the same battles.

**Done when.** From the rough camera the new bot scores higher than the current bot by
more than the margin, and from the perfect camera it is not worse beyond the margin.
Both conditions, with numbers. If only one holds, say so.

