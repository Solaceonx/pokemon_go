# League mixed-screen: screen preset, seed 5301, field mixed

Reference: `website`. Shares and points are in percent with 95% margins; Δ is paired on the reference (same battles). Verdict: Luke's rule (above 50% head to head beyond the margin, no loss beyond the margin against the crowd or PvPoke's AI). ↓ lower is better.

| # | spec | verdict | head to head vs ref | crowd, Δ ref | PvPoke, Δ ref | round robin | reader's gain ↓, Δ ref | predictable (modal share) | live ms median / p99, cut | endgame points lost ↓, Δ ref | creator exam |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | `website` | reference | — | 76.4 ± 2.6 | 86.3 ± 3.0 | 51.3 ± 1.5 | +3.8 ± 3.0 | 97.7 ± 1.2, varies 8.9 (180) | 109 / 531, cut 5.3 | 5.77 ± 2.54 | 73.8 ± 3.4 |
| 1 | `website,shield_mix=0` | pass: confirm on a fresh seed | 54.1 ± 2.4 (500) | 76.3, -0.1 ± 2.6 | 86.5, +0.2 ± 2.7 | — | +3.1 ± 3.0, -0.7 ± 3.6 | 97.8 ± 0.9, varies 10.6 (180) | 109 / 516, cut 5.8 | 5.77 ± 2.54, +0.00 ± 0.00 | 75.3 ± 3.3 |
| 2 | `website,shield_mix=0.05` | no gain shown: head to head within margin | 50.6 ± 2.6 (500) | 73.9, -2.6 ± 2.7 | 85.8, -0.5 ± 3.1 | — | +2.2 ± 3.0, -1.6 ± 3.8 | 92.8 ± 1.7, varies 25.6 (180) | 125 / 531, cut 6.3 | 5.77 ± 2.54, +0.00 ± 0.00 | 75.2 ± 3.3 |
| 3 | `website,shield_mix=0.1` | fail: worse head to head; loses points to crowd; loses points to PvPoke | 46.7 ± 2.6 (500) | 70.5, -5.9 ± 3.0 | 80.8, -5.5 ± 3.4 | — | +1.5 ± 3.2, -2.3 ± 3.9 | 87.9 ± 2.1, varies 38.3 (180) | 109 / 547, cut 6.2 | 5.87 ± 2.54, +0.10 ± 0.20 | 73.1 ± 3.4 |
| 4 | `website,throw_mix=0.03` | fail: worse head to head; loses points to crowd | 46.9 ± 2.5 (500) | 71.1, -5.3 ± 2.7 | 83.3, -3.0 ± 3.2 | — | +2.2 ± 3.0, -1.6 ± 3.6 | 90.3 ± 1.9, varies 31.1 (180) | 125 / 531, cut 4.7 | 6.91 ± 2.60, +1.14 ± 1.85 | 74.1 ± 3.4 |
| 5 | `website,equilibrium=1` | no gain shown: head to head within margin | 48.6 ± 2.7 (500) | 73.7, -2.8 ± 2.9 | 86.2, -0.1 ± 3.0 | — | +2.5 ± 2.5, -1.3 ± 3.4 | 94.9 ± 1.8, varies 18.3 (180) | 125 / 656, cut 9.5 | 5.61 ± 2.53, -0.16 ± 0.31 | 76.1 ± 3.3 |
| 6 | `website,temperature=0.02` | fail: worse head to head; loses points to crowd; loses points to PvPoke | 45.6 ± 2.4 (500) | 68.8, -7.6 ± 2.8 | 81.1, -5.2 ± 3.3 | — | +0.5 ± 3.2, -3.3 ± 3.9 | 89.0 ± 2.1, varies 37.8 (180) | 109 / 531, cut 4.9 | 6.64 ± 2.68, +0.87 ± 1.66 | 73.7 ± 3.4 |

## Round robin (row's score against the column, %)

| | 0 | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|---|
| 0 | · | 45.9 ± 2.4 | 49.4 ± 2.6 | 53.3 ± 2.6 | 53.1 ± 2.5 | 51.3 ± 2.7 | 54.4 ± 2.4 |
| 1 | 54.1 ± 2.4 | · | — | — | — | — | — |
| 2 | 50.6 ± 2.6 | — | · | — | — | — | — |
| 3 | 46.7 ± 2.6 | — | — | · | — | — | — |
| 4 | 46.9 ± 2.5 | — | — | — | · | — | — |
| 5 | 48.6 ± 2.7 | — | — | — | — | · | — |
| 6 | 45.6 ± 2.4 | — | — | — | — | — | · |

No rock-paper-scissors cycle on the point estimates.

## Predictability by kind of decision (modal share; varies = positions with more than one answer)

| # | throw | switch | shield | replace | asks | battles |
|---|---|---|---|---|---|---|
| 0 | 96.9 (varies 11.7, 60) | 96.2 (varies 15.0, 60) | 100.0 (varies 0.0, 60) | — | 8 | 60 |
| 1 | 97.1 (varies 13.3, 60) | 97.1 (varies 13.3, 60) | 99.2 (varies 5.0, 60) | — | 8 | 60 |
| 2 | 96.9 (varies 11.7, 60) | 96.9 (varies 11.7, 60) | 84.8 (varies 53.3, 60) | — | 8 | 60 |
| 3 | 94.6 (varies 18.3, 60) | 95.2 (varies 16.7, 60) | 74.0 (varies 80.0, 60) | — | 8 | 60 |
| 4 | 76.2 (varies 75.0, 60) | 94.8 (varies 18.3, 60) | 100.0 (varies 0.0, 60) | — | 8 | 60 |
| 5 | 97.7 (varies 11.7, 60) | 94.8 (varies 18.3, 60) | 92.3 (varies 25.0, 60) | — | 8 | 60 |
| 6 | 80.2 (varies 61.7, 60) | 86.7 (varies 51.7, 60) | 100.0 (varies 0.0, 60) | — | 8 | 60 |

## Live timing (searched decisions, CPU clock, the website's deadlines; † no deadline: CPU time per searched decision, or per decision if it does not count searches)

| # | battles | decisions | median ms | p99 ms (95%) | worst | cut short (95%) | no round | release limits | crowd under deadlines |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 100 | 2396 | 109 | 531 (495–578) | 797 | 5.3 (3.4–7.5) | 0.0 | ok | 76.0 ± 8.4 |
| 1 | 100 | 2847 | 109 | 516 (484–563) | 734 | 5.8 (3.8–8.5) | 0.1 | ok | 75.0 ± 8.4 |
| 2 | 100 | 2838 | 125 | 531 (500–578) | 797 | 6.3 (4.0–9.0) | 0.1 | ok | 72.0 ± 8.7 |
| 3 | 100 | 2821 | 109 | 547 (495–578) | 797 | 6.2 (3.9–9.1) | 0.0 | ok | 69.0 ± 9.1 |
| 4 | 100 | 2045 | 125 | 531 (509–562) | 984 | 4.7 (2.8–7.0) | 0.1 | ok | 69.0 ± 9.1 |
| 5 | 100 | 2790 | 125 | 656 (615–755) | 1125 | 9.5 (7.4–11.9) | 0.1 | ok | 72.5 ± 8.7 |
| 6 | 100 | 2160 | 109 | 531 (500–562) | 797 | 4.9 (3.1–7.0) | 0.1 | ok | 70.0 ± 9.0 |

## Exact endgames (points lost a decision ×100, clustered by game)

| # | all | moves | shields | blunders ≥ 0.1 | positions |
|---|---|---|---|---|---|
| 0 | 5.77 ± 2.54 | 6.24 | 3.12 | 8.8% | 318 |
| 1 | 5.77 ± 2.54 | 6.24 | 3.12 | 8.8% | 318 |
| 2 | 5.77 ± 2.54 | 6.24 | 3.12 | 8.8% | 318 |
| 3 | 5.87 ± 2.54 | 6.24 | 3.82 | 9.1% | 318 |
| 4 | 6.91 ± 2.60 | 7.58 | 3.12 | 10.4% | 318 |
| 5 | 5.61 ± 2.53 | 6.24 | 2.08 | 8.5% | 318 |
| 6 | 6.64 ± 2.68 | 7.27 | 3.12 | 10.4% | 318 |

## Exploitability detail (score against the probe, not reading / reading)

| # | not read | read | gain ↓ | pairs |
|---|---|---|---|---|
| 0 | 59.4 | 55.6 | +3.8 ± 3.0 | 250 |
| 1 | 59.9 | 56.8 | +3.1 ± 3.0 | 250 |
| 2 | 58.8 | 56.6 | +2.2 ± 3.0 | 250 |
| 3 | 56.4 | 54.9 | +1.5 ± 3.2 | 250 |
| 4 | 54.9 | 52.7 | +2.2 ± 3.0 | 250 |
| 5 | 54.1 | 51.6 | +2.5 ± 2.5 | 250 |
| 6 | 52.7 | 52.2 | +0.5 ± 3.2 | 250 |

Creator exam: from scripts/lab/creator_exam.py

Sizes: pairings 500, rr_pairings 200, crowd 1000, pvpoke 500, reader 250, predict 60, positions 3, asks 8, timing 100, endgame None

## Cost (CPU seconds per unit, this machine) and projected times

- pvpoke: `website` 3.85; `website,shield_mix=0` 4.60; `website,shield_mix=0.05` 4.54; `website,throw_mix=0.03` 3.13; `website,shield_mix=0.1` 4.45; `website,temperature=0.02` 3.42; `website,equilibrium=1` 5.26
- crowd: `website` 3.89; `website,shield_mix=0` 4.68; `website,shield_mix=0.05` 4.59; `website,throw_mix=0.03` 3.32; `website,shield_mix=0.1` 4.51; `website,temperature=0.02` 3.46; `website,equilibrium=1` 5.58
- h2h: `website,throw_mix=0.03 | website` 11.64; `website,temperature=0.02 | website` 12.41; `website,shield_mix=0.05 | website` 13.87; `website,shield_mix=0.1 | website` 13.76; `website,shield_mix=0 | website` 13.92; `website,equilibrium=1 | website` 15.61
- timing: `website` 3.67; `website,shield_mix=0` 4.47; `website,shield_mix=0.05` 4.54; `website,shield_mix=0.1` 4.41; `website,throw_mix=0.03` 3.36; `website,equilibrium=1` 4.91; `website,temperature=0.02` 3.33
- endgame: `website` 0.01; `website,shield_mix=0` 0.01; `website,shield_mix=0.05` 0.01; `website,shield_mix=0.1` 0.01; `website,throw_mix=0.03` 0.01; `website,equilibrium=1` 0.01; `website,temperature=0.02` 0.01
- reader: `website` 12.98; `website,shield_mix=0` 15.93; `website,shield_mix=0.05` 15.49; `website,shield_mix=0.1` 15.33; `website,throw_mix=0.03` 11.58; `website,temperature=0.02` 11.81; `website,equilibrium=1` 19.41
- predict: `website` 6.31; `website,shield_mix=0` 7.93; `website,shield_mix=0.05` 8.04; `website,shield_mix=0.1` 7.69; `website,throw_mix=0.03` 5.93; `website,equilibrium=1` 10.43; `website,temperature=0.02` 5.98
- smoke: 0.37 CPU hours, about 0.03 h on 14 workers, 0.18 h on 2
- screen: 32.48 CPU hours, about 2.32 h on 14 workers, 16.24 h on 2
- confirm: 102.19 CPU hours, about 7.30 h on 14 workers, 51.10 h on 2

Elapsed: 362.6 min in all; this invocation 362.7 min on 8 workers.
