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
| 8 | Guess the opponent's hidden Pokémon | Python | 5 helps |
| 9 | Solve late-game positions exactly | Python | nothing |
| 10 | Form-changing Pokémon in the engine | Python, a browser | nothing |
| 11 | Make the simulator faster | Python | nothing |
| 12 | Measure real timings from footage | Video access | 1 |
| 13 | Live loop on the phone | The owner's iPhone and Mac | 3, 4 |

Tasks 1 to 5 are the footage pipeline, in order. Tasks 6 to 11 are independent of it and
of each other.

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

## 8. Guess the opponent's hidden Pokémon

**Why.** We see their lead and nothing else. Knowing what usually comes with it changes
when to shield and switch.

**Do.** From `data/teams.json` (and its `seen` counts once task 5 has filled them),
build a function that takes the opponent's Pokémon seen so far and returns likely
team-mates with probabilities. Then let the tracker's `state()` report it, and let
`scripts/advise.py` draw unseen Pokémon from it instead of at random.

**Done when.** On teams held out from the list, the true team-mate is in the top five
guesses more often than a guess by overall popularity, with both numbers reported.

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
