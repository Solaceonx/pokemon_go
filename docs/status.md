# Project status, for anyone picking this up

Read this before suggesting improvements. It says what the project is, what has been
measured, what has already been tried and did not work, and what is open. The README
says how to run things.

Last updated 2026-10-18.

## Goal

A bot that plays Pokémon GO trainer battles (Great League, three against three). Given
any team, it should find how to win with it, against good players who play much as an
expert does. The end state: feed in any game state and get back the next action and an
idea of how the rest of the game goes.

It is being built algorithm first, in a simulator. Reading the phone screen and sending
taps come later. Automating the real game breaks Niantic's terms and risks a ban.

## What exists

| Part | Where | State |
|---|---|---|
| Battle rules engine | `pogo/battle.py`, `pogo/gamedata.py` | Reproduces 108 of 108 PvPoke one-on-one battles hit for hit (`scripts/check_pvpoke.py`) |
| Hand-written player ("Planner") | `pogo/agents.py` | Strongest hand-written pilot; every part can be switched off |
| Opponent crowd | `varied()` in `pogo/agents.py` | The Planner with every habit jittered, drawn fresh each battle |
| Per-decision learner | `pogo/learner.py`, `scripts/decide.py` | **The method that works**; see results |
| Bounded exact endgame player | `pogo/endgame.py` | Revealed positions with at most two survivors each; Learner fallback; [checks and results](endgame.md) |
| State tracker | `pogo/tracker.py`, `scripts/track.py` | Builds the full game state from "looks" at the screen; tested on the owner's recordings and public footage, and replayed as if live (`scripts/recording/live_replay.py`) |
| Screen reading of recordings | `scripts/recording/` | Owner's iPhone recordings and Twitch/YouTube footage to looks and tracked games; whole recordings cut into battles |
| Search player ("engine") | `pogo/engine.py`, `pogo/evaluation.py` | **Strongest player measured** (65.0% ± 1.9 against the trained bot); too slow for live play until task 23 |
| Browser game | `scripts/play.py` | Play the trained bot or the engine in real time, with sprites |
| Advice from a state | `scripts/advise.py` | Next action, shield advice, win chance, one typical continuation |
| Team search | `scripts/teams.py` | Done: `data/teams.json` holds 81 teams from the wide search (random starts plus breeding), 25 of them with every lead tested |
| Phone link | `helper/phonectl.swift`, `pogo/phone.py` | Compiles; never run against a phone |

## Results so far

- 2026-10-09: Task 6 PvPoke single-matchup AI port complete in `pogo/pvpoke_ai.py`, from commit `c15fb6f7e8613169740d904d6f96baa1824de480`: acceptance matches 108/108 battles with the same winner in 108; all 26 unit tests pass. No playing-strength improvement measured; team AI remains outside this stage. See [`PORT_NOTES.md`](PORT_NOTES.md) for the port mapping and coverage limits.

Scores are win share (wins plus half of draws) with a 95% margin. "Against the Planner"
means the same teams and battles for both pilots.

| What | Result |
|---|---|
| Planner against a button-masher | 82-84% |
| **Per-decision learning, one model for any team (shield, throw, swap, replace)** | **+13.6 ± 1.9 points over the Planner on random teams (71.3% against 57.7%), 3,000 fresh battles.** After one turn of adversarial training (below): +13.9 ± 1.9 and harder to exploit |
| The same model piloting Melmetal / Jellicent / Altaria | +13.2 ± 1.9 points over the Planner (79.0% against 65.8%), 3,000 fresh battles |
| The same model against a tougher crowd (half the opponents use its own learned decisions, half the teams from the team list) | 61.7% ± 1.9, against 46.9% ± 2.0 for the Planner, 2,500 battles |
| Per-decision learning, one team, shield and throw decisions only | +8.1 ± 1.8 points over the Planner, 3,000 battles |
| Tracker with a perfect simulated camera | Opponent's energy exact on 99% of turns; Planner plays as well from it as from the truth (50.6% ± 4.0) |
| Tracker with a rough camera (1 look in 5 missed, coarse bars, move not named) | Costs about 7 points (42.7% ± 4.0) |
| PvPoke's AI (`pogo/pvpoke_ai.py`), one-on-one, 2,000 battles per seed, seeds 101 and 202, today's rules and model (2026-10-11) | Beats the Planner (43.3% / 43.3%, ± 1.3) and the Learner (42.5% / 43.2%, ± 1.4) |
| PvPoke's fast/charged choice in the final one-on-one only (`pogo/hybrid.py`), `scripts/check_endgame_throws.py`, seeds 101 and 202, today's rules and model | Against PvPoke one-on-one: 49.3% / 49.0% ± 0.6 for both players (mostly a mirror there). 3v3 no cost: Learner against varied / expert / Planner moves +1.1 / +1.2 / +0.5 on seed 101 and +0.3 / +0.4 / −0.6 on seed 202; Planner +0.2 to +1.6 (margins about ± 2.5 per cell, ± 1.3 against the Planner) |

Worth of each hand-written rule, head-to-head against the same player without it:
move timing 56.4% ± 0.8; shields by lookahead 55.8% ± 1.0; sacrifice play 52.2% ± 1.0;
energy farming 51.8% ± 0.8.

## Tried and did not help

Do not re-propose these without a new angle.

- **Learning from win or loss of whole battles** (policy gradient self-play): 60,000
  battles for one team ended at -0.6 ± 0.6 points against the Planner.
- **A learned value of "what I have left against unseen opponents"**: predicted held-out
  positions better than the hand tally (84.2% against 82.2%) but won no more games
  (49.4% ± 1.1).
- **Safe swap against hard-counter swap**, and bringing the hard counter when the
  opponent's switch is locked: no measurable difference. Possibly because simulated
  opponents do not punish counter swaps as people do.
- **Counting stored energy** in the lookahead's tally; **choosing replacements by
  lookahead**: no measurable difference.
- **Length of a charged move** set to 6, 10 or 14 seconds: no measurable difference to
  which player wins.
- **More per-decision training against tougher opponents.** A further hour, with half
  the opponents using our own learned decisions and half the teams drawn from the team
  list, gave a model (`runs/general-decide/q_v2.npz`) no better than the first: -1.5 ± 1.9
  points on the original yardstick, +0.8 ± 1.9 against the tougher crowd, 51.6% ± 1.5
  head to head. `q.npz` is still the first model. The method looks to have levelled off
  with its current inputs.
- **A fixed roster of crude opponent styles**: rejected as unrepresentative of real play.
- **Racing a Pokémon with no shields left** (`Planner(rush=True)`, 2026-10-13): 47.5% ± 0.9 head to head,
  -3.4 ± 0.9 against the crowd. Only once holding no longer pays (`rush_threat=True`): 50.1% ± 0.7. Details
  under the owner's guidance below.
- **Punishing harder** (`Planner(punish_gain=...)`, 2026-10-13, the owner: the bot does not punish with harder
  counters): when they have just switched and are locked in, bring the counter that beats staying by 0.3 (or 0.5)
  even when already ahead. 50.6% ± 0.7 and 50.2% ± 0.6 head to head, +0.0 against the crowd
  (`runs/t23_*.out`). A count over 300 battles first showed that the bot already brings a counter in 70 of the
  82 moments when it was losing the matchup with a counter at least 0.3 better on the bench; the moments this rule
  adds (already ahead, or only a little behind) come up a few times in 262.
- **Switching freely to a counter of a team seen in full** (`Planner(known_team=True)`, 2026-10-13): 50.2% ±
  0.6 head to head; the chance comes about once in three battles and the rule acted on it rarely.
- **A learned mid-matchup swap head at a fixed total example budget (task 20).** Two fresh
  models, each trained on 180,000 retained decisions after 60 minutes of collection with
  three workers, differed by +0.6 ± 1.5 points against the crowd; the new head scored
  51.3% ± 1.3 head to head against the control, on 4,000 fresh battles. No clear overall
  improvement established. It also lost to the model current at the time (version 3, since replaced by the task 19 model), 44.6% ± 1.3 head to head.
  The head remains available for experiments; the current model is unchanged. Full
  counts, commands and comparisons are below.
- **Shortlisting teams by one-on-one coverage score**: a team that ranked 3,818th of
  19,024 on that score came 4th in real battles, so the score is a poor filter.
- **Setting up a sweeper after a losing-lead swap** (task 18, rule 1):
  `Planner(sweeper=0.5, sweep_chance=0.5)` scored **50.1% ± 0.6 head to head**
  on 4,000 fresh battles (seed 90317), and **+0.1 ± 0.2 points** against the
  crowd on the same battles as the baseline. No confirmed gain; `sweeper=0.0`
  remains the default. Details and limitations are under the owner's guidance below.

- **Fainting with a shield in hand, task 18 rule 2 (2026-10-11).** This attempt did
  not help. `Planner(shield_matchups=True, shield_matchup_hp=0.3)` compares shielding
  a nearly fainted Pokémon with saving that shield for its teammates. The existing
  lookahead already includes revealed bench Pokémon; this option lets both rollout
  players choose switches and replacements by one-on-one matchups instead of staying
  in and using a fixed replacement order. Remaining shields carry into those matchups;
  future shield choices still use the quick threshold rule. Unrevealed opponents are
  not guessed. Health cutoffs of 20%, 30% and 50% were tried with `rule_trial.py`,
  4,000 battles per setting, seed 181 (`runs/t18-shield-tuning.out`, selection data
  only). The best head-to-head setting, 30%, was fixed before testing fresh seed 9181:
  **49.7% ± 0.8 head to head**, and against the crowd **56.2% ± 1.5 versus the
  standard player's 56.0% ± 1.5**, a paired difference of **+0.2 ± 0.6 points**
  (`runs/t18-shield-confirm.out`). Each score uses 4,000 battles; head-to-head teams
  are played both ways and all margins are 95%. The separate 800-battle energy
  diagnostic was 6.5 versus 6.6 energy left on fainted Pokémon with a move ready.
  The fresh-seed gain did not exceed its margin, so `shield_matchups` stays **off**
  by default and the crowd is unchanged. The 107-test suite passes, with six existing
  PyAV-dependent skips (`runs/t18-shield-tests.out`), including new checks that the
  remaining teammate can change the shield choice, hidden opponents cannot affect
  it, and rollouts preserve the live state. No promotion, standalone PvPoke command,
  speed-baseline save or learned-layer comparison was run. The other four rules in
  task 18 were not attempted.

- **Catch a charged move with a switch (task 18, rule 3, 2026-10-11): no confirmed gain.**
  `Planner(catch=True, catch_gain=0.4)` reads the exact energy and fast-move readiness
  in the simulator's `View`, including after the initial matchup has been judged.
  Into shields it weighs affordable moves by the existing soft/hard bait read;
  without shields it expects the cheapest knockout or the best damage per energy.
  It chooses a bench Pokémon that resists and survives every move in that read,
  requiring the expected health saved to exceed `catch_gain` (fractions of each
  Pokémon's full health). Having energy does not guarantee a throw this turn;
  the rule does not know the opponent's chosen action.
  Tried thresholds 0.1, 0.2, 0.3 and 0.4 on seed 41, 4,000 battles per setting.
  The last two tied at the printed head-to-head precision; 0.4 had the slightly
  better crowd result and was selected before opening fresh seed 104729.
  On those **4,000 fresh battles**, head to head was **50.5% ± 0.7**; against
  the crowd it scored **56.1% ± 1.5**, versus **55.9% ± 1.5** for the standard
  player on the same battles: **+0.2 ± 0.3 points**. Neither gain exceeds its
  95% margin. Both left 6.5 energy per battle on fainted Pokémon with a move
  ready in the separate 800-battle diagnostic. This implementation did not help
  measurably, so `catch=False` remains the default and the crowd is unchanged.
  `rule_trial.py` now prints margins for raw crowd scores and uses repeatable
  pilot seeds independent of setting order, pairing pilot dice as well as teams
  and opponents. [Tuning output](../runs/t18-catch-tuning.out) is selection data,
  not evidence of improvement; [confirmation output](../runs/t18-catch-confirmation.out)
  is the acceptance check. The [full suite](../runs/t18-catch-tests.out) reports
  110 tests, OK (6 existing video checks skipped because PyAV is unavailable),
  including 8 new catch tests. The rule-3 "Done when" check was run and the
  negative result is recorded here; the other four rules were outside this task.
  Conditional promotion steps 5–8 were not taken (the full suite and this
  negative write-up were required separately). No speed baseline was saved or
  learned-layer comparison run. [Exact commands and outputs](../runs/t18-catch-commands.txt).

## How per-decision learning works

At a decision met in ordinary play, the battle is frozen and played out once for each
option with identical dice: shield or not; throw either charged move, or hold for one,
four or ten more fast moves; stay or swap; which replacement. A small network learns the
chance of winning after each option from what the player can see. The bot follows the
Planner except where the network rates another option clearly higher. The biggest change
it learned was to hold where the Planner would throw.

The best model so far is `runs/general-decide/q.npz` (one hour of examples: about 184,000
shield, 64,000 throw, 163,000 swap and 37,000 replacement decisions). Per battle it
overrules the Planner about 1.9 times on throws, 1.0 on shields, 0.5 on swaps and almost
never on replacements. All of this is measured against the Planner and its variations;
nothing yet says how it does against an outside opponent.

## Strategy guidance from the project owner (a former top player)

1. Type advantage first.
2. Two shields; use them wisely. Shielding in a neutral lead has no fixed rule.
3. Time charged moves to the opponent's fast move, unless about to faint or needing to
   throw first. Sometimes waiting a very long time is right.
4. Bait: farm to the dearer move's energy, then throw the cheaper. Good players bait
   about half the time and read the opponent when facing a possible bait.
5. Neutral lead: stay in and weigh switch advantage against shield advantage. Bad lead:
   swap to the safe swap; aim to win alignment or draw shields and leave with energy.
6. Punish a hard-counter swap; how hard depends on the matchup.
7. Farm energy with a Pokémon that takes little damage. Watch the switch timer.
8. Save a nearly fainted Pokémon as a third shield; bring it in on a read.
9. Opponents are good players with similar strategy, so optimise against that.

### Farm until they are about to get a move (2026-10-10): helps

The owner's rule: do not throw a charged move the moment it is ready; keep building energy
with fast moves until the opponent is about to reach a charged move of their own, as long as
it is not costing too much health. `Planner(hold=True, hold_cost=0.5)`: with a move ready, use
another fast move if it will be over before their energy reaches their cheapest charged move,
energy is not full, and their fast moves in that time take no more than `hold_cost` of current
health. `scripts/hold_rule.py`:

| Their fast moves may take | Head to head against the same player without the rule | Against the crowd, same battles |
|---|---|---|
| 10% of current health | 50.9% ± 0.9 | +0.7 ± 0.7 |
| 20% | 52.0% ± 1.0 | +1.4 ± 1.1 |
| 30% | 52.2% ± 1.1 | +1.6 ± 1.2 |
| 50% | 53.4% ± 1.2 | +2.7 ± 1.4 |
| 100% (always) | 53.3% ± 1.3 | +2.6 ± 1.5 |
| 50%, again on 6,000 fresh battles | 53.6% ± 0.9 | +2.3 ± 0.9 |

So the looser the limit the better, up to about half of current health, after which it makes
no difference. On top of the trained bot (which was trained without the rule): 53.5% ± 1.1
head to head, and against the crowd 71.6% against 70.3%, +1.2 ± 1.1 on the same 4,000 battles.

**Now part of the baseline (2026-10-11).** At the owner's direction the standard player is
being raised with general rules, for any team and any game state. `Planner()` now holds by
default (`hold=True, hold_cost=0.5`), and four in five of the simulated opponents hold too
(`varied_settings`). To reproduce a number from before this date, pass `hold=False` and note
that the crowd it was measured against did not hold. Against the new crowd, same 4,000 battles:

| Player | Wins |
|---|---|
| Rules without the hold rule | 53.2% ± 1.5 |
| Rules as they now stand | 56.8% ± 1.5 (+3.5 ± 1.2) |
| Trained bot on top of the new rules (`Learner(q=..., margin=0.02)`) | 69.0% ± 1.4 (+12.2 ± 1.7 over the rules) |

The learned decisions were trained around a player that throws early and have not been
retrained yet.

### Throw before you faint, and farming that keeps its timing (2026-10-11)

Both at the owner's direction, both now part of the standard player and of four in five
simulated opponents.

**Throw before you faint** (`Planner(last_gasp=True)`). With a move ready and a knock-out
coming before the next chance to act (their fast moves, or a charged move that would not be
blocked), throw now. It comes before every other rule, including finishing them with a fast
move we may not live to land. Before it, 13% of our faints took a ready move down with them
(49 energy each, about 13 a battle). Where that came from: 47% let a charged move through
with a shield in hand, 26% the energy arrived on the last fast move, 19% had thrown once and
still held another move's worth, 8% were waiting. With the rule the energy thrown away falls
from 14.4 to 8.0 a battle.

**Farming that keeps its timing** (`timed_farm=True`). While farming or holding, the throw is
planned for the latest turn that gives the opponent's fast move the fewest turns to run,
before they reach a move or our energy is full, instead of farming until forced. Measured
directly it changes little, because timing was already mostly right: 64% of charged moves
were thrown at the ideal moment before and 66% after (0.42 and 0.40 turns given away a throw).

| On fresh battles (`scripts/rule_trial.py`) | Head to head against the player without it | Against the crowd, same battles |
|---|---|---|
| Throw before you faint | 51.1% ± 1.0 (51.6% ± 1.0 on another set) | +0.9 ± 1.0 |
| Both | 51.1% ± 1.1 | +1.4 ± 1.1 |

Where the standard player stands, against today's crowd on the same 4,000 battles:

| Player | Wins |
|---|---|
| Rules as of 10 October | 51.1% ± 1.5 |
| + hold until they are about to get a move | 53.8% ± 1.5 (+2.7 ± 1.2) |
| + throw before fainting, timed farming | 56.0% ± 1.5 (+2.2 ± 1.1) |
| Trained bot on top (not yet retrained on these rules) | 66.9% ± 1.5 (+10.8 ± 1.7) |

Today's rules beat the rules of 10 October 55.2% ± 1.2 head to head.

### Winning the switch (2026-10-11): the counter-swap helps, the shield bonus does not

The owner's rule: if you win the lead and they swap, try to win the switch; if you lose the
lead, swap, they swap too and it is winnable, either set up a sweeper (rarer) or try to win
the switch.

**Counter-swap when they are locked in** (`Planner(win_switch=0.1)`, now standard). When the
opponent has just swapped they cannot swap again for 45 seconds, so the matchup is ours to
choose. If we are not already winning it (one-on-one margin under 0.15), bring the Pokémon
whose one-on-one against theirs beats staying by at least `win_switch`, with no weight on
being a safe choice, since they cannot answer. The one-on-ones are played out from the real
health, energy and shields with our own simulator, which reproduces PvPoke's battles hit for
hit, so this is the PvPoke matchup estimate the owner asked for, for any pair in any state.

| Must beat staying by | Head to head against the standard player | Against the crowd, same battles |
|---|---|---|
| 0.0 | 51.9% ± 0.9 | +2.6 ± 0.8 |
| 0.15 | 51.2% ± 0.8 (51.8% ± 0.8 on another set) | +2.2 ± 0.8 (+2.0 ± 0.8) |
| 0.3 | 51.5% ± 0.8 | +1.6 ± 0.7 |
| 0.5 | 50.7% ± 0.7 | +0.9 ± 0.6 |
| 0.1, on 6,000 fresh battles | 52.3% ± 0.7 | +2.0 ± 0.6 |

An earlier attempt at this ("bring the hard counter when the opponent's switch is locked")
showed nothing, because it still waited for the present matchup to be bad (worse than -0.2)
and for the counter to be better by 0.35. The gain is in taking small edges too.

**Valuing the win when shielding** (`switch_worth`): while a switch clock is running, add a
bonus to the shield choice that leaves us the winner of the present matchup. No difference at
0.2 or 0.5 (50.4% ± 0.7 and 50.2% ± 0.8 head to head). Left at zero. Setting up a sweeper
is tested separately below.

Where the standard player stands, against today's crowd (four in five opponents use each
rule) on the same 4,000 battles:

| Player | Wins |
|---|---|
| Rules as of 10 October | 50.5% ± 1.5 |
| + hold, throw before fainting, timed farming | 53.1% ± 1.5 (+2.6 ± 1.3) |
| + win the switch | 54.7% ± 1.5 (+1.6 ± 0.8) |
| Trained bot on top (not yet retrained on these rules) | 65.2% ± 1.5 (+10.5 ± 1.6) |

Today's rules beat the rules of 10 October 57.2% ± 1.2 head to head.

### No shields left: knock them out fast; their team known: switch freely (2026-10-13): no gain

Two more rules from the owner, both off by default (`tests/test_owner_rules_2.py`):

- **When they have no shields, kill their Pokémon as fast as you can before it does too much**
  (`Planner(rush=True)`). Once their shields are gone the player stops holding and farming and plays the
  shortest way, in turns, to knock the Pokémon out with its own moves (a search over our energy and their
  health), still timing a throw to their fast move when that does not make the knock-out later, and still
  throwing before fainting. `rush_threat=True` does this only once holding no longer pays: they have a
  charged move ready or soon, or waiting costs too much health.
- **If you know their whole team, you can sometimes switch freely when one of yours counters several of
  theirs** (`Planner(known_team=True)`). Once every Pokémon they have left has been seen and we are not
  already winning the matchup, swap in a bench Pokémon that beats at least two of them (one-on-one ahead by
  `known_edge`), without the usual margin, since whatever they switch to is a matchup we win.

`scripts/rule_trial.py --battles 4000 --seed 41` (`runs/t22_*.out`):

| Setting | Head to head against the standard player | Against the crowd, same battles |
|---|---|---|
| `rush=True` | 47.5% ± 0.9 | -3.4 ± 0.9 (energy lost on faints 7.9 a battle, against 6.3) |
| `rush=True, rush_threat=True` | 50.1% ± 0.7 | -0.3 ± 0.4 |
| `known_team=True` (beaten by 0.15) | 50.2% ± 0.6 | -0.0 ± 0.1 |
| `known_team=True, known_edge=0.0` | 50.3% ± 0.7 | +0.1 ± 0.2 |

Racing every unshielded Pokémon loses: the hold rule's banked energy is worth more than the turns saved, and
the existing play with no shields already takes a knock-out with the cheapest move that does it. Racing only
once they threaten is neutral. Seeing their whole team with two or more left came up in 31 of 100 battles,
and a bench Pokémon beating two of them while the present matchup was not already won was found once; the
simulated opponents may also counter-swap less than people do, which is what this rule protects against.
Nothing gained on the first seed, so no second seed was run.

### Get into the good matchup (task 18, rule 5; 2026-10-11): confirmed gain

`Planner(good_matchup=True, matchup_weight=0.75)` blends the saved one-on-one table
(`data/matchups.json`, fresh Pokémon averaged over zero, one and two shields) with the
existing duel from the current health, energy and shields. The table has 75% of the
weight. This guides ordinary swaps, counter-swaps, rescue destinations and replacements
chosen by outlook; switch cooldowns and sacrifice priorities still apply. Missing pairs
and a fainted opponent use the live duel alone. The table assumes usual builds and moves,
so this is a heuristic, not a fresh simulation of every possible moveset or state.

The option started off. Weights 0.25, 0.5 and 0.75 were tried with
`scripts/rule_trial.py --battles 4000 --seed 41`; those are tuning results only, saved in
`runs/t18_matchup_tuning.out`. The best head-to-head setting, 0.75, was frozen and tested
on seed 18051, with 4,000 fresh battles per comparison:

| Comparison | Win share or paired gain, with 95% margin |
|---|---|
| Rule against the standard player, each team pairing both ways | 52.0% ± 1.2 |
| Standard player against the crowd | 56.3% ± 1.5 |
| Rule against the same crowd on the same battles | 58.4% ± 1.5 |
| Rule's paired gain against the crowd | +2.1 ± 1.4 points |

The head-to-head gain exceeds its margin on the second seed, so the rule is now the
default, and 80% of `varied_settings` opponents use it. `good_matchup=False` restores the
previous rule for comparisons. Both trials preceded promotion: their standard player
and crowd had the new rule off. The trial script now prints margins for absolute crowd
scores as well as the paired difference. Fresh results: `runs/t18_matchup_fresh.out`.

Validation: 109 unit tests ran, passing with six PyAV-dependent video tests skipped;
108 of 108 PvPoke battles reproduced exactly; `scripts/speedcheck.py save` refreshed the
intentionally changed behavior fingerprints. Tests that isolate earlier tactics disable
the new rule. The initial suite exposed four wrong unusual-fast-move inferences in a
tracker fixture (limit one) after the new pilot changed its battle trajectories. Both
tracker fixtures now explicitly retain the old pilot, rather than changing tracker code
or loosening their assertions. This does not validate tracker inference on the new
pilot's unusual-moveset trajectories. Logs are under `runs/t18_matchup_*`.

The learned layer still helps after promotion. `scripts/compare_models.py` with
`runs/general-decide/q.npz:0.02`, 4,000 fresh battles, seed 18061 and one worker, against
the updated crowd: Planner **55.1% ± 1.5**, learned layer **64.1% ± 1.5**, paired gain
**+8.9 ± 1.6 points**. The direct command stopped when the sandbox denied its worker's
priority change; a temporary wrapper reran the same comparison while retaining the
existing below-normal priority of 5. `nice` was requested for every long job, and
numerical threads and workers were limited to one. Exact commands, wrapper source and
outputs are recorded in `runs/t18_matchup_commands.txt`; the successful model log is
`runs/t18_matchup_models_final.out`.

Rule 5's "Done when" check ran and passed: a confirmed second-seed gain, followed by
promotion and all required checks. Rules 1–4 of task 18 were outside this change.

### Set up a sweeper (2026-10-11, task 18 rule 1): no confirmed gain

`Planner(sweeper=0.0, sweep_chance=0.75)` adds an off-by-default experiment.
After our losing lead swaps and the opponent counter-swaps, a winnable new
matchup can become a setup opportunity. Each bench candidate plays through the
other two opponents with their shields removed, carrying health, energy and our
remaining shields through both opponents. It must win in both orders. A hidden
last Pokémon is averaged over `field`, or the top 50 if no field was supplied;
the actual hidden roster is never read. `sweep_chance` is the required fraction
of those candidate teams swept. For a qualifying teammate, `sweeper` adds value
to shields saved and drawn in the existing shield and charged-move lookahead.
If our setup Pokémon faints while the matchup is still locked, that teammate
comes in; the existing farming rule can build its energy from the remainder.

Three settings were tried on seed 41, each with `--battles 4000`: shield bonus
0.5 with sweep thresholds 0.5 and 0.75, and bonus 1.0 with threshold 0.5.
Those are selection data only, in `runs/t18-sweeper-tuning-seed41.out`.
The reported head-to-head scores tied; the smaller bonus and less restrictive
gate were selected before the fresh run (`runs/t18-sweeper-selection.txt`).
No setting was retuned on the confirmation battles.

**Held-out result**, seed 90317, 4,000 head-to-head battles (2,000 team pairings,
each played both ways), plus 4,000 paired battles against the unchanged crowd:

| Measure | `sweeper=0.5, sweep_chance=0.5` |
|---|---|
| Head to head against the standard Planner | 50.1% ± 0.6 |
| Against the crowd | 54.9% ± 1.5 |
| Standard Planner against the same crowd battles | 54.8% ± 1.5 |
| Paired difference against the crowd | +0.1 ± 0.2 points |

All margins are 95%. Energy discarded on faints with a charged move ready was
6.5 per battle for both, over the separate 800-battle diagnostic. Raw output:
`runs/t18-sweeper-confirm-seed90317.out`. `rule_trial.py` now reports margins on
the absolute crowd scores too, and repeats pilot seeds across settings so its
paired comparisons share the pilot's dice as well as teams and opponents.
Exact commands and check results are in `runs/t18-sweeper-commands.txt`.

**Did not help measurably.** The fresh head-to-head advantage is smaller than
its margin, so rule 1's gain check ran and failed. The negative outcome is
recorded under "Tried and did not help"; the option remains off, and the crowd
and other rule defaults stay unchanged. This tests a narrow setup heuristic:
the sweep projection assumes the current counter-swap is removed, uses simple
duel pilots, and treats an unseen last opponent as a field prior. It does not
prove that a real player's setup judgment cannot help.

All 111 unit tests pass (six existing skips), including nine setup tests and
the existing 108 PvPoke reference duels. The setup tests cover the losing-lead
sequence, continuous sweep resources, hidden-team independence, a real changed
shield decision, replacement, plan expiry and cloning. No promotion, crowd
change, speed-baseline save, or learned-layer comparison was done because the
fresh gain was not confirmed. Rules 2–5 and task 18's full five-rule completion
check are outside this run. Jobs were sequential with numerical-library thread
limits of one; `nice -n 10` was invoked but the sandbox denied its priority
change and allowed the jobs to continue.

## Adversarial training (task 14)

An exploiter is a model trained the same way as the bot, but with the bot itself as its
only opponent. One full turn of the loop has been run. Version 1 is the first general
model; version 3 is version 1 retrained for an hour against a crowd that includes the
exploiter and version 1 (version 2 was an earlier retraining that changed nothing).

| Match, 3,000 battles on random teams | Score of the first named |
|---|---|
| Exploiter 1 against version 1 | 55.1% ± 1.5 |
| Exploiter 1 against version 3 | 51.2% ± 1.6 |
| Version 3 against version 1 | 52.2% ± 1.5 |
| Exploiter 2 (trained against version 3) against version 3 | 53.2% ± 1.8 |
| Planner against version 1 | 36.1% ± 1.7 |

| Against the old crowd, points over the Planner | |
|---|---|
| Version 1 | +13.6 ± 1.9 |
| Version 3 | +13.9 ± 1.9 (and +0.5 ± 1.7 against version 1 on the same battles) |
| Exploiter 1 | +9.1 ± 2.0 |
| Exploiter 2 | +10.7 ± 2.0 |

Version 1 could be beaten by about 5 points by something aimed at it. Version 3 closes
that to about 1 point, beats version 1 head to head, and gives up nothing against the old
crowd, so **version 3 is now the best bot** (`runs/general-decide/q.npz`; the versions are
kept beside it as `q_v1.npz`, `q_v2.npz`, `q_v3.npz`).

What exploiter 1 did against version 1: held a ready charged move twice as often (1.58
against 0.75 times a battle), threw the second move where the Planner would throw the
first far more (0.67 against 0.12), swapped more and shielded more.

A second turn of the loop was then run and changed nothing, so the loop has settled.
Each line is 3,000 battles, every pairing played both ways:

| Match | Score of the first named |
|---|---|
| Exploiter 2 against version 3 | 50.6% ± 1.5 (an earlier one-sided test gave 53.2% ± 1.8; pooled with a third sample, about 51.7%) |
| Version 4 (version 3 retrained against both exploiters) against version 3 | 49.6% ± 1.4 |
| Exploiter 2 against version 4 | 50.0% ± 1.5 |
| Exploiter 1 against version 4 | 49.1% ± 1.5 |
| Version 4 against the old crowd, compared with version 3 on the same battles | +1.1 ± 1.5 points |

Version 4 is level with version 3 on every test, so **version 3 stays the best bot**
(version 4 is kept as `q_v4.npz`). Neither exploiter beats version 3 by more than the
margin when each pairing is played both ways. With this method, this crowd and these
inputs, the bot is about as hard to exploit as we can measure. Further gains need
something new: an outside opponent (task 6), a guess at the hidden team (task 8), or
real games.

## Team list

`data/teams.json` is the wide list. Best teams, as win share piloted by the Planner
against a field of half finalists and half random teams, 600 battles each:
Altaria / Charjabug / Corviknight 73.2% ± 3.5; Altaria / Shadow Charjabug / Corviknight
70.9% ± 3.6; Corviknight / Tinkaton / Mandibuzz 66.1% ± 3.8; the owner's Melmetal /
Altaria / Jellicent 64.7% ± 3.8 (4th of the 25 fully tested). Tinkaton is on 39 of the 81
saved teams, Shadow Annihilape on 31, Corviknight on 25. "Best" means best with this
pilot against this field; the `seen` counts for teams met in real games are all still zero.

### Teams better than the owner's, in simulation (2026-10-10)

`python3 scripts/better_teams.py` plays the owner's team (with their real moves), the ten best
teams from the search above, and sixteen one-change versions of the owner's team on the same
1,000 battles, then replays the leaders on 3,000 fresh battles with every choice of lead.
Pilot: the trained bot. Opponents: the usual varied crowd, on teams drawn half from the
good-team list and half at random from the top 50. Second round only:

| Team (best lead first) | Wins | Against the owner's team, same battles |
|---|---|---|
| Corviknight / Tinkaton / Mandibuzz | 83.0% ± 1.3 | +6.5 ± 2.0 |
| Mandibuzz / Tinkaton / Annihilape | 82.4% ± 1.4 | +5.9 ± 2.0 |
| Jellicent / Melmetal / Tinkaton (Altaria changed for Tinkaton) | 81.8% ± 1.4 | +5.3 ± 1.9 |
| Altaria / Shadow Charjabug / Corviknight | 79.5% ± 1.4 | +3.0 ± 2.0 |
| Altaria / Charjabug / Corviknight | 78.5% ± 1.5 | +2.0 ± 2.0 |
| Jellicent / Melmetal / Altaria (the owner's) | 76.5% ± 1.5 | |

For the owner's team the lead hardly matters here (76.3, 75.9, 76.5). Limits: the field is
PvPoke's top 50 for the open Great League with usual moves and IVs, while the owner is playing
the Mega Edition of the league and has met Cramorant, Oinkologne, Talonflame, Stunfisk,
Quagsire, Snorlax, Dusclops and Mimikyu, most of which are not in that field; Mega Pokémon and
Pokémon that change form are not simulated. A field built from teams actually met is the fix,
and needs many more tracked battles.

## Latency

One game turn is 500 ms. The whole path from something appearing on screen to the tap
landing must fit in that 99% of the time, with a target of about 215 ms. Targets are the
owner's; measurements are from `scripts/latency.py` on an Apple-silicon Mac, in pure Python.

| Step | Target | Measured |
|---|---|---|
| Screen capture and transfer | 50 ms | not measured (needs the phone) |
| Visual recognition | 50 ms | not measured. Reading text took 66 ms on a test image, so text cannot be read on every frame |
| Battle tracker update | 5 ms | 0.02 ms at worst |
| AI decision | 10 ms | 0.6 ms at the 99th percentile, 1.0 ms at worst (learned decisions); 5.2 ms at worst for the plain Planner |
| Input transmission and execution | 100 ms | not measured (needs the phone) |

So the software brain uses about 1 ms of the budget. Speed is not a reason to change it.

## Speed of training

Measured 2026-10-10 with `scripts/speedcheck.py`, which also fingerprints every result so
a speed-up can be shown to change nothing.

- **The engine is not where the time goes.** Engine alone (two button-mashers): about
  9,900 battles per CPU second. Planner against the crowd: about 245. Learned bot against
  learned bot: about 127. Nearly all the time is the players looking ahead, which means
  playing out the rest of the visible battle several times per decision.
- **Hot-path pass, done.** Rewriting `Battle.step`, `damage` and `View` for speed gave
  1.40, 1.24 and 1.22 times on those three workloads with identical results.
- **Several cores, done.** `scripts/decide.py --workers 4` produced 3.8 times the examples
  in the same time.
- **What is left** (task 11) is making the look-ahead itself cheaper. That changes what
  the players decide, so it has to be re-measured for strength, not only for speed.

## How the exploiter differs from the bot

`scripts/habits.py` compares two players over 1,500 battles against each other. Exploiter 2
against version 3: it throws the dearer move more often when it could throw either (44%
against 38%, and 34% against 27% into shields) and shields less (65% against 72% of hits
worth over half its health). Everything else is the same to within a point or two: both
throw on the best-timed turn about 91% of the time, hold 53 energy on average when
throwing, and switch about 1.7 times a battle. In that sample the two were level
(50.2% against 48.9%), so the exploiter's true edge is small.

Both leave about 47 energy on Pokémon that faint, per battle: nearly a charged move
wasted every game. Nobody has yet looked at whether that can be reduced.

## Endgames, measured

In 600 simulated battles, 46% reached last Pokémon against last Pokémon: 32% of all
battles with no shields on either side, 13% with shields on one side, 2% on both. That
final one-on-one lasted a median of 6 fighting turns, so it holds few decisions. A full
library of solved one-on-ones for every pair, health and energy would be enormous;
solving one from the actual position is small (about 32,000 positions with no shields).

## IVs

Measured 2026-10-10 with `scripts/ivs.py melmetal jellicent altaria`. Opponents have
PvPoke's default IVs. Stat product is attack x defence x HP; rank 1 is the highest.

How much they matter, the whole team on one kind of spread, best bot piloting, 3,000
battles (the same battles for every row):

| Spread | Win share | Against default |
|---|---|---|
| Best (rank 1: 1/15/14, 1/14/14, 0/14/15) | 84.4% ± 1.3 | +2.9 ± 1.5 |
| PvPoke default (ranks 33, 31, 103) | 81.5% ± 1.4 | |
| 15/15/15 | 74.4% ± 1.6 | -7.1 ± 1.9 |
| Most attack | 75.1% ± 1.5 | -6.4 ± 1.9 |
| Worst stat product | 68.3% ± 1.7 | -13.2 ± 2.0 |
| Random IVs (ten teams) | | -6.3 ± 1.2 |

So about 16 points separate the best spread from the worst, although the stat product
differs by only about 10%. Breakpoints explain why attack does not pay: against the 49
other top-50 Pokémon, the most-attack spread makes our fast move do one more damage to
10, 16 and 7 of them (Melmetal, Jellicent, Altaria) but lets 10, 15 and 10 of them do one
more to us, and it has less HP besides.

Working out an opponent's IVs: the CP shown fits between 92 and 433 combinations for the
five species tried, with attack uncertain by 7 to 10 points. Their fast move's damage on
us, our fast move's share of their bar, and who throws first barely narrow that (for
example 433 to 341, 168 to 167; Tinkaton 101 to 34 was the best case). Fast-move damage
is too small a number to pin stats. The practical route is not to recover IVs but to
learn the damage numbers themselves from the first hits (task 4); charged-move damage,
being a much larger number, should narrow attack far more and has not been tried.

## Screen reader

A first reader for recorded video exists on the `screen-reader-video-pipeline` branch.
Reviewed 2026-10-10: its tests pass, the per-frame path takes 11 ms without text reading,
and values it reads match the frames, but health readings are intermittent and are not
exported to the tracker without a person approving them, and it has no accuracy figure.
Details and the bar it must clear are in [`screen_reader_review.md`](screen_reader_review.md).

On screen, health bars are not in the header: they float above each Pokémon. The header
holds the name, CP, party markers and shield markers.

### First real recording, tracked end to end (2026-10-10)

One of the owner's own battles: iPhone screen recording, 1206×2622 at 60 frames a second,
191 s, a Great League win with Melmetal / Altaria / Jellicent over Cramorant / Oinkologne /
Talonflame. The reader's pixel readings on every frame, plus the announcement text read
three times a second, were turned into 121 looks and fed to the tracker
(`scripts/recording/`, result in `games/lyxia-2026-10-10/`).

What came out right, checked against the announcements in the video:

- every change of Pokémon in order: 2 switches and 4 faints;
- all 10 charged moves, each with its name and who threw it, and the 3 that were shielded;
- Talonflame threw Flame Charge, which was not in its assumed moves; the tracker swapped it in;
- no look was rejected.

Measured on this recording:

| | |
|---|---|
| Health read while bars are on screen | ours 92.6% of half-seconds, theirs 88.3% |
| Longest stretch with no reading | ours 2.5 s, theirs 4.5 s (bars are hidden for a while after a switch) |
| Pixel reading, per frame at full size | 28.9 ms median, 34.2 ms at the 99th percentile |
| Text reading, per look | 0.7 to 1 s, far too slow for live play |
| Real time taken by a charged move | 9.5 to 10 s, shielded or not (the simulator assumes 10 s) |

What is not right yet:

- Hit flashes shift a reading by up to 3 pixels of 138 and now and then read the bar as empty
  or full. Taking the commonest reading in each half-second and refusing any rise deals with
  it (10 readings set aside), but the reader itself should not emit them.
- A yellow bar (25 to 50%) and the orange part that is draining get the same colour label.
- Not read at all: our energy and move buttons, the switch timer.
- The phase templates do not fit this phone's layout, so the start of the fight and our team
  were given by hand, and the text reader stood in for them.
- The text reader missed one "BLOCKED!"; the shield counter in the header did not, so shield
  counts now come from the header.
- Cramorant's "spits out its prey" (22 damage to our Altaria and a defence drop when it was hit
  by a charged move) is not modelled, so it shows up as an unexplained loss of health.

Timing within a charged move, from the cue ("Get Ready!" or "Attack incoming!"): the shield
counter changes at about 8.5 s, the damage lands at about 9.5 s, fighting resumes at 10 s.
The health bar comes back before the damage lands, so a look taken then shows the old health.

**Opponent's fast move and energy.** The first pass assumed the usual fast move for each
opponent and, at 2 of their 5 charged moves, believed they could not afford the move.
Oinkologne was assumed to have Take Down; the steps in our health bars (about 13 on Melmetal
and 3 on Altaria, every 1.5 s) fit only Mud Slap. The tracker now works the fast move out
from the size and rhythm of those steps (`Tracker._fit_fast`): it kept Peck and Incinerate,
and replaced Take Down with Mud Slap 20 s into the battle, recounting the energy.

Their energy just before each charged move, two ways:

| Their charged move | By counting hits | By the clock | Cost |
|---|---|---|---|
| Oinkologne, Body Slam | 50 | 40 | 40 |
| Cramorant, Dive | 32 | 56 | 40 |
| Cramorant, Dive | 48 to 64 | 80 | 40 |
| Talonflame, Flame Charge | 80 | 100 | 50 |
| Talonflame, Flame Charge | 70 | 70 | 50 |

"By the clock" assumes they never pause between fast moves. Counting hits misses any that
land while the bars are hidden (the start of the battle, and a few seconds after every switch
or faint), so the count is a floor and the clock a ceiling; see the totals over both
recordings below. (These numbers are from the first pass, with the start of the fight typed
in; the committed game uses the automatic start, 0.3 s earlier, and differs a little.)

**Steps, frame by frame.** `assemble.py` now follows each bar on every frame (median of the
last ten frames; a step is a fall of two pixels or more; a step from a misread is taken back
when half a second of readings sit above it; a bar that was lower and reads full is an attack
animation covering it, and is skipped). Hits of 4 pixels or more come out clean:

| Hitting | Steps seen | Size, pixels of 138 | Gap between steps |
|---|---|---|---|
| Cramorant on Altaria (Peck: 4, every 2 turns) | 11 | 4 in 8 of them; one of 23 is the spat-out prey | 2 turns in 5 of 7 |
| Oinkologne on Melmetal (Mud Slap: 13, every 3 turns) | 2 | 12 and 13 | 3 turns |
| Talonflame on Jellicent (Incinerate: 11 to 13 with attack raised, every 5 turns) | 4 | 12, 12, 14, and one of 4 | 5 turns, once |
| Oinkologne on Altaria (Mud Slap: 3) | 5 | 2 or 3 | 1, 2 and 3 turns: at the noise floor |

Steps of 2 or 3 pixels (our Altaria's Dragon Breath, Mud Slap on a double resist) are at the
noise floor at this size: their sizes and gaps scatter. Reading the bar at full resolution
(it is about 330 pixels wide in the recording, 138 after the reader's rescale) is the fix.

In simulation, with a perfect camera, the fast move was worked out 148
times in 60 battles and never wrongly; with the rough camera, 1 of 140 was wrong.

Changes made to the tracker for this: it follows Pokémon that change form (Cramorant), learns
a named charged move it had not assumed, carries a part-hit from one look to the next, works
out the opponent's fast move, never counts more fast moves than the time allows, and takes a
charged move's damage off by the rules when the bar has not caught up yet.

### Second real recording (2026-10-10, later the same day)

254 s, a win with the same team over Stunfisk / Melmetal / Quagsire; result in
`games/lyxia-2026-10-10b/`. Nothing was typed in by hand this time: `assemble.py` takes our
team from the header names and starts when both bars are first on screen.

- 157 looks, none rejected. All 15 charged moves named, with the 3 that were shielded; 4 faints
  and 4 switches in order; the tracker ends with them on 0 Pokémon and us on 1, and the
  result screen says win. Both sides threw a charged move on the same turn once (our Dynamic
  Punch, their Mud Bomb) and both were followed.
- Both teams had a Melmetal. "Go, Melmetal!" is now given to the side whose header changes to
  that name.
- The opponent took 10 s to send out a replacement after Stunfisk fainted. A faint is now
  read from the header's count of Pokémon left, not from how soon the next one appears. The
  fight is stopped during that wait, which the tracker's turn clock does not yet allow for.
- The header shows a regional form under the plain name ("Stunfisk" for both kinds). Here
  Discharge settled it; in general the reader needs the types or the picture.
- Fast moves from the health steps alone: Quagsire's Mud Shot confirmed; Stunfisk's left as
  the usual guess because neither candidate fitted well. The words on screen settled it (below).

**Words on screen settle the fast move** (the owner's suggestion). The game writes SUPER
EFFECTIVE! or NOT VERY EFFECTIVE... when a fast move lands that is one or the other. Setting
aside the word our own fast move puts up, a word on screen belongs to their fast move, and a
word that never appears over 4 s of quiet fighting rules out every fast move that would have
shown it (`Tracker._effect_words`, the `effects` field of a look). On the two recordings:

| Opponent | Outcome | When |
|---|---|---|
| Stunfisk | Thunder Shock confirmed; Mud Shot ruled out (it would be super effective on Melmetal). The owner confirms Thunder Shock | 7 s in |
| Oinkologne | Mud Slap; Tackle and Take Down ruled out. This is before its first charged move; the health steps alone were too late with the automatic start | 19.5 s in |
| Cramorant | Peck confirmed; Water Gun ruled out | 66 s in |
| Talonflame, Quagsire | Incinerate and Mud Shot, from the health steps as before | |
| Their Melmetal | Thunder Shock: the species has no other fast move | on sight |

So every opponent fast move in both recordings is now worked out rather than guessed.

**Their energy across both recordings, 13 charged moves.** The hit count was below the cost
of the move they threw 5 times. The ceiling (`energy_by_clock`: never pausing, plus one hit,
because the moment a Pokémon comes out is only known to within a turn or two) was never below
it. So on real footage the count is a floor, and the range a player should plan against runs
from the count up to the ceiling. The tracker uses the ceiling only when the count has just
been shown to be short; using it as the top of the range all the time is the next change,
and it needs the simulated check (`scripts/check_tracker.py`) kept honest while doing it.

### Energy from the rhythm of fast moves (now the tracker's default)

The owner's point: energy is just fast moves times energy per fast move, so count the fast
moves. Counting them from steps in the health bars (the first approach) misses hits whenever
the bars are hidden. Counting them from the clock does not need the bars at all: a fast move
lands every so many turns for as long as its user is on the field and the fight is running.
`Tracker(energy="rhythm")` does this for both sides and is the default; `energy="hits"` is
the old way (`scripts/track.py --hits`, `scripts/check_tracker.py --hits`).

What the count needs to know, all measured on the recordings:

- the fight starts about 1 s after the bars first appear;
- a charged move stops the fight for 10 s from its cue, and a fast move that was in the air
  when the other side threw lands after it;
- after a faint nobody attacks until the replacement is out (the `paused` field of a look);
- a Pokémon attacks from about 0.2 s after its "Go, X!" is first read; a switch costs its turn;
- our switching does not interrupt their rhythm.

Checked against every charged move thrown in the two recordings, since whoever throws must
have had the cost:

| | Charged moves | Tracked energy below the cost |
|---|---|---|
| Ours, counting hits | 12 | 4 |
| Theirs, counting hits | 13 | 4 |
| Ours, by rhythm | 12 | 0 |
| Theirs, by rhythm | 13 | 0 |

By rhythm the tracked energy was within about one fast move of the cost for 10 of the 25
(for example our Dynamic Punch at 45 of 45, Surf at 46 of 45, their Dive at 48 of 40). The
other 15 had more to spare, up to a full bar. Some of that is real (Altaria was farmed to
100 before three Sky Attacks), but the true number is not on screen, so over-counting cannot
be ruled out; Stunfisk's spare energy grew over its five Discharges (14, 10, 24, 29, 25).

The rhythm does the counting, and the hits that are seen keep it in step: if more hits are
seen landing than it had counted, it was running behind and is caught up; if one is seen
landing off its beat, the beat is moved. Pausing is rare (the owner) and is not handled.

In simulation (`check_tracker.py`, 400 battles a camera):

| Camera | Their energy exact, by hits | by rhythm | Their place in the fast move right, by hits | by rhythm |
|---|---|---|---|---|
| Perfect | 98% | 98% | 99% | 100% |
| Rough (one look in five missed, coarse bars) | 56% | 64% | 94% | 96% |

`scripts/recording/rhythm.py` is an independent version of the same count working from exact
times instead of half-second looks; it agrees (25 of 25 payable).

### Recordings in bulk (2026-10-10)

`python3 scripts/recording/run.py recording.mp4 ...` reads each recording once, splits it into
battles, tracks each and gives a pass/fail verdict with nobody watching
(`scripts/recording/README.md`). On the two recordings so far, both battles pass.

Speed of reading, the slow step, for a 254 s recording on this Mac:

| | Seconds | Times real time |
|---|---|---|
| First version: every frame, text read at full size in two bands | 710 + 362 (two passes) | about 2.8 running both at once |
| Now: one pass, 15 frames a second, header text every 2 s, middle band only, text finder on a smaller copy | 224 | 0.88 |

Where the 224 s go: bars and header pixels 90, header text 49, announcement text 40, decoding
the video and the rest 45. Two recordings side by side took 247 s for 445 s of video. The
recordings are about 110 MB a minute, so a gigabyte is about 9 minutes of video and about as
long to read with one job.

Each speed-up was checked against the full reading of the same recording: the tracked result
(every charged move, faint and switch, the fast moves worked out, energy against costs) is the
same at 10 frames a second and with the lower text band dropped. The smaller text finder
catches 96 of 99 announcements per look, each of which stays up for several looks, but it
did lose one cue outright ("Attack incoming!" under an effectiveness line). The assembly now
also builds a charged move from its "X used Y!" line when the cue was not read, and the
verdict fails a game whose shields used do not match the charged moves tracked as blocked,
which is how that miss would have been caught.

What the verdict checks is listed in `scripts/recording/verdict.py`. It needs no ground truth,
so it can pass a game that is wrong in a way the checks do not cover; the shield check was
added after exactly that happened.

### Our energy, read off the charged-move buttons (2026-10-10)

The two buttons at the bottom of the screen each fill from the bottom as energy builds: the
filled share of the height is energy / cost, and once full the button starts again from empty
for a second helping. `scripts/recording/buttons.py` reads the fill and whether the buttons
are on screen; `assemble.py` turns the two fills into one energy (two buttons with different
costs pin down which helping each is on) and puts it in the look as `my_energy`. Which button
is which move is worked out from which pairing agrees. Example, Jellicent with Hex (13 a hit),
Surf at 45: the Surf button read 0.28, 0.58, 0.87 of full, which is 13, 26, 39.

This is the first real measurement of energy we have, so it was used to test the count:

| Compared at the end of each stretch of fighting, while under both costs | Stretches | Count exact | Within one fast move |
|---|---|---|---|
| First recording | 5 | 2 | 5 |
| Second recording | 9 | 4 | 9 |

So the fast-move count is good to one fast move either way, and the verdict now allows a
thrower to be one fast move short. The tracker takes the buttons over its own count when they
disagree by more than 4 for three looks running (the fill lags a hit by a look or two, and
more than that on the second helping, so a single look is not believed): 4 and 8 times in
the two battles.

What the buttons taught about timing, each found as a disagreement with the count:

- A switch takes effect about a second before "Go, X!" is read. Jellicent had landed its
  first fast move 0.7 s before its text; Altaria stopped gaining 1.5 s before "Go, Melmetal!".
  The assembly now puts a switch 1 s before its text (`SWAPPED`).
- The wait after a faint is longer than the header suggested: up to 3 s in which the count
  kept crediting fast moves. Waits are now timed from the buttons going to half a second
  before they return.
- A charged move does not always take 10 s. Cramorant spitting out its prey stretched one to
  13.5 s, and the count over-credited 6 fast moves there until the buttons corrected it.

Tried and worse: using "buttons on screen" as the fight's clock. They go a second early when
we tap a charged move and come back half a second after fighting resumes, and counting only
that time left the opponent short of energy for 9 of 13 moves they threw. Also tried, with no
difference on the measure above: holding a fast move over a charged move instead of landing
it with the move.

Not done yet: reading the move names under the buttons (our moves without a team sheet), and
a one-move Pokémon, whose single button sits elsewhere.

### Third and fourth recordings (2026-10-10): what broke, and the count's real accuracy

Two more of the owner's battles, both wins: against Altaria / Mimikyu / Melmetal, and against
Snorlax / Dusclops / Cramorant. Both failed the verdict at first, each for reasons the first
two recordings could not show. All four now pass.

- **Both teams had Altaria and Melmetal.** Names no longer said whose Pokémon or whose move
  it was. Who is out now comes from the name in each side's header, with the matching
  "Go, X!" giving the moment; whose charged move it is comes from the cue ("Get Ready!" is
  ours), and without a cue from NICE! / GREAT! / EXCELLENT!, which only our own moves show.
- **The battle ended on a fast-move knock-out**, with no replacement to announce the faint.
  The result screen now closes the battle: the Pokémon then out on the losing side is down.
- **The opponent left with a Pokémon still standing.** The result said win, the tracker had
  them on one. The verdict accepts that only when the header's own count of their Pokémon
  agrees with the tracker's up to the last blow, so a missed faint still fails.
- **The last charged move ended the battle before its name came up.** Noted, not failed.
- **A lingering "BLOCKED!"** from our move was taken for the next move's, giving us three
  shields used. A block is now counted only late in its own move.
- **Buttons ignored.** The test for "the buttons are really there" wanted them on screen for
  15% of the battle; with many charged moves they are on for less. Now 4%, at least 5 s.

**The fast-move count against the buttons, all four battles.** At the end of each stretch of
fighting, while under both costs, buttons minus count in fast moves:

| | Stretches | Exact | Within one | Within two | Worse |
|---|---|---|---|---|---|
| First two battles | 14 | 6 | 14 | 14 | 0 |
| Third and fourth | 10 | 2 | 5 | 9 | 1 (four out) |
| All | 24 | 8 | 19 | 23 | 1 |

So "good to one fast move" was too kind: it is within one four times in five, and within two
almost always. The verdict's allowance is about a second of fast moves (two of a one-turn
move). On our side the buttons then correct the count (4 to 8 times a battle). On their side
nothing corrects it, so their energy should be read as the count give or take one or two fast
moves; `energy_odds` in the state file carries exactly these frequencies.

### Chances instead of certainties (2026-10-10)

The owner's direction: much of this should be probabilistic, starting with which moves the
opponent has. Now in the state file for each opposing Pokémon:

- `fast_move_odds` and `charged_move_odds`: the chance of each move, starting from how often
  PvPoke's simulations prefer it (`GameData.move_odds`) and updated by what is seen: a fast
  move ruled out drops to nothing, one confirmed goes to certain, a charged move thrown is
  certain and the rest share what is left of the two slots. Talonflame's Flame Charge, which
  the old picture did not have at all, starts at 0.44.
- `energy_odds`: the count give or take one or two fast moves, at the frequencies measured above.
- `ready_odds`: for each charged move, the chance they have it and can pay for it now.

PvPoke's numbers are a stand-in. The real ones are how often each move turns up in recorded
battles, which is one more reason to track many of them.

Tried, no gain yet: deciding shields by weighing every move they may have by its chance
(`Planner(odds=True)`), against taking their usual two moves as certain. 600 battles against
opponents whose movesets were drawn from the odds (86% carried something unusual), same
battles for both: 70.5% against 69.8%, difference +0.7 ± 2.5 points
(`scripts/moveset_odds.py`). It is off by default. The odds are still worth having for the
tracked games themselves.

### Handing the bulk work on

`handoff/vod_pipeline_instructions.md` tells another agent how to set the pipeline up, what
it has and has not been run on, what will break on other footage, and how to tell a correctly
tracked battle from a wrong one.

### How much of the game state is right: two screens of the same match (2026-10-11)

The official broadcast in the Twitch pilot shows both players' screens. A player's own screen
is the better witness for their own Pokémon, health, shields and (from the buttons) energy,
so it stands in for the truth about what the other screen can only work out. Three complete
matches, each seen from both sides (`scripts/recording/paired_state.py`,
`paired_energy.py`):

| One view's picture of the opponent, against the opponent's own screen | Right | Moments |
|---|---|---|
| Who is out | 98.7% | 818 |
| Health within 3% of the bar | 88.2% | 807 |
| Health within 10% | 96.2% | 807 |
| Shields | 100% | 818 |
| Pokémon left | 99.6% | 818 |
| All of the above at once (health within 10%) | 94.6% | 818 |
| Energy within one fast move | 54.4% | 274 |
| Energy within two fast moves | 69.0% | 274 |
| Everything at once, energy within two | 66.8% | 274 |

The two views also give the same 11, 14 and 15 charged moves, mirrored, with the same names,
and the same switches at the same moments.

So the events and everything the screen shows directly are right about 95% of the time, and
the opponent's energy is the weak part: the count is off by 12 on average (median 9), 2.8 too
high on balance. This is the first measurement of it; until now it had only been checked
against the cost of moves thrown. Part of the difference is the reference itself (the button
fill lags a hit, and the players' own fast moves are guessed in public footage: the two
views assumed the same fast move in 73% of moments).

Under the ending rule used for the owner's recordings (the result screen closes the battle,
checked against the header's count), 7 of the 23 public views would pass every check, 7 more
fail only because their clip has no result screen, and 9 have something else wrong.

### Timing fitted to the truth (2026-10-11)

With the other player's own energy as truth in the two-screen matches, and the owner's own in
their recordings, the timing settings in `assemble.py` were fitted one at a time
(`runs/timing_fit.out`). What changed:

| Setting | Was | Now | Why |
|---|---|---|---|
| The opponent's switch takes effect | 1 s before its "Go, X!" | 0.5 s after | The 1 s head start was measured on our own switches; for theirs it handed the new Pokémon two fast moves it had not made |
| A replacement after a faint starts attacking | 0.2 s after its text | 0.7 s after | |
| The fight starts | 0.7 s after the bars appear | 0.2 s after | |
| Fighting resumes before the buttons return by | 0.5 s | 0.8 s | |
| A long gap in the buttons counts as a pause | only with a faint seen | always | |
| A wait after a faint that comes before a charged move in the same gap | missed | counted | |

| One view's count of the opponent's energy, against their own buttons | Before | After |
|---|---|---|
| Average error | 12.8 | 9.4 |
| Within one fast move | 57% | 69% |
| Within two | 76% | 88% |

Three of the six view-directions improve a lot, two are unchanged and one is slightly worse.
The settings were fitted on these same three matches, so the "after" column is not a test;
it needs new two-screen matches. Also tried: telling each view the other player's real fast
moves (read from single rises of their button energy, which names Thunder Shock, Dragon Breath
and Hex correctly on the owner's recordings). It did not reduce the energy error, so the
error is in the timing and not in which fast move is assumed.

The owner's Pokémon are described in `data/owner_team.json` (moves, CP, IVs), read before the
battle starts. Altaria 0/14/15 is level 29 at exactly the CP shown (1497; the best spread of
4,096) and Jellicent 6/12/11 is level 24 at exactly 1496. Melmetal, given as 2/15/12 (the
second-best spread), is CP 1500 at level 15.5, while every recording shows 1496; 2/14/12 would
be 1496 exactly. The nearest level is used (15.5), which is within one IV point either way. With real stats the count of unexplained health
changes in the four recordings is about the same (32 before, 34 after): the opponent's stats
are still assumed.
Task 9 result (2026-10-09): `scripts/check_endgame.py` printed independent brute-force
agreement **12/12**, independent multi-turn agreement **3/3**, and uncached-tree
agreement **9/9**. The bounded exact player scored **53.33 ± 2.06%** against the best
Learner on 300 fresh battles; the Learner baseline on the same battles scored
51.67 ± 1.78%, for a paired improvement of **+1.67 ± 1.44 points** (95% margins,
150 team-pair clusters, seed 90261019, 210.6 seconds on one core). It solved 1,279
turn decisions and fell back after 3,738 capped searches. Low-health synthetic
1-vs-1 fixtures took 1.2 / 16.6 / 17.2 ms with 0 / 1 / 2 shields per side;
2-vs-1 took 18.9 / 340.9 / 773.2 ms. A 2-vs-2 fixture with one shield each needed
145,413 states and 22.0 seconds; two shields exceeded 200,000 states. Exact search
is still too expensive for many positions. All 32 tests pass. See
[`endgame.md`](endgame.md) for assumptions, commands, limits and full timings.

Replication on fresh battles (same command, `--seed 424242`): endgame player
50.50 ± 1.99%, Learner baseline 49.83 ± 1.77%, paired improvement **+0.67 ± 0.92
points**, which is not distinguishable from zero. Re-running seed 90261019 reproduced
the figures above exactly, so the first result is real but sat at the lucky end. In both
runs about three quarters of endgame decisions hit the search cap and fell back to the
Learner (seed 424242: 1,379 solved, 3,361 capped), and the 0.05-second budget is five
times the 10 ms decision target in the latency table. Verdict: the solver is exact, but
under this budget it does not measurably win more games; a faster engine (task 11) is
the way to let it solve more positions.

## Known gaps in the simulator

- Form-changing Pokémon are left out (Aegislash, Mimikyu, Cramorant, Morpeko).
- Switching and chance-based stat changes have not been checked against PvPoke.
- The real length of a charged move on the clock is unconfirmed; 10 seconds is assumed.
- Opponents' stats are assumed typical for the species.
- Every charged move counts as fully charged.

## Open directions

Each of these has a full brief in [`tasks.md`](tasks.md), with its state and the commands at the top of
that file.

- **The engine in real time** (task 23): search during our own fast moves, with a deadline and the trained
  bot's pick as the fallback. Measured to fit; not built.
- **Live assembly** (task 24): incremental, so a live update is not a rebuild of the whole battle.
- **Shields in the engine** (task 25).
- **Opposing teams as good as ours** (task 21), so team choice is not decided by a lopsided list.
- **Learn from tracked games** (task 5) and **predict hidden teams** (task 8), now that footage is tracked.
- **Opponent stats from CP, charge-move priority and damage per hit** (task 7). Secondary.
- **Form-changing Pokémon** (task 10).
- **Handling uncertain information** (task 15): on hold until real-game testing.
- **The phone** (task 13, the owner only): whether iPhone Mirroring passes synthetic drags is untested.

Not worth repeating without a new idea: more strategy rules of the simple kind, more training of the
current kind, and distilling the engine (all in the results above).

## Rules for proposing a change

- Say which script measures it and against what. An idea that cannot be measured in the
  simulator should say what data it needs.
- Report results as a score with a margin, on battles not used for tuning.
- Training and testing must run unattended, on one core, without a language model in the
  loop.
- The owner is short on assistant usage: prefer changes that are small, local and cheap
  to verify.
- **Opponents (owner, 2026-10-18): realistic, but do not overfit.** New measurements, team choice and opening
  books use the mixed field (`--field mixed`, `pogo.teamshape.mixed_field`: teams as PvPoke's usage data has them
  three times in four, the usual broad draw otherwise). A change is adopted only if it gains on the mixed field,
  confirmed on a fresh seed, and does not lose beyond its margin on the usual field (`--field standard`).
  PvPoke's data is one snapshot of its training battles, not GBL; refresh it rather than tuning to it.

## Twitch intake pilot (2026-10-10)

`scripts/recording/vod.py` now downloads calibrated completed Twitch recordings,
keeps one playable source, discovers battle candidates and exports cropped clips
with compressed source-frame alignment. Details and rerun commands are in
`scripts/recording/VOD_README.md`; `data/vod_pilot_report.json` holds the measured
source intervals, checksums, storage and evaluation roles. Media remains outside Git.

Two sources produced 19 match candidates and 23 player-view clips: 15 from
HomeSliceHenry and four from the official Pokémon GO broadcast with two views
each. Three replay sections were excluded, and the official opening match stays
incomplete. The broadcaster's replay badge is read separately from the phone UI,
including entrances whose phone header appears before the badge. Paired views
share a match ID and evaluation group.

The download aborts on missing fragments, checks the expected duration, and
normalizes Twitch's nonzero MPEG-TS timestamp origin by packet-copying into MP4.
An interrupted metadata update is recoverable without losing the original.
Unchanged clips can be reused after correcting replay metadata; different source
bytes, crop rectangles or boundaries are rejected.

All 41 unit tests passed. All 228,285 saved video frames decoded and matched their
source-alignment logs within 0.000687 seconds; playback and seeking worked in
Chrome on a Henry clip and both official views. Originals plus clips and their
alignment/metadata occupy 4.737 GB. No tracker changes were made.

This is intake and media validation: full game-state tracking and its verdict have
not run on these clips. Sampled boundaries still need review. Henry is development
data; the official footage is exposed regression data after layout calibration.
Neither is an untouched accuracy test, and possible YouTube overlap is unchecked.

## Public VOD tracking (2026-10-10)

`Track Battle Videos.cmd` now reads the 23 saved clips and opens their synchronized
viewer. `vod_track.py` samples screen pixels at 15 Hz and text at 3 Hz, keeps
immutable raw readings, and publishes a causal evidence ledger alongside the
existing tracker's inferred states. Public footage uses observed move labels
instead of the owner's fixed movesets. Expanded health regions handle shorter
Pokemon; faint markers and both tournament cameras have separate calibration.
The core tracker and its decision logic are unchanged.

The run produced 57,079 screen samples and 2,568 model states over all saved clip
time. The viewer shows HP fraction ranges, shields, party counters, observed and
guessed moves, energy ranges, inferred stages and switch estimates, and remembered
bench readings with their ages. Exact HP stays unknown without verified maximum
HP. Forms, unseen teammates, some fast moves and exact clocks remain unresolved.

No view passes every strict consistency check: all 23 retain an ending/terminal
roster failure. Four also have charged-event disagreements, three have energy
failures, one has a shield failure, and two start mid-match. The original
assembler filled in a zero-HP terminal knockout; the public-footage adapter now
keeps only the named attack and leaves unobserved damage/counts out. Result-screen
outcomes remain recorded separately. An unresolved final faint is not a pass.
These are consistency checks, not ground-truth field accuracy.

Without correcting the model from buttons, its energy differed from button
estimates by 12.15 units on average over 1,147 looks; two partial views had no
coverage. Equal energy rates still cannot distinguish fast moves such as Bite
and Dragon Breath. Button estimates themselves need labelled validation.

All 62 pipeline tests and 107 reader tests passed. All 108 PvPoke reference duels
still reproduced exactly. The default tracker simulation produced byte-identical
before/after output across 2,400 battles per run. Source timestamps matched for
all 57,079 readings; compressed logs reproduced a Henry clip's model states and
events byte for byte. Chrome playback, seeking, the 17-column values table,
partial-clip flags and split filters passed on four clips.

Portable results occupy 2.23 MB for all 23 views in `games/twitch/`. Local current
clip data occupies 35.75 MB plus 84.06 MB of historical calibration analyses;
media and saved clip data total 4.852 GB. Videos remain outside Git. Details,
rerun commands, runtime-cache limits and storage are in
`scripts/recording/VOD_README.md`; `data/vod_pilot_report.json` holds the receipts.
Henry remains development footage and the official broadcast exposed regression
footage. Paired views stay together; there is still no untouched accuracy test.

## Public transition accuracy iteration (2026-10-10)

A party counter can fall before the replacement header appears. The core tracker
previously consumed that count immediately and called the later replacement a
voluntary switch, incorrectly restarting its 45-second timer. It now remembers
the outgoing identity until the replacement arrives. The evidence ledger also
assigns a delayed counter confirmation to the identity at the start of the run,
rather than marking the incoming Pokemon fainted.

The public assembler now uses local counter drops and replacement prompts.
Low HP alone no longer proves a faint; a six-second lookahead no longer mistakes
a later faint for the cause of an earlier switch. In official left match 02,
Melmetal switches out alive for Quagsire, then later briefly returns before
fainting. Both real switches were previously labelled as faints. Uninterrupted
counter runs are required, and counters cannot restore fainted party members.
Timeline entries retain their header timestamps and transition evidence.

Visual review produced 15 incoming-transition labels in Henry match 01 and
official left match 02, saved with video checksums and source frame timestamps in
`data/vod_transition_labels.json`. Against baseline `1750c52`, assembly kind/order
improved from 13/15 to 15/15; the saved model's switch/faint events improved from
8/15 to 15/15. `scripts/recording/check_transition_labels.py` reproduces that
comparison; `data/vod_transition_validation.json` holds its receipts. These two
exposed clips guided the fix. The labels are agent-reviewed, not independently
adjudicated by the user, and do not validate exact timing or whole-game accuracy.

All 23 views were rebuilt using the existing raw OCR, with no new downloads.
All 73 pipeline tests and 108 PvPoke reference duels pass. The default synthetic
tracker run remains byte-identical before/after across 2,400 battles per run;
targeted tests additionally cover delayed replacement counters on both sides,
partial initial counters, timer preservation and ledger ownership. Source PTS,
code fingerprints and uncertainty checks pass for all 57,079 samples. The
compressed Henry export replays identically. Four-clip Chrome playback and the
17-column table remain verified.

An unnamed public final charge now fails the move check and is described as an
unverified resolution. A cut during an attack does not prove that attack ended
the battle. All 23 views still fail the strict ending check; four also fail
moves, three energy, one shields and two coverage. Categories count affected
views once even when a view has several failures in that category. Blind energy
disagreement worsened from 12.15 to 12.77 units over the same 1,147 looks. That is
reported honestly: corrected faint/switch behavior does not establish energy
accuracy, and button readings themselves remain unvalidated.

Current clip data occupies 35.81 MB, with 116.17 MB of retained analysis history.
Videos plus data total 4.885 GB; portable results occupy 2.30 MB. The rebuilt
41-clip viewer is 23.93 MB and embeds no videos. Exact HP, forms, fast moves,
energy, final outcomes and an untouched test source remain unresolved.

## Animation continuity (2026-10-10)

The public evidence ledger now carries known identities, moves, unaffected
counters and fresh pre-animation readings through charged animations. An
incoming attack marks the defender's health and shield decision pending; our
charge marks our energy pending. Resolution also considers a fast move already
in flight and possible faints. A readable move announcement records its exact
energy cost once. It does not invent a resulting energy balance or damage.
Normal fighting must resume before unchanged bars and counters resolve pending
changes; an actual counter decrease can resolve its own change during animation.

The viewer's cards, remembered teams and values table share those statuses.
Retained means carried from evidence; pending means a last known value awaiting
the attack's outcome; stale means current validity is unconfirmed. A fainted
Pokemon's old bar and energy are historical. Unknown initial facts stay unknown,
and an animation cannot make an already uncertain balance reliable. The raw
visible bar and clickable controls continue to describe only the current frame.
The user confirmed that switch cooldown continues during charged attacks. Both
the per-frame model display and playback timer now follow elapsed video time,
while the switch's cause and exact timer start remain inferred.

All 88 pipeline tests, 107 reader tests, 13 viewer-value checks and 108 PvPoke
reference duels pass. Browser checks cover an incoming charge, its resolution,
our minigame, timer progress, four-clip playback and the previously reviewed
Melmetal replacement sequence. All 57,079 readings in 23 views have matching
compressed continuity exports and source timestamps. Core observations, states
and events are byte-identical to commit 2fc5765 on all 23 views; the 15 reviewed
transition labels still pass. This verifies persistence and provenance, not
whole-game recognition accuracy. The existing consistency failures and 12.77
unit blind energy disagreement remain unchanged.

`data/vod_continuity_validation.json` records the new checks. Per-frame evidence
is portable as gzip JSON Lines in `games/twitch/*/continuity.jsonl.gz`; no video
was downloaded or duplicated and the immutable OCR cache was reused.
<!-- Current continuity storage -->

Current data for the 23 Twitch views is 53.76 MB (2.34 MB per view on average), plus 175.30 MB of retained analysis history. The portable results total 14.63 MB, including 12.33 MB of continuity records. Videos plus saved data total 4.962 GB. The 41-clip HTML is 31.22 MB and embeds no videos. A typical complete view's video remains 30.2 MB (median). These are measured sizes for this pilot; repeated calibration archives are separate from current data.

## Official paired battle sample (2026-10-11)

The owner requested about ten new games from the official pokemongo Twitch
channel, with both players' views. Original VODs 2897166800 and 2897312743 now
provide ten reviewed complete games and twenty player clips, five games per VOD.
Their source broadcast intervals do not overlap. Rebroadcast VODs were not
downloaded; eighteen instant-replay perspective candidates were excluded within
the discovery windows. Both views share a match ID and synchronized coverage.
The rebuilt library contains 61 video views, with a **New official sample** filter.

Intake now bounds discovery, limits unique games while preserving paired views,
recognizes broadcast result graphics, keeps a live game immediately after a
replay, and joins header fragments under complete peer coverage. Brief result
graphics between native keyframes receive quarter-second sampling near endings.
If only one phone shows the result, the peer clip retains attributed
`paired_result_visible` evidence. Missing source edges remain partial. Review
frames, original fragment intervals and camera-specific evidence are saved.

All twenty videos passed checksum, crop, audio, duration and source-alignment
verification over 224,002 decoded frames; maximum alignment error was 0.001084
seconds. Four browser playback checks cover both views of both VODs, pending
analysis, unknown values, lazy data loading and separation from training and
regression filters. All 102 pipeline tests and 108 PvPoke reference duels pass;
the reader branch's 24 core tests and 108 reference duels also pass.

The state tracker remains at 7fd4650. Fourteen state-processing files match that
commit, and all nine pixel-reader hashes match an existing pre-collection raw
cache. New clips are `not_analyzed`, with zero state readings. Layout/boundary
review exposed the sources, and intake rules improved on these cases; this is a
reserved state-evaluation sample, not an untouched end-to-end pipeline test.
Full state accuracy and exact action timing remain unmeasured. The earlier
23-view pilot/continuity reports are preserved as separate measurements.

The new cropped videos occupy 774.40 MB, plus 4.27 MB of alignment and metadata.
A sampled game averages 77.44 MB of video and 0.427 MB of saved data for both
views; state-analysis data has not yet been generated. One retained original
per VOD occupies 11.86 GB combined, including unused games and broadcast breaks.
The additional media and clip data total 12.64 GB, excluding caches, review
images and the shared runtime. The 61-view HTML remains 31.22 MB and embeds no
videos. `data/vod_additional_sample.json` holds the receipts;
`docs/official_sample.md` explains reproduction and the Windows launcher.

## Retraining on the new rules (2026-10-11)

The model in `runs/general-decide` was trained before the hold, throw-before-fainting, timed-farming and
win-the-switch rules existed. `runs/general-rules2` is a fresh model trained with them: 65 minutes on one
core, 5,020 battles, 30k shield / 11k throw / 20k swap / 5k replacement examples. The old model has eleven
times as many (336k / 115k / 298k / 66k). Compared with `scripts/compare_models.py` on the same 3,000 battles
(teams half from the good-team list and half random, today's crowd):

| Pilot | Score | Over the Planner | Against the old model |
|---|---|---|---|
| Planner alone | 55.9% ± 1.8 | | |
| Old model, margin 0.02 | 66.7% ± 1.7 | +10.8 ± 2.0 | |
| Retrained, margin 0.05 (its own choice) | 62.4% ± 1.7 | +6.5 ± 1.7 | −4.2 ± 1.8 |
| Retrained, margin 0.02 | 60.9% ± 1.7 | +4.9 ± 2.0 | −5.8 ± 2.0 |
| Fitted on both sets of examples, margin 0.02 | 67.3% ± 1.7 | +11.4 ± 1.9 | +0.6 ± 1.7 |

Head to head on 2,000 battles the retrained model gets 44.6% ± 1.8 against the old one.

The old model stays. An hour of examples played out under the right rules is worth less than eleven hours
played out under slightly older ones, and adding the new examples to the old changes nothing measurable.
Matching the old volume with new-rule examples would take about eleven core-hours; the expected gain is a
few points at most, so it has not been run. Log: `runs/general-rules2.out`, `runs/compare_models_1.out`.

### Task 19: the full-size retrain (2026-10-12)

Two runs of `decide.py --minutes 180 --rounds 3 --teams data/teams.json --workers 4` (12 core-hours each):
`runs/retrain-today` (today's crowd) and `runs/retrain-today-rivals` (the same with
`--opponents runs/general-decide/q.npz`, so half the opposing pilots use the old model). Each ended with
1.2 to 1.4 million shield examples, about four times the old model's 336k.

`compare_models.py`, all three on the same 4,000 battles (seed 19019, `runs/compare_task19.out`):

| Pilot | Score | Over the Planner | Against the old model |
|---|---|---|---|
| Planner alone | 55.6% ± 1.5 | | |
| Old model (version 3) | 64.3% ± 1.5 | +8.7 ± 1.7 | |
| Retrained | 66.3% ± 1.5 | +10.7 ± 1.6 | +2.0 ± 1.5 |
| Retrained with learned opponents | 67.5% ± 1.4 | +11.9 ± 1.6 | +3.2 ± 1.5 |

Head to head against the old model: retrained 50.9% ± 1.3; retrained with learned opponents 51.8% ± 1.3.

Only the second meets both parts of the rule. Picked from two, so it was rechecked alone on fresh battles
(seed 29029, `runs/compare_task19_confirm.out`): 68.4% ± 1.4 against 65.8% ± 1.5, **+2.6 ± 1.5** against the
crowd, and **53.6% ± 1.3** head to head. **It replaces the old model** in `runs/general-decide/q.npz`
(margin 0.02). Version 3 is kept as `q_v5.npz`, the name the hand-off asks for.

With the good-matchup rule on as well (seed 39039, `runs/compare_rule5_with_new_model.out`), the new model
is still ahead of version 3, by less: +1.6 ± 1.5 against the crowd, 51.5% ± 1.2 head to head.

A third run with the good-matchup rule on during training (`runs/retrain-rule5`, `--minutes 90 --workers 8`,
the same 12 core-hours, 1.2 million shield examples, half the opponents on the new model) did not beat the
new model: −1.9 ± 1.4 and +0.0 ± 1.4 against the crowd, 49.5% ± 1.2 and 49.6% ± 1.3 head to head (seeds 49049
and 59059, `runs/compare_rule5_a.out`, `_b.out`). The new model stays.

## Learned mid-matchup swaps (task 20, 2026-10-12)

`Q_HEADS` now includes `mid_swap`: stay, or bring in either living bench Pokémon. The
`Learner` offers it in an already judged matchup when the switch is ready, our active
Pokémon can act, and the opponent is at most two of its fast moves from its cheapest
charged move, including a move already ready. It uses `Learner._decide`, with the
Planner's sacrifice/rescue choice as its default; the training script plays out each
legal option with the same dice. Choosing a switch clears any pending fast-move hold.
Models without the head keep their previous behavior. `Learner(mid_swap=False)` and
`scripts/decide.py --no-mid-swap` provide explicit ablations.

**Training.** Both models started fresh, with the same seed (20000), three rounds,
three workers, team source (half `data/teams.json`, half random top-50 threes), usual
Planner crowd, network/fit settings, and margin-selection procedure. The new-head run
finished before the control started. Each collected for 60 minutes: 60.07 and 60.03
measured minutes, respectively; including fitting, validation and the final test, they
took 64.6 and 64.7 minutes. Both selected margin 0.02 on validation seeds 20051–20053.

Equal wall time can produce different amounts of data, so `--examples-per-round 60000`
retained exactly 60,000 fresh decisions per round, uniformly sampled across heads,
and each fit used all retained rounds. Generated totals were 720,555 with the new head
and 692,086 without; each final model was fitted on **180,000** decisions. The cap was
fixed before either full run or acceptance test. Per-head retained counts:

| Model | Shield | Throw | New-matchup swap | Replacement | Mid-matchup swap | Total |
|---|---:|---:|---:|---:|---:|---:|
| `runs/task20-with/q.npz` | 38,053 | 13,510 | 25,493 | 5,672 | 97,272 | 180,000 |
| `runs/task20-without/q.npz` | 84,661 | 29,039 | 54,257 | 12,043 | 0 | 180,000 |

This measures a fixed total decision budget: the new head uses about 54% of it, leaving
fewer examples for each original head. The result applies to that allocation. Each
run's `training.json` records generated and retained counts by round; the ignored
`examples.npz` files retain the actual fitting samples.

**Fresh evaluation.** The training scripts' final tests used seed 20999, 3,000 battles,
separate from margin selection. With the new head: 64.4% ± 1.7 against 55.4% ± 1.8 for
the Planner, a paired +8.9 ± 2.0 points. Without it: 64.4% ± 1.7 against the same
55.4% ± 1.8, a paired +9.0 ± 1.8 points. These are supporting checks; the task's
acceptance comparison uses `scripts/compare_models.py` on 4,000 other battles, seed
20261020, reserved before training and never used for tuning:

| Pilot, margin 0.02 for each model | Against the crowd | Over the Planner | Against the control, paired |
|---|---|---|---|
| Planner | 54.9% ± 1.5 | | |
| Control, without the new head | 65.4% ± 1.5 | +10.4 ± 1.6 | |
| With the new head | 66.0% ± 1.5 | +11.0 ± 1.7 | +0.6 ± 1.5 |
| Current model, `runs/general-decide/q.npz` | 65.2% ± 1.5 | +10.2 ± 1.7 | −0.2 ± 1.6 |

Head to head uses seed 20261021, 2,000 random team pairings played both ways (4,000
battles), also unused for tuning:

| Match | First named player's score |
|---|---|
| With the new head against the control | 51.3% ± 1.3 |
| Current model against the control | 53.5% ± 1.3 |
| With the new head against the current model | 44.6% ± 1.3 |

The second `compare_models.py` command directly compared the new model with the current
one, repeating the same crowd battles and adding their direct match. Its paired crowd
difference was +0.8 ± 1.7 points; both crowd scores reproduced the first command exactly.

**Outcome.** No clear overall improvement from the new head at this budget: the paired
crowd gain is smaller than its margin, and the head-to-head result is near the 50%
boundary. Task 20's **Done when check was run**: equally sized training sets were
verified and the two trained models were compared with `compare_models.py`. The new
model also loses clearly to the current model head to head and fails the replacement
criteria. No files in `runs/general-decide/` were replaced or changed.

**Reproduction and checks.** Exact commands, including environment settings and seeds,
are in [`runs/task20/commands.txt`](../runs/task20/commands.txt). Full training output:
[`task20-with.out`](../runs/task20-with.out) and
[`task20-without.out`](../runs/task20-without.out). Acceptance output:
[`compare.out`](../runs/task20/compare.out) and
[`compare-current.out`](../runs/task20/compare-current.out). Every reported score above is win share
with a 95% margin on battles excluded from tuning; validation scores in the training
logs are tuning diagnostics.

The full suite passed: 111 tests run, with six existing video checks skipped because
PyAV is absent from the requested interpreter. All 108 PvPoke reference battles
reproduced exactly.
Tests cover the two-fast-move boundary, switch availability, masks, slot mappings,
catching an actual charged move, forced play-outs, old models/policies, and sampling.
An additional 100 old-model battle logs matched the pre-edit `Learner` exactly. The
saved `speedcheck.py` baseline is stale for the unchanged Planner too; it was not
overwritten. Artifact checks verify array shapes, finite model weights, equal training
settings and totals, and the presence/absence of the new head. Input hashes and every
file in `runs/general-decide/` also verified unchanged. Comparison workers now reset
pilot seeds per job so worker reuse does not change the comparison's random choices.

All long commands were invoked with `nice`, with one NumPy/BLAS thread per worker.
The sandbox denied further priority reductions; the scripts retained their inherited
low priority (`nice=5`), with at most three workers. Models and logs are small; large
example archives remain ignored. These are simulator results against the existing
crowd and learned models, with exact battle information.

## Best teams from the owner's own Pokémon (2026-10-11)

**Do not use the table in this section to pick a team.** The owner rejected it: at their level the game
is close to 50-50, so 82% means the opposition was too weak. It was, in two ways, measured by re-scoring
the same 15 line-ups on 2,000 battles each (`runs/roster_calibration.out`):

| Opponents | Best line-up | Current three, Melmetal lead |
|---|---|---|
| The crowd on random teams from the top 100 (the table below) | 82% | 78% |
| The same bot as ours on random teams from the top 100 | 70% | 64% |
| The same bot as ours on teams from the good-team list | 60% | 60%, and it is the best of the 15 |

With an opponent as good as we are on good teams, the Umbreon line-ups fall four points or more behind
the current three. `roster_teams.py` now takes `--rival bot` and `--listed SHARE` for this; the rerun of
the full search is the next section. What follows is the first run, kept as a record.

`scripts/roster_teams.py` searches every line-up the owner can field. Their 20 Pokémon are in
`data/owner_team.json` (the current three) and `data/owner_roster.json` (17 more, with IVs; moves are the usual
ones except where the owner gave them; each is taken to be at the highest level within 1500). That is 3,366
line-ups counting who leads (Quagsire and Shadow Quagsire cannot share a team).

Opponents, as the owner asked: a random legal three from the top 100 supported Pokémon, every such team
equally likely (about 485,000 with the lead counted), played by the usual crowd. Each candidate meets a random
sample of them, the same sample for every candidate, piloted by the trained bot. Stages: 150 battles each,
keep 500; 600 more, keep 50; 3,000 more, keep 12; then 6,000 fresh battles each, which are the only numbers
reported. 47 minutes on three cores, about a million battles.

| Line-up (lead first) | Score | Against the top line |
|---|---|---|
| Umbreon / Melmetal / Altaria | 82.1% ± 1.0 | |
| Altaria / Melmetal / Araquanid | 80.9% ± 1.0 | −1.2 ± 1.3 |
| Altaria / Melmetal / Umbreon | 80.7% ± 1.0 | −1.4 ± 1.2 |
| Melmetal / Altaria / Umbreon | 80.3% ± 1.0 | −1.7 ± 1.3 |
| Melmetal / Altaria / Araquanid | 80.1% ± 1.0 | −2.0 ± 1.4 |
| Umbreon / Melmetal / Feraligatr | 79.8% ± 1.0 | −2.2 ± 1.2 |
| Umbreon / Altaria / Empoleon | 79.1% ± 1.0 | −3.0 ± 1.2 |
| Melmetal / Altaria / Jellicent (current, best lead) | 77.6% ± 1.1 | −4.5 ± 1.4 |

Melmetal is in 11 of the 12 survivors, Umbreon in 9, Altaria in 7, Araquanid in 5. Jellicent is the slot to
change: Umbreon in its place is worth about four points, Araquanid about three. The full list is in
`data/roster_teams.json`; log in `runs/roster_teams.out`.

What this does not show: random threes from the top 100 are easier than the teams real opponents build, so
the scores are high and the gaps may shrink or reorder against coherent teams; form-changers (Cramorant,
Mimikyu, Aegislash, Morpeko) are not in the pool; and Umbreon is assumed to have Snarl with Dark Pulse and
Last Resort.

## The team search again, with an opponent as good as we are (2026-10-11)

`python3 scripts/roster_teams.py --rival bot --listed 0.8`: the same trained bot pilots both sides, and 80%
of opposing teams come from the good-team list (`data/teams.json`), the rest random threes from the top 100.
All 3,366 line-ups, stages 120:450, 500:40, 2500:12, then 5,000 fresh battles each (50 minutes, three cores).
The second column re-scores the same line-ups against the same bot on random top-100 teams only (2,000
battles each, `runs/roster_recheck_2.out`).

| Line-up (lead first) | Against the good-team list (80%) | Against random top-100 teams |
|---|---|---|
| Stunfisk / Melmetal / Altaria | 74.4% ± 1.2 | 58.1% ± 2.2 |
| Ninetales / Melmetal / Jellicent | 70.0% ± 1.3 | 58.7% ± 2.2 |
| Feraligatr / Melmetal / Mantine | 69.9% ± 1.3 | 56.9% ± 2.2 |
| Feraligatr / Melmetal / Altaria | 69.6% ± 1.3 | 60.8% ± 2.1 |
| Feraligatr / Altaria / Stunfisk | 69.2% ± 1.3 | 51.1% ± 2.2 |
| Ninetales / Stunfisk / Empoleon | 68.6% ± 1.3 | 49.0% ± 2.2 |
| Melmetal / Altaria / Jellicent (current) | 60.6% ± 1.4 | 64.1% ± 2.1 |

**This is still not an answer.** By the owner's test (the game is near 50-50 between equals), 74% says the
opposing teams are beatable, and the second column shows how: the line-ups that top the first column fall
to 49 to 61% once the opposing teams change, and the current three, last in the first column, are first in
the second. The good-team list is narrow and heavy with Steel types (Tinkaton in 39 of 81 teams,
Corviknight in 25), so the search found its counters: Stunfisk, Ninetales and Feraligatr. Real opponents
would not keep bringing teams that lose three games in four.

What the two columns do agree on: Melmetal is in every line-up that holds up in both, and the current
three are not beaten in both columns by anything. Feraligatr / Melmetal / Altaria matches them in the
worse of its two columns (60.8 against 60.6) and is nine points better against the list.

The order of teams is decided by what the opponents bring, and that is the missing piece: a set of
opposing teams whose own best teams score about 50% against it (task 21 in `tasks.md`), or the teams the
owner actually meets. The script now prints a caution, and writes it into `data/roster_teams.json`, when
its best line-up wins more than 65%.

## Opposing team mixture (task 21, 2026-10-12): reduced run did not meet the target

**The new list is experimental, not an accepted replacement.**
`scripts/self_consistent_teams.py` now builds a weighted mixture with the same trained bot on both sides
(`runs/general-decide/q.npz`, margin 0.02), using the top 100 supported Pokémon. It measures a matrix of
three-on-three battles, fits a zero-sum mixture by fictitious play, searches for counters among random
threes and every one-member change to its strongest parents, adds counters and fits again. Earlier teams
stay in the population. No one-on-one coverage filter is used. `pogo.teamlist.drawer` understands explicit
mixture weights while preserving the original score/seen weighting for old lists.

The smaller run used eight rounds, 256 random threes per round with every lead, two mutation parents,
stages of 8 and 64 mirrored pairs, and 12 pairs per matrix entry. It examined 16,185 distinct line-ups
during fitting and retained 145. None of the eight rounds met the development stopping condition.
The weights were then frozen in **`data/teams_v2.json`**; `data/teams.json` was not changed.

An independent counter search screened another 3,397 line-ups against the frozen mixture. Its ten
finalists and every retained member were tested on **1,000 untouched mirrored pairs (2,000 battles) per
team**, 154 teams altogether. Margins below are 95% intervals across independent pairs, not across their
two correlated battles. No final-test battles affected fitting, stopping or candidate selection.

| Fresh check | Score against the new list |
|---|---|
| Strongest counter found: Shadow Annihilape / Guzzlord / Stunfisk | **62.7% ± 3.0** |
| Shadow Empoleon / Jellicent / Stunfisk | 62.1% ± 3.0 |
| Forretress / Jellicent / Stunfisk | 62.0% ± 3.0 |
| Best retained member: Carbink / Feraligatr / Marowak | 53.2% ± 3.1 |

The eight highest-scoring tested teams were outside the fitted population. The matrix fit holds up much
better within its retained population than against newcomers: candidate coverage and more counter-search
rounds are still needed. The task's counter check **ran and failed**, printing:

```text
Done-when counter check: FAIL (best found under 55%); simultaneous 95% upper-bound check: FAIL
```

Selected audit candidates were also tested against the old list with matching draw uniforms, pilot seeds
and battle dice, on the same 1,000 fresh pair indices per column:

| Team | Old list | New list | New minus old, paired points |
|---|---|---|---|
| Shadow Annihilape / Guzzlord / Stunfisk | 47.3% ± 3.0 | 62.7% ± 3.0 | +15.4 ± 4.3 |
| Shadow Empoleon / Jellicent / Stunfisk | 63.5% ± 3.0 | 62.1% ± 3.0 | −1.5 ± 4.2 |
| Clefable / Hippowdon / Lapras | 65.8% ± 2.9 | 52.1% ± 3.1 | −13.7 ± 4.2 |

So this budget did **not** solve the opposing-field problem. The mix resists Clefable / Hippowdon /
Lapras better, leaves the Shadow Empoleon counter essentially unchanged, and loses much more often to
the strongest new counter. A 50% average for a mixture playing itself would be a zero-sum identity,
not an acceptance test.

The build and audit took 108.2 minutes on three workers. This is a sampled search, not enumeration of
all 474,270 legal top-100 line-ups. The broader run was not attempted: its first-stage screens alone
would require several million battles, beyond three hours at the measured rate, before matrix fitting,
validation and the roster comparison. [The rerun guide](team_mixture.md) gives the exact smaller and
larger commands, an exhaustive-screening option, the method and its limits.
`runs/teams_v2.out` contains the printed results; `data/teams_v2.report.json` contains every held-out
score, simultaneous uncertainty bounds, paired comparisons, settings, seeds and model/code/data hashes.

`--observed` imports cumulative sighting snapshots and preserves `seen` counts without changing fitted
weights again at draw time. Real-game sighting aggregation (task 5) was not performed; the saved counts
remain zero. No real ladder distribution is claimed. The battle engine and learned pilot are unchanged.
All 113 unit tests ran successfully (107 passed, six optional video checks skipped); all 108 PvPoke
reference battles reproduced exactly. A small end-to-end replay produced identical weights and held-out
results with one and three workers, and verified cumulative sighting import. All saved source, model,
input and list hashes matched the audit.

### Owner's roster against both lists

The paired roster search screened all **3,366** legal owner line-ups against each list, using their
actual IVs and moves. It kept twelve finalists from each search plus every lead of the current three:
26 distinct line-ups. Each was then tested on **2,000 new mirrored pairs (4,000 battles) per list**,
with the trained bot on both sides and 100% listed opponents. These final battles were not used to
select candidates. The draw uniforms, battle dice and pilot seeds match between columns; the selected
opposing team changes with the list. Within each column every line-up faces identical opponents.

This table contains the ten highest fresh scores under **each** list, plus the current line-up.
Ranks are among the 26 finalists; close ranks need not be distinguishable. All margins are 95%,
computed across independent mirrored pairs. These 100%-listed results differ from the earlier
80%-listed experiment above.

| Owner line-up (lead first) | Old rank | Old list | New rank | New list |
|---|---:|---|---:|---|
| Mantine / Jellicent / Umbreon | 25 | 41.6% ± 2.2 | 1 | **69.5% ± 2.0** |
| Ninetales / Melmetal / Jellicent | 8 | 71.2% ± 2.0 | 2 | 68.2% ± 2.0 |
| Melmetal / Shadow Quagsire / Azumarill | 20 | 52.8% ± 2.2 | 3 | 66.6% ± 2.1 |
| Feraligatr / Jellicent / Stunfisk | 13 | 68.1% ± 2.0 | 4 | 65.3% ± 2.1 |
| Empoleon / Ninetales / Feraligatr | 23 | 50.3% ± 2.2 | 5 | 65.0% ± 2.1 |
| Empoleon / Jellicent / Feraligatr | 24 | 48.4% ± 2.2 | 6 | 64.8% ± 2.1 |
| Azumarill / Jellicent / Ninetales | 16 | 58.2% ± 2.2 | 7 | 64.6% ± 2.1 |
| Melmetal / Altaria / Ninetales | 18 | 54.4% ± 2.2 | 8 | 64.5% ± 2.1 |
| Melmetal / Jellicent / Feraligatr | 17 | 57.1% ± 2.2 | 9 | 64.5% ± 2.1 |
| Stunfisk / Vigoroth / Umbreon | 22 | 52.3% ± 2.2 | 10 | 62.7% ± 2.1 |
| Stunfisk / Melmetal / Altaria | 1 | **78.1% ± 1.8** | 13 | 60.7% ± 2.1 |
| Jellicent / Stunfisk / Fearow | 7 | 71.2% ± 2.0 | 14 | 59.3% ± 2.2 |
| Ninetales / Stunfisk / Empoleon | 2 | 74.2% ± 1.9 | 17 | 51.5% ± 2.2 |
| Shadow Quagsire / Jellicent / Stunfisk | 9 | 71.1% ± 2.0 | 18 | 50.8% ± 2.2 |
| Feraligatr / Melmetal / Altaria | 6 | 71.9% ± 2.0 | 19 | 50.5% ± 2.2 |
| Jellicent / Ninetales / Stunfisk | 3 | 73.7% ± 1.9 | 20 | 49.0% ± 2.2 |
| Feraligatr / Altaria / Stunfisk | 4 | 72.4% ± 2.0 | 21 | 49.0% ± 2.2 |
| Melmetal / Altaria / Jellicent (current) | 15 | 59.0% ± 2.2 | 22 | 48.9% ± 2.2 |
| Stunfisk / Ninetales / Empoleon | 5 | 72.4% ± 2.0 | 25 | 41.1% ± 2.2 |
| Shadow Quagsire / Melmetal / Stunfisk | 10 | 69.9% ± 2.0 | 26 | 39.9% ± 2.1 |

The old winner's score falls **17.4 ± 2.8 percentage points** under the new field, while the new
winner gains **27.9 ± 3.0 points**. The field still determines the recommendation, and the new list
still has large vulnerabilities. This does not establish Mantine / Jellicent / Umbreon as the best
real-world choice. The roster-reporting part of the task's "Done when" check is complete; the
under-55% counter requirement failed, so task 21 remains unfinished as a validated opponent model.

The comparison took 64.0 minutes, bringing the two reduced experiments to **172.2 minutes** on at most
three workers. `data/roster_teams_v2.json` holds all 26 rows, paired changes, differences from the
current line-up, seeds and provenance; `runs/roster_teams_v2.out` has the printed output. The original
`data/roster_teams.json` is preserved. Exact commands for both results and the larger continuation are
in [the rerun guide](team_mixture.md).

**Fuller builder run (2026-10-12).** The continuation in the rerun guide, run with `--workers 6` instead
of 3 (`runs/teams_v2_full.out`, 408.7 minutes, ten rounds from `data/teams_v2.json`), wrote
`data/teams_v2_full.json`. The strongest counter found now scores **58.3% ± 1.7** against the list (was 62.7%
± 3.0), still above 55%, so the check still fails. The roster comparison against this fuller list had not
finished when this was written.

## Reserved official sample: frozen state evaluation (2026-10-11)

The latest GitHub handoff at 0fd98ff requested the twenty reserved views' readings
without tuning the state tracker on them. All ten games are now read at 15 FPS
and three text looks per second: 56,034 screen readings,
2,534 published model states and matching lossless
continuity records. Videos stay local. Both sources retain the reserved role.
The three protected tracker files and all nine pixel-reader hashes are unchanged.
New source IDs inherit identical prior button geometry, with no numeric fit.

The exact before/fitted `--told` comparison on these ten games gives mean energy
disagreement 16.32 → 14.15
and within-two-fast-move agreement
73.4% → 75.7%.
These compare eligible looks against the other camera's imperfect saved readings,
not independently verified truth. Full per-field results and denominators are in
`docs/reserved_state_evaluation.md` and `data/vod_reserved_state_evaluation.json`.
Strict ending checks fail in 20 of twenty views. A reviewed frame shows combat by
4.517 seconds while one view starts its battle model at 20.7 seconds. Forms,
exact HP and unobserved events remain unresolved; nothing was tuned on this case.

All 102 pipeline tests and 108 reference duels pass. Export audits cover all
twenty clips; browser checks cover four player views, playback and twelve seeks,
populated live values, single-view decompression and dataset separation. Current
new data occupies 55.36 MB, retained history
10.16 MB and portable exports
15.31 MB, alongside the unchanged 774.40 MB
of cropped video. The 61-view HTML is 58.92 MB
and embeds no video. Earlier collection and 23-view reports remain historical
measurements, separate from these results.

## Tracking live, replayed from recordings (2026-10-13)

Until now every tracked game was built after the battle, from the whole recording: `assemble.py` smooths a
health bar with later frames, takes back a step that later frames contradict, works out a faint from the
header up to six seconds later, and closes the battle from the result screen. A live bot has only what has
been seen so far. `scripts/recording/live_replay.py` measures what that costs. At every half-second t it
rebuilds the looks from the readings up to t only (`assemble(..., now=t)`), with each text reading arriving
`--text-delay` seconds after its frame, and hands the tracker the looks for that half-second as soon as they
exist; a look that only appears later is lost, since the tracker cannot go back. No video is needed: it runs
on the saved readings in `games/*/raw/`.

`assemble.py` is now a function as well as a command (`assemble(rows, texts, argv, span, now)`); the command's
output is byte-identical to before on all 47 recordings and clips with saved readings. With the whole battle
in hand, live mode gives exactly the offline looks (`tests/test_live_assembly.py`).

**Bugs that only show live, found and fixed.** Each was a rule written for a finished recording:

- "The battle ended on our charged move" fired at every moment one of our moves was still playing. It now
  needs the result screen.
- On public footage, a charged move still playing was taken for the clip ending on a named attack, so the
  tracker was told of the same move up to seven times and spent the opponent's energy each time. This alone
  had live public tracking at 72.9% (energy within two fast moves) against 79.2% offline.
- A gap in the buttons that had not closed yet counted as a pause even after the replacement was out and
  fighting (20 energy short on one Talonflame). It now ends when a Pokémon comes out.
- With text read late, the effectiveness words never reached a look; they now go to the look in which they
  are read.

**Your recordings, against the offline picture** (four battles, every half-second; offline is not the truth
but it is what seeing the future gives):

| Live, text read on time | Agrees with offline |
|---|---|
| Who is out, shields, Pokémon left, both sides | 98 to 100% |
| Health within 3%, both sides | 99.4% (ours), 99.8% (theirs) |
| Their energy within one fast move | 93.0% (95.1% before the change below) |
| Every switch, faint and charged move | all 71 seen, at the same look; our own switches 1.0 s later |

Waiting a second before believing a look (`--lag 1`) changes little: our energy agrees with offline 84.4% at
no wait and 86.6% at one second (the buttons are smoothed over frames that come after), their energy 95.1% either
way (measured before the late-switch change below).

**The opponent's energy against the truth.** In the three two-screen matches already used for fitting
(`2897295240`, both views each), each view's count of the opponent's energy is set against the other
player's own buttons:

| | Average error | Within one fast move | Within two |
|---|---|---|---|
| Offline | 9.2 | 64.3% | 79.2% |
| Live, text on time | 7.7 | 71.0% | 81.0% |
| Live, text 1 s late | 8.9 | 60.1% | 81.2% |
| Live, text 1 s late, buttons stop the fight (below) | 8.7 | 63.4% | 79.8% |
| Live, text on time, buttons stop the fight | 8.0 | 67.5% | 81.2% |

So live tracking is no worse than offline; if anything better (offline's look-ahead rules were fitted to
these same matches, and some of them were costing it). Text read a second late costs about ten points within
one fast move and nothing within two. Who is out, health, shields and Pokémon left are the same live as
offline (96.7%, 89.2% within 3%, 100%, 99.6%).

Settings were then fixed and the same replay run once on the reserved sample (ten matches, twenty views, never
used for any of the above):

| Reserved sample, 744 to 750 moments | Average error | Within one fast move | Within two |
|---|---|---|---|
| Offline | 15.1 | 59.0% | 73.3% |
| Live, text on time | 14.3 | 59.9% | 75.7% |
| Live, text 1 s late | 14.8 | 57.3% | 73.5% |

Who is out 95.6 to 96.1%, health within 3% 77.9%, shields 95.0 to 95.1%, Pokémon left 99.5 to 99.6% in all
three. So on footage nothing was tuned on, tracking live is as good as tracking afterwards, and reading text a
second late costs about two points within one fast move. The opponent's energy remains the weak part, as it
is offline: about one moment in four is more than two fast moves out. Seeing the future was never what held
it back.

**Charged moves from pixels.** The two charged-move buttons vanish the moment either side starts a charged
move. On your four recordings they went before the text cue every time: for the opponent's 21 moves a median
0.4 s before "Attack incoming!" was read (0.07 to 1.2 s), for our 20 a median 1.0 s before "Get Ready!" (in
play the bot knows its own taps anyway). Of 160 other gaps in the buttons, 130 were flickers under 0.25 s and
30 were switches, faints and the wobble as fighting resumes. So "buttons gone for 0.25 s" is a signal that a
charged move (or a faint or switch) has begun, from pixels, before any text. Used to hold looks back until the
text says why (`--buttons-stop 0.25`), it made no measurable difference to the opponent's energy (table
above), so it is off by default; it stays the way to know a charged move has started without reading text.

Why late text costs energy: looks given in the first second of a charged move the tracker has not been told
of yet credit fighting turns; when the charged move arrives, the tracker's clock would go negative and is held
at zero, so those turns stay counted.

**A change of their Pokémon learnt late.** Live, the header shows a new opponent a second or two after it came
out, and the tracker used to give all that time to the one that left. A look may now say how long the new one
has been out (`Observation.foe_out_for`), and the tracker counts from then. Tested
(`tests/test_live_assembly.py`), but no measurable gain on the two-screen matches (7.7 against 7.8 average error).

**Energy only goes down when a charged move is thrown** (the owner). The tracker already keeps to it for the
opponent: their energy fell between charged moves 4 times in 1,333 live looks, each when it re-identified the
fast move and recounted. Our button reading does not: 7 of 231 readings fell with no charged move of ours,
by 6 to 58 energy, mostly the wrong helping of a button that had filled once. `--monotone-buttons yes` sets
such a reading aside unless four frames in a row agree on it. On the four recordings it changed how far our
count sits from the buttons by nothing measurable (5.3 against 5.4), so it is off by default.

**Speed.** Rebuilding from scratch every half-second takes 3 ms early in a battle and 150 ms by its end (one
core), too slow to run live in a 500 ms turn next to recognition. The live path needs the assembly made
incremental; the replay is the yardstick it must match.

What this does not cover: the readings are the recorded ones, at 15 frames a second and with text every third
of a second; a live reader on the phone will be slower and rougher. Phone capture and taps are still unmeasured.

### Whole-recording battle extraction — 2026-10-13

The owner's extraction target accepts clipped starts and endings. The former
Windows menu silently applied five-game limits and 40–45-minute scans. Full
intake now accepts completed Twitch/YouTube links, scans the entire recording,
keeps partial fragments down to three seconds, and offers automatic phone-crop
proposals for unfamiliar source IDs. Unknown layouts fail explicitly for review.
The earlier sample workflow remains available only through explicit limits.

Observed false splits during long charged animations and stale party/shield
resets across lobbies were corrected. Readable-HUD lookahead catches a reviewed
restart even when a shield was spent before the next usable sample. Asymmetric
camera coverage can retain paired partial starts. Displayed player-name changes
separate official highlight montages into partial excerpts instead of combining
several matchups into one apparent game.

The two official sources were scanned across 15,206 seconds: 32 ordinary game
interval candidates and ten edited excerpts, each with two views, yield 84 clips.
This is not a claim of 42 unique games. All 760,904 decoded frames passed source,
crop and timestamp verification (maximum error 0.0016671 seconds). Coverage checks
found no ten-second uncovered detected-HUD runs outside selections and labelled
replay exclusions. Both reviewed YouTube sources match all nine known battle
intervals each at IoU >= 0.5, with no extras. Independent recall on unfamiliar
recordings remains unmeasured.

The twenty reserved clips' four protected files per view retain their original
hashes. Their state-evaluation report is unchanged; no state-engine or fitted
recognition parameter changes are included. New footage from these sources stays
outside training. New clips are pending analysis, and the existing tracked clips
still populate the playback table. Browser checks pass for both POVs of ordinary
and edited new clips, both POVs of both tracked sources, twelve tracked seeks,
and sample separation. All 187 repository tests and 108 reference duels pass;
two upstream Linux-only assumptions were made portable to Windows.

Sources occupy 11.86 GB; selected clip media 2.63 GB; saved clip data 73.08 MB.
Nineteen earlier cuts were reused. Four superseded montage clips (106.04 MB)
remain on disk and are hidden from the active viewer. The viewer has 126 active
views and a 58.93 MB HTML file with zero embedded video bytes. Receipts, code and
source hashes, per-clip storage, and limitations are in
`data/vod_full_extraction_validation.json`. Double-click `Extract all battles.cmd`;
details are in `docs/full_vod_extraction.md`. Accurate full game-state tracking
and independently measured whole-VOD battle recall remain separate next work.

## The bot against real players' decisions (2026-10-13)

`scripts/real_decisions.py` takes tracked battles and, at every decision the player on our side made, rebuilds
the position from the tracker's state and asks the trained bot what it would do: throw or keep fast-moving (and
which move), shield or not, switch or stay. Where the two differ, the position is played on 200 times each way
with the same dice, the player's choice first and then the bot's, both continued by the bot against the varied
crowd (their unseen Pokémon and exact energy drawn as `advise.py` does). 47 tracked views: the owner's four
recordings, 15 HomeSliceHenry clips and 28 official broadcast views (20 of them the reserved sample, used here
only to score, not to tune). Cramorant and Mimikyu are played in the form they start in. Rows are in
`runs/real_decisions/`.

| Decisions, all 47 views | How many | Bot agrees with the player | Where they differ: the bot's choice wins more often by | Bot better / player better (by over 2 points) |
|---|---|---|---|---|
| Throw or hold, which move | 694 | 51% | +1.8 ± 1.8 points | 91 / 61 |
| Shield | 197 | 71% | +1.6 ± 3.6 | 20 / 17 |
| Switch or stay | 261 | 61% | +0.2 ± 3.4 | 39 / 29 |

By player: the owner (four recordings) 58% / 77% / 60% agreement on throws / shields / switches, and on the
owner's 8 switch decisions where the bot differed the owner's choice did better in 6 (-10.6 ± 17.1 points for the
bot); the official broadcast's players 44 to 50% / 64 to 66% / 56 to 69%; Henry 53% / 81% / 64%.

What it says: the bot and good players make different choices about half the time, and where they do, neither is
clearly better even when judged by the bot's own simulator, which favours the bot (it is the world the bot was
trained in, and the bot plays on after either choice). The commonest difference by far: **the player keeps
fast-moving where the bot would throw** (187 of 337 throw disagreements), against 69 the other way, 50 where
the bot would switch instead and 31 where both throw but different moves. Real players hold ready charged moves
far more than the bot does, which is the owner's hold rule pushed further. Shields split both ways (32 shielded
where the bot would not, 25 the reverse); switches lean towards players switching where the bot stays (56
against 38).

Limits: our side's energy in public footage is off by about 10 on average, so a "hold" there is counted only when
the buttons showed enough energy; the opponent's energy is the tracker's estimate; players' fast moves and IVs
in public footage are guessed; and the judge is the simulator, not the result of the real battle.

## Playing the bot in a browser (2026-10-13)

`python3 scripts/play.py` opens a page where a person plays the trained bot in real time on the same engine:
sprites (Pokémon Showdown's, falling back to PokeAPI's, then a badge), both health bars, our energy on the two
charged-move buttons, shields, party, the switch timer and a shield prompt when the bot throws. Fast moves are
used all the time, as if holding the screen; charged moves count as fully charged (no swiping), and hold the
screen for two seconds (`--charged-pause`) while the clock loses ten. The opponent's energy is not shown. Each
battle is saved to `games/played/` (teams, every turn, every choice) with a running tally in
`games/played/results.jsonl`, so games against people can be studied like the recordings. Tested end to end in
a headless browser (`tests/test_play.py` for the player logic); not yet played by a person.

## How decisive a win was, and an engine's evaluation (2026-10-13, the owner's idea)

**The score.** `pogo.arena.decisive(battle, side)` says how well a finished battle went, from 0 to 1: the
winner's health share left on each Pokémon plus 0.35 per unused shield (the worth the Planner's lookahead gives a
shield), over the most it could have (`left_over`), blended so that any win scores above any loss. A narrow win
is 0.75, a win losing nothing 1.0, a narrow loss 0.25, a rout 0, a draw 0.5. Over 200 ordinary battles, wins
scored 0.75 to 0.87 and losses 0.13 to 0.25: the typical winner keeps about 15% of what it started with.
`tests/test_decisive.py`.

**Learning from it.** `scripts/decide.py --score margin` scores each played-out option by this instead of by win
or loss alone. Win/loss says nothing when every option wins (or every option loses); the score still ranks them
by how comfortably. The test is two fresh models on exactly the same number of decisions and the same battles
(`--examples-per-round 40000 --rounds 3 --teams data/teams.json --opponents runs/general-decide/q.npz`), one
scored each way: `runs/score-result/` and `runs/score-margin/` (120,000 decisions each; the second was resumed
after its second round fell 192 decisions short of the quota, so its later battles differ). On the same 4,000
fresh battles (`runs/compare_score.out`):

| Pilot | Against the crowd | Over the Planner |
|---|---|---|
| Planner | 56.3% ± 1.5 | |
| Scored by win / loss | 60.5% ± 1.5 | +4.2 ± 1.3 |
| Scored by decisiveness | 60.9% ± 1.5 | +4.5 ± 1.4 (+0.4 ± 1.4 over win / loss; 51.4% ± 1.2 head to head) |
| Current model, about ten times the decisions | 66.2% ± 1.5 | +9.8 ± 1.6 |

So scoring by decisiveness is at most a small help at this budget, inside the margin; the amount of training is
what decides strength. Each model's own final test had suggested +5.0 against +3.0, but those were different
battles.

**A longer run.** `runs/general-margin/`: the same settings scored by decisiveness, two cores, every decision kept,
stopped by a container restart during its fourth round; the round-3 model has about 540,000 decisions (+8.2 ± 3.2
over the Planner on 1,000 validation battles). Against the current model on the same 4,000 fresh battles
(`runs/compare_general_margin.out`): 64.2% ± 1.5 against 66.3% ± 1.5, -2.1 ± 1.4 points, and 47.9% ± 1.3 head
to head. Not better than the current model, which was trained on more than twice as many decisions; the current
model stays.

Resumed for a fourth round (`runs/general-margin-part2.out`; 772,000 decisions, +9.8 ± 3.0 over the Planner on
its validation battles, margin 0.02); another container restart stopped the fifth during collection. Against the
current model on the same 4,000 battles (`runs/compare_general_margin_round4.out`): 64.5% ± 1.5 against
66.4% ± 1.5, -1.8 ± 1.4 points, and 46.3% ± 1.3 head to head. Still not better; this run stops here.

**Its weights.** `scripts/score_study.py`: 800 positions from ordinary battles, each played on 30 times with fresh
dice for its true chance of winning (`runs/score_study.out`, raw play-outs in `runs/score_study.json`). One
play-out's plain result explains 93.7% of the spread in true chances; decisiveness with a bare win at 0.5 (as
used) 93.5%, at 0.75 93.8%, at 0.25 90.1%; the shield weight hardly matters. In the 45 contested positions (true
chance 20% to 80%) the order is the same (28.2% for the plain result, 27.0% as used). As a predictor of who
wins, decisiveness is no better than the result; whatever it adds is in ranking options within wins and within
losses. Only 45 of 800 random positions were contested at all: most simulated battles are settled early, largely
by the teams.

**An engine's evaluation.** A chess engine has an evaluation (how good a position is) and a search (which moves
lead to the best positions). `pogo.evaluation.Evaluator` is the first: from what one player can see (the same 45
numbers the trained bot reads), the expected decisiveness of the battle from here. `pogo.evaluation.material` is
the plain count to beat, as a chess player counts pieces: health and shields on each side, unseen Pokémon taken as
untouched. `scripts/train_eval.py` trains the evaluation on positions from simulated battles (the trained bot
against the crowd and against itself) and tests it on battles kept back: 777,318 positions from 39,997 battles,
3,999 battles held out (`runs/eval/eval.npz`, `runs/eval/report.json`, `runs/eval_train.out`).

| Points to the eventual winner | Early (first third) | Middle | Late | All |
|---|---|---|---|---|
| Learned evaluation | 65.6% | 74.0% | 86.8% | 74.5% |
| Material count | 58.0% | 68.5% | 80.6% | 68.0% |

Off by 0.188 from the final decisiveness on average, against 0.259 for the count. It is an expected
decisiveness, not a win chance: positions rated 0.6 to 0.7 were won 72% of the time, 0.7 to 0.8 91%, 0.4 to 0.5
36%. The browser game uses it for its review when the file is there.

How the rest of a chess engine maps onto this game:

| Chess engine | Here | State |
|---|---|---|
| Evaluation | `Evaluator` (learned) or `material` | built (above) |
| Search | `pogo.engine.Engine`: at each judgement call (throw or hold, swap or stay, which replacement), play each option a few turns ahead in several imagined battles (their unseen Pokémon drawn at random, the same dice for every option) and judge where it ends up with the evaluation; take the best if it beats the trained bot's pick by `edge`. Both players choose at once, so a fuller search would treat a choice as a small game to solve (`solve_2x2` exists) rather than a minimax | first version built; see below |
| Endgame tablebase | `pogo/endgame.py`, Marco's exact solver for at most two Pokémon a side | built; too slow for most two-against-two |
| Opening book | the lead and team choice | the team searches |
| Game review | the evaluation over a battle, and the moments it swung | in the browser game's end screen |

The difference from chess that matters most: a decision has to be made within a fraction of a 500 ms turn, so
the search must be shallow and the evaluation cheap, which is why the evaluation is a small network.

### The first search (2026-10-13)

`scripts/engine_trial.py`: the engine against the trained bot (`runs/general-decide/q.npz`, margin 0.02), head to
head on random teams with every pair played both ways, and both against the usual crowd on the same battles.
Judged by the learned evaluation unless said otherwise; 20 turns ahead, 6 imagined battles per option.

| Variant (seed 51 for the first two, 61 for the rest) | Head to head | Against the crowd, engine minus bot | Decisions changed |
|---|---|---|---|
| Quick players inside the look-ahead, 2,000 pairings | 37.0% ± 1.4 | -8.0 ± 2.6 | 33% |
| The same judged by the plain count | 35.3% ± 1.3 | -9.3 ± 2.6 | 31% |
| Quick players, override only when ahead by 0.05 (500) | 44.2% ± 2.6 | -2.1 ± 4.7 | 13% |
| Quick players, switches and replacements only (500) | 42.9% ± 2.6 | -1.6 ± 4.7 | 43% of those |
| Quick players, 40 turns ahead (500) | 36.7% ± 2.6 | -8.4 ± 5.3 | 31% |
| **The trained bot playing both sides inside the look-ahead**, 4 per option, edge 0.03 (500) | **65.0% ± 2.5** | **+6.8 ± 4.8** | 15% |

With cheap players inside, the look-ahead imagines a different game from the one being played, and the more the
engine trusts it the worse it does. With the trained bot itself playing both sides inside, it is the strongest
player measured in this project so far, by a wide margin. Two cautions before believing the size: it is the best of
four variants on 500 pairings, and head to head the engine imagines its opponent as the trained bot, which is
exactly what it is playing, so the head-to-head figure is flattered; the crowd figure is the fairer one and has a
wide margin.

**Confirmed on fresh battles** (seed 71, 800 pairings, the settings fixed beforehand; `runs/engine_D_confirm.out`):
head to head **65.0% ± 1.9** against the trained bot; against the crowd 71.4% ± 3.1 against 66.1% ± 3.3 for the
trained bot on the same battles, **+5.4 ± 3.7 points**. The crowd is not what the engine imagines its opponents
to be, so that is the fairer figure, and it is now clear of its margin. It changed the trained bot's pick at 15%
of the 54,059 decisions it searched.

**Does it punish?** (the owner's complaint that the bot does not punish with harder counters;
`scripts/punish_count.py 300`, `runs/punish_engine.out`). Moments when the opponent has just switched and our
switch is ready, 300 battles against the crowd each:

| Matchup now, and the best counter on our bench | Trained bot brings a counter | Engine brings a counter |
|---|---|---|
| Losing, a counter 0.3 or more better | 70 of 82 (85%) | 74 of 85 (87%) |
| Losing, a counter less than 0.3 better | 37 of 80 (46%) | 48 of 78 (62%) |
| Even or ahead, a counter 0.3 or more better | 8 of 11 | 10 of 11 |
| Ahead, a counter less than 0.3 better | 18 of 89 (20%) | 29 of 101 (29%) |

The engine punishes more often, most of all when only a little behind, in the direction the owner described; the
hand-written version of the same idea (`punish_gain`, above) gained nothing, the search does it with judgement.

Looking 40 turns ahead instead of 20, with the trained bot inside (seed 81, 300 pairings,
`runs/engine_E_bot_h40.out`): 66.2% ± 3.4 head to head, -1.8 ± 6.3 against the crowd. No better; 20 stays.

Cost: a searched decision takes a median of 45 ms, 141 ms at the 90th percentile and 273 ms at worst (one core,
shared), against 10 ms budgeted for a decision in live play. Fine inside the browser game's 0.75 s turns:
`python3 scripts/play.py --bot engine`.


### What the engine does differently, and whether it makes rules (2026-10-13)

`scripts/engine_habits.py` (2,000 battles against the crowd, seed 91, `runs/engine_habits.json`, reports in
`runs/engine_habits.out`, `runs/engine_habits_spots.out`, `runs/engine_habits_rules.out`): the engine as
confirmed above, writing down every decision it searched (45,856) with the trained bot's pick, its own, and the
look-ahead's worth of each option. It overruled the bot at 14% of throws, 16% of swaps and 22% of replacements.
Where it overrules most often, by one or two simple conditions:

| The bot's pick | Engine's change | Most often when | Rate there |
|---|---|---|---|
| Stay in | Switch to the bench's better matchup | Losing, and they have a charged move ready / their switch is locked | 31% / 28% |
| Hold the charged move | Throw the cheaper one | They have a move ready and we would faint within two of their fast moves; or losing with a move of theirs ready | 21% / 18% |
| Throw the cheaper move | Hold and keep fast-moving | They have both shields and we are winning the matchup | 21% |
| After a faint, bring the better matchup | Bring the other one | Their Pokémon is under a third of its health | 28% |

So the tendencies are: get out of a losing matchup before their charged move lands, throw rather than faint holding
energy, don't throw cheap moves into two shields while winning, and don't spend the best answer on a Pokémon that
is nearly finished. None of them is a habit: even in the best spot the engine overrules less than a third of the
time.

**As rules they gain nothing.** Scored by the look-ahead's own worths, "in this situation always do X" (every
choice X, under every one or two of 24 simple conditions, 300 or more decisions each) never beats the bot's pick:
the best of each kind is within its margin of zero or below it (the best, always staying in at a swap, is
+0.0006 ± 0.0010; always switching to the better matchup when one is 0.3 better and their switch is locked,
-0.0008 ± 0.0053). Rules with up to three numeric thresholds (energy over each move's cost, their energy, fast
moves to a knockout each way, outlooks, Pokémon left, turn), searched for on half the decisions and scored on the
other half, do no better: what looks best on the first half is at or below zero on the second. This agrees with
the hand-written owner rules above (`rush`, `known_team`, `punish_gain`), none of which gained: the trained bot
already plays the simple strategies about as well as simple conditions allow, and what the engine adds depends
on the particular position. The way to keep it is to teach the bot the engine's worths (below), not more rules.

Real players' decisions (`runs/real_decisions/`, above) say the same at much smaller size: where the bot wanted
to switch out but the player held and kept fast-moving, the player did better (14 of 18 clear cases; bot -5.6 ±
5.2 points over 34), the only direction close to a margin, and too small to build on yet.

### Teaching the bot the engine's judgement (distillation): worse (2026-10-13)

If the engine's edge is not in rules, perhaps a network can learn it: `scripts/distill.py collect` (6,000 battles,
seed 301, the engine against training's crowd on teams half from the list) wrote down, at 136,208 throw, swap and
replacement decisions, what the bot's networks see and the look-ahead's worth of every option;
`scripts/distill.py fit` refitted the throw, swap and replacement networks to those worths, starting from the
trained bot's (`runs/distill/q.npz`) or from scratch. On held-out decisions the refitted swap network follows the
engine's preferences far better than the trained bot's does (correlation 0.48 against 0.21); throws and
replacements no better (0.32 against 0.32, 0.28 against 0.27). In battles it is worse
(`runs/compare_distill.out`, seed 7301, 4,000 battles against the crowd, the same for all; head to head against
the trained bot, every pair both ways):

| Model | Against the crowd, minus the trained bot | Head to head against the trained bot |
|---|---|---|
| The trained bot with the distilled swap network | -3.5 ± 1.1 | 46.5% ± 1.1 |
| ... and the distilled replacement network | -3.4 ± 1.1 | 46.7% ± 1.1 |
| All three distilled (margin 0.02) | -3.5 ± 1.4 | 45.7% ± 1.2 |
| All three distilled, margin 0 | -6.7 ± 1.6 | 43.8% ± 1.3 |

The look-ahead's worths are short-sighted: it plays 20 turns (10 seconds) and judges the position there, while a
swap mostly pays later; the trained bot's networks learned from whole battles played out. The engine does well
because it leaves the trained bot's pick only when its search is clearly convinced (edge 0.03), not because its
worths are better values. Not adopted; the engine stays the strongest player and the trained bot the fast one.

### Thinking while the fast move plays out (2026-10-13, the owner's idea)

The 10 ms for a decision in the latency table is a target from when the brain was the trained bot alone, not a
rule of the game. What the game asks is that the next action be ready when the current fast move ends, and while
a fast move plays out there is nothing to choose. `scripts/engine_timing.py` (600 battles against the crowd, seed
401, `runs/engine_timing.out`) has the engine predict, each time it starts a fast move, the position when that move
ends, from what it can see and assuming the opponent keeps fast-moving; at its next decision the prediction is
checked, and every searched decision is timed (one cloud core each, three at once).

| What came before the searched decision (13,377) | Share | Search time, median / 90th / worst (ms) | Ready in time |
|---|---|---|---|
| Our fast move of 1 turn, predicted exactly | 28% | 45 / 114 / 395 | 99.9% within 300 ms |
| Our fast move of 2 turns, predicted exactly | 27% | 46 / 114 / 337 | 100% within 800 ms |
| Our fast move of 3 or 4 turns, predicted exactly | 9% | 45 / 118 / 273 | 100% within 1.3 s |
| A charged move (theirs, or ours) | 19% | 41 / 98 / 258 | the game pauses for it |
| A faint, or choosing the replacement | 10% | 30 / 57 / 173 | an animation, and a choice of replacement |
| The start of the battle | 4% | 76 / 108 / 174 | the countdown |
| They switched during our fast move | 3% | 42 / 103 / 209 | whatever is left of our fast move |

"Ready in time" is the fast move's length at 500 ms a turn, less 200 ms for seeing the screen and for the tap.
The prediction never failed except for something the player sees happen (a charged move, a switch, a faint): when
the opponent only fast-moves, the position at the end of our fast move is known exactly. So the engine as it is
fits live play if it starts searching when its fast move starts: 64% of its searches are then done well ahead
of time, almost all of the rest follow a pause, and the few that cannot finish (their switch in the last turn of
our fast move, or the slowest 0.1% after a one-turn move) can fall back on the trained bot's own pick, which takes
about a millisecond.

## Is the network too small? No (2026-10-14)

The last two long training runs gave models no better than the current one, so before more of the same: the
bot's networks have 48 hidden units each. Refitted at 48, 128 and 256 on the same 772,000 saved decisions
(`runs/general-margin/examples.npz`, nine tenths fitted, one tenth held out; `runs/capacity/h*.out`), the
held-out squared error barely moves (throw 0.0539, 0.0532, 0.0530; replacement 0.0585, 0.0575, 0.0575;
shield, swap and mid-matchup swap the same to the third digit). In battles, against the current model on the
same 4,000 (`runs/compare_capacity.out`, seed 61061): -2.8 ± 1.4, -3.3 ± 1.5 and -2.5 ± 1.4 points against the
crowd, 47.3%, 45.9% and 45.9% (± 1.3) head to head. Size makes no difference; the noise of a single play-out
per option is what limits how well the networks can predict, and 48 stays.

## Does the bot need to see their other Pokémon? Predicts better, plays the same (2026-10-14)

The bot's inputs (`describe()`) cover the matchup in play: how each of ours does against their Pokémon in
front of us, and nothing about their Pokémon already seen and off the field. The engine sees those, and its
clearest habit (bring the other Pokémon when theirs is nearly finished) is about them. `pogo.learner.known_foes`
adds them as twelve optional inputs: for each of their seen Pokémon off the field (up to two), whether it is
up, its health and energy, and the saved one-on-one of each of ours against it (`data/matchups.json`). A
model trained with `decide.py --wide` takes them; older models are unaffected.

The test holds everything else fixed. The current bot piloted all the training battles (three 40-minute
rounds, three workers, its model put back before each; `runs/wide-collect-*.out`), with the new inputs
recorded: 14,000 battles a round, 564,000 decisions in all (no mid-matchup swaps). Two networks were fitted
on exactly those examples, one with the new inputs and one without (`scripts/fit_examples.py`, same seed;
`runs/wide-fit*.out`).

| Held-out squared error (one tenth) | Shield | Throw | Swap | Replacement |
|---|---|---|---|---|
| Without the new inputs | 0.1765 | 0.1660 | 0.1796 | 0.1783 |
| With them | 0.1637 | 0.1515 | 0.1697 | 0.1606 |

They predict the result much better (6 to 10% less error, against under 2% for a network five times the
size). In battles (`runs/compare_wide.out`, seed 71071, 4,000 against the crowd, then every pair of teams
both ways):

| Model, margin 0.02 | Against the crowd | Against the one without, same battles | Head to head against it |
|---|---|---|---|
| Fitted without the new inputs | 64.2% ± 1.5 | | |
| Fitted with them | 64.2% ± 1.5 | +0.0 ± 1.3 | 50.3% ± 1.2 |
| The current model | 65.5% ± 1.5 | +1.4 ± 1.4 | 51.3% ± 1.2 |

No difference. What the new inputs predict is who is winning the battle, which is the same for every
option at a decision; they do not change which option is better. Not adopted (the option stays, off unless
`--wide`). With the size test above and the two long runs, three ways of improving the trained bot by
training (more examples, a bigger network, more information) leave it where it is. A side result: 564,000
decisions played out by the current bot give a model level with it (head to head 48.7% ± 1.2 for the refit),
from far fewer examples than it was trained on.

## Learning from both sides of the bot's battles against itself: better head to head (2026-10-14, the owner's idea)

In every training battle so far only our side's decisions became examples; the opponent's were thrown away,
even when the opponent was a copy of the bot. `decide.py --both-sides SHARE` makes that share of battles the
learner against itself and plays out and keeps both players' decisions, each scored from its own side
(`play_out(..., side=1)`; `tests/test_both_sides.py` checks that replaying either player's real choice gives
the real result).

The test copies the known-foes run above in everything else (the current bot piloting every round, its model
put back before each; three 40-minute rounds on three workers; teams half from the list; half the crowd on the
current model; no mid-matchup swaps; then `scripts/fit_examples.py`), with `--both-sides 0.5`
(`runs/both-collect-*.out`). Battles of the bot against itself are slower, but each teaches two players:
8,500 to 8,800 battles a round against 13,300 to 14,500, and 512,000 decisions in all against 564,000. The
control is that run's network without the extra inputs (`runs/wide/q_narrow.npz`), made the same way from
crowd battles only.

| Model, margin 0.02 | Seed 81081: against the control, crowd / head to head | Seed 91091: against the current model, crowd / head to head |
|---|---|---|
| Control (crowd battles only) | | -1.0 ± 1.4 / 49.3% ± 1.2 |
| Half its battles against itself, both sides kept | -1.1 ± 1.5 / **52.8% ± 1.3** | -1.3 ± 1.4 / 51.0% ± 1.3 |
| Current model | +1.8 ± 1.4 / 51.8% ± 1.2 | |

(`runs/compare_both.out`, `runs/compare_both_confirm.out`.) Learning from both sides gains about two points head
to head at the same cost, clear of the margin on the first seed and in the same direction on the second, and
costs nothing measurable against the crowd. From 40% of the current model's examples it is level with it: not
yet the replacement the rule asks for (ahead against the crowd and above 50% head to head, both beyond the
margin), but the first change since task 19 that moves head to head play, which is the test against opponents
as good as the bot. The next step is the full-size version: more rounds, with the newest model on both sides.

**Full size (`runs/both-full`, found unrecorded on 17 October).** The same with `--both-sides`, half the opponents
using the learned model and 12 workers: 409k shield, 136k throw, 271k swap and 63k replacement examples in one
round. On the same 4,000 battles (`runs/compare_both_full.out`): +8.4 ± 1.6 over the Planner against the current
model's +8.8 ± 1.6 (−0.4 ± 1.5 between them), and 52.6% ± 1.2 head to head against the current model. Better head
to head, level against the crowd: by the acceptance rule (ahead against the crowd beyond the margin, and above 50%
head to head) it is not adopted. Whether head to head alone should decide is the owner's call: it is the test
against an opponent as good as ours.

## Learning from the bot's own losses (task 26, 2026-10-16, the owner's idea): no change survives

`scripts/losses.py` replays every decision of every lost battle of the bot against itself with each other legal
choice (the opponent becomes a different variation of the bot after the changed decision). Checked first:
with the opponent left unvaried, replaying the choice actually made repeats the battle's result for all 553
decisions of 8 battles, wins and losses (`tests/test_losses.py`, `win_chance(..., vary=False)`).

**The losses** (`python3 scripts/losses.py --battles 1200 --workers 3 --confirm 48 --seed 3`, `runs/losses.out`;
`--confirm` doubled from 24 to cut false positives): side 0 lost 598 of 1,200; 25,988 decisions were tried
every other way. In 432 of the 598 (72%) one different decision would have won (the alternative won at least
half its 48 fresh play-outs where ours won under a quarter), 4.5 such decisions per battle that had one.
The earliest such decision in each battle:

| What we did -> what would have won | Share | Typical situation |
|---|---|---|
| fast move -> switch | 48% | first minute 72%, all three each 67%, losing the matchup 56%; 190 of all 1,108 at turns 0-9 |
| shield decision the other way | 15% | split evenly: 86 "no shield -> shield", 79 "shield -> no shield" |
| fast move -> charged move | 12% | our move ready (100%), their switch locked 70% |
| everything else | 25% | none above 6% |

**On balance, counting wins** (`scripts/losses_balance.py --kinds "fast->switch,fast->throw,no shield->shield,shield->no shield"
--battles 600 --workers 3 --confirm 32 --per-battle 2 --seed 11`, `runs/losses_balance.out`): fresh battles,
won and lost alike; at up to two sampled moments per battle where the change was possible, the best
alternative of that kind against the bot's own choice on the same 32 play-outs. Change in win chance:

| Change | All battles | Battles won | Battles lost |
|---|---|---|---|
| fast move -> switch (1,188 moments) | **−2.5 ± 1.8** | −14.0 ± 2.6 | +7.8 ± 2.2 |
| fast move -> charged move (1,184) | **−1.8 ± 1.2** | −7.6 ± 2.0 | +3.3 ± 1.4 |
| no shield -> shield (1,035) | **−6.3 ± 1.7** | −18.2 ± 2.5 | +3.9 ± 2.0 |
| shield -> no shield (1,121) | **−10.3 ± 2.0** | −25.5 ± 3.3 | +2.8 ± 1.9 |

Every change helps in the battles that were lost and costs more in the ones that were won, so none helps
on balance. No situation in the split is clearly positive: the best are fast -> switch with all three each
(+1.2 ± 2.6) and fast -> charged move in the first minute (+0.4 ± 2.1). Switching at the lead (turns 0-4) is
+0.9 ± 5.4 (151 moments); only badly lost leads (matchup below −0.3, a cut chosen after looking) reach
+9.3 ± 12.5, on 30 moments. The 72% above is mostly hindsight: looking only at losses picks the moments
where the dice later went against us.

**The swap thresholds, as the one change the losses point at** (`rule_trial.py --battles 4000 --seed 2601`,
`runs/task26_swap_thresholds.out`). The Planner leaves a new matchup only below `bad_matchup` (−0.2) and for a
bench Pokémon `switch_margin` (0.35) better; neither had been tuned. Switching more readily gains nothing:

| Setting | Head to head | Against the crowd |
|---|---|---|
| `switch_margin=0.25` | 50.1% ± 0.7 | −0.0 ± 0.5 |
| `switch_margin=0.15` | 50.3% ± 0.8 | −0.1 ± 0.7 |
| `bad_matchup=-0.1` | 50.1% ± 0.8 | −0.2 ± 0.4 |
| `bad_matchup=-0.1, switch_margin=0.25` | 50.2% ± 0.9 | −0.1 ± 0.7 |

None was close enough to rerun on a fresh seed. Defaults unchanged. Not done: the optional engine-as-side-0
comparison (step 5), and a weighted retrain on these positions, which the balance numbers give no reason to
expect to help.

## The engine in real time (task 23, 2026-10-17)

`pogo/realtime.py`: `RealTime` is the engine with a deadline on every search, set by what came before the
decision (the owner's point: a fast move of n turns leaves n half-seconds, and charged moves stop the game for
seconds). Budgets: a predicted decision gets the fast move's turns at 500 ms less 200 ms for seeing and tapping
(Incinerate: 2.3 s); after a charged move 2 s; after a faint or for a replacement 1 s; the start 2 s; unforeseen
(their switch, our switch, a failed prediction) 300 ms. The pause lengths are cautious guesses, not measured.
The search (`pogo/engine.py`) now goes round by round, one imagined battle per option, and decides on the
complete rounds when time is up; with none it plays the trained bot's pick. Without a deadline it plays exactly
as before (`tests/test_realtime.py`: same battle logs).

`python3 scripts/realtime_trial.py --timing 300` (`runs/realtime_timing.out`, CPU time on the owner's Mac):

| | Default budgets | Every budget a fifth as long |
|---|---|---|
| Searched decisions | 6,736 | 6,690 |
| Search time, median / 99th percentile / worst | 18 / 69 / 126 ms | 18 / 62 / 129 ms |
| Cut short by the deadline | 0.0% | 0.8% |
| No complete round (trained bot's pick) | 0.0% | 0.0% |
| Decisions with any wait when due | 2.9% (unforeseen only; worst 53 ms) | 3.2% |
| Predicted from the start of our fast move | 66% | 66% |

So on this machine the real-time engine makes the unhurried engine's choices: nothing is cut, and 97% of
decisions are ready before they are due. The head-to-head check against the unhurried engine
(`--pairings 600 --crowd 1000`, hours) only matters on a slower machine or with tighter budgets; it has not
been run. Searches here are about 2.5 times faster than the 13 October measurement (45 ms median), which used
wall-clock time on another machine. `scripts/play.py --bot engine` now plays `RealTime` on the wall clock, with
no search allowed longer than one of the game's turns, and saves every search's timing with the game.

## Learning from games against a person, and the line-up's win chance (2026-10-17)

`scripts/play.py` now saves each game's seeds and exact teams, so `python3 scripts/losses.py --played` can replay
every saved game the bot lost and try each of its decisions every other way, as task 26 did for the bot against
itself; after a changed decision the person is played by variations of the bot. Checked: a game saved as the
browser saves it replays exactly (`tests/test_losses.py`), including a headless game against the real-time
engine. Games saved before today have no seeds and cannot be replayed.

`pogo/lineup.py` / `python3 scripts/lineup.py A B C --vs D E F`: the chance that one team beats another, both
known, with both sides played by the bot with shifted habits; also with each of our Pokémon leading. Example:
Melmetal / Altaria / Jellicent against Corviknight / Tinkaton / Mandibuzz, 300 battles: Melmetal leading 38% ± 5,
Altaria 66% ± 5, Jellicent 81% ± 4. The browser game shows this number for the two teams after each battle and
saves it.

**Teams that should beat the owner's** (`python3 scripts/counters.py`, 2026-10-17): 543 candidates (the good-team
list with each lead, and 300 random threes from the top 50) scored against Melmetal / Altaria / Jellicent as the
browser game builds it, Melmetal leading, both sides the bot with shifted habits; 25 survivors on 300 fresh
battles each won 88 to 99% (Corviknight / Mandibuzz / Thievul 99%). Saved to
`data/counters/melmetal-altaria-jellicent.json`; `python3 scripts/play.py --counters` draws the bot's team from it.
At the owner's request the saved list is now the band below that (`--least 0.7 --most 0.9`, stages keeping the
teams nearest 80%): 30 teams winning 77 to 89% on 300 fresh battles each, for example Tinkaton / Thievul /
Galarian Corsola 89%, Corviknight / Guzzlord / Altaria 85%, Quagsire / Azumarill / Thievul 80%. The owner's own
three with Jellicent leading are in it at 78%.
The lead decides much of it: against Annihilape / Mandibuzz / Tinkaton the owner's three win 8% ± 4 with Melmetal
leading and 87% ± 5 with Altaria (`scripts/lineup.py`). Lopsided numbers like 0% between equal players say the
bot, on the losing side, rarely finds a way back; games against the owner will show whether a person does.

## Holes by lead, and a fast move before swapping (2026-10-17, the owner's points)

**Averages hide holes.** The owner: a team that scores well on average can still have no answer to a lead, for
example Shadow Empoleon / Jellicent / Stunfisk into a Charjabug lead. `scripts/lead_holes.py` plays a team against
each of the top 50 as the opposing lead (random back two from the top 50, both sides the bot with shifted habits,
60 battles per lead; `runs/lead_holes_1.out`):

| Team (lead first) | Average over leads | Leads it loses to | Worst leads |
|---|---|---|---|
| Shadow Annihilape / Guzzlord / Stunfisk | 63% | 9 of 50 | Galarian Corsola 20%, Shadow Sableye 27%, Sableye 34% |
| Melmetal / Altaria / Jellicent | 56% | 16 | Stunfisk 13%, Shadow Charjabug 18%, Annihilape 30% |
| Clefable / Hippowdon / Lapras | 51% | 20 | Corviknight 7%, Shadow Corviknight 7%, Shadow Ninetales 17% |
| Shadow Empoleon / Jellicent / Stunfisk | 50% | 21 | Thievul 10%, Charjabug 15%, Marowak 18% |
| Ninetales / Melmetal / Jellicent | 49% | 30 | Shadow Hydreigon 22%, Mantine 27%, Guzzlord 27% |

The team that looked most robust against the two opposing lists (Shadow Empoleon / Jellicent / Stunfisk, about
62% against both) is only level against random teams by lead, with the Charjabug hole the owner named. Which team
is best still depends on what the opponents bring; a lead-by-lead table shows where a team breaks.

**A fast move before swapping.** The owner: players, above all with fast moves of two turns or more, often use one
fast move in a new matchup before swapping out. `Planner(fast_first=p)` does that with chance p per matchup (fast
moves of 2+ turns only). For our own side it does not help (`rule_trial.py --seed 2701`, `runs/fast_first_trial.out`):
always 48.9% ± 1.0 head to head, half the time 49.1% ± 0.8; off by default. As a habit of opponents it is now in
the crowd (`varied_settings`: a third never, a third half the time, a third always), which changes the crowd for
every later measurement. Against it the trained bot is +10.5 ± 1.6 over the Planner (65.8% against 55.3%, 4,000
battles, `runs/compare_fast_first_crowd.out`), as before.

## On the owner's website (2026-10-17)

`python3 scripts/build_pvpbot_site.py FOLDER` builds `solaceonx.github.io/pokemon_go_pvpbot/` (pushed to the
website repo `Solaceonx/solaceonx.github.io`, folder `pokemon_go_pvpbot/`). Everything runs in the visitor's
browser with Pyodide (Python in WebAssembly, with numpy): `bundle.zip` holds the simulator's modules, the game data,
the trained model and the engine's evaluation (about 0.5 MB; Pyodide and numpy add about 15 MB on first visit).

- **Line-up odds** (`index.html`): any two teams, every lead against every lead, 120 battles a cell; about 10 s on
  the owner's Mac (three background workers), same numbers as `scripts/lineup_site.py`.
- **Battle the bot** (`play.html`): the battle screen of `scripts/play.py` driven by `play_api.py` one turn at a
  time; a shield or replacement prompt winds the turn back and plays it again with the answer. Opponents: random
  from the top 50, a top team from `data/teams.json`, or custom; the trained bot or the engine (`RealTime`, no search
  longer than a turn less 100 ms). In the browser the engine's searches took 16 ms median, 218 ms worst over three
  games on the owner's Mac, inside its limit; a slower device falls back to the trained bot's pick more often.
  After each game: the line-up's win chance, the engine's evaluation over the battle with its biggest swings, and a
  notes box. Games and notes stay in that browser; "Download my games" gives a file that
  `python3 scripts/import_played.py FILE` puts in `games/played/` for `scripts/losses.py --played`. Checked: a game
  against the trained bot played on the page replays exactly; an engine game replays exactly only if no search was
  cut (each game saves its search times as `bot_searches`).

## Six against six: which three to bring (2026-10-17, the owner's question)

The Play! Pokémon GO format: both players register six and see each other's six; before each game each picks three
in secret, the first leading. That is a simultaneous zero-sum game with 60 choices a side. `scripts/sixes.py`
(`pogo/sixes.py`) simulates every choice against every choice (both sides the trained bot with shifted habits, the
same battles down each column) and solves the table (regret matching+, averaged); the mix is also found on half the
battles and scored on the other half. Each game is treated on its own: choices that depend on earlier games of a
set are not modelled.

First case (40 battles for each of 3,600 pairs, 9 minutes on three cores, `runs/sixes_1.out`): the owner's
Melmetal / Altaria / Jellicent / Stunfisk / Shadow Quagsire / Umbreon (their IVs) against Tinkaton / Shadow Annihilape /
Corviknight / Mandibuzz / Carbink / Thievul, the Pokémon most common in `data/teams.json`.

- When both sides choose well the owner wins 40% (38% when the mix is scored on battles it was not found on).
- The opponent's right answer is nearly always the Dark core: Mandibuzz, Thievul and Shadow Annihilape together in
  75% of their mix, mostly Mandibuzz or Thievul leading.
- The owner's mix brings Melmetal 97% and Stunfisk 92% of the time, Altaria 58%, Umbreon 36%, Jellicent 18%,
  Shadow Quagsire never. Leads: Melmetal 27%, Umbreon 33%, Stunfisk 23%, Jellicent 18%.
- Best single choice without mixing: Stunfisk leading, Melmetal and Altaria behind: 40% against their mix, 22% at worst.
- The choice that is best on average against a random three of theirs (Stunfisk / Melmetal / Jellicent, 72% on
  average) gets only 33% against their right answer: averages over the opponent's choices mislead when the opponent
  chooses too.

So with open sheets the six decides much: one of the owner's six is never worth bringing here, and the six has no good
answer to a Dark core. Choosing which six to register needs these tables for many sixes against many sixes; one
table costs 144,000 battles, so that search is for a bigger machine or a cache of three-against-three results.

## More engine samples and longer look-ahead (task 27, 2026-10-18): initial runs superseded by cache-isolation fix

**Superseded selection data; not valid for adoption.** The prescribed `time-grid` command ran with seven workers,
seed 2701, 1,000 head-to-head team pairings (each both ways), 1,000 crowd battles and 500 PvPoke AI battles per
setting. Baseline: 4 samples, 20 turns, edge 0.03, bot rollouts, margin 0.02. Every score and paired difference
has its 95% margin; timing columns are observed CPU-time quantiles, not confidence intervals. No reader probe
was requested for this task. The code, models and data hashed before the run remained unchanged throughout it.

The baseline scored 69.5% ± 2.8 against the crowd and 76.7% ± 3.7 against PvPoke's AI. Parentheses below are paired
percentage-point differences from that baseline; all grid settings use edge 0.03.

| Samples / horizon | Head to head | Crowd score (difference) | PvPoke score (difference) | Search CPU ms, median / p99 / maximum |
|---|---|---|---|---|
| 8 / 20 | 51.8% ± 1.7 | 72.1% ± 2.8 (+2.6 ± 2.9) | 79.0% ± 3.6 (+2.3 ± 3.6) | 57 / 208 / 488 |
| 16 / 20 | 52.2% ± 1.7 | 73.2% ± 2.7 (+3.8 ± 2.8) | 79.2% ± 3.6 (+2.5 ± 3.5) | 123 / 455 / 1193 |
| 32 / 20 | 53.0% ± 1.7 | 75.0% ± 2.7 (+5.6 ± 2.8) | 78.0% ± 3.6 (+1.3 ± 3.5) | 250 / 921 / 2403 |
| 4 / 30 | 48.7% ± 1.9 | 67.6% ± 2.9 (-1.8 ± 3.1) | 71.6% ± 4.0 (-5.1 ± 4.0) | 42 / 153 / 362 |
| 4 / 40 | 48.4% ± 1.9 | 65.6% ± 2.9 (-3.8 ± 3.2) | 71.9% ± 3.9 (-4.8 ± 4.4) | 48 / 185 / 395 |
| 16 / 30 | 50.9% ± 1.8 | 73.2% ± 2.7 (+3.8 ± 3.1) | 77.4% ± 3.7 (+0.7 ± 3.8) | 168 / 592 / 1404 |
| 16 / 40 | 55.0% ± 1.9 | 71.8% ± 2.8 (+2.4 ± 3.2) | 75.9% ± 3.7 (-0.8 ± 4.1) | 190 / 728 / 1543 |
| 32 / 40 | 54.1% ± 1.8 | 74.5% ± 2.7 (+5.1 ± 3.1) | 77.8% ± 3.6 (+1.1 ± 4.0) | 384 / 1453 / 3526 |

The highest eligible head-to-head score selected **16 samples / 40 turns**. Longer horizons with only four
samples did not help: both lost ground against PvPoke beyond the margin, and 40 turns also lost ground against
the crowd. More samples at 20 turns helped in these selection battles, but 32 samples / 40 turns scored lower against the baseline
than 16 / 40 did; those two settings were not compared directly. Grid times use the search rows retained by `engine_versus.py`; the separate
`realtime_trial.py --timing` checks will measure the deadline-limited player before any live recommendation.

**The repeatability check failed before confirmation.** Repeating 16 / 40 / edge 0.03 on seed 2701 changed
223 of 1,000 head-to-head pair results, 44 of 1,000 crowd results and 20 of 500 PvPoke results. Even the
unchanged baseline changed 39 of 1,000 crowd results and 23 of 500 PvPoke results. Source/model hashes were
unchanged. `engine_versus.py` shared one mutable `Evaluator` across players and worker jobs; its cached
matchup features are keyed by team slot and opposing species, not our team's identity. Evaluating another
team first changed three features for the same subsequent position in a small reproducer. Thus worker
assignment and preceding searches could alter the supposedly paired games.

The queue was stopped before opening reserved confirmation seed **272701**. The partial edge results are
retained in [the interrupted-run summary](../runs/task27-time-edge-interrupted-summary.out). These original
tables describe what printed, but do not establish a reliable setting ranking or a gain. Corrected runs
will use new tags so that their checkpoints cannot mix cache-sharing policies.

The fix shares only model weights, with a fresh evaluation cache for each player in each battle. It applies
to the comparison and timing harnesses and isolates the local/website bot from the human-side review cache.
It does not change the model, the simulator, or a player's existing within-game look-ahead. The regression
check in `tests/test_engine_versus.py` covers interference from another player and from a preceding battle.
After this fix, the direct full suite ran **223 tests: OK, seven skipped**, and the reference check printed
**108 of 108 PvPoke battles reproduced exactly**. A seven-worker repeat with chunk sizes 1 and 5 matched every score exactly (10 head-to-head pairings,
10 crowd and 5 PvPoke battles per candidate, plus baseline fields); these are reproducibility checks, not
strength estimates. Logs: [first](../runs/task27-repeat-a.out), [second](../runs/task27-repeat-b.out),
[exact comparison](../runs/task27-repeat-check.out). The harness rejects checkpoints without the new
cache-policy metadata.

The corrected run is underway with tag `time-grid-isolated`; it repeats the full prescribed grid. It will
then run `time-edge-isolated`, confirm only the selected setting on untouched seed 272701 with tag
`time-confirm-isolated-seed272701` (2,000 pairings, 2,000 crowd, 1,000 PvPoke), and measure baseline/candidate
timing on 300 battles using CPU and wall clocks, including the 400 ms website cap.
[Corrected input hashes](../runs/task27-isolated-provenance.json) and
[exact launched commands](../runs/task27-isolated-pipeline-commands.json) are saved.
No new sample/horizon/edge defaults have been adopted.

Outputs: [grid](../runs/task27-time-grid.out), [resumable scores](../runs/engine_versus/time-grid.json),
[selection](../runs/task27-time-grid-selection.json), [input hashes and selection rule](../runs/task27-provenance.json).
All long jobs request `nice -n 10`; the sandbox refuses further lowering and the workers retain inherited
`nice=15`. NumPy threads are limited to one per worker, with at most seven workers in this task.

Before repository edits, the PvPoke reference check reproduced **108 of 108** battles exactly. The initial
unit command hit two sandbox `os.nice(10)` errors; a temporary launcher retaining the already-low priority
then ran **222 tests: OK, seven skipped**. `scripts/losses.py` now uses the existing `low_priority()` helper
so the suite can run directly. `scripts/realtime_trial.py` now accepts samples, horizon, edge, clock
and a search cap instead of measuring only the fixed old settings. Neither script was imported by the
running grid. The final acceptance result remains pending.

### Task 27, corrected runs (after the cache-isolation fix): 32 imagined battles adopted

The grid again, with isolated caches (`engine_versus.py --tag time-grid-isolated --workers 7 --pairings 1000 --crowd 1000
--pvpoke 500 --seed 2701`, `runs/task27-time-grid-isolated.out`; interrupted once when the agent running it stopped, resumed
by tag). Baseline: 4 imagined battles, 20 turns, edge 0.03. Differences are paired, in points:

| Setting | Head to head | Crowd | PvPoke | Search ms, median / 99th / worst |
|---|---|---|---|---|
| samples 8 | — (see file) | | | 58 / 212 / 526 |
| samples 16 | 51.4% ± 1.7 | +4.6 ± 2.7 | +3.1 ± 3.3 | 116 / 430 / 1,075 |
| **samples 32** | **53.7% ± 1.7** | **+6.6 ± 2.9** | **+3.7 ± 3.3** | 240 / 885 / 2,132 |
| horizon 30 | 48.9% ± 1.9 | −0.2 ± 3.2 | −3.9 ± 4.0 | 41 / 145 / 314 |
| horizon 40 | 50.3% ± 1.9 | −1.8 ± 3.3 | −3.7 ± 4.4 | 46 / 181 / 337 |
| samples 16, horizon 30 | 51.1% ± 1.8 | +5.0 ± 3.1 | +2.3 ± 3.9 | 164 / 581 / 1,375 |
| samples 16, horizon 40 | 53.4% ± 1.8 | +3.5 ± 3.3 | −0.1 ± 4.0 | 193 / 726 / 1,604 |
| samples 32, horizon 40 | 55.0% ± 1.9 | +6.3 ± 3.2 | +1.3 ± 4.0 | 390 / 1,453 / 3,404 |

More imagined battles help; a longer look-ahead does not. 32 / 20 was taken forward over 32 / 40: level head to head
within the margins, better against PvPoke, and its worst search fits the live budgets (300–2,300 ms) where 32 / 40's does
not. Edge at 32 samples (`--tag time-edge-isolated`, same battles): 0.01 49.8% ± 1.8 (+3.0 ± 3.0, +2.1 ± 3.4); 0.03 as above;
0.05 53.5% ± 1.8 (+8.0 ± 2.8, +2.9 ± 3.6). Level, so edge stays 0.03.

**Confirmed on the untouched seed 272701** (`--tag time-confirm-isolated-seed272701 --pairings 2000 --crowd 2000 --pvpoke 1000`,
`runs/task27-time-confirm-isolated.out`): samples 32 against the current engine, **head to head 53.4% ± 1.2; against the crowd
+1.7 ± 1.9; against PvPoke's AI +5.5 ± 2.4** (82.3% against 76.8%). Better head to head beyond the margin and not worse
against either field: adopted.

**In real time** (`realtime_trial.py --timing 300 --samples 32 --seed 2704`, CPU clock, `runs/task27-timing-samples32.out`):
7,069 searched decisions, median 225 ms, 99th percentile 782, worst 1,233; 12.7% cut short by the deadline (41.6% of those
after a one-turn fast move, which has 300 ms), 0.0% left with no complete round; 4.5% of decisions wait at all, worst 302 ms.
Cut short, it still plays as well as unhurried (`realtime_trial.py --pairings 600 --crowd 1000 --samples 32 --seed 2705`,
`runs/task27-realtime-vs-unhurried-samples32.out`): real-time against unhurried 50.7% ± 2.0 head to head; against the crowd
71.5% against 71.4%, +0.1 ± 0.8; real-time minus the trained bot +4.3 ± 2.9. These times are on Marco's Mac (Apple
silicon); the owner's Mac should be checked with the same `--timing` command before relying on the margins.

## Mixed choices and randomisation (task 29, 2026-10-18): no confirmed gain

**Adopt no randomisation setting.** All seven policies were measured, and the best screened candidate,
`mix=1`, failed fresh-seed confirmation: head to head **48.7% ± 1.2**, reader paired change
**+0.8 ± 1.7 points** (95% margins). It loses head to head and has no clear reader improvement.
The task's performance criterion was not met. All mixing and randomisation flags remain off; retain the
cache-isolation correctness fix described below.

**Measurement correction.** The original grid and partial extension results below used a
worker-shared evaluator cache and are retained as diagnostics, **not adoption evidence**. Repeating the
same seeded baseline changed 8 of 500 crowd outcomes, 6 of 250 PvPoke outcomes and 41 of 250 reader pairs.
`Evaluator` keeps `Learner._outlooks` across players and battles, but its key omits our Pokémon. With the
same Melmetal opponent, warming the cache with Altaria makes Stunfisk inherit an outlook of −0.562
instead of its fresh +0.512. This exposes worker-history dependence despite fixed seeds and inputs.
The extension run was stopped before code changes. Its saved baseline is 67.5% ± 4.1 crowd (500),
78.4% ± 5.1 PvPoke (250), 49.8% ± 3.8 reader (250 pairs); its incomplete shield-only control is
50.7% ± 4.4 head to head (140 pairings). No extension candidate completed.

The comparison and timing scripts now give each player a private evaluator cache while sharing the
loaded model weights. Production defaults and models are unchanged. Legacy checkpoints are explicitly
rejected for resumption under the corrected method; new runs use new tags. The suite passes 234 tests
with seven skips and PvPoke remains 108/108. The chunk-size repeatability check passes: all 110 scores
match with chunks of five and one on three workers. With a separate fresh evaluator for each original
and modified player, all 25 compatibility game logs also match exactly. The corrected full grid completed
under tag `mixing-isolated`, with the prescribed counts and reader (28,000 rows / 41,000 battles). All 16
input hashes in `runs/task29-inputs-isolated.json` remain unchanged.

The same cache sharing also affected the browser game factories. `scripts/play.py` and the website's
`play_api.py` now give each new bot and its human-side evaluation graph separate caches, sharing only
model weights. These modules were not imported by the running comparison. Both new integration
regressions pass in the full suite (234 tests, seven skips); PvPoke remains 108/108. An offline website
build passes ZIP and syntax checks for all 15 Python modules, then loads its models and advances two new
games five turns each with independent, reset caches. The smoke script's initial path assertion needed
`/tmp` normalized to `/private/tmp`; no repository code needed changing. No randomisation setting has been adopted.

Completed corrected selection grid (`mixing-isolated`; private evaluator caches; 95% margins):

| Setting | Head to head, 2,000 pairings both ways | Crowd, 2,000 battles | PvPoke, 1,000 battles | Reader, 1,000 pairings both ways |
|---|---|---|---|---|
| Confirmed baseline | — | 67.6% ± 2.0 | 76.2% ± 2.6 | 51.4% ± 1.8 |
| `mix=1` | 50.0% ± 1.2 | 67.0% ± 2.1; paired −0.6 ± 1.3 points | 77.2% ± 2.6; paired +0.9 ± 1.8 points | 51.3% ± 1.8; paired −0.1 ± 1.7 points |
| `temperature=0.01` | 48.8% ± 1.3 | 67.8% ± 2.0; paired +0.1 ± 1.6 points | 75.9% ± 2.6; paired −0.3 ± 1.9 points | 50.3% ± 1.8; paired −1.1 ± 1.8 points |
| `temperature=0.03` | 42.4% ± 1.3 | 60.4% ± 2.1; paired −7.2 ± 2.2 points | 70.2% ± 2.8; paired −6.1 ± 2.8 points | 43.0% ± 1.9; paired −8.5 ± 2.3 points |
| `mix=1,temperature=0.02` | 46.1% ± 1.3 | 64.9% ± 2.1; paired −2.7 ± 2.1 points | 72.4% ± 2.8; paired −3.9 ± 2.7 points | 46.3% ± 1.8; paired −5.1 ± 2.2 points |

The first two candidates show no clear improvement. `temperature=0.03` loses beyond the margin
on all four comparisons, as does the combined setting. These are selection data, not a fresh-seed
confirmation. Grid search times (median / p99 / worst, ms) are 32 / 225 / 487 for `mix=1`,
29 / 106 / 243 for temperature 0.01, 31 / 105 / 248 for temperature 0.03, and 34 / 233 / 524 for
the combined setting. The separate `realtime_trial.py --timing` measurement is recorded below.

The corrected extension screen completed as `mixing-extensions-isolated`, seed 2701, three workers,
500 head-to-head pairings, 500 crowd battles, 250 PvPoke battles and 250 reader pairings per setting.
It includes a shield-head control, shield mixing with that head, simultaneous-switch mixing and variable
hold lengths. Its 20 frozen input hashes are in `runs/task29-inputs-extensions-isolated.json`.
All 1,000 baseline scores exactly match the corresponding corrected full-grid scores despite the
different job plan: 500 crowd, 250 PvPoke and 250 reader pairs. These repeated cases are not pooled as
additional evidence. The extension baseline is **66.6% ± 4.1 crowd**, **76.0% ± 5.3 PvPoke** and
**50.8% ± 3.5 reader**. Completed extension blocks (95% margins):

| Setting | Head to head, 500 pairings both ways | Crowd, 500 battles | PvPoke, 250 battles | Reader, 250 pairings both ways |
|---|---|---|---|---|
| Shield-search control (`heads=throw+swap+mid_swap+replace+shield`) | 49.2% ± 2.6 | 64.5% ± 4.2; paired −2.1 ± 4.3 points | 72.2% ± 5.6; paired −3.8 ± 6.1 points | 49.1% ± 3.6; paired −1.7 ± 4.3 points |
| Shield mixing (control plus `mix_shield=1`) | 46.0% ± 2.5 | 59.7% ± 4.3; paired −6.9 ± 4.5 points | 71.4% ± 5.6; paired −4.6 ± 6.2 points | 48.2% ± 3.7; paired −2.6 ± 4.6 points |
| Simultaneous-switch mixing (`mix_switch=1`) | 41.4% ± 2.6 | 56.0% ± 4.3; paired −10.6 ± 5.0 points | 69.8% ± 5.7; paired −6.2 ± 6.4 points | 41.3% ± 3.7; paired −9.5 ± 4.8 points |
| Variable hold lengths (`random_hold=1`) | 50.6% ± 2.5 | 68.1% ± 4.1; paired +1.5 ± 2.1 points | 74.8% ± 5.4; paired −1.2 ± 2.4 points | 47.9% ± 3.5; paired −2.9 ± 2.3 points |

The control shows no clear change and is not a task-29 adoption candidate. Shield mixing has clear
head-to-head and crowd losses, with no reader benefit. Its paired effect versus shield search alone is
**−4.8 ± 3.4 points crowd**, **−0.8 ± 4.7 points PvPoke** and **−0.9 ± 3.5 points reader**: the crowd
loss is attributable to mixing. Simultaneous-switch mixing has clear head-to-head, crowd and reader losses;
its PvPoke difference is not clear at this sample size. Variable hold lengths show no clear head-to-head
or field change, but lose against the reader beyond the margin. Extension grid search times (median /
p99 / worst, ms) are 29 / 116 / 230 for the shield control, 35 / 160 / 320 for shield mixing,
49 / 290 / 825 for simultaneous-switch mixing, and 31 / 110 / 190 for variable holds. All 20 input
hashes remained unchanged over the 7,000 result rows / 10,250 battles.

**Choice frozen before confirmation:** `mix=1`. The rule selects the largest mean paired reader change
among settings with no clear head-to-head, crowd or PvPoke loss; exact ties prefer more reader cases,
then the original candidate order. This selects `mix=1` (−0.1 ± 1.7 reader points) over temperature 0.01
(−1.1 ± 1.8) and variable holds (−2.9 ± 2.3). The other settings have clear losses in the required
comparisons; the shield control is not a task-29 adoption candidate. **No screened setting demonstrates
a gain.** The fixed choice, raw metrics, dataset hashes, input manifest and acceptance rule are in
`runs/task29-selection.json`. Fresh confirmation completed with seed **2902027**, tag
`mixing-confirm-2902027`, three workers and the full prescribed counts. The choice was not changed after
reading that result. All 20 input hashes and both selection datasets remained unchanged.

| Setting | Head to head, 2,000 pairings both ways | Crowd, 2,000 battles | PvPoke, 1,000 battles | Reader, 1,000 pairings both ways |
|---|---|---|---|---|
| Confirmed baseline | — | 68.8% ± 2.0 | 74.7% ± 2.7 | 50.9% ± 1.8 |
| Frozen `mix=1` candidate | 48.7% ± 1.2 | 67.5% ± 2.0; paired −1.3 ± 1.5 points | 75.1% ± 2.7; paired +0.4 ± 1.7 points | 51.7% ± 1.8; paired +0.8 ± 1.7 points |

The fresh head-to-head upper 95% bound is below 50%, using unrounded values. The reader change does not
exceed its paired margin; crowd and PvPoke differences are also unclear. The frozen adoption criterion
therefore fails on both head-to-head safety and reader improvement. No alternative was selected after
confirmation. The complete checkpoint has 10,000 rows / 14,000 battles; raw metrics and acceptance checks
are in `runs/task29-confirmation-summary.json`. This grid's CPU search times (median / p99 / worst) were
35 / 238 / 571 ms; the required real-time timing measurement is recorded separately below.

**Legacy shared-cache runs below are invalidated as adoption evidence.**

The prescribed four-candidate grid completed with three workers, seed 2701 and tag `mixing`,
including the reader probe (28,000 result rows, 41,000 battles). It is retained only as legacy output.
The exact command and check history are in [`runs/task29-commands.txt`](../runs/task29-commands.txt);
the output is [`runs/task29-mixing.out`](../runs/task29-mixing.out), with a saved legacy checkpoint
at `runs/engine_versus/mixing.json`. Source, model and data hashes at launch are in
[`runs/task29-inputs.json`](../runs/task29-inputs.json). These legacy tags cannot resume under the corrected method.

Legacy grid (printed win shares and nominal 95% margins; invalidated as adoption evidence):

| Setting | Head to head, 2,000 pairings both ways | Crowd, 2,000 battles | PvPoke, 1,000 battles | Reader, 1,000 pairings both ways |
|---|---|---|---|---|
| Confirmed baseline | — | 68.5% ± 2.0 | 76.2% ± 2.6 | 51.7% ± 1.8 |
| `mix=1` | 50.0% ± 1.2 | 68.0% ± 2.0; paired −0.5 ± 1.6 points | 77.8% ± 2.6; paired +1.6 ± 2.1 points | 51.4% ± 1.9; paired −0.3 ± 1.9 points |
| `temperature=0.01` | 48.8% ± 1.3 | 67.8% ± 2.0; paired −0.7 ± 1.7 points | 75.7% ± 2.7; paired −0.5 ± 2.0 points | 50.5% ± 1.8; paired −1.2 ± 1.8 points |
| `temperature=0.03` | 42.2% ± 1.3 | 59.9% ± 2.1; paired −8.6 ± 2.3 points | 68.5% ± 2.9; paired −7.8 ± 2.8 points | 44.5% ± 1.9; paired −7.2 ± 2.4 points |
| `mix=1,temperature=0.02` | 45.7% ± 1.3 | 64.8% ± 2.1; paired −3.8 ± 2.1 points | 72.6% ± 2.8; paired −3.6 ± 2.7 points | 45.4% ± 1.8; paired −6.3 ± 2.4 points |

The printed legacy grid had no apparent gain. These figures are retained for diagnosis and were not
used to select or adopt a setting; the corrected runs above replace them as measurement evidence.
Legacy grid CPU times (median / p99 / worst, ms), in the table's candidate order, were
34 / 243 / 572, 31 / 112 / 283, 31 / 107 / 234 and 35 / 239 / 648.

Three additional options are implemented, off by default, and measured in the corrected screen above:
`mix_shield=1` solves shielding against the affordable incoming moves (requires the shield head);
`mix_switch=1` solves all legal first actions (fast moves, ready charged moves, switches) against their
possible actions when both switches are free and both active Pokémon idle, including ongoing matchups
without a learned mid-swap head, using imagined hidden bench slots; `random_hold=1` samples equally well-timed moments inside the hold rule's
existing safe window. Each uses the private, cloneable mixing generator. Mixed searches now record changed
choices and incomplete rounds; real shield prompts receive a timed charged-move pause.
`scripts/realtime_trial.py --settings SPEC` selects the engine setting to time.

Before changes, the exact full-suite command encountered two sandbox `os.nice(10)` permission errors.
The untouched suite then passed with a priority-only wrapper: 222 tests, seven optional skips. PvPoke
reproduced 108 of 108 battles. `scripts/losses.py` now uses the existing `low_priority()` helper, which
retains an inherited positive nice level when further lowering is denied. After implementation, the exact
suite passed: 228 tests, seven optional skips, and PvPoke remained 108 of 108. Five default-engine game logs
matched the original engine exactly. The mixing seed hash also matched in three fresh Python processes.
The sandbox retains inherited nice=15; all long jobs request `nice`, with at most three workers and one
numerical-library thread per worker.

The legacy grid retained all 14 launch hashes. After the extension changes, 231 tests passed with seven
skips and PvPoke remained 108 of 108; 25 complete game logs (five per original setting, including baseline)
matched the original engine exactly. Before the cache-method guard was added, a zero-job resume preserved
every score and timing frequency and printed the identical summary; exact timing histograms reduced the
checkpoint from 3,971,221 to 475,715 bytes.

The two three-game functionality smokes combined all mixing flags and the shield head, before the
cache correction. Each recorded 81 searched decisions. CPU median / p99 / worst was 41 / 194 / 214 ms
before the switch-action correction and 66 / 371 / 413 ms afterward; both had 0.0% deadline cuts and
0.0% fallbacks. Wait median / p99 / worst was 0 / 7 / 35 ms and 0 / 6 / 32 ms respectively, with 1.2%
of decisions waiting in each. These were functionality checks, not the final timing measurement or
strength evidence.

The required `realtime_trial.py --timing 300` runs completed sequentially, with three workers, one
numerical-library thread per worker and seed **2903027**, using the default real-time budgets:

| Setting | Searched decisions | CPU search median / p99 / worst | Wait median / p99 / worst | Decisions with any wait |
|---|---|---|---|---|
| `mix=1` | 6,689 | 31 / 251 / 478 ms | 0 / 34 / 238 ms | 3.0% |
| Confirmed baseline | 6,638 | 28 / 107 / 231 ms | 0 / 33 / 101 ms | 2.9% |

Both print 0.0% overall deadline cuts and 0.0% fallbacks, rounded to one decimal. **The mixed run did
have cuts:** its one-turn fast-move group prints 0.1% cuts, with a 332 ms worst search against a 300 ms
budget. The baseline prints 0.0% cuts in every group. Timing quantiles and wait rates are observed
measurements, not strength scores or confidence intervals; these use the script's CPU clock, not
wall-clock scheduling latency under other workloads. Full per-cause tables are in
`runs/task29-timing-mix1.out` and `runs/task29-timing-baseline.out`.

Final source matches the tested version: **234 tests, OK (seven optional skips)**, and
**108 of 108 PvPoke battles reproduced exactly**. The 20 frozen source/model/data hashes remain
unchanged after confirmation and timing. The task-29 table row and heading record the negative finding,
preserving the existing owner claim. No randomisation defaults or models changed; all work is uncommitted.
The exact experiment and check commands, including failures and discarded measurements, are in
[`runs/task29-commands.txt`](../runs/task29-commands.txt).

## Task 28: mixed look-ahead opponents and listed teams (2026-10-18)

**No setting adopted.** On fresh seed 280281, the selected `opponents=mix,profile=1` gains +3.4 ± 2.1
points against the crowd and +5.6 ± 2.6 against PvPoke, but scores 48.4% ± 1.3 head to head against the
current engine. That head-to-head loss exceeds its margin and fails task 28's adoption rule. Playing
defaults remain unchanged. Timing is comfortably inside the simulated budgets on this Mac.
The original run sheet completed, but a shared evaluator cache made its outcomes depend on worker job order.
Those numbers are retained below as exploratory only; all six candidates were remeasured with independent
player caches before selection and confirmation.
[Exact commands and outputs](../runs/task28/commands.txt) accompany the results.

All jobs use `/Users/marco/Developer/pokemon_go/.venv/bin/python`, `nice -n 10`, at most three workers and one
numerical-library thread per worker. The sandbox denies further priority changes; the existing helper retains
inherited nice=15. No network, git-history changes, other worktrees, or reserved official footage were used.

**Calibrate before profiling.** `calibrate_styles.py --battles 4000 --workers 3` ran before the comparisons.
The original script printed rounded rates only. It now checkpoints by tag, retains exact event counts, and
reports 95% margins treating battles as independent clusters. Repeating all 4,000 battles per style reproduced
every probability used by the first comparison exactly; a second invocation resumed with zero new chunks.

| Imagined opponent | Shields used / opportunities | Shield rate | Cheaper throws / opportunities with both moves ready | Cheaper-throw rate |
|---|---:|---|---:|---|
| Trained bot | 7,394 / 20,449 | 36.2% ± 0.5 | 8,511 / 15,232 | 55.9% ± 0.9 |
| Bot with varied habits | 7,553 / 18,574 | 40.7% ± 0.6 | 9,113 / 14,837 | 61.4% ± 0.9 |
| Original human-like guess | 7,557 / 19,572 | 38.6% ± 0.5 | 9,306 / 15,665 | 59.4% ± 0.9 |
| PvPoke AI | 8,000 / 8,302 | 96.4% ± 0.4 | 5,593 / 9,993 | 56.0% ± 1.1 |

Rates and counts are in `data/opponent_styles.json`; the original rates are also preserved under
`runs/task28/`. The mixture weights remain 0.4 / 0.3 / 0.2 / 0.1. These are simulated style rates against the
crowd, not estimates of real players' shield or bait frequencies.

**Original grid, seed 2701 — invalid for adoption because of shared evaluator caches.** Each candidate played 2,000 team pairings both ways against the confirmed engine
(4,000 battles), plus 2,000 crowd and 1,000 PvPoke battles. The field battles, teams and dice are paired across
settings. All score margins below are 95%; head-to-head margins use the independent team-pair averages.
The baseline retains four samples, 20 turns, edge 0.03, trained-bot rollouts and margin 0.02.

| Setting | Head to head vs current engine | Crowd score | Paired crowd change | PvPoke score | Paired PvPoke change |
|---|---|---|---|---|---|
| Current engine | — | 68.0% ± 2.0 | — | 75.8% ± 2.7 | — |
| `opponents=mix` | 49.6% ± 1.3 | 71.6% ± 2.0 | +3.7 ± 2.2 | 79.8% ± 2.5 | +4.0 ± 2.7 |
| `opponents=mix,profile=1` | 49.0% ± 1.3 | 71.4% ± 2.0 | +3.5 ± 2.1 | 81.8% ± 2.4 | +5.9 ± 2.7 |
| `unseen=teams` | 49.4% ± 1.3 | 67.7% ± 2.0 | −0.3 ± 2.1 | 73.6% ± 2.7 | −2.2 ± 2.8 |
| `opponents=mix,profile=1,unseen=teams` | 50.1% ± 1.3 | 71.5% ± 2.0 | +3.6 ± 2.2 | 80.9% ± 2.4 | +5.1 ± 2.7 |

Changes are percentage points, calculated before rounding. These are the margins printed by the original
script; cross-battle cache dependence undermines their independence assumption. They must not be used to
claim a gain or select the final candidate. The reader probe was not used (`--reader 0`).

`engine_versus.py` printed descriptive search times (median / 99th percentile / observed worst, CPU ms):
28 / 106 / 267 for the plain mixture; 29 / 106 / 244 with profiling; 31 / 114 / 243 for the team prior alone;
28 / 102 / 228 for the combination. These are its capped per-chunk timing samples; the dedicated
`realtime_trial.py --timing` measurement is separate. The original grid took about 201 minutes on this Mac.
All source/model/data fingerprints recorded before that run were unchanged afterward.
Full output: [`opponents.out`](../runs/task28/opponents.out); compact exploratory scores:
[`opponents-exploratory.json`](../runs/task28/opponents-exploratory.json). Large resumable checkpoints,
including raw search-time arrays, remain local and are ignored by git.

**Human-style attempt: stronger existing holding and farming settings.** `check_human_style.py` uses the
15 Henry development clips for selection and reports the four owner recordings separately. It follows
`real_decisions.py`'s reconstructed-state method, averaging 16 seeded style draws per decision. No official
recordings are loaded. `games/played/` is absent in this worktree. Henry held in 228 of 290 recorded throw
decisions; the owner held in 57 of 81. This motivated changing existing hold/farm settings, without adding a
new tactical rule or changing our own pilot's rules.

| Human-style variant | Henry throw agreement | Paired change | Owner throw agreement | Paired change |
|---|---|---|---|---|
| Original | 54.1% ± 3.6 | — | 60.3% ± 17.5 | — |
| `hold_cost=1.5` | 54.5% ± 3.7 | +0.4 ± 0.6 | 60.5% ± 17.2 | +0.2 ± 0.6 |
| `farm=True,farm_cost=0.7` | 55.0% ± 3.6 | +0.9 ± 1.2 | 60.5% ± 17.4 | +0.2 ± 2.4 |
| Both | 55.4% ± 3.7 | +1.3 ± 1.4 | 60.6% ± 17.3 | +0.3 ± 2.4 |

These margins resample whole games and pair variants within the same games. **None establishes better
imitation beyond its margin.** The best attempted change on Henry's throw agreement, both settings, was frozen
for an engine test; the owner check did not choose it. Predicted hold rates changed from 52.4% ± 4.9 to
54.4% ± 5.1 on Henry and from 60.8% ± 14.0 to 63.6% ± 15.1 on the owner. Shield agreement stayed at
82.2% ± 6.8 on Henry (57 decisions) and 71.3% ± 11.8 on the owner (22); switch agreement stayed at
64.0% ± 7.6 (86) and 70.3% ± 14.8 (20), respectively. Full results for every variant, including hold rates,
are in [`human-style.out`](../runs/task28/human-style.out) and its JSON.

The stronger variant uses `hold_cost=1.5` instead of the original jittered value around 0.9, and always enables
farming with `farm_cost=0.7` instead of the varied settings around 0.35. Fast-first behavior, last-gasp frequency,
the learned model and its margin distribution are unchanged. A separate 4,000-battle-per-style calibration
records human shielding 38.5% ± 0.5 (7,546 / 19,613), cheaper throws 59.8% ± 0.9 (9,515 / 15,904);
the other three styles reproduce the original rates exactly. `style_file` supplies the calibrated rates and
optional `human_settings` together, so testing this variant does not silently replace the original mixture.

**The v2 prior needs its actual weights and species.** The original engine hard-coded `data/teams.json`,
floored explicit weights at 0.02 and substituted pool members for listed species outside the top 50.
`team_file` now selects the prior; `weights_for()` preserves its explicit mixture weights, zero-weight matches
are excluded, and listed unseen builds are retained. If no positive-weight team matches what was seen, the
fallback remains the original top-50 pool. The original list contains no out-of-pool species and all its seen
counts are zero, so its behavior is preserved. The v2 list contains 21 out-of-pool species.

The two extension candidates use the combined setting above: one with the stronger human-style file, one with
`team_file=data/teams_v2.json`. Both are included at the full original counts on seed 2701 in the corrected grid
below. The structure choice and rule for selecting a final candidate were saved before these trials in
`runs/task28/extension-plan.json`: avoid a head-to-head loss beyond its margin, then maximize the smaller of
the crowd and PvPoke paired lower 95% bounds. The best setting must still pass on a new seed and tag.

**Why the measurements were restarted.** Comparing the unchanged baseline on the same seed found 142 of
2,000 crowd outcomes and 43 of 1,000 PvPoke outcomes differed between runs. `engine_versus.evaluator()`
returned one cached `Evaluator` per worker, shared by every player and game. Its internal `Learner.outlook()`
cache is indexed by team slot, opposing build, shields and coarse health, without our build; its entries
therefore carry unrelated teams' values into later games. A direct two-team check reproduced three wrong
outlook features. This is an existing evaluation-harness issue, independent of the new opponent settings.

The extension run was stopped with 3,290 saved rows (the 3,000 baseline rows and 290 partial head-to-head
pairings). Its checkpoint and log remain; partial scores are preserved in
[`opponents-extensions-exploratory.json`](../runs/task28/opponents-extensions-exploratory.json).
The harness now shares only immutable network weights and creates an independent evaluator for each player.
The timing harness does the same. The engine's decision rules and its within-player cache behavior are
unchanged. A three-worker check repeated 30 battles across three settings in reversed job order: all scores
matched exactly. A regression test checks that a player's evaluator cannot inherit another team's cache.
The normal suite then passed 228 tests (seven optional skips); PvPoke remained 108/108.

The corrected grid, tag `opponents-isolated`, evaluated all six settings together on seed 2701 and the full
2,000 / 2,000 / 1,000 counts. Its source/data hashes and unchanged selection rule are frozen in
`runs/task28/isolated-inputs.json`. `runs/task28/batch.py` ran that grid, froze one choice, confirmed it on
seed 280281, timed it on seed 280282, and compared it and the old engine against the trained bot on seed
280283, sequentially with three workers. Corrected results, not the exploratory table above, decide adoption.

**Corrected selection grid, seed 2701.** All 33,000 result rows completed (45,000 battles), with 2,000 mirrored
head-to-head pairings, 2,000 crowd games and 1,000 PvPoke games per candidate. Every player has its own evaluator
cache. All recorded source/model/data fingerprints matched after the run. Margins below are 95%; changes are
paired percentage-point differences from the current engine on the same teams and seeds.

| Setting | Head to head vs current engine | Crowd score | Paired crowd change | PvPoke score | Paired PvPoke change |
|---|---|---|---|---|---|
| Current engine | — | 67.6% ± 2.0 | — | 76.2% ± 2.6 | — |
| Mixture | 49.3% ± 1.3 | 72.5% ± 2.0 | +4.9 ± 2.1 | 78.7% ± 2.5 | +2.5 ± 2.7 |
| Mixture + profiling | 49.4% ± 1.3 | 72.0% ± 2.0 | +4.4 ± 2.1 | 82.6% ± 2.4 | +6.3 ± 2.6 |
| Original team prior only | 50.4% ± 1.2 | 67.5% ± 2.1 | −0.2 ± 1.9 | 73.7% ± 2.7 | −2.6 ± 2.6 |
| Mixture + profiling + original team prior | 49.9% ± 1.2 | 71.3% ± 2.0 | +3.7 ± 2.2 | 81.1% ± 2.4 | +4.9 ± 2.7 |
| Same combination, stronger human style | 49.9% ± 1.2 | 71.8% ± 2.0 | +4.1 ± 2.2 | 80.8% ± 2.4 | +4.5 ± 2.7 |
| Same combination, v2 team prior | 49.2% ± 1.3 | 71.7% ± 2.0 | +4.1 ± 2.2 | 81.0% ± 2.4 | +4.7 ± 2.8 |

The human-style change alone, compared with the original combination, adds +0.4 ± 0.6 crowd points and
−0.4 ± 0.7 PvPoke points. Replacing the prior with v2 adds +0.4 ± 1.9 and −0.2 ± 2.2, respectively.
Neither extension helps beyond its margin. The original team prior alone does not help; the plain mixture
does not clear its PvPoke margin. The predeclared rule selects **mixture + profiling**: its weaker paired
lower bound is +2.27 points. This is a selection result, not a confirmed gain. The exact choice and rule were
written to [`selection.json`](../runs/task28/selection.json) before starting seed 280281.

Descriptive `engine_versus.py` search times, in table order after baseline (median / 99th / observed maximum,
CPU ms): 28 / 103 / 204; 27 / 99 / 215; 29 / 108 / 236; 25 / 96 / 228; 27 / 97 / 225; 27 / 100 / 238.
These capped per-chunk samples do not replace the dedicated timing run. Reader was not used. Full printed
output: [`isolated.out`](../runs/task28/isolated.out). The small
[`opponents-isolated-summary.json`](../runs/task28/opponents-isolated-summary.json) retains exact scores,
margins and all individual outcomes as quarter-point strings in battle-number order.

**Fresh-seed confirmation, seed 280281, tag `opponents-confirm`.** The frozen mixture + profiling candidate
completed another 2,000 mirrored pairings, 2,000 crowd games and 1,000 PvPoke games. The score and paired-change
margins are 95%.

| Player | Head to head vs current engine | Crowd | Paired crowd change | PvPoke | Paired PvPoke change |
|---|---|---|---|---|---|
| Current engine | — | 70.5% ± 2.0 | — | 76.3% ± 2.6 | — |
| Mixture + profiling | 48.4% ± 1.3 | 73.9% ± 1.9 | +3.4 ± 2.1 | 81.9% ± 2.4 | +5.6 ± 2.6 |

The exact head-to-head upper confidence limit is 49.644%, below 50%. Although both outside-opponent gains
exceed their margins, **the full acceptance criterion fails**. No alternative was chosen after inspecting
this confirmation seed. No engine setting is promoted to desktop or website defaults, and no site build or
publication is needed. Full output: [`confirmation.out`](../runs/task28/confirmation.out); exact scores and
outcomes: [`opponents-confirm-summary.json`](../runs/task28/opponents-confirm-summary.json);
machine-readable decision: [`verdict.json`](../runs/task28/verdict.json). Its descriptive search times were
27 / 101 / 231 CPU ms (median / 99th / observed maximum).

**Dedicated real-time measurement, seed 280282.** `realtime_trial.py --timing 300 --workers 3
--settings 'opponents=mix,profile=1'` measured 6,974 searched decisions with the real-time wrapper's default
budgets, independent evaluator caches, and process CPU time on macOS 26.6.2 arm64 / Python 3.13.13.
Whole-battle bootstrap 95% intervals:

| Measurement | Estimate | 95% interval |
|---|---:|---|
| Median search time | 24.41 ms | 22.69–26.02 ms |
| 99th-percentile search time | 96.82 ms | 91.05–101.69 ms |
| Decisions requiring any wait | 2.72% | 2.37–3.10% |

The observed maximum search was **172.66 ms** and maximum wait **85.77 ms**. These are sample maxima,
not population limits with inferential margins. No search was cut short and none fell back to the trained
bot; the exact one-sided 95% upper bound on the probability of a battle having either observed-zero event
is 0.994% for each event type. A zero-event bootstrap alone would incorrectly suggest no uncertainty.
The smallest simulated search budget was 300 ms; all observed searches fit. CPU timing on this native Mac
does not establish loaded wall-clock or browser/Pyodide performance. Full per-cause table:
[`timing.out`](../runs/task28/timing.out); exact measurements: [`timing.json`](../runs/task28/timing.json).

**Its edge against the trained bot, fresh seed 280283.** Each engine played 1,000 mirrored pairings against
the trained bot (2,000 battles each). The current engine scored **63.9% ± 1.8**; mixture + profiling scored
**64.1% ± 1.8**, a paired change of **+0.2 ± 2.1 points** (all 95%). There is no measured shrinkage or gain
in this edge. This secondary comparison was not used for selection or adoption. Its descriptive search times
were 33 / 114 / 239 CPU ms for the current engine and 31 / 103 / 231 for the candidate (median / 99th / maximum).
Full output: [`bot-confirmation.out`](../runs/task28/bot-confirmation.out); exact scores, paired difference and
individual outcomes: [`opponents-bot-confirm-summary.json`](../runs/task28/opponents-bot-confirm-summary.json).

**Checks and unsuccessful execution attempts.** The initial exact unit command failed only at two raw
`os.nice(10)` calls in `scripts/losses.py`. A process-local priority fallback passed all 222 tests with seven
optional skips before any repository change. `losses.py` now uses the existing `low_priority()` helper;
the normal command passed 227 tests after the option changes, with the same seven skips, including new checks for weighted unseen teams,
out-of-pool species, missing calibration files and human-style routing. PvPoke reproduces 108/108 before and
after these changes. The first human audit included a raw-only folder without tracked states; discovery was
corrected to the exact saved development-summary names and the failed log was preserved. No game or tracker
data was changed. The initial command and its failed fallback, successful retries, and logs are in
[`commands.txt`](../runs/task28/commands.txt).

**Final checks.** The full normal suite passed **228 tests, seven optional skips**, in 10.503 seconds;
`check_pvpoke.py` reproduced **108/108** battles exactly. All 22 frozen source/model/data fingerprints still
matched after the complete corrected batch. `git diff --check` passed. The learned networks, battle rules,
team-list data and desktop/website defaults were not changed. All changes remain uncommitted. Large raw
checkpoints are retained locally for resumption and excluded by exact `.gitignore` entries; the retained
text/JSON summaries contain the scores needed to verify every reported margin.

## Shield decisions in the engine (task 25, 2026-10-18): no gain

**Corrected run (2026-10-18).** The first comparison below was made before a bug in `scripts/engine_versus.py` was
fixed: one evaluation cache was shared between both players and across worker jobs, so paired games could be
changed by earlier searches (found and fixed in task 27; see that section). Rerun with the fix, under a new tag and a
fresh seed (`engine_versus.py --tag shields-isolated --seed 2502 --workers 3 --pairings 2000 --crowd 2000 --pvpoke 1000
--candidates "heads=throw+swap+mid_swap+replace+shield"`, `runs/task25/shields-isolated.out`): head to head **50.8% ± 1.3**;
against the crowd **−3.5 ± 2.2** points; against PvPoke's AI **−0.9 ± 2.8** points; search time median 28 ms, 99th
percentile 116, worst 279. The conclusion stands: shield search stays off.

**Keep shield search off by default.** The already-built shield head was measured with the run sheet's
task-25 command, without changing its decision logic. Both engines use the confirmed settings: the trained
bot inside the look-ahead, four samples per option, 20 turns, edge 0.03 and learned margin 0.02. The candidate
adds `shield` to `throw+swap+mid_swap+replace`. No alternative settings were tried.

The full comparison used seed 2701 and three workers: 2,000 team pairings played both ways head to head
(4,000 battles), plus 2,000 crowd and 1,000 PvPoke battles per setting on matching seeds, teams and opponents.
All score margins below are 95%; head-to-head uncertainty is across independent pairings, and differences
against the outside opponents are paired battle differences, computed before rounding.

| Measure | Current engine | With shield search | Candidate minus current |
|---|---|---|---|
| Candidate head to head against current | — | 49.2% ± 1.3 | −0.8 ± 1.3 points from 50% |
| Against the crowd, 2,000 battles each | 68.1% ± 2.0 | 65.7% ± 2.1 | −2.4 ± 2.2 points |
| Against PvPoke's AI, 1,000 battles each | 76.3% ± 2.6 | 73.2% ± 2.7 | −3.2 ± 3.0 points |

The head-to-head gain check failed, and both outside-opponent differences are negative beyond their margins.
**Nothing helped in this experiment.** No fresh-seed strength confirmation was run because the candidate did
not look better; seed 25025 had been reserved for that confirmation but was not used. The reader was not run
(`--reader 0`, as in the task-25 run sheet). Defaults in the engine, browser game and website are unchanged;
there was no promotion or website build. This measures this shield implementation at the confirmed search
settings, not every possible shield-search method.

**Timing.** `RealTime` previously inherited the shield method without timing or bounding its searches, so
those searches were absent from its timing rows. It now wraps shield decisions with the existing charged-pause
budget (2,000 ms, subject to `cap_ms`). `scripts/realtime_trial.py` accepts `--heads`, applied to both the
real-time and unhurried engines. Tests check that an unlimited shield search matches the unhurried engine,
leaves the live position unchanged, and falls back to the learned bot when the deadline leaves no search time.

Both timing commands used `--timing 300 --workers 3 --seed 2501`, sequentially, on this shared arm64 Mac
(macOS 26.6.2, Python 3.13.13), with one numerical-library thread per worker and default live budgets.
The second adds `--heads throw+swap+mid_swap+replace+shield`.

| Searched decisions | Median CPU ms | 99th percentile CPU ms | Worst CPU ms |
|---|---:|---:|---:|
| Current engine, all 6,748 searches | 30 | 109 | 170 |
| Shield candidate, all 8,759 searches | 27 | 116 | 202 |
| Shield decisions within the candidate | 26 | 70 | 94 |

Both printed 0.0% cut short and 0.0% with no complete round. Wait at the decision, median / 99th / worst:
current 0 / 35 / 100 ms (2.9% with any wait), candidate 0 / 29 / 107 ms (2.4%). The strength run also printed
candidate search time 28 / 119 / 286 ms. These are observed timing and deadline statistics, not confidence
intervals; the clock measures process CPU time and does not include time descheduled by other jobs.
Adding shields changes the mixture of searched decisions; the shield-only row isolates their measured cost.
The timing seed is fresh, but this is not a fresh-seed strength confirmation. Speed fits the configured
budgets here; it does not rescue the negative strength result.

**Reproduction and validation.** [Exact commands and output summary](../runs/task25/commands.txt),
[full comparison output](../runs/task25/shields.out), [resumable scores](../runs/engine_versus/shields.json),
[baseline timing](../runs/task25/timing-baseline.out), [shield timing](../runs/task25/timing-shields.out),
and [input hashes and environment](../runs/task25/provenance.json). All long jobs requested `nice -n 10`
and used at most three workers. The sandbox denied further priority reductions, so the batch scripts
retained inherited nice level 15. No code imported by a running job was edited.

Before edits, the literal unittest command failed in two existing `scripts/losses.py` priority calls;
with a temporary `/tmp/e25-runtime/sitecustomize.py` retaining already-low priority when that call is
denied, all 222 tests passed (7 existing skips). It changes no battle or test logic; its source is in the
command receipt. The final [224-test run](../runs/task25/tests-final.out) passes (7 skips), and the final
[PvPoke check](../runs/task25/pvpoke-final.out) reproduces all 108 of 108 reference battles exactly.
The [saved-result audit](../runs/task25/audit.json) verifies every requested battle/pair index and unchanged
input hashes. No game rules, model weights or task claims changed. All work remains uncommitted.

## Self-play improvement loop (task 31, 2026-10-18): round 1 not adopted

`python3 scripts/selfplay_eval.py --run selfplay-1 --workers 3 --rounds 5 --games 20000 --compare 1500` (`runs/selfplay-1.out`,
`runs/selfplay/selfplay-1/rounds.json`). Before running it, the script was changed to give each player and the position
recorder a fresh evaluation cache in every game. The shared `Evaluator` cache is keyed by team slot and opposing species,
not by our team, so a cache carried across games or players can change a position's features (the bug found in task 27).
`scripts/engine_versus.py` has the same fix.

Round 1: 20,000 engine-against-engine games (192 minutes on three cores) gave 196,256 positions. The evaluation
refitted on them predicts better on the held-out tenth of games (log loss 0.6308 against 0.6443 for the current one), but
plays no better, on 1,500 pairings both ways and 1,500 crowd battles (comparison seed 4018): head to head **49.2% ± 1.5**; against the
crowd **−1.7 ± 2.4** points (current engine 70.7% ± 2.3). The loop's rule (head to head above 50% beyond the margin and not
worse against the crowd) stopped it after round 1. As with the extra inputs (status: "Does the bot need to see their
other Pokémon?"), a better-predicting evaluation does not by itself make better decisions.

## Evolving the rulebook (task 30, 2026-10-18, the owner's idea): a confirmed gain

`python3 scripts/evolve_rules.py --run rules-1 --workers 3 --generations 100 --population 32 --pairings 2000` (`runs/rules-1.out`,
about 15 hours on three cores): CMA-ES over the `Planner`'s 34 genes, fitness head to head against the standard rules on the
same 2,000 pairings for the whole generation. Best / median of each generation (the best is the top of 32, so flattered):

| Generation | 1 | 10 | 25 | 50 | 75 | 100 |
|---|---|---|---|---|---|---|
| Best | 51.0% | 52.1% | 53.8% | 54.1% | 53.7% | 55.0% |
| Median | 46.9% | 50.2% | 52.2% | 53.0% | 52.8% | 53.7% |

`--final` re-scored the five best on 5,000 fresh pairings each (`runs/rules-1-final.out`): 54.9%, 54.7%, 54.6%, 54.4%, 54.2%
against the standard. The best (generation 93) was confirmed with the printed command on a new seed
(`rule_trial.py ... --battles 8000 --seed 3008`, `runs/rules-1-confirm.out`): **head to head 54.0% ± 0.9; against the crowd
59.1% ± 1.1 against 55.8% ± 1.1, +3.4 ± 1.0 points.**

**The trained bot on top** (`scripts/bot_on_rules.py`; `runs/rules-1-bot-on-top.out`, seed 3030): the bot on
the evolved rules against the bot on the standard rules, 4,000 pairings both ways, **51.6% ± 0.8** head to head (margin over
chunks of 50 pairings); against the crowd on the same 4,000 battles 67.9% ± 1.4 against 67.3% ± 1.5, **+0.6 ± 1.1**. So the bot
on top is not worse, and is better head to head. Both conditions for adoption hold.

The settings that changed (the on/off rules and the bait and shield styles kept their defaults; `catch_gain`,
`shield_matchup_hp` and `sweep_chance` belong to rules that stay off, so their values do nothing):

| Setting | Standard | Evolved |
|---|---|---|
| `switch_margin` | 0.35 | 0.058 |
| `shield_share` | 0.4 | 0.972 |
| `energy_worth` | 0.0 | 0.5 |
| `hold_cost` | 0.5 | 0.903 |
| `switch_worth` | 0.0 | 0.289 |
| `safe_weight` | 0.0 | 0.212 |
| `win_switch` | 0.1 | 0.0 |
| `expect_shield` | 0.7 | 0.446 |
| `known_edge` | 0.15 | 0.4 |
| `sac_margin` | 0.1 | 0.029 |
| `shield_worth` | 0.35 | 0.392 |
| `belief` | 2.0 | 1.840 |
| `bad_matchup` | −0.2 | −0.179 |
| `farm_cost` | 0.35 | 0.387 |
| `matchup_weight` | 0.75 | 0.741 |

The largest change is a much lower `switch_margin`: swap for a bench Pokémon only slightly better, where the standard needed
0.35. Lowering it on its own gained nothing (task 26: 0.25 and 0.15, 50.1–50.3% head to head), so the gain comes from the
combination, which is what the evolution was for. **The second run, with the trained bot on top during evolution** (`evolve_rules.py --run rules-bot-1 --pilot bot --workers 3
--generations 60 --population 24 --pairings 1500`, `runs/rules-bot-1.out`): `--final` re-scored its five best at 51.9–52.5%
(bot on top against the bot on the standard rules, 5,000 fresh pairings; `runs/rules-bot-1-final.out`). On fresh seeds the
bot on its best rules beat the bot on the standard rules 51.9% ± 0.8 head to head (crowd ±0.0 ± 1.3,
`runs/rules-bot-1-bot-on-top.out`) and the bot on the rules-1 rules 51.0% ± 0.9 (crowd +0.2 ± 1.2,
`runs/rules-bot-1-vs-rules-1.out`). But **those rules on their own do not beat the standard**: 49.9% ± 0.9 head to head, crowd
−1.3 ± 1.1 (`rule_trial.py ... --battles 8000 --seed 3009`, `runs/rules-bot-1-confirm.out`). Only the rules-1 rulebook meets
both conditions, so that is the one kept.

**Kept as a preset, not yet the default:** `pogo.agents.EVOLVED_RULES` holds the rules-1 settings above
(`Planner(**EVOLVED_RULES)`, likewise `Learner(q=..., **EVOLVED_RULES)`). Making them the default changes the trained bot
and the engine on the website, and part of the crowd too: `varied_settings` sets most of these values explicitly around
the standard ones, but not `energy_worth`, `switch_worth`, `sac_margin`, `known_edge` or `belief`, which crowd players take
from the defaults. That changes the yardstick every result is measured against, so it is left to the owner, with the
crowd re-centred and a retrain of the learned layer on the new rules as the follow-ups. Still running when this was written:
`engine-1` (the engine's settings).

## Real pause lengths (2026-10-17)

`scripts/recording/pause_lengths.py` over the 49 tracked battles with timelines (the owner's recordings and the public
clips; `runs/pause_lengths.out`):

| Pause | Count | Median | 10th to 90th percentile |
|---|---|---|---|
| Charged move: start to its damage on the bar | 280 | 9.4 s | 8.9 to 11.9 |
| Charged move: damage shown to play resuming | 239 | 0.9 s | 0.4 to 2.2 |
| Charged move, start to play resuming: unblocked / blocked | 239 / 155 | 10.4 / 9.4 s | 9.6 to 13.3 / 7.6 to 10.8 |
| Faint: knockout to the replacement in | 137 | 10.6 s | 2.5 to 15.7 |
| Faint: replacement in to play resuming | 143 | 1.2 s | 0.4 to 2.5 |
| Start: the lead's "Go" to the first hit | 49 | 3.0 s | 0 to 4.8 |

The guesses in `pogo/realtime.py` (2 s after a charged move, 1 s after a faint) assumed the search starts once the
outcome is on screen; measured, that leaves only 0.4 s at the 10th percentile. The defaults are now those 10th
percentiles (400 ms after a charged move, 350 ms after a faint, 2 s for choosing a replacement, 1 s at the start).
With them nothing is cut either (`runs/realtime_timing_measured.out`: 6,748 searched decisions, worst 132 ms, none
cut). The bigger opening is the 9 s while a charged move plays: only the shield and which move are unknown, so the
engine could search those few outcomes during it. That matters once a slower, stronger setting is adopted (task 27).

## Form-changing Pokémon in the engine (task 10, 2026-10-17)

Aegislash, Mimikyu, Cramorant and Morpeko now change form in battle as PvPoke's simulator does (its `Battle.js`
and `Pokemon.js`, read on 17 October):

- **Aegislash** fights in Shield form (fast moves do 1 damage and give 6 energy), takes Blade form just before a
  charged move (at a level recomputed to fit the league: for the default build, level 22, attack 172.9, defence
  69.5, health kept at 139) and goes back to Shield form when it shields or switches out.
- **Mimikyu**: the first unshielded charged move against it does 1 damage (its disguise), then it is Busted for the
  rest of the battle, with Defence one stage lower, switches included.
- **Cramorant**: after Surf or Dive it is Gulping (above half health) or Gorging. The next unshielded charged move
  against it is answered at once by Gulp Missile: 15% of the attacker's maximum health plus 1, unshieldable, even if
  Cramorant fainted, with Defence -1 (Arrokuda) or Attack -2 (Pikachu) on the attacker; then it is back to normal.
  Switching out resets it.
- **Morpeko**: changes mode with every charged attack (Aura Wheel Electric in Full Belly Mode, Dark in Hangry Mode)
  and starts each entry in Full Belly Mode, as the game does (Bulbapedia, "Morpeko (GO)"). PvPoke's simulator only
  ever turns it Hangry; `scripts/check_pvpoke.py` uses that rule (`pogo.battle.MORPEKO_TOGGLES = False`) while it
  compares with PvPoke's battles.

`tests/data/pvpoke_forms.txt`: 132 one-on-one battles (each of the four against ten common opponents and each other,
0 to 2 shields) played by PvPoke's own simulator on pvpoke.com. `python3 scripts/check_pvpoke.py --forms`:
**132 of 132 reproduced exactly** (130 before matching PvPoke's Morpeko); the original 108 still all match, and the
speed check's results are identical. Every Pokémon is now built with its forms by default (`allow_forms=True`);
the pools simulations draw from (`GameData.meta`) still leave the four out unless `forms=True`, so every model and
result so far stays comparable. The line-up tools (`lineup.py`, `lineup_site.py`, `sixes.py`, the website build)
list them. The trained bot and the rules have never played them; their predictions (one-on-one outlooks, damage
counts) ignore form changes.

**Which six to register** (`runs/sixes_swaps.out`, same opposing six, 40 battles for each of 3,600 pairs each): the
owner's six with Shadow Quagsire (never brought) replaced.

| Sixth Pokémon | Win chance, both choosing well | Scored on separate battles | Against their best single reply | How often it is brought |
|---|---|---|---|---|
| Shadow Quagsire (as registered) | 40% | 38% | 26% | 0% |
| **Azumarill** | **53%** | **52%** | **48%** | 75% |
| Mantine | 45% | 45% | 39% | 59% |
| Fearow | 44% | 43% | 33% | 84% |
| Vigoroth | 40% | 38% | 26% | 0% |

Azumarill (Fairy, resists Dark and Fighting) turns the matchup: with it the opponent's best answer is no longer the
Dark core alone (their mix spreads over Tinkaton, Shadow Annihilape, Corviknight and Thievul), and the owner's mix
leans on Stunfisk leading with Melmetal and Azumarill behind (22%). Vigoroth is never brought, like Shadow Quagsire.
One opposing six only; the next question is how each six does against several opposing sixes.

## From decisions to touches on the phone, and the minigame (task 13, 2026-10-17)

**Where to touch** (`pogo/controls.py`). Measured on frames of the owner's recordings
(`scripts/recording/contact_sheet.py`) and checked by drawing every planned touch onto real frames
(`scripts/recording/overlay_controls.py`): fast move, a tap on the open field (0.50, 0.45); charged moves, the two
buttons (0.31 and 0.69 across, 0.89 down); switch, the bench portrait at the right edge (0.915 across; 0.585 the
earlier team slot, 0.67 the later; with one left it moves to the top); the shield prompt's shield (0.50, 0.815) and
"Not now" (0.50, 0.95); after a faint, the two choices side by side in team order (0.33 and 0.67, 0.865) or one in
the middle. Every touch is checked against keep-out zones (the flee button at the top left forfeits the battle), and
`Controller` sends through `pogo.phone.Phone` only when `live=True`, with a cap on touches per battle and a log.
`tests/test_controls.py`. Not yet tested on the phone (step 1: does iPhone Mirroring pass synthetic taps and drags).

**The minigame.** It scales a charged move's damage from a quarter to all of it (Excellent: 95% of the icons swiped),
so every number the engine learned assumes the bot does it well. Icons are discs in the type's colour with a white
symbol; they vary in size a lot, fade once swiped, and Flying icons are pale against clouds. A first detector
(`pogo/minigame.py`: circles with a flat colour and a white middle; `scripts/recording/minigame_eval.py` over the 24
recorded minigames, `runs/minigame_eval_1.out`) finds Water icons well (Surf: 1 to 2 a frame, an estimated 60% swiped
with 100 ms between seeing and swiping) and others poorly (23% on average at 100 ms, 7% at 300 ms): not usable as is.

What the recordings show instead: **the pattern is fixed for each move, with a few variants.** The first icon appears
1.5 to 1.65 s after the move starts in every run; two of the three Surfs have icons at the same places at the same
moments (median 0.07 radii apart), and the six Double Iron Bashes fall into two groups of three that match the same
way (0.04 to 0.07 radii). Sky Attack and the others cannot be compared yet because the detector misses too many of
their icons. So the bot does not need to chase icons live: it can replay a swipe path per pattern variant, chosen by
where the first icons appear. The owner's own swipes in these recordings reached Excellent and the game draws the
touch trail, so the paths can be learned from them. Next: read the owner's touch trails per run, group runs by
variant, and test replayed paths against the recorded icons; and a continuous multi-point drag in the phone helper
(`helper/phonectl.swift` lifts the finger between segments today).

The owner confirms the minigame is one pattern per type (not per move), which agrees with the runs above. Reading the
owner's own swipes off the video is harder than expected: the touch ring is about a quarter of the screen across and
faint, and vanishes against white Pokémon (Jellicent), so the per-type paths will come from the icon patterns
combined over several runs of a type. The phone helper now has an unbroken multi-point swipe (`phonectl path`,
`Phone.path`, used by `Controller` for drags); `python3 scripts/probe.py --path` tests it on the phone.

**Per-type minigame library, first attempt** (`scripts/recording/minigame_library.py`, 2026-10-17; the owner: "a little
minigame for each type"). The owner's 24 recorded minigames cover five types: Flying (9 Sky Attacks), Steel (6 Double
Iron Bash), Water, Fire and Fighting (3 each). Steps: the type's icon colour from confident detections, icons found by
colour (`pogo.minigame.detect_colour`), followed, timed from the first icon, runs grouped into variants, a swipe
schedule per variant, and each run scored on the schedule built without it. Not usable yet:

| Type | Colour found | Icons followed per run | Variants | Held-out run hit by the schedule |
|---|---|---|---|---|
| Fighting | red (209, 58, 84) | 35 to 38 | 3 of 1 run | none to test on |
| Fire | orange (246, 156, 73) | 38 to 57 | 1 of 3 | 35% |
| Flying | pale blue (150, 175, 225) | 104 to 145 | 7 + 2 | 10 to 15% |
| Steel | teal (73, 139, 152) | 79 to 107 | 1 of 6 | 20% |
| Water | blue (85, 161, 216) | 127 to 143 | 1 of 3 | 27% |

A minigame shows perhaps 15 to 30 icons, so the counts say colour alone also catches other things, and the frames
show which: collected icons swell into large faded discs as they burst, the move's own animation shares the colour
(Dynamic Punch's orange fists, Flamethrower's flames), and Flying and Steel are close to the sky. What only a live icon
has is its crisp white type symbol (fist, flame, drop, wing, steel emblem). Next: match each type's symbol (templates
cut from clean frames) to find live icons, then rebuild the schedules; and more recordings per type (the owner offered
to record each type).

**Zones and circling swipes for 14 types** (`scripts/recording/minigame_zones.py`, `data/minigame/<type>.json`,
2026-10-17). The owner added two recordings for more types ("they're always at the same place"; "most of them you
can just swipe circles in the same place"), so the library is now a zone per type plus a swipe that circles in it,
started 1.45 s after the move (the first icon comes 1.30 to 1.54 s after it, by type). Live icons are found by their
white symbol inside a ring of the type's colour (`pogo.minigame.detect_symbol`): precise, but it misses many, so the
zone pools every sighting over a type's runs. A plain loop at the zone's edge misses icons in its middle; a spiral
that breathes in and out does better. Share of detected icons the chosen swipe crosses while they are on screen:

| Type | Runs | Zone (centre) | Loop | Best spiral |
|---|---|---|---|---|
| Fire | 3 | 0.51, 0.73 | 65% | 76% |
| Ice | 2 | 0.52, 0.71 | 65% | 76% |
| Bug | 1 | 0.21, 0.57 | 67% | 72% |
| Electric | 1 | 0.60, 0.54 | 32% | 61% |
| Water | 3 | 0.74, 0.48 | 56% | 57% |
| Rock | 1 | 0.27, 0.48 | 33% | 53% |
| Flying | 9 | 0.85, 0.56 | 45% | 51% |
| Grass | 1 | 0.25, 0.54 | 36% | 48% |
| Poison | 4 | 0.53, 0.74 | 29% | 43% |
| Fighting | 3 | 0.51, 0.61 | 35% | 42% |
| Normal | 1 | 0.42, 0.71 | 20% | 40% |
| Steel | 6 | 0.55, 0.63 | 28% | 39% |
| Dark, Fairy | 1 each | 0.48, 0.63 / 0.38, 0.70 | 24% / 19% | 32% / 32% |

These are estimates from the recordings (the detector's icons only, the best of seven shapes chosen on the same runs,
one run for several types), not the game's count. Missing: Dragon, Ghost, Ground, Psychic. The owner's other idea is
better still: record their own swipes and replay them. `phonectl record <seconds> <out.jsonl>` (`Phone.record`) now
listens (never acts) to the mouse in the iPhone Mirroring window and writes each press, drag and release with its time
and position; the owner plays minigames through iPhone Mirroring with the trackpad, and those swipes become the
library. It needs the Input Monitoring permission and has not been run yet.


## An opening book: a plan for every opposing lead (2026-10-17, the owner's idea)

`pogo/openings.py` (`Booked` wraps any player with a book {their lead: plan}) and `scripts/openings.py`. Plans: stay
in; swap to either team-mate at once or after 2, 4 or 8 fast moves; throw our first charged move, then swap. Each of
the top 50 leads (their back two from listed teams holding it, 70%, else random), 200 battles per plan, trained bot
with shifted habits on both sides; a plan is kept if it beats staying in by more than its margin. For Melmetal /
Altaria / Jellicent (`runs/openings_1.out`, `data/openings/melmetal-altaria-jellicent.json`) 20 of 50 leads got a
plan, e.g. Stunfisk: swap to Jellicent at once; Hippowdon: swap to Altaria at once; Melmetal, Ninetales: two fast
moves then Jellicent; Clodsire, Deoxys-D: four fast moves then Altaria; Araquanid, Feraligatr: throw first then
Jellicent. **Check on 3,000 fresh battles: 56.0% ± 1.8 with the book, 53.8% ± 1.8 without, +2.2 ± 0.9 points.**
The per-lead gains (+8 to +32) are the best of nine plans each and so flattered; the fresh check is the number. Not
yet in the book: Cramorant and Mimikyu leads (see below), and books for other teams.

## Team shapes, and PvPoke's public team data (2026-10-17, the owner's rule)

The owner: balanced teams (ABC, ABB) are common, BAB and AAA are not. `pogo/teamshape.py` gives each Pokémon a
letter by its one-on-one record (two share a letter when their records against the pool correlate 0.3 or more) and
draws opposing teams by shape (`shaped_drawer`, `pogo.teamlist.drawer(style="shaped")`).

Public data: PvPoke publishes usage from its training battles (players and bots at Elite and Champion; 14,540
Great League teams, updated 2026-10-17): each Pokémon's games, the best-scoring teams with 20+ games, and the 37
hand-made teams its bots bring. Saved in `data/pvpoke_training_1500.json`; `scripts/pvpoke_teams.py` →
`runs/pvpoke_teams.out`. No official GBL usage or tournament team lists were found (Silph and Pikalytics pages seen
are predictions or not Pokémon GO data).

- **Our opponent pool misses the two most-used Pokémon.** Cramorant (8.5% of team slots, the lead in 16% of listed
  team games) and Mimikyu (8.0%) are left out of `gd.meta()` because they change form; Melmetal (8.5%) and Tinkaton
  (6.2%) are in. Our pool holds 60% of team slots, 76% with the form-changers; Morpeko, Jumpluff and Lickilicky
  (1.1, 1.0, 0.6%) are not in our top 50 at all. Every model and measurement so far has met neither Cramorant nor
  Mimikyu.
- **Shapes** (letters over 65 Pokémon: our pool with form-changers plus everything PvPoke lists, one-on-ones in
  `data/matchups_wide.json`): listed teams ABC 94 / ABB 6 / AAB 0 / AAA 0 (98 / 2 / 0 / 0 by games), bot teams
  92 / 3 / 5 / 0, random threes by usage 73 / 8 / 19 / 0. So the owner's rule holds for AAB and AAA, and ABB is
  rarer than guessed (0.2 times its random share). `PVPOKE_WEIGHTS` (1, 0.2, 0.05, 0.01) with `usage=pvpoke_usage()`
  draws 97 / 2 / 1 / 0. The listed teams are the best-scoring ones, so they lean balanced; bots' teams are
  hand-picked; neither is GBL itself.

## The engine, the bot and the opening book against teams as PvPoke's data has them (task 32, 2026-10-18)

The field: `pogo.teamshape.pvpoke_field` (our top 50 with Cramorant and Mimikyu, plus Morpeko, Jumpluff and
Lickilicky; teams by PvPoke usage and `PVPOKE_WEIGHTS`). `scripts/engine_versus.py --field pvpoke` and
`scripts/openings.py --field pvpoke`; the same runs on the usual field, same seed, for comparison.
Cramorant or Mimikyu is in 74% of these battles.

| | usual field | PvPoke field |
|---|---|---|
| engine head to head against the bot, 3,000 pairings both ways | 64.4% ± 1.0 | 66.3% ± 1.1 |
| bot against the crowd, 4,000 | 66.5% ± 1.5 | 67.1% ± 1.4 |
| engine against the crowd, same battles | 69.0% ± 1.4 (+2.6 ± 1.6) | 71.2% ± 1.4 (+4.0 ± 1.6) |

(`runs/field_standard.out`, `runs/field_pvpoke.out`.) **The engine's edge holds on the realistic field, and the bot
does not fall off against form-changers.** Split by Cramorant or Mimikyu (`scripts/field_breakdown.py`,
`runs/field_breakdown.out`): engine against bot 66.1% ± 1.2 with one of them in the battle, 66.8% ± 2.0 without;
against the crowd the bot is 67.1 / 65.9 / 68.5 (± 2.9) with them on our side / theirs / neither, the engine
70.1 / 69.2 / 74.9 (± 2.8): perhaps a smaller edge when they are present, within the margins.

**Opening book on the PvPoke field** (Melmetal / Altaria / Jellicent; 30 most-used leads, 300 battles per plan;
`runs/openings_pvpoke.out`, `data/openings/melmetal-altaria-jellicent-pvpoke.json`): on 4,000 fresh battles **51.9% ±
1.5 with the book, 46.2% ± 1.5 without, +5.8 ± 1.2 points**, against +2.2 ± 0.9 for the book built on the usual
field. Cramorant (71% staying in) and Mimikyu (63%) leads: stay in. Changes from the usual-field book: against
Stunfisk and Araquanid four fast moves then Jellicent; against Melmetal and Clodsire four fast moves then Altaria;
Deoxys-D two then Altaria; Shadow Ninetales, Ninetales and Shadow Quagsire: Jellicent at once. Note the team itself:
46.2% without the book here against 53.8% on the usual field; the usual field flatters it.

**Task 27 under the measured pauses (2026-10-18).** After the pauses measured from recordings became the defaults in
`pogo/realtime.py` (400 ms after a charged move, 350 ms after a faint, where the guesses were 2,000 and 1,000), 32
imagined battles was timed again on the merged code (`realtime_trial.py --timing 300 --samples 32 --seed 2706`,
`runs/task27-timing-samples32-new-pauses.out`): median 244 ms, 99th percentile 791, worst 1,241; 19.8% cut short by the
deadline (45% after a one-turn fast move, 23% after their charged move), 0.2% left with no complete round. Real time
against unhurried (`realtime_trial.py --pairings 600 --crowd 1000 --samples 32 --seed 2707`,
`runs/task27-realtime-vs-unhurried-samples32-new-pauses.out`): **head to head 49.8% ± 1.9; against the crowd 73.4% against
74.6%, −1.2 ± 0.9**; real time minus the trained bot +7.6 ± 3.0. So under the measured pauses the deadlines cost about a
point against the crowd and nothing head to head. Live, 32 imagined battles keeps its head-to-head gain and is about level
with the current engine against the crowd (+1.7 ± 1.9 unhurried, less about 1.2). If the owner prefers a margin for slower
machines, 16 imagined battles (51.4% ± 1.7, +4.6 ± 2.7 crowd unhurried, median 116 ms) would be cut far less often.

### Which opening book fits only its own field (2026-10-18, the owner: "try not to overfit")

Three books for Melmetal / Altaria / Jellicent, built on the usual field, the PvPoke field and the mixed field
(`--field mixed`: 30 most-used leads plus the usual top 50, 55 leads; `runs/openings_mixed.out`), each checked on
4,000 fresh battles (seed 77, not used to build any of them) on every field (`--book`, `runs/openings_cross.out`).
Points gained over the bot without a book:

| book built on \ checked on | usual field | PvPoke field | mixed field |
|---|---|---|---|
| usual | +2.8 ± 0.9 | +4.6 ± 1.2 | +3.9 ± 1.1 |
| PvPoke | +0.2 ± 0.9 | +5.4 ± 1.2 | +4.3 ± 1.1 |
| mixed | +1.2 ± 0.7 | +5.4 ± 1.2 | +5.2 ± 1.1 |

The PvPoke-only book is overfit: nothing on the usual field. The mixed book meets the rule (gains on the mixed field
on fresh battles, no loss on the usual) and is the one to use: `data/openings/melmetal-altaria-jellicent-mixed.json`
(18 of 55 leads get a plan; Cramorant and Mimikyu: stay in). The usual book is the most even across fields, a
sign that much of what a book learns is about our own team, not the field.

### Task 30, the engine's own settings: interim, stopped after 12 of 30 generations (2026-10-19)

`evolve_rules.py --run engine-1 --engine --generations 30 --population 16 --pairings 300` (`runs/engine-1.out`; three
workers for generation 1, then twelve; `engine_versus.py` with the cache fix). Fitness is head to head against the current
engine on 300 pairings per candidate, so each score is noisy (about ± 3) and the best of 16 is flattered.

| Generation | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Best | 52.8% | 56.8% | 54.3% | 56.5% | 56.2% | 56.0% | 59.8% | 56.5% | 57.2% | 52.8% | 55.9% | 55.2% |
| Median | 48.6% | 50.8% | 52.0% | 51.8% | 52.4% | 52.8% | 54.6% | 54.2% | 54.5% | 51.2% | 54.0% | 53.6% |

The median rose to about 54% by generation 7 and has not improved since. The search moved towards about 30 imagined
battles and a 60-turn look-ahead (the best seen: samples 31, horizon 60, edge 0.067, margin 0.028), so generations slowed
from under an hour to about two and a half. It was stopped after generation 12 (about 20 hours) to free the machine.

**Not yet established.** Nothing here has been re-scored on fresh battles, and the fitness is head to head only: task 27
found that a longer look-ahead can win head to head without helping against the crowd or PvPoke's AI. No setting is adopted
from this run. To finish it, from the repository root (the saved state is in `runs/evolve/engine-1/state.json`):

```bash
python3 scripts/evolve_rules.py --run engine-1 --engine --workers 12 --generations 30 --population 16 --pairings 300   # resume, or skip
python3 scripts/evolve_rules.py --run engine-1 --engine --workers 12 --final --final-pairings 600                     # re-score the five best
```

then confirm the best with `engine_versus.py` on a fresh seed (head to head, crowd, PvPoke) and time it with
`realtime_trial.py --timing` against the live budgets.

## Team choice on the mixed field, cross-checked on the usual one (2026-10-18)

`scripts/roster_teams.py --field mixed --rival bot` (the default field is now mixed): all 3,366 line-ups from the
owner's 20 Pokémon, opponents piloted by the same bot; `runs/roster_teams_mixed.out`, `data/roster_teams_mixed.json`.
Then the 15 finalists rechecked on the usual field (80% listed good teams, `--recheck --field standard --listed 0.8`,
`runs/roster_teams_mixed_on_standard.out`). 6,000 fresh battles each:

| line-up (lead first) | mixed field | usual field |
|---|---|---|
| Vigoroth / Altaria / Stunfisk | 64.4% ± 1.2 | 45.3% ± 1.3 |
| Vigoroth / Stunfisk / Umbreon | 64.1 | 47.4 |
| Jellicent / Stunfisk / Vigoroth | 63.6 | 67.1 |
| Jellicent / Stunfisk / Umbreon | 60.2 | 69.9 |
| Jellicent / Melmetal / Altaria | 59.4 | 71.2 |
| Altaria / Melmetal / Jellicent | 50.6 | 55.5 |
| Melmetal / Altaria / Jellicent | 48.0 | 53.8 |

The mixed field's winners with a Vigoroth lead are overfit to it: below 50% on the usual field. Robust on both:
Jellicent leads. **The owner's own three with Jellicent leading** (59.4 / 71.2) are as good as any line-up on both
fields together; with Melmetal leading they are 11 to 17 points worse. The opening book (built for a Melmetal lead)
brings that lead to about 53% on the mixed field, still below a Jellicent lead.

## Answers whenever a new opposing Pokémon comes in, not only the lead (2026-10-18, idea from the owner's friend)

`pogo.openings.Answers` (book {ours: {theirs: plan}}, starting when theirs arrives: lead, switch or replacement) and
`scripts/answers.py`; Melmetal / Altaria / Jellicent, 55 opposing Pokémon, up to 500 battles per pair, each plan
replayed from the arrival on the same battles; `runs/answers_1.out`, `data/openings/melmetal-altaria-jellicent-answers.json`.
21 pairs got a plan (14 with Melmetal in, mostly the opening ones; 4 with Altaria in; 3 with Jellicent in, +2 to +8).
Check on 4,000 fresh battles, points over the bot with no book:

| | answers book | opening book alone | answers on top of the opening book |
|---|---|---|---|
| mixed field | +4.8 ± 1.2 | +5.7 ± 1.1 | −0.9 ± 1.1 |
| usual field | +1.9 ± 1.2 | +0.9 ± 0.7 | +1.0 ± 1.2 |

**Not adopted: fixed plans help in the opening only;** after that the bot's own play is as good as any fixed plan.
The friend's examples: Ninetales arriving on Melmetal, best plan one fast move then Jellicent (+6 ± 5); Shadow
Ninetales, Sableye, Shadow Sableye: nothing beats the bot's own play, including Double Iron Bash then Altaria.

## The evolved rulebook is the default (2026-10-19, the owner)

`Planner()` (and so the trained bot, the engine's look-ahead bot and the website) now uses `EVOLVED_RULES` (task 30:
alone 54.0% ± 0.9 against the standard rules, the bot on top 51.6% ± 0.8). Kept as they were, so that results stay
comparable: the crowd (`varied_settings` now sets the six values it used to take from the defaults to
`STANDARD_RULES`), and the quick player inside the rulebook's own shield look-ahead (`_rollout`, with which the
evolved rules were found). Rule tests that pin mechanisms down use `STANDARD_RULES`. Checks: 257 tests OK (7
skipped), PvPoke 108 of 108 and 132 of 132 with form-changers. Follow-up: task 33 retrains the networks on these rules;
numbers for "the bot" measured before today are on the standard rules.

## The owner's team played out thousands of times against PvPoke's most-played teams (2026-10-19, the owner)

`scripts/best_lines.py` (the trained bot on our side choosing at random a third of the time at shields, swaps and
replacements and a tenth at throws; their side the bot with shifted habits; each battle summed up as a line: what
our lead did, our first three shield calls, the lead's first charged move, whom we sent in after the first faint).
Melmetal / Altaria / Jellicent, Melmetal leading, against the five most-played teams in PvPoke's data, 3,000 battles
each plus 600 of the bot alone (`runs/best_lines_1.out`, `runs/best_lines/melmetal-altaria-jellicent.json`):

| Their team | bot alone | what stands out |
|---|---|---|
| Melmetal / Galarian Corsola / Cramorant | 8% ± 2 | swapping Melmetal out at once to Altaria 30% ± 5 against staying 11% ± 1 (the bot stays three times in four) |
| Melmetal / Altaria / Shadow Ninetales | 74% ± 3 | Melmetal stays and opens with Dynamic Punch (41% against 21% for Double Iron Bash); swapping out at once 10–20% |
| Cramorant / Jumpluff / Stunfisk | 67% ± 4 | stay a while, then Jellicent; Double Iron Bash first; Altaria after the first faint |
| Cramorant / Marowak / Shadow Sableye | 97% ± 1 | the bot's own play is close to perfect |
| Stunfisk / Cramorant / Mimikyu | 7% ± 2 | no line above 12%: a team problem, not a play problem |

Line scores include the random choices made elsewhere in those battles, so they are compared with each other, not
with the bot's own score; lines seen fewer than about 50 times are flattered as the best of many small groups.

## The website games, replayed from their logs (2026-10-19)

22 games came back from the store (`import_played.py --store`): 14 by the owner (6 won, 8 lost against the engine),
8 by a friend with a Water team against an all-Fire team (all won; line-up 100%). `scripts/losses.py --played` now
replays a game from its log (the person's choices and the bot's logged moves, `Logged`), so a game replays exactly
whatever version of the bot played it (13 of 14; one has two of the bot's switches logged on the same turn), and
tries every other choice at the loser's decisions: the owner's in games they lost, the bot's in games it lost
(`runs/losses_website_2.out`, `runs/losses/played.jsonl`). With Melmetal / Altaria / Jellicent, choices better by 0.3
or more: staying in with Melmetal against Annihilape (25–38%) where swapping to Altaria at once won 62–75% (the
opening book's plan too); Double Iron Bash into Thievul (8%) where waiting for Dynamic Punch won 75%; a nearly
fainted Altaria left against a fresh Clodsire (8%) where Jellicent won 75%. The bot's: a Corviknight shield at 34%
health (33%; no shield 83%), and Corviknight switching to Shadow Annihilape (0%) where Altaria won 54%. Its Moonblasts
into Jellicent (the owner's note) were not among its losing choices: neutral on Jellicent and its hardest-hitting
move. Hindsight flatters losses (task 26); these are examples to judge, not rules.

## Bait rates, and calls calibrated to the risk and reward of each bait (2026-10-19, the owner): measured, not adopted

`scripts/bait_rates.py` (`runs/bait_rates.out`): in 4,000 battles on the mixed field, of 29,918 charged moves thrown
while the defender had a shield and the thrower could pay for both, the softer move came 34% of the time: 30% from
the trained bot, 47% from the crowd; 57–61% when the softer move would knock out, 20% (bot) and 45% (crowd) when only
the harder would, 25% and 44% when neither would. Shields and health matter little. Defenders shielded the harder
move or let the softer through 48% of the time (not shielding a hard hit can be a choice, so this is not an error rate).

The owner: a bait rate calibrated to how risky or rewarding the bait is. As a two-by-two game, the bait rate at
which the defender is indifferent is p = saves / (saves + wastes) (what shielding the harder move saves, what
shielding a bait wastes); the shield rate at which the thrower is indifferent is the matching ratio of what the
harder move adds if taken to what it loses if shielded. `bait="calibrated"` and `guess="calibrated"` start from
those, move towards the opponent's record (worth `belief` observations), play the mix while the record is within
0.05, and best-respond once it is not. The trained bot on top, against the current bot, mixed field, 4,000 pairings
both ways and 4,000 crowd battles (`bot_on_rules.py ... --field mixed`, seed 3101, `runs/bait_calibrated_1.out`):

| | head to head | crowd, paired |
|---|---|---|
| both calibrated | 49.2% ± 0.6 | −1.1 ± 0.8 |
| shield calls only | 49.1% ± 0.6 | −1.1 ± 0.8 |
| bait choice only | 49.8% ± 0.5 | −0.2 ± 0.2 |

No gain, a small loss from the shield calls. The current defaults stay (`bait="mix"`, already the equilibrium mix
from the same values; `guess="read"`, a 50% prior read towards the opponent's record). Starting the read from the
equilibrium and mixing loses against players who are not at it: these opponents bait far less than evenly (the bot
a quarter of the time), and a fixed 50% that is soon corrected exploits that better than playing the safe mix.

## The Melmetal mirror, one on one, solved (2026-10-19, the owner)

`scripts/mirror.py` (`runs/mirror_melmetal.out`): each side has 72 plans (cheaper or dearer move for each of its first
three throws while the other has a shield; shield, take it, or shield only if the dearer move was affordable for the
first two throws it faces), every plan against every plan, the table solved for both sides' best mixes; the trained
bot against itself as a check (it agrees in every case). Owner's Melmetal (attack 119.9, 145 HP) against PvPoke's
default (attack 121.0, 146 HP), from full health:

| shields ours-theirs | ours wins, best play | ours wins with the higher attack (`--swap`) |
|---|---|---|
| 2-2 | 0% | 100% |
| 2-1 | 100% | 100% |
| 1-2 | 0% | 0% |
| 1-1 | 50% (every line a draw: both Dynamic Punches land, both faint together) | 50% |

Both reach 45 energy on the same turn, so both throw Dynamic Punch together and the stronger attack goes first;
with two shields each the third punch decides, and the faster one lands it. No choice of bait or shield changes any
of these: the mirror is decided by shields in hand and by attack, not by play. The owner's Melmetal loses the tie to
a default-IV one; the opening book's answer to a Melmetal lead (four fast moves, then Altaria) fits.

**The owner: "if I bait once and they shield, I outpace them."** The plans above baited only as soon as the cheaper
move was affordable (35 energy), when a defender counting energy knows it cannot be Dynamic Punch. With the real
bait added (Double Iron Bash once Dynamic Punch is affordable too, 243 plans a side, `runs/mirror_melmetal_2.out`):
shield it and the baiter keeps 10 energy, throws its next Dynamic Punch at turn 59 against 80, and wins. At 2-2 the
side that loses ties now wins **44.4%** with best play (from 0%); 1-1 stays a draw, uneven shields stay decided.
The trained bot against itself still gives 0%: it always shields on its last Pokémon, so it can be baited this way.
Deciding the last Pokémon's shields by the rulebook's look-ahead instead (`last_always=False`, bot on top against
the current bot, mixed field, seed 3201, `runs/last_shield_1.out`): 48.9% ± 0.5 head to head, −1.0 ± 0.5 against the
crowd. Worse on average against these opponents, who rarely bait at full energy; `last_always` stays True. A real fix
needs the endgame solved as this game is (the guessing between baits and shield timing), not a look-ahead.

## Last-Pokémon fights solved as a game (2026-10-19, the owner): neutral, +1 against a baiter, not adopted

`pogo/finale.py`: once both sides are on their last Pokémon, `Finale` solves the rest as `mirror.py` does (plans of
the next two throws: cheaper move at once, the bait at the dearer move's energy, or the dearer; and the next two
shield calls: shield, take it, or shield only if the dearer move was affordable; every plan against every plan from
the position as it stands, both mixes solved), plays a plan drawn from its mix, and solves again after every charged
move (about 0.4 s a solve, about one a battle). `scripts/finale_trial.py`, mixed field, seed 4401
(`runs/finale_trial_1.out`):

| | solved | as it is |
|---|---|---|
| head to head, 2,000 pairings both ways | 50.0% ± 0.6 | |
| against the crowd, 3,000 battles (paired) | 66.0% ± 1.7 | 66.5% ± 1.7 (−0.5 ± 0.6) |
| against a baiter that opens every last-Pokémon fight with the bait at full energy, 2,000 pairings | 51.2% ± 0.6 | 50.2% ± 0.6 (+1.0 ± 0.6) |

The baiter hardly punishes the bot's always-shield (50.2%): few endgames turn on that one bait. Solving them gains
a point against it and nothing against the bot or the crowd, so it stays an option (`Finale`), off by default; worth
switching on if real opponents turn out to bait at full energy on their last Pokémon often.

## Farming right up until they have a move, again (2026-10-20, the owner): no gain

In the 14 website games (replayed from their logs), 46 of the bot's 100 charged moves came while the person still
needed two or more fast moves for a move, 44 of them with room to keep farming and not for a knock-out; those games
were played on the standard rules (`hold_cost` 0.5, the hold rule gives up when the wait costs half the health left).
On today's evolved rules (`hold_cost` 0.9), in 400 simulated battles on the mixed field, 250 of 2,631 throws were
early in that sense (above 30% health): in 94 the rulebook was still farming and the networks threw anyway, in 156
the rulebook itself threw because waiting cost too much health. Both closed off, the trained bot against the current
one, mixed field, seed 3301 (`runs/respect_hold_1.out`): the networks may not cut farming short (`respect_hold=True`)
50.1% ± 0.5 head to head, +0.1 ± 0.5 against the crowd; and with any health cost allowed (`hold_cost=2.0`) as well
49.6% ± 0.6, −1.0 ± 0.7. The farming window already throws at the best-timed fast move within it (`_latest_good_turn`:
the moment that gives their fast move in progress the fewest free turns, the latest of equally good). Nothing kept.

## Throw timing and the last hit (2026-10-20, the owner): the bot mostly does both; enforcing them, no clear gain

Two rules already in the rulebook: throw on the fast move that leaves the opponent's fast move in progress the fewest
free turns (it lands in full when a charged move is thrown), and throw before a fast move would knock us out
(`last_gasp`). Measured as free turns beyond the best timing within reach (`scripts/timing_check.py` on the website
games; the same count in 400 simulated battles), leaving out knock-outs and throws when about to faint:

| | best timing | 1 turn more | 2+ more | fainted to a fast move with a move ready |
|---|---|---|---|---|
| the owner, website games | 62 of 79 | 12 | 5 | 4 of 35 faints |
| the bot (engine, older rules), website games | 62 of 78 | 9 | 7 | 4 of 27 |
| the trained bot now, simulated | 1,943 of 2,037 | 73 | 21 | 74 of 779 |
| the same, networks not allowed to break either rule | 1,997 of 2,039 | 32 | 10 | 80 of 771 |

(Two Pokémon with two-turn fast moves in step cannot avoid one free turn, so it is counted against the best timing in
reach, not against zero.) `Learner(respect_timing=True)` against the current bot, mixed field, seed 3401
(`runs/respect_timing_1.out`): 50.3% ± 0.5 head to head, +0.4 ± 0.6 against the crowd: no clear gain; left off.
On the phone the other half matters: a charged-move tap before our own fast move has registered can lose that fast
move, so the live controller should tap only once the fast move has landed (task 13).

## How well we can predict the opponent (2026-10-20, the owner: "try very hard to predict the opponent")

`scripts/predict_bench.py` (`runs/predict_bench_1.out`): the opponent's decisions at every turn they could throw (fast
move, either charged move, switch) and every shield call, from 150 battles on the mixed field against each kind of
opponent and from the owner's 14 website games. Each style (the trained bot; the bot with shifted habits, 6 of them;
the human-like style, 6; PvPoke's AI) is asked what it would do in the copied position. Predictors: `bot` (they play
like us: what the engine assumes), `mix` (task 28's fixed style mix), `profile` (that mix reweighted by their shield
and bait rates: task 28's profile=1), `match` (reweighted by how likely each style made every decision so far in
the battle), `habit` (their own shares so far). Geometric-mean chance given to what they did / top guess right:

| throw, fast or switch | bot | mix | profile | match | habit |
|---|---|---|---|---|---|
| the bot (3,078) | 87% / 98% | 79 / 98 | 81 / 97 | 86 / 98 | 36 / 66 |
| the crowd (2,847) | 39 / 76 | 60 / 78 | 58 / 78 | 64 / 84 | 36 / 63 |
| human-like style (3,259) | 58 / 87 | 69 / 88 | 68 / 87 | 73 / 91 | 38 / 67 |
| PvPoke's AI (1,885) | 16 / 51 | 42 / 54 | 56 / 66 | 78 / 92 | 31 / 51 |
| the owner (249) | 18 / 55 | 29 / 56 | 27 / 57 | 27 / 57 | 34 / 59 |

| shield calls | bot | mix | profile | match | habit |
|---|---|---|---|---|---|
| the bot (723) | 91 / 98 | 82 / 97 | 84 / 98 | 87 / 98 | 43 / 43 |
| the crowd (567) | 38 / 69 | 54 / 69 | 54 / 69 | 56 / 75 | 45 / 51 |
| human-like style (644) | 60 / 84 | 71 / 85 | 72 / 85 | 72 / 87 | 43 / 43 |
| PvPoke's AI (310) | 9 / 22 | 22 / 22 | 25 / 22 | 38 / 25 | 58 / 93 |
| the owner (72) | 39 / 69 | 53 / 69 | 52 / 69 | 53 / 71 | 44 / 50 |

Matching every decision recognises a simulated opponent within the battle (close to the right model for each),
where profiling by shield and bait rates barely moves from the fixed mix: the calibrated rates of the bot, the
varied bot and the human-like style are nearly the same (data/opponent_styles.json), which is why task 28's profile
could not tell a copy of our engine from the crowd. A real person is predicted badly by every style (the owner:
about 27% per decision, against 87% for the bot predicting itself); their own running habits do best. Next: the
engine with `match` instead of `profile`, and a human style fitted to real decisions as games come in.

## The engine weighing opponent styles by every decision (2026-10-20): better against the crowd and PvPoke, level head to head

`Engine(opponents="mix", matching=True)`: at every turn the opponent could throw, and at every shield call of theirs,
each style is asked what it would have done in their place (in a battle imagined from what we can see: their unseen
Pokémon are drawn, not read), and its weight moves with how likely that made what they did (`scripts/predict_bench.py`
showed this recognises simulated opponents within a battle where task 28's shield-and-bait profile cannot). Against
the confirmed engine (4 imagined battles), mixed field, seed 3501 (`runs/matching_1.out`):

| | head to head, 2,000 pairings both ways | crowd, 2,000 (paired) | PvPoke's AI, 1,000 (paired) |
|---|---|---|---|
| the style mix, profiled (task 28) | 49.6% ± 1.3 | +2.9 ± 2.1 | +7.0 ± 2.5 |
| the style mix, matched | 49.0% ± 1.3 | +4.3 ± 2.1 | +9.2 ± 2.4 |

(Confirmed engine: crowd 70.8% ± 2.0, PvPoke 81.0% ± 2.4.) Matching gains more than profiling against both outside
opponents; head to head both stay level within the margin (the engine it plays is not one of the styles, so it is
never recognised exactly). The adoption rule asks for a head-to-head gain, so not adopted on this run; on a fresh seed
and the usual field it would be the owner's call whether level head to head with these outside gains is enough.

Also found on the way: PvPoke's AI failed after a form change (Morpeko's Aura Wheel changes id), and in a worker
the error (StopIteration) ended `engine_versus.py`'s result loop quietly, as if all jobs were done; both fixed.
## Task 33: the networks retrained with form inputs, two play-outs per option and mixed opponents (2026-10-21, on the cloud machine)

The owner's one job, run on the cloud machine instead of the PC (the owner's call): `decide.py --run qnet-1 --forms
--playouts 2 --field mixed --both-sides 0.5 --start runs/general-decide/q.npz --workers 4`, five rounds of 80 minutes
(`runs/qnet-1.out`; the container restarted 25 minutes into round 2, which was redone from the saved round 1 with
`--resume`, so the log shows two runs, of one and four rounds). 26,335 battles, 1,046,177 decisions with every option
played out twice (227k shield, 79k throw, 157k swap, 35k replacement, 548k mid-matchup swap); margin 0.02 chosen on
validation, and +6.0 ± 2.0 over the (evolved) rulebook on decide.py's own 3,000-battle final test.

Against the current model, 4,000 battles against the crowd and then every pair of teams both ways:

| Field | Against the crowd, new minus current | Head to head | Task 33's condition |
|---|---|---|---|
| Mixed (`runs/qnet-1-compare-mixed.out`, seed 3301) | **+2.5 ± 1.6** (68.7% against 66.2%) | 51.2% ± 1.3 | crowd: beyond the margin, met; head to head: above 50% beyond the margin, **missed by 0.1 point** |
| Usual (`runs/qnet-1-compare-usual.out`, seed 3302) | -0.5 ± 1.5 | 49.8% ± 1.3 | loses neither beyond its margin: met |

Better against realistic teams and the crowd, level head to head, and no loss on the usual field; but the
head-to-head condition is not met, so by the rule it is **not adopted** and the confirming run on seed 3303 was not
started. The model is kept at `runs/qnet-1/q.npz` (margin 0.02). Whether +2.5 on the mixed field with head to head
level is enough is the owner's call; if so, the confirmation on seed 3303 comes first, read with the same rule.
