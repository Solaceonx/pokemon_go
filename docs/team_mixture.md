# Rebuilding the opposing team list

`scripts/self_consistent_teams.py --help` describes the options. It uses only the
standard library and NumPy, the saved game data, and the existing learned model.
It does not download data or retrain the pilot. Both sides use the same model,
margin 0.02, and today's default rules.

The original `data/teams.json` is preserved. The new list is
`data/teams_v2.json`; its `weight` fields define the opponent distribution.
`pogo.teamlist.drawer` uses explicit weights when present and retains its old
score/seen weighting for old lists. Do not replace fitted weights with scores:
the weights are how often a team should appear, not how often it wins.

The 2026-10-12 reduced run failed its acceptance check: the strongest new counter
won **62.7% ± 3.0** on 2,000 untouched battles. The best retained member won
53.2% ± 3.1. More counter discovery and fitting are needed; the saved list is an
experiment, not a validated opponent field. See [the results](status.md).
The build and audit took 108.2 minutes; the paired owner-roster comparison took
64.0 minutes (172.2 total). The status report contains the ten best line-ups
under each list, with both scores and margins; all 26 finalists are saved in
`data/roster_teams_v2.json`.

## Method

1. Start with the old list, preserving lead identity and canonicalizing the two
   bench slots. The search pool is the top 100 **supported** species/forms,
   with typical IVs and recommended moves. Normal and shadow versions of one
   species cannot share a team.
2. Measure every pair of teams, playing each pairing on both sides. Their mean
   score minus 0.5 gives an antisymmetric, zero-sum payoff matrix.
3. Solve that finite game with 50,000 steps of symmetric fictitious play: keep
   adding the current best response to the accumulated distribution. Its
   average is the next mixture. Earlier counters stay available.
4. Screen random legal threes with every lead, the existing population, and
   every one-member change to the strongest parents. Keep the stronger teams
   in stages. The one-on-one coverage score is not used as a filter.
5. Evaluate those candidates on separate development battles to choose additions
   and decide whether to stop. Stop when none beats 50% by more than its ordinary
   95% margin, or the round budget is exhausted. These are tuning battles;
   their scores are not reported as results.
6. Freeze the list. Run another counter search, then test its finalists and
   **every** member of the fitted population on untouched battles. This final
   audit cannot change the list. The JSON report includes all scores, ordinary
   95% margins, and conservative simultaneous margins across the tested teams.

The mean of a symmetric mixture playing itself is always 50%; that identity is
not evidence of strength. The useful check is the best counter's held-out score.
Sampled search cannot prove that an untested team cannot do better. Even
`--exhaustive` only screens all legal line-ups before staged pruning; it does
not measure every line-up precisely. There are 474,270 legal top-100 line-ups
with the lead counted and the bench order ignored in the current data.

The saved report records model/code/data hashes, seeds, settings, the number of
candidates, the stop decision and elapsed time. Fitting, candidate searches,
development stopping and final evaluation use separate deterministic seed
streams. Each worker gets explicit pilot and battle seeds; process scheduling
does not change the battles. No training examples or large battle logs are saved.

## Rerun the smaller experiment

From the repository root (the interpreter below is the owner's existing NumPy
environment):

```bash
nice -n 10 /Users/marco/Developer/pokemon_go/.venv/bin/python scripts/self_consistent_teams.py --pool 100 --rounds 8 --random 256 --parents 2 --stages 8:48,64:12 --add 8 --matrix-pairs 12 --stop-pairs 600 --audit-random 512 --audit-keep 10 --finals 1000 --workers 3 --seed 21021 --out data/teams_v2.json > runs/teams_v2.out 2>&1
nice -n 10 /Users/marco/Developer/pokemon_go/.venv/bin/python scripts/roster_teams.py --rival bot --listed 1 --teams data/teams.json --compare-teams data/teams_v2.json --stages 40:240,160:40,800:12 --finals 4000 --workers 3 --seed 21121 --out data/roster_teams_v2.json > runs/roster_teams_v2.out 2>&1
```

The builder's `--stages`, `--matrix-pairs`, `--stop-pairs` and `--finals` count
**pairings**, each played in both directions. The roster script retains its
existing convention: stage counts and `--finals` count **individual battles**.
Its new comparison mode therefore requires even battle counts.

The roster comparison searches all 3,366 owner line-ups separately against each
list, retains both sets of finalists plus all leads of the current three, then
reports their union on untouched battles. Each line-up sees identical opponents
within a column. Across columns the draw uniforms, engine dice and both pilots'
seeds match; the selected listed opponent necessarily changes. With
`--listed 0.8`, random-team slots would also be identical across columns.

Margins treat a mirrored pair as one independent sample; paired difference
margins use the difference within each sample. Closely ranked line-ups may be
statistically indistinguishable. The roster's ten highest fresh scores are
reported against both fields; the frozen mixture's audit is a separate check.

## Larger run

A broader continuation is substantially more expensive than the smaller
experiment. Start from the saved 145-team population, with a new seed and new
output paths so the smaller run and its untouched evaluation remain a record:

The smaller run's initial matrix took 7.6 minutes for 77,760 battles on three
workers, about 170 battles per second. The broader command below can screen
over 6,000 random line-ups plus several thousand local changes per round, with
48 battles per line-up in the first stage, for up to ten rounds. Screening
alone is several million battles: comfortably over three hours at that measured
rate, before matrix fitting, validation and the roster search.

```bash
nice -n 10 /Users/marco/Developer/pokemon_go/.venv/bin/python scripts/self_consistent_teams.py --teams data/teams_v2.json --pool 100 --rounds 10 --random 2048 --parents 4 --stages 24:96,160:16 --add 12 --matrix-pairs 24 --stop-pairs 1200 --audit-random 4096 --audit-keep 16 --finals 3000 --workers 3 --seed 22021 --out data/teams_v2_full.json > runs/teams_v2_full.out 2>&1
nice -n 10 /Users/marco/Developer/pokemon_go/.venv/bin/python scripts/roster_teams.py --rival bot --listed 1 --teams data/teams.json --compare-teams data/teams_v2_full.json --stages 120:450,500:40,2500:12 --finals 6000 --workers 3 --seed 22121 --out data/roster_teams_v2_full.json > runs/roster_teams_v2_full.out 2>&1
```

The builder compares audit candidates with its input list (`teams_v2.json` in
this continuation). The roster command still compares against the original
`teams.json`.

Add `--exhaustive` to the builder command to screen every legal line-up in every
search. At 24 pairs per line-up, the first stage alone then requires 22,764,960
battles per round. This is far outside a three-hour, three-core budget.

The scripts cap numerical libraries at one thread per worker. Use `--workers 3`
or fewer on this machine. The current sandbox rejects priority changes, so
`nice` prints `setpriority: Operation not permitted` and continues at inherited
priority; the worker initializer tolerates that restriction as well.

## Verification

The checks run after implementation were:

```bash
/Users/marco/Developer/pokemon_go/.venv/bin/python -m unittest discover -s tests > runs/task21_tests.out 2>&1
/Users/marco/Developer/pokemon_go/.venv/bin/python scripts/check_pvpoke.py > runs/task21_pvpoke.out 2>&1
```

They printed `Ran 113 tests` and `OK (skipped=6)` (107 passed; six optional video
checks need PyAV), and `108 of 108 PvPoke battles reproduced exactly`.
Both scripts' `--help` commands also completed successfully. The added unit
tests cover old and explicit weights, invalid mixtures, species legality,
counter cycles, separate seed streams, matching cross-list schedules, worker
history independence and mirrored results.

## Observed teams

Pass `--observed FILE ...` to add **cumulative** sighting snapshots, in the same
`{"teams": [{"team": ["lead", "bench1", "bench2"], "seen": 3}]}` format.
Duplicate counts take the maximum, preventing repeated import of the same
snapshot from multiplying sightings. These teams enter the candidate population
and retain their counts. Sampling still follows the fitted explicit weights;
the counts are not multiplied into the mixture again after its audit.

Illegal, unsupported or out-of-pool observations fail with an explanation.
Expand the pool deliberately if necessary. There is no automatic extraction
from recording data: verified sighting aggregation belongs to task 5. No new
real-world counts were invented for this experiment. The resulting field is a
simulation equilibrium approximation, not a measured ladder distribution.
