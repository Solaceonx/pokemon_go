# The lab's league (`scripts/lab/league.py`), lab-bench, 2026-11-24

One command compares engines on more than win rate against one bot. Every engine is an `engine_versus.py` spec passed
through `engine_versus.parse()` and `pilot()` unchanged, so an engine another branch adds there plugs in after a merge.

## How to use it

    python -X utf8 scripts/lab/league.py website bot "website,temperature=0.02" "website,mix=1" --preset smoke --tag smoke-1 --workers 2
    python -X utf8 scripts/lab/league.py --reference website "website,mix=1" --preset screen --workers 14 --tag mix-screen
    python -X utf8 scripts/lab/league.py --reference website "website,mix=1" --preset confirm --seed 2611901 --workers 14 --tag mix-confirm

- The reference is `--reference` (default `website`), then the specs in order. Every spec plays the same battles
  (paired dice); head to head, crowd, PvPoke and the reader's battles are drawn exactly as engine_versus.py draws them
  for the same seed, field and team pool.
- Results save as they come to `runs/lab-league/<tag>/league.json`. The same command resumes, skipping what is done; a
  bigger preset or more specs only add what is missing. While `runs/lab-league/<tag>/pause` exists (or `--pause-file`),
  workers finish their job and wait.
- Output: `table.md` (the tables below, plus CPU seconds per unit and projected times for each preset) and `summary.json`.
- `--measures` picks a subset of h2h, round, crowd, pvpoke, reader, predict, timing, endgame and creator. Any preset
  count can be overridden (`--pairings 300`, `--reader 100`...). `--field` defaults to mixed (the owner's rule); also run
  `--field standard --measures h2h,crowd,pvpoke` before proposing an adoption. `--team-pool 50` as in engine_versus.
- confirm refuses a seed any other tag in `runs/lab-league/` has used.

## Plugging in a new engine

- Add its key to `engine_versus.parse()` and `pilot()`. Nothing in the league needs to change.
- Live timing calls `pilot(settings, seed, cls=league.Live)`, a RealTime with the game's own pauses. An engine built
  on RealTime gets real deadlines; anything else is timed per searched decision with no deadline (marked †).
- Predictability clones the player (`clone()`, else `copy.deepcopy`) and replaces every `random.Random` and numpy
  `Generator` it holds as an attribute. An engine that keeps its dice elsewhere should define `reseed(seed)`.
- The reader probe calls `target.clone()` (pogo.reader).
- Creator exam: if `scripts/lab/creator_exam.py` exists and defines
  `league_scores(specs, workers=, seed=) -> {spec: {"score": share, "margin": share, "n": int}}`, the league calls it
  once per spec and shows the score; otherwise the column is "—".

## The columns

| Column | What it is |
|---|---|
| verdict | Luke's rule: head to head above 50% beyond the 95% margin, and no loss beyond the margin against the crowd or PvPoke's AI. A screen's "pass" is a candidate for confirm on a fresh seed; only confirm prints PASS. |
| head to head vs ref | Score against the reference, each pair of teams both ways (engine_versus h2h), with (pairings). |
| crowd, PvPoke | Score against the varied crowd / PvPoke's AI, and Δ: the paired difference from the reference on the same battles. |
| round robin | Mean score against every other spec. The matrix and any rock-paper-scissors cycles (on point estimates, flagged when every edge clears its margin) follow the main table. |
| reader's gain ↓ | Exploitability: score against the probe not reading minus score against the same probe reading the spec's next throw (pogo.reader: engine_versus's confirmed engine, 4 imagined battles), same battles and dice. Lower is better; Δ is paired on the reference. It reads throws only, when both sides have a charged move ready. |
| predictable | Positions from the spec's own battles against the crowd: throws with a charged move ready, switches at a new matchup, shield calls, replacements from two or more. Each is asked again `asks` times with every generator reseeded. The share of the most common answer (100% = always the same); "varies" = positions with more than one answer; by kind in its own table. This is what an opponent meeting the same position across games sees. A reader that knows the engine's current dice is the reader column. Positions are each engine's own, so this is not a paired comparison. |
| live ms | Searched decisions under pogo.realtime's default pauses on the CPU clock (Windows steps of about 16 ms): median / 99th percentile, share cut short; its table adds the bootstrap interval, the share with no complete round, the release-check limits (p99 800 ms, cut 20%, no round 0.5%) and the score in those battles. † = no deadline. |
| endgame points lost ↓ | scripts/bench.py's 318 frozen exact endgames: points given away per decision ×100, margins clustered by game; Δ paired on the reference. Narrow: late positions only; the website engine does not search shields, so its shield points equal the bot's. |
| creator exam | The creators' decisions exam, when present. |

## Presets and time

| Preset | Head to head vs ref / other pairs | Crowd / PvPoke | Reader pairs | Predict battles × positions × asks | Timing battles | Endgames | Time for these 4 specs |
|---|---|---|---|---|---|---|---|
| smoke | 4 / 4 | 10 / 6 | 3 | 4 × 3 × 4 | 3 | 318 | 5.2 min on 2 workers (0.17 CPU hours) |
| screen | 500 / 200 | 1,000 / 500 | 250 | 60 × 3 × 8 | 100 | 318 | 13.4 CPU hours: about 1 to 1.5 h on 14 workers |
| confirm | 2,000 / 500 | 2,000 / 1,000 | 1,000 | 150 × 3 × 8 | 200 | 318 | 41.5 CPU hours: about 3 h on 14 workers |

CPU seconds per unit from the smoke, on the PC while other lab agents were running:
- Pairing: 6.7 (website and bot) to 11.5 (two website engines).
- Battle against the crowd: 3.3; against PvPoke: 2.8.
- Reader pair: 14 (website), 10 (temperature), 16 (mix), 0.9 (bot).
- Predict battle at 3 × 4: about 5; timing battle: 4 to 6; endgame position: 0.01.

The reader and the head to head between engines are most of the cost. Every table.md prints the projection for its
own specs.

## The smoke run (`runs/lab-league/smoke-1/`, seed 2611, mixed field, 2 workers)

| # | spec | verdict | head to head vs ref | crowd, Δ ref | PvPoke, Δ ref | round robin | reader's gain | predictable | live median / p99, cut | endgame lost, Δ ref |
|---|---|---|---|---|---|---|---|---|---|---|
| 0 | `website` | reference | — | 70.0 ± 29.9 | 83.3 ± 32.7 | 45.8 ± 8.2 | +0.0 | 100.0, varies 0 (12) | 156 / 466, cut 14.9 | 5.77 ± 2.54 |
| 1 | `bot` | no gain shown | 75.0 ± 28.3 (4) | 50.0, −20.0 ± 39.2 | 100.0, +16.7 ± 32.7 | 62.5 ± 33.7 | +0.0 | 100.0, varies 0 (12) | 0 / 1 † | 7.21, **+1.45 ± 1.28** |
| 2 | `website,temperature=0.02` | no gain shown | 37.5 ± 24.5 (4) | 50.0, −20.0 ± 26.1 | 83.3, +0.0 | 54.2 ± 24.5 | +0.0 | 91.7 ± 5.8, varies 25 (12) | 125 / 518, cut 5.2 | 6.75, +0.99 ± 1.45 |
| 3 | `website,mix=1` | no gain shown | 50.0 ± 0.0 (4) | 70.0, +0.0 | 83.3, +0.0 | 37.5 ± 8.2 | +0.0 | 97.9 ± 3.5, varies 8 (12) | 172 / 564, cut 20.6 | 5.61, −0.16 ± 0.30 |

- **A smoke only tests the plumbing.** With 4 pairings and 10 crowd battles the margins are ±25 to ±40 points, and no
  verdict means anything.
- **Endgames do separate at this size.** The trained bot gives away 1.45 ± 1.28 points a decision more than the
  website engine, over all 318 positions. A first pass on a spread of 30 missed all 10 positions where the two differ,
  so every preset now scores all 318 (about 2 seconds a spec).
- **Predictability shows mixing at once.** By kind of decision, temperature 0.02 changes its throw on half of its
  throw positions (modal share 81%) and some switches; `mix=1` on a quarter of its throw positions (94%). The website
  engine and the trained bot gave the same answer every time, so at 32 imagined battles the search noise alone did
  not flip a choice here.
- **The reader gained nothing in 3 pairs for anyone.** Checked: the probe reads (2 to 9 reads a battle) and the
  battles differ from the unread ones, but no winner changed. Task 29 saw reader changes of a few points at 1,000
  pairs, so this column needs the screen's 250 pairs at least.
- **Live timing:** `mix=1` was cut short on 20.6% of its searched decisions, just over the release limit (20%), on 3
  battles; its p99 (564 ms) is the highest. The website engine: 14.9%, p99 466 ms.
- **Round robin:** 0 beats 2, 2 beats 1 and 1 beats 0 on the point estimates, well within the margins: an example of
  what the cycle line reports.

## The screen run (not started)

`runs\lab-bench-screen.cmd`: the four specs above, preset screen, 14 workers, tag `screen-1`, seed 2611, output
appended to `runs\lab-bench-screen.out`. About 1 to 1.5 hours (13.4 CPU hours measured on the shared PC).

## Limits

- The reader reads throws only, and only when both sides have a charged move ready; a shield or switch mix is not
  probed by it (the predictability table shows those).
- Predictability uses each engine's own positions, so two engines are compared on different positions; margins are
  clustered by battle.
- Live timing uses the CPU clock, which on Windows moves in steps of about 16 ms; the trained bot (†) is timed on
  the wall clock.
- No creator exam yet: `scripts/lab/creator_exam.py` does not exist on any lab branch.
