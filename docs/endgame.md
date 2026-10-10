# Exact late-game search (task 9)

`pogo/endgame.py` solves fully revealed positions with at most two living Pokémon
on each side. The active Pokémon must be alive; forced replacements are unique in
this scope. It includes voluntary switches, timers, fast-move progress, energy,
stat stages, timeout scoring, simultaneous choices, random CMP and chance buffs.
The value is side 0's win share under optimal play: win 1, draw 0.5, loss 0.

Each turn is replayed through the existing rules engine for every action, shield
choice and chance outcome. Shield information sets exclude the pending charged
move and opposing action. A pure turn strategy includes contingent shield choices;
the resulting zero-sum matrix is solved with numpy vertex enumeration and checked
against its dual. Future values are memoized by full state, including the clock.
This is numerical exact search (floating-point tolerance), not a rollout estimate.
The rules engine and its information assumptions are the reference, not real-game
validation. Builds and opponent energy must be known correctly.

## Run

From the repository root, using the supplied Python:

```python
from pogo.endgame import Solver, EndgamePlayer
from pogo.learner import QNet

# battle is an existing Battle paused between turns.
solution = Solver(max_nodes=20000, seconds=5).solve(battle)
print(solution.value)  # side 0's optimal win share
# solution.plans[side] and solution.mixtures[side] give contingent strategies.

player = EndgamePlayer(q=QNet.load('runs/general-decide/q.npz'), margin=.02,
                       max_nodes=1000, seconds=.05, seed=123)
# Pass player as agent_a or agent_b when constructing Battle.
```

`Solver.solve` raises `ValueError` outside its scope and `SolveLimit` when the
position, work or time budget expires. A partial search never supplies a value.
`EndgamePlayer` uses the Learner outside scope or on a capped search, and samples
an optimal contingent strategy when search succeeds. For a busy player receiving
a shield callback without an act callback that turn, it also uses the Learner:
the engine offers no pre-turn callback there. The solver itself supports busy
states. With two survivors, replacement requires no choice.

The player clears its search cache between decisions to bound retained memory.
The time cap is soft (checked during search); close-to-cap decisions can depend on
machine speed. This implementation does not claim the 10 ms live decision target.

```sh
/Users/marco/Developer/pokemon_go/.venv/bin/python -m unittest discover tests
/Users/marco/Developer/pokemon_go/.venv/bin/python scripts/check_endgame.py
/Users/marco/Developer/pokemon_go/.venv/bin/python scripts/check_endgame.py --measure --pairings 150 --seed 90261019 --seconds 0.05 --max-nodes 1000
```

The check script forces numpy to one thread. The measurement uses 150 random team
pairings from the top 50, both team orientations, and fresh battle/agent seeds.
For each of those 300 battles it also runs the baseline Learner on exactly the
same teams and seeds against the same best Learner (`q.npz`, margin .02).
Margins are 1.96 standard errors clustered by team pairing; the improvement uses
paired differences. The held-out seed was not used to tune the player.

## Checks and timings

The independent reference enumerates explicit action/shield pairs for one-turn
cases, and recursively enumerates joint actions for deterministic no-shield cases.
It shares the matrix routine, which separately has matching-pennies, rock-paper-
scissors and rectangular/degenerate tests. The uncached check expands the complete
turn tree without transposition reuse. Additional tests cover chance buffs, tied
CMP, hidden teams, busy states, search limits, fallback and nonmutation.

```text
Independent brute-force agreement: 12/12 (tolerance 1e-9)
Independent multi-turn brute-force agreement: 3/3 (1v1, 2v1, 2v2)
Uncached exhaustive-tree agreement: 9/9 (1v1, 2v1, 2v2)
```

The agreement fixtures are intentionally small and near timeout. Timing fixtures
start at turn 0 with 12 HP / 60 energy Azumarill against 15 HP / 60 energy Medicham;
extra team slots duplicate that side's Pokémon. Medicham's chance buff is disabled
in these deterministic fixtures. These are synthetic complexity probes, not a
representative latency sample from games. Shield counts below are **per side**.
With 20,000 positions / 5 seconds allowed:

| Survivors | 0 shields | 1 shield | 2 shields |
|---|---:|---:|---:|
| 1 vs 1 | 0.001204 s (6 states) | 0.016644 s (98) | 0.017172 s (98) |
| 2 vs 1 | 0.018869 s (115) | 0.340878 s (1,773) | 0.773241 s (4,415) |
| 2 vs 2 | 0.723915 s (4,541) | capped at 3.185749 s | capped at 3.402616 s |

Both capped fixtures exceeded 20,000 positions; they have no reported exact value
at this budget. Full-health endgames and switch-rich positions can grow much
larger. General three-survivor positions and uncertain/hidden teams are unsupported.

A supplemental solve with `Solver(max_nodes=200000, seconds=60)` on the same
2-vs-2 fixtures solved one shield per side in **22.025847 s**, 145,413 states,
value 0. Two shields exceeded 200,000 states after **33.834548 s**. Larger budget
probes can be reproduced with:

```sh
/Users/marco/Developer/pokemon_go/.venv/bin/python scripts/check_endgame.py --solve-nodes 200000 --solve-seconds 60
```

## Held-out result (2026-10-09)

The exact command above (`--measure --pairings 150 --seed 90261019 --seconds 0.05
--max-nodes 1000`) printed:

```text
Endgame vs best: 53.333 +/- 2.056 (95%)
Learner vs best, same battles: 51.667 +/- 1.775 (95%)
Paired improvement (points): 1.667 +/- 1.441 (95%)
300 battles per player; seed=90261019; solved decisions=1279; capped decisions=3738; elapsed=210.619s
```

That is **+1.67 ± 1.44 percentage points** on these held-out battles, a small
positive result with a fairly wide margin. The baseline's realized score need not
be 50%: each orientation has independent battle and agent seeds. No parameters
were changed in response to this measurement. Most attempted solves hit the cap;
this is not evidence that general two-vs-two play is solved within live latency.
The full suite printed `Ran 32 tests` and `OK`.
