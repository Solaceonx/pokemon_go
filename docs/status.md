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
| Team search | `scripts/teams.py` | First pass was too narrow; a wider rerun was in progress at the time of writing |
| Phone link | `helper/phonectl.swift`, `pogo/phone.py` | Compiles; never run against a phone |

## Results so far

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

## Known gaps in the simulator

- Form-changing Pokémon are left out (Aegislash, Mimikyu, Cramorant, Morpeko).
- Switching and chance-based stat changes have not been checked against PvPoke.
- The real length of a charged move on the clock is unconfirmed; 10 seconds is assumed.
- Opponents' stats are assumed typical for the species.
- Every charged move counts as fully charged.

## Open directions

- **PvPoke's AI as an outside opponent.** Brief and bundle are in `handoff/`
  (`pvpoke_port_instructions.md`). Acceptance test: `scripts/check_pvpoke_ai.py`.
- **Opponents that use our own learned decisions**, mixed with the old crowd, keeping the
  old crowd as a fixed yardstick (`scripts/decide.py --opponents ... --resume`). Built,
  not yet run.
- **Exact endgames.** A single matchup has few distinct positions (about 567,000 with one
  shield each in one sample), so last-Pokémon positions can be solved exactly.
- **Guessing the opponent's hidden Pokémon.** Needs data on which Pokémon are run
  together.
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
