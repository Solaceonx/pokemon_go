# Engine lab: what the creators do that the engine does not (lab-creators, 2026-11-24)

## What was built

**`scripts/lab/creator_exam.py` — the creator exam**
- A decision-quality benchmark that is not win rate.
- Decisions: 657 from the 29 creator records that pass every check: switch 157, shield 114, throw 168, hold 218 (new).
  A hold is the first look in each stretch of one matchup where the tracker's ledger puts the player 8+ energy over
  their cheapest move and they kept fast-moving.
- Every legal first action is played to the end of the battle 100 times with the same dice for every action. Our side
  is continued by the trained bot; their side is the crowd, or a people-like opponent (the "human" style, with shield
  calls drawn at the creators' shield network's probability).
- Reported per decision kind: agreement with the player; regret against the player (the engine's action's value minus
  the player's); shortfall to the best action; "near best" (share within 0.03 of the best action); paired
  engine-against-engine differences; how predictable the shield calls are from the coarse situation.
- Caches committed: values `runs/lab-creators/exam/values-{crowd,people}-g100-s1.json`, and answers for the engines below.
- `league_scores(specs, workers=, seed=)` for the lab league (score = share within 0.03 of best).

**`scripts/lab/creator_habits.py`**: shield rates by situation, bait share, spare energy at the throw and switch timing,
for every charged move in the creator records from both sides, with predictability (leave-one-record-out majority
copying within coarse situations, and same call in identical situations across records). Output
`creator_habits_all84.txt` (77 usable records) and `creator_habits_passed29.txt`.

**`scripts/lab/bot_habits.py`**: the same measures for any engine spec in the simulator. Output
`bot_habits_bot_vs_bot.txt` (1000 battles) and `bot_habits_website_vs_bot.txt` (60 battles).

**How to run**

    python -X utf8 scripts/lab/creator_exam.py "<spec>" website --opponent people --workers 2

About 1 minute for a website-type engine on 2 workers with the committed values; seconds for bot-type specs.
`--opponent crowd` for the second judge, `--limit 60` for a smoke run (about 10 s), `--asks 3` for mixing engines.
Building a value cache from scratch takes about 10 minutes per opponent on 2 workers.

## Patterns: what good players do (all 84 records unless marked; humans' energy is the tracker's ledger)

### 1. The first shield goes early, and the second is used too

When the defender is not on their last Pokémon:

| Situation | Creators | Their opponents | Bot (sim, 1000 battles) | Website (sim, 60) |
|---|---|---|---|---|
| All shield chances | 37% ± 6 | 42% ± 6 | 34% ± 1 | 30% ± 5 |
| With two shields | 43% ± 8 | 45% ± 8 | 33% ± 2 | 27% ± 6 |
| With one shield | 30% ± 8 | 39% ± 8 | 35% ± 2 | 35% ± 10 |
| First charged move faced | 43% ± 11 | 44% ± 11 | 26% ± 3 | 27% ± 11 |
| Hit under 30% of health | 19% ± 14 | 21% ± 21 | 6% ± 2 | 4% ± 7 |
| Move would knock out | 60% ± 11 | 61% ± 11 | 51% ± 3 | 45% ± 11 |

- Per creator, two shields up against one: Reis 49% (20/41) against 28% (11/39); ItsAXN 38% (30/78) against 23%
  (18/77); Henry is the exception, 48% against 59%.
- Examples: Henry `2904735277-002` 0:07.5 shields Kingdra's Swift (60 energy, so Surf was also affordable), then Surf at
  0:31.5, both shields gone on the lead. ItsAXN `2930158499-003` 0:06.8 shields Hydro Cannon. Shield wars with all four
  shields gone by about 45 s: Henry `2904735277-011`, ItsAXN `2930158499-001`.
- Both shields are usually spent: in the 29 passing records, creators ended with none in 23 and their opponents in 28.
- Opponents who kept the last shield for their last Pokémon won with it: Reis `2887787713-011`, Walrein shields both
  Swifts at 2:01.4 and 2:11.4.

### 2. Real baits are mixed

Situation: both moves affordable, the defender has a shield, the dearer move hits at least 1.3x harder, and the cheaper
one does not knock out.

| Player | Throws the cheaper move (bait) |
|---|---|
| Creators | 32% ± 9 (36/111) |
| Their opponents | 49% ± 11 (39/79) |
| Bot (sim) | 24% ± 2 |
| Website (sim) | 22% ± 10 |

The owner's guidance #4 says good players bait about half the time. At the 77 creator throws where both moves were
affordable and their shield was up: creators threw the cheaper move 51 times and the dearer 26; the bot would throw
cheaper 22, dearer 29, hold 20, switch 6; website cheaper 20, dearer 18, hold 15, switch 24. The judge has no preference
between cheaper and dearer here: +2.6 ± 4.2 points for the cheaper.

### 3. Energy is held

| Player | Spare energy at the throw: median (quartiles) | Throws with 20+ to spare |
|---|---|---|
| Creators | 26 (15–45) | 65% |
| Their opponents | 27 (10–46) | 61% |
| Bot (sim) | 10 (2–24) | 33% |
| Website (sim) | 8 (1–20) | 27% |

Ledger numbers, approximate. Examples: Henry `002` Sableye throws Foul Play at 96 energy, then 64; ItsAXN
`2904685033-001` 1:16.1 Thievul throws Night Slash at 100.

### 4. Throw, then switch

Share of switches within 12 s of clock (about 2 s of play) after the player's own charged move: creators 61% ± 8, their
opponents 63% ± 8, bot (sim) 51% ± 3, website (sim) 46% ± 10. Examples: ItsAXN `2904685033-001` Body Slam at 0:17.1,
switch at 0:27.0; Henry `2904735277-005` Foul Play at 0:13.8, switch at 0:24.0. Lead switched within 12 s: creators 10%
± 6 of records, their opponents 13% ± 7, bot (sim) 14% ± 2, website (sim) 10% ± 8 (turn-0 swaps not counted), live bot
42% (status.md). Oddity: the bot opponent switched its lead early in 42% ± 12 of battles against website, against 17%
against the bot; unexplained.

### 5. Sacrificial switch-ins

ItsAXN `2930158499-009` 1:35.5: Fearow comes in and takes Gigaton Hammer (77% to 0); Tinkaton returns and knocks out at
1:52.5. Henry `2904735277-006` 2:28.5: a Sableye sacrifice.

### 6. Our live losses

`games/live` has 16 league losses and 21 league wins. About 6 of the losses involve a decision a strong player would
make differently; the rest are taps, reading or identification.
- `20261107-173302`: 0 of 8 shield prompts used; Scrafty lands four moves.
- `20261108-105348`: at 20%, Vigoroth threw Body Slam where Bulldoze would have knocked out Hisuian Arcanine; both shields
  went on Bruxish's Psychic Fangs within 36 s.
- `20261108-124100`: Vigoroth at 31% waited for Bulldoze and fainted holding the energy.
- `20261108-171011`: Jellicent stayed in for 47 s against Shaymin.

## Predictability (the owner wants mixed decisions tested)

Coarse situation (our shields, hit size, last Pokémon, their shields), leave-one-record-out majority copy:

| Player | Copy rate | Base rate | Entropy given the situation |
|---|---|---|---|
| Creators | 71% | 63% | 0.76 bits |
| Their opponents | 65% | 58% | 0.89 bits |
| Fully deterministic bot (sim) | 68–69% | 66–67% | 0.81 bits |

These coarse features cannot tell mixing from hidden state. On the same 114 creator positions: creators 58.8% copy
against a 54.4% base (+4.4); bot 72.8% against 63.2% (+9.6); website with the shield head 70.2% against 57.9%. The
creators look a little less predictable; the gap is within noise. Identical situations repeated across records: the
creators make the same call 89% of the time (33/37 pairs), their opponents 74% (14/19), the bot (sim) 70–72% on a looser
match. Shields look rule-like; nothing shows deliberate shield mixing. Baits are unpredictable from the coarse situation
for everyone (copy rate at or below the base rate), consistent with real mixing at 1/3 to 1/2.

The engines' own randomness: website gives different answers across 3 asks at 29 of 657 decisions (4%), from search
noise, never on shields; `website,temperature=0.02` at 256 of 543 non-shield decisions (47%).

## Exam results

657 decisions, 100 play-outs per action, value seed 1, engine seed 1. Files: `exam_people.out`, `exam_crowd.out`,
`exam_people_temperature.out`, `exam_crowd_variants.out` (the earlier 439-decision set, with `ko_wait`).

### People-like judge

| Engine | Agrees with player | Regret vs player (points) | Within 0.03 of best |
|---|---|---|---|
| website | 43.7% ± 3.8 | +4.0 ± 1.6 | 73.5% ± 3.4 |
| bot | 53.0% ± 3.8 | +2.0 ± 1.3 | 70.3% ± 3.5 |
| website with the shield head searched | 44.0% ± 3.8 | +4.5 ± 1.6 | 76.0% ± 3.3 |
| bot with copied creator shields (in-sample) | 54.6% ± 3.8 | +2.1 ± 1.3 | 71.7% ± 3.4 |
| `website,temperature=0.02` (3 asks) | 38.4% ± 3.3 | +3.7 ± 1.6 | 68.5% ± 3.6 |

The creators themselves are within 0.03 of best on 66.7% ± 3.6.

By decision kind (people judge): website agrees / regret — switch 47% / +2.7 ± 3.1, shield 68% / −0.9 ± 3.1, throw 42% /
+5.8 ± 3.8, hold 29% / +6.2 ± 2.9; bot — switch 55% / +3.2 ± 2.6, shield 68% / −0.9 ± 3.1, throw 57% / −0.4 ± 2.4, hold
40% / +4.6 ± 2.3.

Paired against website (people judge): bot −2.0 ± 1.2 points per decision (throws −6.2 ± 3.3); shield head searched
+0.5 ± 0.6 (shields +1.6 ± 2.9; near best +7.0 ± 8.0); temperature 0.02 −0.4 ± 0.3 (near best −4.0 ± 2.0).

Crowd judge: website regret +4.4 ± 1.7, near best 74.6%; bot +2.3 ± 1.4, 71.1%; creators 67.1%. Website against bot
+2.2 ± 1.2. `ko_wait` answers like the bot at 99.8% of decisions.

Where website and the creators differ (people judge, website's value minus the creator's): creators hold, website throws
104 of 218, +9.9 ± 4.8; creators hold, website switches 50, +6.5 ± 7.2; creators throw, website switches 40 of 168,
+8.9 ± 9.5; creators throw, website holds 38, +9.9 ± 10.6; creators switch, website stays 30, +10.1 ± 7.9; website
switches, creators stay 48, −2.3 ± 7.2; creators shield, website doesn't 23, −3.3 ± 14.7; website shields, creators
don't 13, −2.0 ± 9.8.

Reading: the judge continues with our own bot, and website's look-ahead uses that same bot; it cannot value a threat or a
read. So "beats the creators" means "agrees with our simulator", not better play. Engine-against-engine paired
differences are the useful output, with margins of ±1–2 points per decision.

## Ranked engine changes to test (all opt-in; none built here)

1. **`finish_safe=1` (a bug fix).** `Learner._pick_move` (`pogo/learner.py:381`) returns a fast move whenever that fast
   move would finish the opponent, before last-gasp and before the engine's throw search; `Planner` checks last-gasp
   first (`pogo/agents.py:386–391`). Example: Henry `2904735277-006` at 211.1 s (3:23.1): Empoleon 62/122 HP, 48
   energy, Hydro Cannon ready; Diggersby 4 HP, 100 energy, Scorching Sands (82 damage), Mud Shot with 1 turn left.
   Metal Sound (2 turns) would finish Diggersby, but Scorching Sands lands first. Throwing wins 1.00 and holding 0.00
   under both judges; both bot and website hold. Fix: apply `_doomed(view, fast.turns)` before that return.
2. **Front-loaded shields at the same overall rate:** `shield_two=a, shield_one=b`, margins on the shield head by
   shields left, tuned so the total stays about 34% (task 41 found more shielding loses against bots; re-time rather
   than add). Evidence: pattern 1.
3. **`bait_mix=p` (0.35–0.5):** when a real bait is available, throw the cheaper move with probability p. Evidence:
   pattern 2 and the owner's guidance #4; the bot's bait is near deterministic, so readable. Measure against
   `engine_versus --reader` and the people-like opponent; this exam cannot judge reads.
4. **A people-like opponent as a benchmark field:** `PeopleLike` from `creator_exam.py` as an `engine_versus` field
   (`--people N`) and an imagined opponent style. The simulator's opponents shield 33%, evenly; people 42–45%, early,
   and about 40% of baits.
5. **`swap_after_throw=1`:** when the search picks a mid-matchup swap while a charged move is affordable, throw first
   and ask again. Evidence: pattern 4, and website switches at 24 of 77 bait positions where creators never do. Low
   confidence: the judge rates website's switches neutral to good.
6. **Holding energy: no rule.** Humans hold about 26 to spare, engines 8–10; the judge prefers throwing at creator holds
   (+8–10) but cannot value a threat, and the ledger energy is uncertain. Test `respect_hold=1` or a larger `hold_cost`
   only against the people-like opponent and the reader probe.

## Bugs and data problems

- `scripts/real_decisions.py` / `advise.rebuild`: `Side.shown` is left at `[0]` on both sides. In 280 of 439 decisions
  the opponent's active Pokémon is not their lead, so the bot's bench and unseen inputs were wrong. Fixing it changes 32
  of the bot's 439 answers and raises agreement from 56% to 59%; status.md's 29-battle table was computed with the bug.
  The same omission makes `pogo.engine.imagine` raise StopIteration. Fixed only inside the exam (`position()`).
- `real_decisions.py` records no holds for creators (only 31 of 10,665 looks have a read energy), so its "throw or hold"
  row is throws only.
- Tracker data: the ledger sometimes says energy was short of the move's cost at a throw (25 "short by" lines in
  game.txt); some estimates exceed what the clock allows (Henry `2930047987-007` 0:48.5: 100 against 56); self-switch
  lines ("We switch Corviknight -> Corviknight" at 0:00 in ItsAXN `2904685033-008`); moves thrown that are not in the
  listed moveset (Electrode's Energy Ball in ItsAXN `2930158499-014`); Weather Ball name variants; 7 of the 84 records
  have different numbers of states and looks and are skipped.
- Live records: more than two "we shielded" in one game (`174143`: 4); moves outside the moveset (Stunfisk "Bubble
  Beam"); throws by a fainted Pokémon (`171944`); duplicate opponent-move lines.

## Long run proposed

`runs\lab-creators-exam.cmd`, 2 workers, about 45–50 minutes: a second value seed (2) at 200 play-outs for the crowd and
the people-like judge, then scores for website, bot and website with the shield head on both judges, appended to
`runs\lab-creators-exam.out`, to confirm the paired engine differences on fresh dice with half the play-out noise.

## Open questions

- Why does the bot opponent switch its lead early 42% of the time against website (17% against the bot)? Are website's
  turn-0 swaps involved? Turn 0 is not logged.
- Does the people-like opponent need its own bait rate (it baits like the bot) before it is used as a benchmark?
- Should the exam add the opponents' shield calls, from the mirrored state (about 117 more decisions)?
- Luke's 35 website games (`runs/people/owner_games.jsonl`) can be replayed exactly with `pogo.review`: a second,
  error-free set of decisions for this exam.
