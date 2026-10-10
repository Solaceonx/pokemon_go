# Project status, for anyone picking this up

Read this before suggesting improvements. It says what the project is, what has been
measured, what has already been tried and did not work, and what is open. The README
says how to run things.

Last updated 2026-10-10.

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
| State tracker | `pogo/tracker.py`, `scripts/track.py` | Builds the full game state from "looks" at the screen; tested on simulated cameras only |
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
- **Shortlisting teams by one-on-one coverage score**: a team that ranked 3,818th of
  19,024 on that score came 4th in real battles, so the score is a poor filter.

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
0.2 or 0.5 (50.4% ± 0.7 and 50.2% ± 0.8 head to head). Left at zero. Setting up a sweeper is
not attempted.

Where the standard player stands, against today's crowd (four in five opponents use each
rule) on the same 4,000 battles:

| Player | Wins |
|---|---|
| Rules as of 10 October | 50.5% ± 1.5 |
| + hold, throw before fainting, timed farming | 53.1% ± 1.5 (+2.6 ± 1.3) |
| + win the switch | 54.7% ± 1.5 (+1.6 ± 0.8) |
| Trained bot on top (not yet retrained on these rules) | 65.2% ± 1.5 (+10.5 ± 1.6) |

Today's rules beat the rules of 10 October 57.2% ± 1.2 head to head.

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

## Known gaps in the simulator

- Form-changing Pokémon are left out (Aegislash, Mimikyu, Cramorant, Morpeko).
- Switching and chance-based stat changes have not been checked against PvPoke.
- The real length of a charged move on the clock is unconfirmed; 10 seconds is assumed.
- Opponents' stats are assumed typical for the species.
- Every charged move counts as fully charged.

## Open directions

Each of these has a full brief in [`tasks.md`](tasks.md). Strategy rules, retraining and team choice
are tasks 18 to 21 there, with the commands for each at the top of that file.

- **PvPoke's AI as an outside opponent.** Brief and bundle are in `handoff/`
  (`pvpoke_port_instructions.md`). Acceptance test: `scripts/check_pvpoke_ai.py`.
- **Opponents that use our own learned decisions**, mixed with the old crowd, keeping the
  old crowd as a fixed yardstick (`scripts/decide.py --opponents ... --resume`). Built,
  not yet run.
- **Exact endgames.** A single matchup has few distinct positions (about 567,000 with one
  shield each in one sample), so last-Pokémon positions can be solved exactly.
- **Predicting the opponent's hidden Pokémon** from real team combinations (task 8).
- **Adversarial training**: an opponent trained to beat our bot, then training against it
  (task 14).
- **Handling uncertain information**: training through the tracker with flawed cameras
  and wrong assumptions (task 15).
- **Opponent stats from CP, charge-move priority and damage per hit.** Secondary.
- **Team list weighted by teams seen in real games** (`seen` counts in `data/teams.json`).
- **Footage.** `docs/what_to_see.md` lists what recognition must read;
  `docs/agent_instructions.md` is the brief for an agent turning videos into looks.
- **The phone.** Whether iPhone Mirroring passes synthetic drags is untested.

## Rules for proposing a change

- Say which script measures it and against what. An idea that cannot be measured in the
  simulator should say what data it needs.
- Report results as a score with a margin, on battles not used for tuning.
- Training and testing must run unattended, on one core, without a language model in the
  loop.
- The owner is short on assistant usage: prefer changes that are small, local and cheap
  to verify.

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

