# Benchmarking

Why this exists: nearly every number in `status.md` comes from the bot playing near copies of itself. That is cheap and
precise, but it cannot see what the owner sees, and it let a bug ship (the same-cost rule nesting look-aheads) because
what was measured was not what was published. The owner's two requests: much better benchmarks, and a way to evaluate
a benchmark itself.

## What was wrong

- **The bot grades itself.** Head to head is against a near copy; the crowd is variations of the bot.
- **Circular tests.** `matching` imagines the crowd's styles and PvPoke's AI, then is scored against those same opponents.
- **PvPoke's AI is not fair** (the owner: it sees which charged move is coming).
- **Scores do not compare across versions.** Test opponents come from the code under test, so changing a default moves them too.
- **What ships is not what is tested.** The website: 32 imagined battles with time limits. Most tests: 4 to 8 with no limits.
- **Real games are too few to judge a change.** 30 website games give a margin near ±18 points; ±5 takes about 400.

## How a benchmark is evaluated

A judge earns trust by passing these, in this order. `python3 scripts/bench.py check` runs the ones that can be automated.

| Test | Question | How |
|---|---|---|
| Catches known damage | Can it see a bot we know is worse? | A ladder of known strengths and bots broken on purpose (`BUILDS` in `scripts/bench.py`) |
| Repeats | Same bot, same score? | New dice; hidden repeat positions in the exam |
| Predicts real results | Do its verdicts line up with who won real games? | Real games, after allowing for line-ups |
| Independent judge | Is the bot marking its own work? | By design, and by comparing the owner's answers with the play-out judge |
| Agrees with other judges | Do separate judges rank bots the same way? | Compare rankings, investigate any split |
| Cost | How many battles or positions to see 1, 2, 5 points? | From each judge's measured noise |
| Cannot be gamed | Can we tune to it and fool it? | Keep positions back that are never tuned on |

## The judges

| Judge | What it scores | Depends on our bot? | Weakness |
|---|---|---|---|
| The owner's exam | Real positions, the owner's call (`scripts/exam_positions.py`, `scripts/exam_page/`) | No | One person, few positions, costs the owner's time |
| Exact endgames | Points given away against exact play (`pogo.endgame.action_values`, `bench.py endgame`) | No | Only late positions with at most two Pokémon a side; replacements are forced there |
| Agreement with the owner | How often a build plays what the owner played (`bench.py people`) | No | The owner is not always right; rewards imitation |
| Reader | What a player gains by reading the build (`bench.py exploit`) | Partly | Reads throws only |
| The field | Score against the trained bot, the crowd and PvPoke's AI (`bench.py field`) | Yes | Kept for comparison with past results |

## First results (2026-11-01, `python3 scripts/bench.py check`, `runs/bench/check.out`)

A ladder (random, masher, rulebook, trained bot, engine with 8 imagined battles) and six bots broken on purpose went
through every judge: 318 frozen endgame positions (48 shield calls, 22 from real games), the owner's 30 website games, 400
battles a line against each opponent, 100 battles against the reader.

| Judge | Ladder pairs right | Broken bots caught, of 6 | To see ±2 points |
|---|---|---|---|
| Battles against the crowd | 10/10 | 5 | 2,500 battles |
| Battles against PvPoke's AI | 8/10 | 5 | 1,900 battles |
| Battles against the trained bot | 10/10 | 4 | 3,200 battles |
| Exact endgames | 10/10 | 2 | 140 positions |
| Agreement with the owner | 8/10 | 1 | |
| Reader's gain | 4/10 | 1, barely | 3,900 pairs |

- **Battles catch gross damage well.** They were the best here, though this test favours them: a broken bot loses to
  everything. It says nothing on whether they rank two strong versions as real people would.
- **Agreement with the owner is not a strength score.** A bot that never switches scores above the unbroken one (+3.5 ± 4.6).
  Use it for prediction only.
- **The reader's gain fails as built.** Weak bots lose anyway, so reading adds nothing, and the margin is ±10.
- **Exact endgames are cheap and narrow.** About twenty times fewer samples than battles for the same margin, with no
  opponent model. They catch no shields and no throws but not no switches, and cannot see replacements by construction.
- **Nothing catches the same-cost rule** (`first_listed`), the owner's own complaint: too rare in these sets. The exam holds
  two such positions.
- One false alarm to keep in mind: the same build scored +4.4 ± 3.9 against PvPoke with other dice. With six judges at 95%
  this is not surprising, so a single judge's small gain is not evidence.

**The engine's edge depends on how well it models the opponent.** Gain over the trained bot, averaging the two engine runs:
+17 points against the trained bot (which is exactly what it imagines), +4 against the crowd (variations of it), -2 against
PvPoke's AI (unlike it). Margins are about ±6 on each. That follows how well "they play like us" predicts each of them
(`scripts/predict_bench.py`, chance given to what they did): the trained bot 87%, the crowd 39%, PvPoke's AI 16%. The owner is
18%, about as far as PvPoke's AI, so head-to-head gains overstate what it gains against a person. This is an inference: the
gain against people is not measured.

## Release check (`python3 scripts/release_check.py`, `runs/bench/release.json`)

The website's settings live in `pogo.realtime.WEBSITE`. The check runs the tests, the PvPoke reference battles, 30 battles of
timing under the website's time limits, and 200 battles against the crowd, and ties the result to the commit;
`scripts/build_pvpbot_site.py` refuses code without a passing record (`--unchecked` overrides it). Limits: 99th percentile 800 ms,
20% of decisions cut short, 0.5% with no complete round. On the recorded numbers they fail the nesting bug (1,292 ms, 30%) and pass
the fix (`tests/test_bench.py`). First run, commit 4105bda: passed, 477 ms, 11.3% cut, no fallbacks, crowd 68.0 ± 6.5 against the
trained bot's 66.5 ± 6.5. 200 battles only catch gross damage. Browser speed is not covered.

## Predicting the owner, and whether more games help (`python3 scripts/people_model.py`, `runs/bench/people_model.out`)

A small conditional logit over the options of 954 of the owner's decisions in 30 website games, tested on 5 games it has not seen.
How often the top choice was what the owner played:

| Predictor | Top choice right |
|---|---|
| The engine / with `matching` | 54% / 56% |
| The rulebook / the trained bot | 60% / 62% |
| The model, trained on 2 games | 61.7% ± 1.4 |
| 5 games | 63.6% ± 1.1 |
| 10 games | 65.5% ± 0.8 |
| 15 games | 64.6% ± 1.2 |
| 20 games | 65.3% ± 1.1 |
| 25 games | 65.9% ± 0.9 |

It flattens at about 10 games. So more of the owner's games add little to a model this small. This says nothing about other
players, or about a larger model that more data could support. The same model's chance per decision, 42% rising to 45% with
all options equal at 36%, is on these decisions only and is not comparable with `predict_bench.py`'s 18%.

## Observation cost

The observation-cost diagnostic is now `scripts/check_tracker.py --pilot both --field mixed --seed 3602`:
exact-state, perfect-camera and rough-camera play on fixed pairings and RNG streams, with paired margins.
It compares each pilot against the same seeded Planner to isolate the cost of tracking; it is not a human
strength judge. Task 36's commands and results are in `docs/status.md` and `runs/energy_reconstruction_*.out`.

## Not built yet

- Frozen old versions as opponents, so scores compare across versions.
- Whether a judge's verdicts predict who won real games: needs more games, or the exam.
- The fitted model as an imagined opponent inside the engine, and as a test opponent.
- Predicting other players from tracked footage.
