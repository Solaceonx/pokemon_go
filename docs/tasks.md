# Outstanding tasks that can be handed to another agent

Each task below is written so that an agent (or a person) who has only this repository
can pick it up. Read [`status.md`](status.md) first, then the task.

To take a task, put your name after its title in this file and push that change before
starting, so two people do not do the same one.

## Where things stand (2026-10-14)

- **The bot** is a set of hand-written rules (the `Planner` in `pogo/agents.py`) with a small learned
  layer on top that may overrule it at four kinds of decision: shield, throw or hold, swap at a new
  matchup, replacement (`Learner` in `pogo/learner.py`, model `runs/general-decide/q.npz`, margin 0.02).
  The learned layer adds about 9 points against the crowd (+8.9 ± 1.6 on 4,000 battles, 13 October). The
  model is task 19's retrain; two longer runs since (`runs/general-margin`, decisiveness-scored, rounds 3
  and 4) came out slightly worse (-2.1 ± 1.4, -1.8 ± 1.4), so more training of the same kind is not the
  next step.
- **The owner's rules that helped are the default:** hold or farm until the opponent is about to reach a
  move, throw before fainting, keep charged-move timing while farming, counter-swap to win the switch, get
  into the good matchup. Tried and no gain: setting up a sweeper, shielding by the other matchups,
  catching a charged move with a switch, rushing once shields are gone, switching freely once their team
  is known, punishing with a harder counter (all off-by-default options, in `status.md`).
- **The engine** (`pogo/engine.py`) is the strongest player measured: at each judgement call it imagines
  the battle from what it can see, plays each option 20 turns ahead with the trained bot playing both
  sides, and judges the result with a learned evaluation (`pogo/evaluation.py`, `runs/eval/eval.npz`).
  Against the trained bot 65.0% ± 1.9 head to head; against the crowd +5.4 ± 3.7 points
  (`scripts/engine_trial.py`). It needs 45 ms per searched decision (395 ms at worst), so it is not yet in
  live use. Thinking during its own fast moves would make it fit (task 23).
- **Its edge is not in rules.** None of its habits, as "in this situation always do X" rules, beats the
  trained bot by its own look-ahead (`scripts/engine_habits.py --rules`), and teaching its values to the
  bot's networks made the bot worse (`scripts/distill.py`, -3.5 ± 1.1). Both are written up in `status.md`.
- **Tracking.** Recordings from the owner's iPhone and public footage go through `scripts/recording/` to
  tracked game states. Replayed as if live (`scripts/recording/live_replay.py`) the picture matches the
  offline one: who is out, shields and Pokémon left 98 to 100%, health within 3% 99%+, their energy within
  one fast move 93%. Live assembly is still rebuilt from scratch every half-second (task 24). Whole
  recordings can now be cut into battles automatically (task 22, Codex).
- **Ways to see the bot play.** `python3 scripts/play.py` is a browser game against the trained bot
  (`--bot engine` for the engine). `scripts/real_decisions.py` compares the bot with real players'
  decisions in tracked games: it agrees with them on about half of throws and two thirds of shields and
  switches, and where they differ neither is clearly better.
- **Team choice.** `scripts/roster_teams.py` ranks the owner's line-ups; its answer depends on the
  opposing team list, which is still not self-consistent (task 21).

The three sections below are how to carry on with strategy, training and team choice. `docs/status.md`
has every result so far, including what did not help. Task 23 is the most promising open work.

## How to test a strategy rule

About a minute per setting, one core, nothing to install beyond `numpy`.

Every rule measured after the good-matchup rule (11 October) has gained nothing, and the engine's own look-ahead says simple rules
of the "in this situation always do X" kind no longer beat the trained bot (`status.md`, "What the engine
does differently"). Before building a rule, check whether the look-ahead thinks it helps:
`python3 scripts/engine_habits.py --from-saved --rules` scores rules made of the conditions in
`conditions()` against 45,856 recorded decisions in a minute (the recording itself is not in git;
`python3 scripts/engine_habits.py --battles 2000 --workers 3` remakes it in about 20 minutes). A rule that
scores at or below zero there is unlikely to win in battles.

1. Write the rule in the `Planner` behind a constructor option that defaults to off. The existing ones
   to copy from are `hold`, `last_gasp`, `timed_farm` and `win_switch`.
2. Try it against the standard player:

   ```bash
   python3 scripts/rule_trial.py "my_rule=True" "my_rule=True,my_threshold=0.2" --battles 4000
   ```

   Each quoted setting is played head to head against the standard `Planner` on random teams (every
   pair of teams both ways round), and against the usual crowd on the same battles as the standard
   player. It prints both scores with margins, and the energy thrown away on fainted Pokémon.
3. Head to head is the number that matters most: the opponent there is as good as we are. The crowd
   is a little weaker than the standard player.
4. If you tried several settings, run the one you picked again with `--seed` set to a new number. The
   best of several is flattered by luck.
5. A rule counts when it is ahead by more than its margin on that second run. Then make it the
   default, give it to the crowd in `varied_settings` (on in about 80% of opponents, like the others),
   add `my_rule=False` to any test that isolates another rule, and run the checks in step 6.
6. `python3 -m unittest discover -s tests`, `python3 scripts/check_pvpoke.py` (108 of 108), and
   `python3 scripts/speedcheck.py save` because behaviour changed on purpose.
7. Check the learned layer still helps on top:
   `python3 scripts/compare_models.py runs/general-decide/q.npz:0.02`.
8. Write the result in `docs/status.md` under "Strategy guidance from the project owner", with the
   numbers, whether or not it helped.

The owner is a former top player. Their principles are in that section of `status.md`. Ask them before
inventing a rule; implement what they describe and measure it.

## How to train the learned layer

Training plays battles, freezes each one at a decision, plays out every option from there with the same
dice, and fits a network to predict the result of each option ("How per-decision learning works" in
`status.md`). The bot then overrules the `Planner` when another option is rated higher by a margin.

```bash
python3 scripts/decide.py --run my-run --minutes 180 --rounds 3 --teams data/teams.json --workers 4 > runs/my-run.out
python3 scripts/compare_models.py runs/general-decide/q.npz:0.02 runs/my-run/q.npz:$(cat runs/my-run/margin.txt) --battles 4000
```

- `--minutes` is the time spent generating examples; `--workers` is how many cores do it. Examples
  are what matter: one core-hour gives about 30,000 shield examples, and the current model was fitted on
  about 1.3 million (task 19). Runs of a similar size since then have not beaten it.
- The run tests itself against the `Planner` at the end. That is not the acceptance test. The second
  command is: it plays the current model and the new one on the same battles against the crowd, and
  then against each other.
- **A new model replaces the current one only if** it is ahead of it by more than the margin against
  the crowd and scores above 50% beyond the margin head to head. Then copy it to
  `runs/general-decide/q.npz` (keep the old one beside it as `q_v5.npz` and so on), put its margin in
  `margin.txt`, and record the table in `status.md`.
- Useful options: `--opponents runs/general-decide/q.npz` makes half the opposing pilots use a learned
  model; `--resume` carries on a run; `--team a b c` trains for one team (the general model has done
  better than a one-team model so far).
- Example files (`runs/*/examples.npz`) are not in git. `--resume` without them starts collecting
  again from the saved model.
- It runs at low priority and needs nobody watching. The owner's Mac should not run this for hours;
  use another machine for long runs.

## How to choose a team

```bash
python3 scripts/roster_teams.py --rival bot --listed 0.8
```

It plays every line-up from the owner's Pokémon (`data/owner_team.json` and `data/owner_roster.json`,
with their IVs and moves) on the same battles, drops the weak ones in stages, scores the survivors on
fresh battles and writes `data/roster_teams.json`. About 45 minutes on three cores.

`--rival bot` gives the opponent the same pilot as ours; `--listed 0.8` draws 80% of opposing teams
from the good-team list in `data/teams.json`. Both matter. The owner's test for any result here: at their
level the game is close to 50-50, so a line-up that wins 80% means the opposition is wrong, and the
order of teams changes when the opposition is fixed. `--recheck` re-scores the saved line-ups under
different opponents in a few minutes.

## Overview

| # | Task | State (2026-10-14) | Needs |
|---|---|---|---|
| 1 | Catalogue of battle videos, weighted by player skill | Partly: `data/video_sources.csv` lists the sources used so far | Web access |
| 2 | Turn videos into looks and game states | Largely done by `scripts/recording/` (owner's recordings, Twitch, official VODs) | |
| 3 | Recognition: a frame in, a look out, fast | Working on recorded video (`scripts/recording/`); the brief's per-frame accuracy and 50 ms checks are not reported | |
| 4 | Make the tracker cope with real games | Much of it done on real recordings (`status.md` from "First real recording"); check the brief's list against that before starting | Python |
| 5 | Learn from the tracked games | Open | Python, numpy |
| 6 | Port PvPoke's battle AI | **Done**: `pogo/pvpoke_ai.py`, 108 of 108 | |
| 7 | Opponent stats from CP, move priority and damage | Open (first look in `status.md`, "IVs") | Python |
| 8 | Predict hidden teams from real team combinations | Open | Python; real teams |
| 9 | Solve late-game positions exactly | **Done**: `pogo/endgame.py`, exact, gain not significant under the time budget | |
| 10 | Form-changing Pokémon in the engine | Open | Python, a browser |
| 11 | Make the simulator faster | Hot paths done (1.2 to 1.4 times); cheaper look-ahead open | Python |
| 12 | Measure real timings from footage | Partly, inside the tracker's timing fit | Video access |
| 13 | Live loop on the phone | Owner only | The owner's iPhone and Mac |
| 14 | Adversarial training against stronger AI | **Done**, stopped: exploiters gain no more than the margin | |
| 15 | Train the AI to handle uncertain battle information | On hold until real-game testing | |
| 16, 17 | Public and official footage | Codex; acceptance work listed in each | Video access |
| 18 | More strategy rules from the owner | Rules 1, 2, 3 and 5 measured: rule 5 (good matchup) is the default, the others no gain; rule 4 is a count `rule_trial.py` prints | |
| 19 | Retrain the learned layer with enough examples | **Done**: the retrain replaced the old model (+2.6 ± 1.5) | |
| 20 | A learned decision for swapping mid-matchup | **Done**, not adopted: +0.6 ± 1.5 | |
| 21 | Opposing teams as good as ours, for choosing a team | Unfinished: best counter still 58.3% ± 1.7 against the list (target under 55%) | Python, numpy, hours |
| 22 | Extract whole recordings into battles | Codex; recall on unfamiliar recordings unmeasured | Video access |
| **23** | **The engine in real time: think during its own fast moves** | **Open, most promising** | Python, numpy |
| 24 | Live assembly without rebuilding every half-second | Open | Python |
| 25 | Let the engine search shield decisions | Open | Python, numpy |

Tasks 23 to 25 are independent of each other and of the footage work. A task marked done keeps its brief
below as a record.

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

## 6. Port PvPoke's battle AI (done 2026-10-09)

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

## 9. Solve late-game positions exactly (done; see `endgame.md`)

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

## 14. Adversarial training against stronger AI (done, stopped; see "Adversarial training" in `status.md`)

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

## 18. More strategy rules from the owner

**Why.** Each of the owner's rules measured so far was worth one to three points, and they are general:
they hold for any team and any position. These are the ones they have described that are not built.

**Do.** One at a time, by "How to test a strategy rule" above.

1. **Set up a sweeper.** The owner: if you lose the lead and swap, and they swap too, and the new
   matchup is winnable, the options are to try to win the switch (built: `win_switch`) or, more rarely,
   to set up a sweeper: spend this Pokémon drawing shields or building energy so that another one of
   ours can run through what is left. Needs a test for "which of mine sweeps their last two once the
   shields are gone", which `_outlook` in `pogo/agents.py` is close to.
2. **Fainting with a shield in hand.** The owner: whether to spend a shield on a Pokémon that is nearly
   down "depends on the other matchups". Compare the remaining matchups with and without that shield
   and let that decide. Today the shield choice looks ahead from the present matchup only.
3. **Catch a charged move with a switch.** When their move is about to land on something it hurts,
   swap to something that resists it. This is a read, so it needs their energy and likely move
   (`TrackedView.foe_energy_odds` and `foe_move_odds` exist for the tracker's picture). Task 20 is the
   learned version of the same decision.
4. **Wasted energy.** Fainted Pokémon still take 8.0 energy a battle with them while a move was ready
   (14.4 before the throw-before-fainting rule). `rule_trial.py` prints this for every setting.
5. **Get into the good matchup.** Use the one-on-one table (`data/matchups.json`, or `matchups()` in
   `scripts/teams.py`) to steer switches toward matchups we win, the way a player uses PvPoke's matrix.

**Deliver.** For each rule: the option in the `Planner`, the `rule_trial.py` output saved under
`runs/`, and a paragraph in `status.md`.

**Done when.** Each of the five is either the default with a confirmed gain on a second seed, or
written up under "Tried and did not help" with its numbers.

**Already tried, no gain:** weighting the shield decision by the odds of each move (+0.7 ± 2.5), a
shield bonus for staying the winner of the matchup while a switch clock runs (`switch_worth`, 50.4% ±
0.7 head to head), and timed farming on its own (neutral; kept on because
it raises well-timed throws from 64% to 66%).

**Measured since (2026-10-11 to 13):** rule 1 (`sweeper`), rule 2 (`shield_matchups`) and rule 3 (`catch`)
gave no confirmed gain and stay off; rule 5 (`good_matchup`) is the default. Three more rules from the owner
were built and gave nothing: `rush` (once their shields are gone, knock them out as fast as possible),
`known_team` (once their whole team is seen, switch to whatever beats two of them) and `punish_gain`
(punish a switch with the harder counter). The engine does punish more than the bot (59% against 51% of
chances), but by judgement, not by a rule.

## 19. Retrain the learned layer on today's rules, with enough examples (done 2026-10-12)

**Why.** The current model was trained when the `Planner` played by older rules, so its examples were
played out by a weaker player than today's. A retrain with one core-hour of examples (30,000 shield
examples against the old model's 336,000) lost to the old model: −4.2 ± 1.8 against the crowd and
44.6% ± 1.8 head to head. Fitting on old and new examples together changed nothing (+0.6 ± 1.7). So the
open question is what a retrain with the full amount of examples is worth.

**Do.** Run the two commands in "How to train the learned layer" on a machine that can give it about
twelve core-hours (`--minutes 180 --workers 4`, or more cores for less time). Then, as a second run,
the same with `--opponents runs/general-decide/q.npz` so that half the opponents are as good as the bot,
and compare both.

**Deliver.** The models under `runs/`, both logs, and the `compare_models.py` table in `status.md`.

**Done when.** The table is in `status.md` with margins, and the current model has been replaced or
kept by the rule in "How to train the learned layer". Say plainly if neither run beats it.

## 20. A learned decision for swapping in the middle of a matchup (done 2026-10-12, not adopted)

**Why.** The learned layer decides four things: whether to shield, whether to throw or hold, whether to
swap when a new matchup begins, and whom to send in after a faint. Nothing decides a swap in the middle
of a matchup, such as bringing in a resist as their charged move comes (task 18, rule 3).

**Do.** Follow "A new learned decision" in the README: add a head to `Q_HEADS`, route the choice
through `Learner._decide`, and let `scripts/decide.py` play out its options. Offer the decision only
when the switch is available and their next charged move is within about two fast moves, so it does
not slow every turn.

**Done when.** A model trained with the new head is compared with one trained the same way without it,
both on the same amount of examples, by `compare_models.py`. Report it either way.

## 21. Opposing teams as good as ours, for choosing a team

**Why.** The owner's goal: from their own Pokémon, simulate against the teams they will meet and play
one of the best line-ups. The first search (`status.md`, "Best teams from the owner's own Pokémon")
used a weaker opposing pilot on random teams from the top 100. Its best line-up won 82%, which the
owner rejected at once, and re-scoring the same line-ups against the same bot on good teams brought
them to 50 to 60% and put a different one on top. The full search rerun that way
(`--rival bot --listed 0.8`) still has a best line-up at 74%, and its winners are counters to the list:
Stunfisk, Ninetales and Feraligatr line-ups that fall to 49 to 61% against other opposing teams, where
the owner's current three come first (`status.md`, "The team search again"). So the order of teams is
decided by the opposing list, and the list is what is wrong: `data/teams.json` was found with the
`Planner` as pilot, among the top 50 only, against a field that was half random, and it is heavy with
Steel types (Tinkaton in 39 of 81 teams, Corviknight in 25). A real field would not keep bringing teams
that lose three games in four to a counter.

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

## 22. Extract whole recordings into individual battles — Codex

The owner accepts clipped beginnings and endings. The importer and Windows
launcher now scan completed Twitch or YouTube recordings without the earlier
five-battle / 40–45-minute sample limits. Long charged animations no longer create
the observed false restart, readable-header lookahead catches the reviewed
missed restart, and official player-name changes split edited highlight montages.

Completed validation: two whole official recordings, 32 ordinary interval
candidates plus 10 partial highlight excerpts, 84 POV clips, 760,904 verified
decoded frames; 18/18 previously reviewed YouTube intervals matched with no extras.
The twenty protected tracked views are unchanged. Receipts and limitations:
`data/vod_full_extraction_validation.json`; usage: `docs/full_vod_extraction.md`.

Remaining acceptance work: independently label all actual games in unfamiliar
recordings, measure misses/false splits/merges, and test layout changes and
unlabelled same-matchup replays. Source-frame agreement and full scanning do not
establish universal battle recall or accurate game-state reconstruction.

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

## 25. Let the engine search shield decisions

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

