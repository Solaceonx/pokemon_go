# League tactics-screen: screen preset, seed 5401, field mixed

Reference: `website`. Shares and points are in percent with 95% margins; Δ is paired on the reference (same battles). Verdict: Luke's rule (above 50% head to head beyond the margin, no loss beyond the margin against the crowd or PvPoke's AI). ↓ lower is better.

| # | spec | verdict | head to head vs ref | crowd, Δ ref | PvPoke, Δ ref | round robin | reader's gain ↓, Δ ref | predictable (modal share) | live ms median / p99, cut | endgame points lost ↓, Δ ref | creator exam |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | `website` | reference | — | 75.1 ± 2.7 | 87.3 ± 2.9 | 52.1 ± 1.9 | +3.0 ± 2.6 | 98.3 ± 0.9, varies 8.3 (180) | 109 / 578, cut 5.8 | 5.77 ± 2.54 | 75.2 ± 3.3 |
| 1 | `website,finish_safe=1` | no gain shown: head to head within margin | 49.8 ± 2.1 (500) | 75.6, +0.4 ± 0.5 | 87.3, +0.0 ± 0.0 | — | +3.2 ± 2.6, +0.2 ± 0.5 | 98.3 ± 0.9, varies 8.3 (180) | 109 / 547, cut 5.9 | 4.82 ± 2.26, -0.94 ± 1.04 | 75.0 ± 3.3 |
| 2 | `website,bait_mix=0.4` | fail: worse head to head | 45.3 ± 2.4 (500) | 74.2, -1.0 ± 1.6 | 88.2, +0.9 ± 1.3 | — | +3.8 ± 2.8, +0.8 ± 2.5 | 98.2 ± 0.9, varies 9.4 (180) | 109 / 575, cut 5.9 | 6.08 ± 2.66, +0.31 ± 0.61 | 74.0 ± 3.4 |
| 3 | `website,shield_two=0.05,shield_one=0` | no gain shown: head to head within margin; loses points to crowd | 49.7 ± 2.4 (500) | 73.1, -2.1 ± 1.6 | 86.1, -1.2 ± 2.1 | — | +2.8 ± 2.8, -0.2 ± 2.1 | 97.6 ± 1.1, varies 11.7 (180) | 109 / 547, cut 5.6 | 5.61 ± 2.53, -0.16 ± 0.31 | 74.1 ± 3.4 |
| 4 | `website,swap_after_throw=1` | no gain shown: head to head within margin; loses points to crowd | 48.9 ± 2.2 (500) | 73.9, -1.2 ± 0.9 | 88.1, +0.8 ± 1.0 | — | +3.4 ± 2.6, +0.4 ± 1.3 | 98.3 ± 0.9, varies 8.3 (180) | 109 / 578, cut 5.6 | 6.10 ± 2.59, +0.33 ± 0.62 | 74.0 ± 3.4 |
| 5 | `website,finish_safe=1,bait_mix=0.4,shield_two=0.05,shield_one=0,swap_after_throw=1` | fail: worse head to head; loses points to crowd | 46.0 ± 2.5 (500) | 71.7, -3.5 ± 2.2 | 87.4, +0.1 ± 2.6 | — | +1.8 ± 2.8, -1.2 ± 3.1 | 97.5 ± 1.2, varies 13.3 (180) | 109 / 562, cut 5.7 | 5.32 ± 2.47, -0.45 ± 1.40 | 73.2 ± 3.4 |

## Round robin (row's score against the column, %)

| | 0 | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|---|
| 0 | · | 50.2 ± 2.1 | 54.7 ± 2.4 | 50.3 ± 2.4 | 51.1 ± 2.2 | 54.0 ± 2.5 |
| 1 | 49.8 ± 2.1 | · | — | — | — | — |
| 2 | 45.3 ± 2.4 | — | · | — | — | — |
| 3 | 49.7 ± 2.4 | — | — | · | — | — |
| 4 | 48.9 ± 2.2 | — | — | — | · | — |
| 5 | 46.0 ± 2.5 | — | — | — | — | · |

No rock-paper-scissors cycle on the point estimates.

## Predictability by kind of decision (modal share; varies = positions with more than one answer)

| # | throw | switch | shield | replace | asks | battles |
|---|---|---|---|---|---|---|
| 0 | 97.7 (varies 10.0, 60) | 97.1 (varies 15.0, 60) | 100.0 (varies 0.0, 60) | — | 8 | 60 |
| 1 | 97.7 (varies 10.0, 60) | 97.1 (varies 15.0, 60) | 100.0 (varies 0.0, 60) | — | 8 | 60 |
| 2 | 97.1 (varies 15.0, 60) | 97.5 (varies 13.3, 60) | 100.0 (varies 0.0, 60) | — | 8 | 60 |
| 3 | 97.3 (varies 13.3, 60) | 95.4 (varies 21.7, 60) | 100.0 (varies 0.0, 60) | — | 8 | 60 |
| 4 | 97.7 (varies 10.0, 60) | 97.1 (varies 15.0, 60) | 100.0 (varies 0.0, 60) | — | 8 | 60 |
| 5 | 96.7 (varies 20.0, 60) | 95.8 (varies 20.0, 60) | 100.0 (varies 0.0, 60) | — | 8 | 60 |

## Live timing (searched decisions, CPU clock, the website's deadlines; † no deadline: CPU time per searched decision, or per decision if it does not count searches)

| # | battles | decisions | median ms | p99 ms (95%) | worst | cut short (95%) | no round | release limits | crowd under deadlines |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 100 | 2294 | 109 | 578 (500–609) | 812 | 5.8 (3.8–8.1) | 0.2 | ok | 78.0 ± 8.2 |
| 1 | 100 | 2295 | 109 | 547 (516–609) | 797 | 5.9 (4.0–8.1) | 0.3 | ok | 77.0 ± 8.3 |
| 2 | 100 | 2323 | 109 | 575 (500–641) | 797 | 5.9 (3.6–8.8) | 0.3 | ok | 79.5 ± 7.9 |
| 3 | 100 | 2272 | 109 | 547 (500–594) | 797 | 5.6 (3.5–8.3) | 0.3 | ok | 72.0 ± 8.8 |
| 4 | 100 | 2276 | 109 | 578 (516–609) | 781 | 5.6 (3.6–8.0) | 0.3 | ok | 77.0 ± 8.3 |
| 5 | 100 | 2331 | 109 | 562 (516–609) | 781 | 5.7 (3.8–8.0) | 0.2 | ok | 73.5 ± 8.6 |

## Exact endgames (points lost a decision ×100, clustered by game)

| # | all | moves | shields | blunders ≥ 0.1 | positions |
|---|---|---|---|---|---|
| 0 | 5.77 ± 2.54 | 6.24 | 3.12 | 8.8% | 318 |
| 1 | 4.82 ± 2.26 | 5.13 | 3.12 | 7.9% | 318 |
| 2 | 6.08 ± 2.66 | 6.61 | 3.12 | 9.1% | 318 |
| 3 | 5.61 ± 2.53 | 6.24 | 2.08 | 8.5% | 318 |
| 4 | 6.10 ± 2.59 | 6.63 | 3.12 | 9.1% | 318 |
| 5 | 5.32 ± 2.47 | 5.89 | 2.08 | 8.2% | 318 |

## Exploitability detail (score against the probe, not reading / reading)

| # | not read | read | gain ↓ | pairs |
|---|---|---|---|---|
| 0 | 58.8 | 55.8 | +3.0 ± 2.6 | 250 |
| 1 | 59.7 | 56.5 | +3.2 ± 2.6 | 250 |
| 2 | 54.9 | 51.1 | +3.8 ± 2.8 | 250 |
| 3 | 56.7 | 53.9 | +2.8 ± 2.8 | 250 |
| 4 | 57.1 | 53.7 | +3.4 ± 2.6 | 250 |
| 5 | 52.4 | 50.6 | +1.8 ± 2.8 | 250 |

Creator exam: from scripts/lab/creator_exam.py

Sizes: pairings 500, rr_pairings 200, crowd 1000, pvpoke 500, reader 250, predict 60, positions 3, asks 8, timing 100, endgame None

## Cost (CPU seconds per unit, this machine) and projected times

- reader: `website` 12.79; `website,finish_safe=1` 12.77; `website,bait_mix=0.4` 12.99; `website,shield_two=0.05,shield_one=0` 12.81; `website,swap_after_throw=1` 12.71; `website,finish_safe=1,bait_mix=0.4,shield_two=0.05,shield_one=0,swap_after_throw=1` 13.11
- timing: `website` 3.66; `website,finish_safe=1` 3.71; `website,bait_mix=0.4` 3.77; `website,shield_two=0.05,shield_one=0` 3.64; `website,swap_after_throw=1` 3.69; `website,finish_safe=1,bait_mix=0.4,shield_two=0.05,shield_one=0,swap_after_throw=1` 3.77
- crowd: `website` 3.87; `website,finish_safe=1` 3.86; `website,bait_mix=0.4` 3.89; `website,shield_two=0.05,shield_one=0` 3.86; `website,swap_after_throw=1` 3.82; `website,finish_safe=1,bait_mix=0.4,shield_two=0.05,shield_one=0,swap_after_throw=1` 3.87
- endgame: `website` 0.01; `website,finish_safe=1` 0.01; `website,bait_mix=0.4` 0.01; `website,shield_two=0.05,shield_one=0` 0.01; `website,swap_after_throw=1` 0.01; `website,finish_safe=1,bait_mix=0.4,shield_two=0.05,shield_one=0,swap_after_throw=1` 0.01
- pvpoke: `website` 3.73; `website,finish_safe=1` 3.72; `website,bait_mix=0.4` 3.75; `website,shield_two=0.05,shield_one=0` 3.77; `website,swap_after_throw=1` 3.70; `website,finish_safe=1,bait_mix=0.4,shield_two=0.05,shield_one=0,swap_after_throw=1` 3.75
- predict: `website` 5.69; `website,finish_safe=1` 5.72; `website,bait_mix=0.4` 5.59; `website,shield_two=0.05,shield_one=0` 5.86; `website,swap_after_throw=1` 5.74; `website,finish_safe=1,bait_mix=0.4,shield_two=0.05,shield_one=0,swap_after_throw=1` 5.96
- h2h: `website,shield_two=0.05,shield_one=0 | website` 12.61; `website,finish_safe=1 | website` 12.44; `website,swap_after_throw=1 | website` 12.39; `website,bait_mix=0.4 | website` 12.56; `website,finish_safe=1,bait_mix=0.4,shield_two=0.05,shield_one=0,swap_after_throw=1 | website` 12.71
- smoke: 0.28 CPU hours, about 0.02 h on 14 workers, 0.14 h on 2
- screen: 24.82 CPU hours, about 1.77 h on 14 workers, 12.41 h on 2
- confirm: 78.07 CPU hours, about 5.58 h on 14 workers, 39.04 h on 2

Elapsed: 189.2 min in all; this invocation 189.2 min on 8 workers.
