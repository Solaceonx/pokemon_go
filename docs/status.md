# Project status, for anyone picking this up

Read this before suggesting improvements. It says what the project is, what has been
measured, what has already been tried and did not work, and what is open. The README
says how to run things.

Last updated 2026-10-09.

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

## Known gaps in the simulator

- Form-changing Pokémon are left out (Aegislash, Mimikyu, Cramorant, Morpeko).
- Switching and chance-based stat changes have not been checked against PvPoke.
- The real length of a charged move on the clock is unconfirmed; 10 seconds is assumed.
- Opponents' stats are assumed typical for the species.
- Every charged move counts as fully charged.

## Open directions

Each of these has a full brief in [`tasks.md`](tasks.md).

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
