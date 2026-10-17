# Tasks

Open work on the bot, each brief self-contained. Read `AGENTS.md` first (setup, rules, how to claim a
task), then `docs/status.md` for every result so far. To take a task, put your name after its title here
and push that before starting.

## Where things stand (2026-10-15)

- **The bot**: hand-written rules (`Planner`, `pogo/agents.py`) plus a learned layer that may overrule
  them at shield, throw-or-hold, swap and replacement decisions (`Learner`, `pogo/learner.py`, model
  `runs/general-decide/q.npz`, margin 0.02). The layer adds about 9 points against the crowd (+8.9 ± 1.6).
- **The owner's rules that helped are on by default**: farm until they are about to reach a move, throw
  before fainting, keep charged-move timing, counter-swap to win the switch, get into the good matchup.
  Seven more were built and gained nothing (task 18 lists them).
- **The engine** (`pogo/engine.py`) is the strongest player: it plays each option 20 turns ahead and
  judges the result with a learned evaluation. 65.0% ± 1.9 head to head against the bot, but 45 ms per
  decision (up to ~400 ms), so not yet live (task 23). Its edge is judgement, not rules: turning its
  habits into rules or into the bot's networks did not help.
- **Tracking**: owner recordings and public footage go through `scripts/recording/` to game states;
  replayed as if live, shields / Pokémon left / who is out are 98–100% right and their energy is within
  one fast move 93% of the time.
- **Team choice**: `scripts/roster_teams.py` ranks the owner's line-ups, but the answer depends on the
  opposing team list, which is not yet self-consistent (task 21).
- **Task 26 (learning from losses)** is done: every change it found costs more in won battles than it gains in lost ones.
- **Try it**: `python3 scripts/play.py` is a browser game against the bot (`--bot engine` for the engine).

## Open tasks

| # | Task | Needs |
|---|---|---|
| 23 | The engine in real time: think during its own fast moves | Python, numpy |
| 25 | Let the engine search shield decisions | Python, numpy |
| 21 | Opposing teams as good as ours, for choosing a team | Python, numpy, hours of computing |
| 24 | Live assembly without rebuilding every half-second | Python |
| 5 | Learn from the tracked games (teams, movesets, habits seen) | Python |
| 8 | Predict hidden teams from real team combinations | Python, real teams (task 5) |
| 7 | Opponent stats from CP, move priority and damage | Python |
| 10 | Form-changing Pokémon (Aegislash, Mimikyu, Cramorant, Morpeko) | Python, a browser |
| 16, 17, 22 | Footage: acceptance work on public VODs, the reserved official sample, whole-VOD splitting | Codex; video access |
| 15 | Train the bot on the tracker's uncertain picture | **On hold** until real-game testing |
| 13 | Live loop on the phone | Owner only |

**Done or stopped** (details in `status.md`): 2–4 and 12 (footage to game states, by `scripts/recording/`),
6 (PvPoke's AI, `pogo/pvpoke_ai.py`), 9 (exact endgames, `pogo/endgame.py`, no significant gain),
11 (simulator 1.2–1.4× faster), 14 (exploiters gain nothing beyond the margin), 18 (owner's rules),
19 (retrain, adopted), 20 (mid-matchup swap head, not adopted), 26 (losses: 72% had a decisive decision in
hindsight, but no change helps once wins are counted). Task 1 (catalogue of videos) is partly
covered by `data/video_sources.csv`; task 3 (fast frame recognition for live play) waits on task 13.

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

