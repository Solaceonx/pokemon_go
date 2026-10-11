# Outstanding tasks that can be handed to another agent

Each task below is written so that an agent (or a person) who has only this repository
can pick it up. Read [`status.md`](status.md) first, then the task.

To take a task, put your name after its title in this file and push that change before
starting, so two people do not do the same one.

## Overview

| # | Task | Needs | Depends on |
|---|---|---|---|
| 1 | Catalogue of battle videos, weighted by player skill | Web access | nothing |
| 2 | Turn videos into looks and game states | Video access, ideally Python | 1 |
| 3 | Recognition: a frame in, a look out, fast | Python, sample footage | 2 helps |
| 4 | Make the tracker cope with real games | Python | 2 helps |
| 5 | Learn from the tracked games | Python, numpy | 2 |
| 6 | Port PvPoke's battle AI | Python | nothing |
| 7 | Opponent stats from CP, move priority and damage | Python | nothing |
| 8 | Predict hidden teams from real team combinations | Python | 1 and 5 for real data |
| 9 | Solve late-game positions exactly | Python | nothing |
| 10 | Form-changing Pokémon in the engine | Python, a browser | nothing |
| 11 | Make the simulator faster | Python | nothing |
| 12 | Measure real timings from footage | Video access | 1 |
| 13 | Live loop on the phone | The owner's iPhone and Mac | 3, 4 |
| 14 | Adversarial training against stronger AI | Python, numpy, hours of computing | 6 helps |
| 15 | Train the AI to handle uncertain battle information (on hold until real-game testing) | Python, numpy | 4 helps |

Tasks 1 to 5 are the footage pipeline, in order. Tasks 6 to 11, 14 and 15 are independent
of it and of each other.

## What every task must do

- Deliver what its "Deliver" line says, and state plainly whether its "Done when" check
  was run and what it printed. Do not describe something as working unless the check ran.
- Keep to the standard library plus `numpy`. No services, no language model in the loop
  at run time.
- Do not commit videos, frames or other large files. Results go in small text files.
- Add a line to `docs/status.md` for any result, including ones that did not help.

---

## 1. Catalogue of battle videos, weighted by player skill

**Why.** We want to learn how good players actually play and what they bring. That needs
many recorded Great League battles, and a way to trust some more than others.

**Do.** Find YouTube videos and Twitch VODs of Great League battles played by strong
players. Record them in `data/videos.csv`, one row per video:

`url, platform, channel, player, skill_evidence, skill_weight, recorded_date, league,
language, resolution, overlays, battle_count, notes`

- `skill_evidence`: what shows the player is strong (Legend rank, a leaderboard place, a
  tournament result), with a link.
- `skill_weight`: 1 to 5. 5 is a top-of-leaderboard or tournament-winning player, 1 is
  unknown. Say in the notes how you decided.
- `overlays`: what covers the game (facecam position, banners, a cropped screen).
- `recorded_date` matters: move stats change between seasons, and our game data is
  current. Old footage is still useful for habits, less so for exact numbers.

Then for each video, list its battles in `data/video_battles.csv`:
`url, battle_no, start_time, end_time, player_lead, opponent_lead, result`.

**Deliver.** The two files, and a short `data/videos.md` saying how you searched and how
many battles there are per skill weight.

**Done when.** At least 300 battles are listed; ten rows picked at random have correct
times when checked against the video; every row has skill evidence or a weight of 1.

**Note.** This is a list of links and times, not a download. Whoever processes footage
is responsible for doing so within the platform's terms.

## 2. Turn videos into looks and game states

**Why.** The tracker turns "looks" at the screen into a full game state. This task
produces the looks from real footage and tests whether the tracker's picture holds up.

**Do.** Follow [`agent_instructions.md`](agent_instructions.md) exactly. It is
self-contained and defines the files. Work through the battles in
`data/video_battles.csv`, highest skill weight first. One folder per battle under
`games/`.

**Deliver.** For each battle: `team.json`, `observations.jsonl`, `report.md`, and, if you
can run Python, the tracker's three output files.

**Done when.** `python3 scripts/track.py games/<name>` reads every line without
rejecting any, and each remaining `unexplained` event is listed in the report with what
the footage shows at that moment. Start with five battles and report before doing more.

## 3. Recognition: a frame in, a look out, fast

**Why.** Task 2 can be done slowly by an agent watching video. A live bot needs the same
thing from code, within 50 ms a frame.

**Do.** Write `pogo/vision.py` with a function `look(frame, t) -> Observation` (see
`pogo/tracker.py` for `Observation`). [`what_to_see.md`](what_to_see.md) lists every
item and how exactly it must be read. Health bars, shield and party markers, charged
button fill and "is a charged move playing" must come from pixels in fixed regions, with
positions as fractions of the screen so any resolution works. Names and CP may use text
reading, but only when the Pokémon changes.

**Deliver.** `pogo/vision.py`, a test script `scripts/check_vision.py`, and the labelled
frames it tests on (a few hundred small crops, not whole videos).

**Done when.** On frames not used to build it: health bars within 1% of the label on 95%
of frames; shields, Pokémon left and the charged-move flag right on 99%; median time per
frame under 50 ms with text reading off. Report each number.

**Started.** The `screen-reader-video-pipeline` branch is a first version, built for
recorded video. [`screen_reader_review.md`](screen_reader_review.md) says what was
measured on it and lists the seven things it must show before it can drive the tracker,
chief among them a settled health value for both sides in 99% of half-seconds of fighting.

## 4. Make the tracker cope with real games

**Why.** `pogo/tracker.py` was tested only on simulated cameras. Real games break its
assumptions.

**Do.** Fix these, each with a test in `scripts/check_tracker.py` or `tests/`:

- The opponent's stats are assumed typical. Learn the true damage per fast hit from the
  first few steps of our health bar, and stop flagging those steps as unexplained.
- The opponent's fast move is assumed to be the usual one. Detect from the rhythm and
  size of the steps when it is not, and switch to the right one.
- A charged move is assumed to take exactly 10 seconds. Use what the looks show instead.
- Looks arrive many times a turn in real use, not once. Accept that.
- A nickname in place of a species name must not crash it.

**Deliver.** The changed `pogo/tracker.py` and tests.

**Done when.** `python3 scripts/check_tracker.py` shows no loss on the perfect camera
(the Planner from the tracker's picture still scores within its margin of 50%), the new
tests pass, and on real games from task 2 the count of unexplained events falls. Report
before and after.

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

## 6. Port PvPoke's battle AI

Fully specified in [`../handoff/pvpoke_port_instructions.md`](../handoff/pvpoke_port_instructions.md),
with a bundle. **Done when** `python3 scripts/check_pvpoke_ai.py` prints 108 of 108.
A second stage, porting PvPoke's `TrainingAI.js` (team play and switching), follows it.

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

## 9. Solve late-game positions exactly

**Why.** Once every Pokémon is revealed nothing is hidden, and the position can be
worked out exactly instead of estimated. Read "Endgames, measured" in `status.md` first:
the final one-on-one is short, so aim at two against one and two against two as well.

**Do.** Write `pogo/endgame.py`: from a position, work backwards over all positions
reachable from it to the chance of winning under best play by both sides. Both players
choose at once, so each position is a small matrix game (`solve_2x2` in `pogo/agents.py`
handles the two-by-two case). Then a player that uses it when the position qualifies and
the `Learner` otherwise.

**Done when.** On small cases it agrees with brute-force enumeration; the solve time is
reported for positions with zero, one and two shields; and the player using it is
measured against the best bot on the same battles.

## 10. Form-changing Pokémon in the engine

**Why.** Aegislash, Mimikyu, Cramorant and Morpeko are left out. Two of them are in the
top ten.

**Do.** Add their rules to `pogo/battle.py` from the `formChange` entries in
`data/gamemaster.json` and PvPoke's source. Produce reference battles from pvpoke.com the
way `tests/data/pvpoke_duels.txt` was made (its header gives the format; PvPoke's
`Battle`, `Pokemon` and `GameMaster` are available in the page's JavaScript console).

**Done when.** `python3 scripts/check_pvpoke.py` still prints 108 of 108, and a second
file of at least 40 battles involving these four is also reproduced exactly.

## 11. Make the simulator faster

**Why.** Training plays out millions of positions. Every part of it is plain Python.

**Do.** Speed up `pogo/battle.py` and the play-outs in `scripts/decide.py` without
changing any result.

**Done when.** All tests pass, `scripts/check_pvpoke.py` prints 108 of 108, a fixed-seed
run of `scripts/arena.py --pairings 200` prints the same scores as before, and battles
per second is reported before and after.

## 12. Measure real timings from footage

**Why.** The simulator assumes a charged move takes 10 seconds off the clock. Nobody has
checked.

**Do.** From ten battles in `data/video_battles.csv`, measure the items in section 7 of
[`what_to_see.md`](what_to_see.md): the length of a charged move shielded and
unshielded, how far the switch countdown drops across one, the time allowed after a
faint, and the others listed there.

**Deliver.** `docs/timings.md` with each measurement, the number of examples, and the
spread.

**Done when.** Each of the eight items has at least five examples or a note saying why
it could not be measured.

## 13. Live loop on the phone

Needs the owner's iPhone and Mac, so it cannot be handed off. Listed for completeness:
run `scripts/probe.py --drag` to find out whether iPhone Mirroring passes synthetic
drags, then connect capture, `pogo/vision.py`, the tracker, the bot and taps, logging
the time of each step against the targets in `status.md`.

## 14. Adversarial training against stronger AI (Claude Code: first exploiter run started 2026-10-09)

**Why.** Every opponent our bot has trained against is the hand-written Planner or a
variation of it, and the bot now beats those by a wide margin. It has never faced
something built to beat *it*. An opponent trained to exploit the bot shows where it is
weak, and training against that opponent fixes it.

**Do.** Run this loop with `scripts/decide.py`, which already learns one decision at a
time and can give opponents a learned model (`--opponents`).

1. **Exploiter.** Train a new model whose every opponent is the current best bot
   (`runs/general-decide/q.npz`, margin 0.02), not the crowd. This needs a small change
   so the share of opponents using the learned model can be set to 1. Save it under
   `runs/exploiter-1/`.
2. **Measure it.** Play the exploiter against the best bot on fresh battles. If it wins
   clearly, the best bot has an exploitable weakness; read battle logs
   (`scripts/arena.py --show` shows the idea) and write down what the exploiter does.
3. **Retrain.** Train the bot against a mixed crowd: the old Planner variations, its own
   earlier versions, and the exploiter. Save as a new version.
4. **Repeat** with an exploiter for the new version, until an exploiter gains no more
   than the margin.

When task 6 delivers `pogo/pvpoke_ai.py`, add PvPoke's AI to the crowd and to the tests.

**Deliver.** The change to `scripts/decide.py`, the models, and one table in
`docs/status.md`: each version of the bot, each exploiter and the Planner, every pair
played on the same battles, with margins.

**Done when.** The table exists; a new version is accepted only if it does not lose to
the previous version beyond the margin, does not drop against the old crowd (the fixed
yardstick, currently +13.6 points over the Planner), and does better against the
exploiter than the previous version did. Report it plainly if the loop goes in circles,
with each version beating the last but losing to an older one.

**Cost.** Each training run is about an hour on one core. Expect four or more.

## 15. Train the AI to handle uncertain battle information

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

## 16. Public VOD screen tracking — Codex

The first implementation reads the 23 calibrated Twitch player-view clips and
publishes screen readings, a persistent evidence ledger, model states, events,
and consistency results to the video viewer. Reproduction and measured limits
are in `scripts/recording/VOD_README.md`; portable compressed results are in
`games/twitch/`. This does not establish full game-state accuracy.

Next acceptance work: label fainting and charged-attack transitions, measure each
field against those labels, identify forms, resolve energy-count disagreements,
and reserve a new untouched source before tuning. Keep both tournament views
of a match in the same evaluation group. Exact HP needs independent maximum-HP
evidence; a visible bar alone cannot determine it.

## 17. Official paired evaluation sample — Codex

Collected ten reviewed complete battles from two original official pokemongo
Twitch VODs, with both views kept together as twenty clips. The viewer's
**New official sample** filter keeps these separate from earlier exposed clips.
Selection, source/frame provenance, boundary evidence, measured storage and
verification receipts are in `data/vod_additional_sample.json`; reproduction is
in `docs/official_sample.md`. The latest handoff's frozen evaluation at
0fd98ff is now complete: all twenty views' readings and compressed tracked data
are published, with before/fitted timing comparisons in
`docs/reserved_state_evaluation.md` and `data/vod_reserved_state_evaluation.json`.
No recognition/timing parameters were fitted on these games. Independent labels,
terminal faints, early battle-clock origins, forms and energy discrepancies remain
next acceptance work. Keep these sources reserved and do not use them to tune.
