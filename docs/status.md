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
| Bounded exact endgame player | `pogo/endgame.py` | Revealed positions with at most two survivors each; Learner fallback; [checks and results](endgame.md) |
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
| **Per-decision learning, one model for any team (shield, throw, swap, replace)** | **+13.6 ± 1.9 points over the Planner on random teams (71.3% against 57.7%), 3,000 fresh battles** |
| The same model piloting Melmetal / Jellicent / Altaria | +13.2 ± 1.9 points over the Planner (79.0% against 65.8%), 3,000 fresh battles |
| Per-decision learning, one team, shield and throw decisions only | +8.1 ± 1.8 points over the Planner, 3,000 battles |
| Tracker with a perfect simulated camera | Opponent's energy exact on 99% of turns; Planner plays as well from it as from the truth (50.6% ± 4.0) |
| Tracker with a rough camera (1 look in 5 missed, coarse bars, move not named) | Costs about 7 points (42.7% ± 4.0) |
| PvPoke's AI (`pogo/pvpoke_ai.py`), one-on-one, 2,000 battles per seed, seeds 101 and 202 | Beats the Planner (42.6% / 44.4%, ± 1.4) and the Learner (40.8% / 42.0%, ± 1.4) |
| PvPoke's fast/charged choice in the final one-on-one only (`pogo/hybrid.py`), `scripts/check_endgame_throws.py`, seeds 101 and 202 | Against PvPoke one-on-one: 49.3% / 49.0% ± 0.6 for both players (mostly a mirror there). 3v3 unchanged within margins, no consistent sign: Learner against varied / expert / Planner moves +0.8 / +1.3 / −1.8 on seed 101 and −0.5 / −2.7 / +0.1 on seed 202 (margins about ± 2.5 per cell) |

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

## Team list

`data/teams.json` is the wide list. Best teams, as win share piloted by the Planner
against a field of half finalists and half random teams, 600 battles each:
Altaria / Charjabug / Corviknight 73.2% ± 3.5; Altaria / Shadow Charjabug / Corviknight
70.9% ± 3.6; Corviknight / Tinkaton / Mandibuzz 66.1% ± 3.8; the owner's Melmetal /
Altaria / Jellicent 64.7% ± 3.8 (4th of the 25 fully tested). Tinkaton is on 39 of the 81
saved teams, Shadow Annihilape on 31, Corviknight on 25. "Best" means best with this
pilot against this field; the `seen` counts for teams met in real games are all still zero.

## Simulator speed

Task 11 (2026-10-09): small simulator speedup, with identical checked results.
Skip work and training snapshots when both fast moves are still in progress; avoid
unused log formatting, equal-stage damage scaling and system seeding of cloned battle
RNGs. Baselines were recorded before code edits. Measured with
`/Users/marco/Developer/pokemon_go/.venv/bin/python scripts/arena.py --pairings 200 --seed 0`,
one process/core, 400 battles per row. Rates are the script's `perf_counter` timings
(excluding game-data loading), rounded to battles/s; these are single-run measurements.

| Matchup (Planner unless stated) | Score before = after, 95% margin | Won/lost/drawn before = after | Battles/s before → after |
|---|---|---|---|
| Expert model | 57.5% ± 3.9 | 230/170/0 | 121 → 125 |
| Expert model against itself | 47.9% ± 3.5 | 191/208/1 | 161 → 167 |
| Masher | 82.6% ± 3.4 | 330/69/1 | 365 → 371 |
| Spammer | 59.1% ± 4.3 | 234/161/5 | 212 → 216 |
| Baiter | 51.9% ± 4.2 | 206/191/3 | 196 → 201 |
| Straight | 50.9% ± 4.0 | 202/195/3 | 209 → 216 |
| Shield saver | 67.9% ± 4.2 | 270/127/3 | 168 → 176 |
| Stayer | 66.0% ± 4.2 | 264/136/0 | 313 → 320 |

Training collection: 20 source battles took 3.038273 s before and 2.852242 s after
(6.582688 → 7.012027 source battles/s, including all option play-outs). Used
`scripts.decide.collect(None, pool, None, .03, crowd, 21, 0, draw)` with
`pool = GameData().meta(50)`, `crowd = lambda rng: varied(rng, pool)` and
`draw = lambda rng: rng.sample(pool, 3)`. To fix the work instead of the time budget,
patched `decide.time.time` with `unittest.mock.patch.object` and
`side_effect=itertools.count()`; timed the call with `time.perf_counter`. All four
BLAS/OpenMP thread limits were 1. SHA-256 hashes of each head's feature and outcome
arrays were identical: 86 shield, 34 throw, 78 swap and 20 replacement examples.

Acceptance checks ran: `scripts/check_pvpoke.py` printed
`108 of 108 PvPoke battles reproduced exactly` both before and after; all eight arena
scores, counts and average lengths matched; `python -m unittest discover tests`
passed all 27 tests, including new stage-rounding, idle-timeout and clone tests.
Additional comparison against the original source matched 9,423 turn states, logs,
hits and RNG states across 100 battles, plus every collected feature and option
outcome in ten battles each with and without learned players (all throw decisions
sampled). No long training run was attempted; the modest timing gains may vary with
machine load. A fixed time budget will now collect more examples, so it is the same
fixed battle sequence, rather than a timed training run, that remains identical.

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

## Endgames, measured

In 600 simulated battles, 46% reached last Pokémon against last Pokémon: 32% of all
battles with no shields on either side, 13% with shields on one side, 2% on both. That
final one-on-one lasted a median of 6 fighting turns, so it holds few decisions. A full
library of solved one-on-ones for every pair, health and energy would be enormous;
solving one from the actual position is small (about 32,000 positions with no shields).

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

Each of these has a full brief in [`tasks.md`](tasks.md).

- **PvPoke's AI as an outside opponent.** Brief and bundle are in `handoff/`
  (`pvpoke_port_instructions.md`). Acceptance test: `scripts/check_pvpoke_ai.py`.
- **Opponents that use our own learned decisions**, mixed with the old crowd, keeping the
  old crowd as a fixed yardstick (`scripts/decide.py --opponents ... --resume`). Built,
  not yet run.
- **Larger exact endgames.** Task 9 implemented bounded search and measured a small gain;
  many two-against-two positions still exceed the budget. See [`endgame.md`](endgame.md).
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
