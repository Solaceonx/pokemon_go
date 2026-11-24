# League best-screen: screen preset, seed 5501, field mixed

Reference: `website`. Shares and points are in percent with 95% margins; Δ is paired on the reference (same battles). Verdict: Luke's rule (above 50% head to head beyond the margin, no loss beyond the margin against the crowd or PvPoke's AI). ↓ lower is better.

| # | spec | verdict | head to head vs ref | crowd, Δ ref | PvPoke, Δ ref | round robin | reader's gain ↓, Δ ref | predictable (modal share) | live ms median / p99, cut | endgame points lost ↓, Δ ref | creator exam |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | `website` | reference | — | 75.2 ± 2.7 | 85.1 ± 3.1 | 36.8 ± 2.1 | +1.9 ± 3.0 | 97.6 ± 1.1, varies 8.9 (180) | 125 / 532, cut 5.6 | 5.77 ± 2.54 | 75.3 ± 3.3 |
| 1 | `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh` | pass: confirm on a fresh seed | 60.7 ± 2.5 (500) | 82.2, +6.9 ± 2.7 | 85.6, +0.5 ± 3.3 | — | -0.7 ± 2.7, -2.6 ± 3.6 | 97.0 ± 1.2, varies 11.1 (180) | 125 / 547, cut 6.4 | 4.95 ± 2.34, -0.81 ± 1.20 | 76.0 ± 3.3 |
| 2 | `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0` | pass: confirm on a fresh seed | 63.8 ± 2.5 (500) | 80.5, +5.2 ± 2.9 | 86.0, +0.9 ± 3.3 | — | +2.2 ± 2.7, +0.3 ± 3.8 | 94.9 ± 1.6, varies 19.4 (180) | 141 / 531, cut 5.6 | 4.95 ± 2.34, -0.81 ± 1.20 | 76.1 ± 3.3 |
| 3 | `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1` | pass: confirm on a fresh seed | 64.2 ± 2.5 (500) | 80.8, +5.5 ± 2.9 | 86.0, +0.9 ± 3.3 | — | +2.2 ± 2.7, +0.3 ± 3.7 | 94.9 ± 1.6, varies 19.4 (180) | 141 / 547, cut 5.7 | 4.01 ± 1.96, -1.76 ± 1.49 | 76.0 ± 3.3 |
| 4 | `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1,shield_two=0.05,shield_one=0` | pass: confirm on a fresh seed | 64.1 ± 2.4 (500) | 80.8, +5.5 ± 2.9 | 85.7, +0.6 ± 3.3 | — | +2.7 ± 2.8, +0.8 ± 3.9 | 94.8 ± 1.6, varies 18.9 (180) | 141 / 547, cut 5.8 | 3.85 ± 1.95, -1.91 ± 1.51 | 76.4 ± 3.2 |
| 5 | `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1,shield_two=0.05,shield_one=0,swap_after_throw=1` | pass: confirm on a fresh seed | 63.0 ± 2.5 (500) | 79.6, +4.3 ± 2.9 | 85.4, +0.3 ± 3.3 | — | +1.5 ± 2.8, -0.4 ± 3.9 | 95.1 ± 1.6, varies 18.3 (180) | 141 / 531, cut 6.1 | 3.91 ± 2.01, -1.86 ± 1.59 | 76.4 ± 3.2 |

## Round robin (row's score against the column, %)

| | 0 | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|---|
| 0 | · | 39.4 ± 2.5 | 36.2 ± 2.5 | 35.8 ± 2.5 | 35.9 ± 2.4 | 37.0 ± 2.5 |
| 1 | 60.7 ± 2.5 | · | — | — | — | — |
| 2 | 63.8 ± 2.5 | — | · | — | — | — |
| 3 | 64.2 ± 2.5 | — | — | · | — | — |
| 4 | 64.1 ± 2.4 | — | — | — | · | — |
| 5 | 63.0 ± 2.5 | — | — | — | — | · |

No rock-paper-scissors cycle on the point estimates.

## Predictability by kind of decision (modal share; varies = positions with more than one answer)

| # | throw | switch | shield | replace | asks | battles |
|---|---|---|---|---|---|---|
| 0 | 98.3 (varies 8.3, 60) | 94.6 (varies 18.3, 60) | 100.0 (varies 0.0, 60) | — | 8 | 60 |
| 1 | 96.2 (varies 15.0, 60) | 94.8 (varies 18.3, 60) | 100.0 (varies 0.0, 60) | — | 8 | 60 |
| 2 | 94.6 (varies 18.3, 60) | 93.1 (varies 25.0, 60) | 96.9 (varies 15.0, 60) | — | 8 | 60 |
| 3 | 94.6 (varies 18.3, 60) | 93.1 (varies 25.0, 60) | 96.9 (varies 15.0, 60) | — | 8 | 60 |
| 4 | 93.5 (varies 21.7, 60) | 93.1 (varies 25.0, 60) | 97.7 (varies 10.0, 60) | — | 8 | 60 |
| 5 | 94.0 (varies 21.7, 60) | 93.5 (varies 23.3, 60) | 97.7 (varies 10.0, 60) | — | 8 | 60 |

## Live timing (searched decisions, CPU clock, the website's deadlines; † no deadline: CPU time per searched decision, or per decision if it does not count searches)

| # | battles | decisions | median ms | p99 ms (95%) | worst | cut short (95%) | no round | release limits | crowd under deadlines |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 100 | 2197 | 125 | 532 (516–578) | 797 | 5.6 (3.9–7.7) | 0.1 | ok | 75.0 ± 8.4 |
| 1 | 100 | 2177 | 125 | 547 (531–594) | 703 | 6.4 (4.5–8.2) | 0.3 | ok | 80.5 ± 7.7 |
| 2 | 100 | 2717 | 141 | 531 (500–562) | 688 | 5.6 (4.1–7.1) | 0.3 | ok | 79.5 ± 7.9 |
| 3 | 100 | 2711 | 141 | 547 (516–573) | 766 | 5.7 (4.1–7.3) | 0.2 | ok | 78.5 ± 8.0 |
| 4 | 100 | 2729 | 141 | 547 (500–578) | 766 | 5.8 (4.1–7.3) | 0.3 | ok | 78.5 ± 8.0 |
| 5 | 100 | 2701 | 141 | 531 (500–578) | 797 | 6.1 (4.4–7.7) | 0.2 | ok | 77.5 ± 8.2 |

## Exact endgames (points lost a decision ×100, clustered by game)

| # | all | moves | shields | blunders ≥ 0.1 | positions |
|---|---|---|---|---|---|
| 0 | 5.77 ± 2.54 | 6.24 | 3.12 | 8.8% | 318 |
| 1 | 4.95 ± 2.34 | 5.28 | 3.12 | 8.2% | 318 |
| 2 | 4.95 ± 2.34 | 5.28 | 3.12 | 8.2% | 318 |
| 3 | 4.01 ± 1.96 | 4.17 | 3.12 | 7.2% | 318 |
| 4 | 3.85 ± 1.95 | 4.17 | 2.08 | 6.9% | 318 |
| 5 | 3.91 ± 2.01 | 4.23 | 2.08 | 6.6% | 318 |

## Exploitability detail (score against the probe, not reading / reading)

| # | not read | read | gain ↓ | pairs |
|---|---|---|---|---|
| 0 | 55.4 | 53.5 | +1.9 ± 3.0 | 250 |
| 1 | 63.6 | 64.3 | -0.7 ± 2.7 | 250 |
| 2 | 68.6 | 66.4 | +2.2 ± 2.7 | 250 |
| 3 | 68.8 | 66.6 | +2.2 ± 2.7 | 250 |
| 4 | 69.4 | 66.7 | +2.7 ± 2.8 | 250 |
| 5 | 68.1 | 66.6 | +1.5 ± 2.8 | 250 |

Creator exam: from scripts/lab/creator_exam.py

Sizes: pairings 500, rr_pairings 200, crowd 1000, pvpoke 500, reader 250, predict 60, positions 3, asks 8, timing 100, endgame None

## Cost (CPU seconds per unit, this machine) and projected times

- endgame: `website` 0.01; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh` 0.01; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0` 0.01; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1` 0.01; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1,shield_two=0.05,shield_one=0` 0.01; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1,shield_two=0.05,shield_one=0,swap_after_throw=1` 0.01
- predict: `website` 6.38; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh` 6.55; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0` 8.57; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1` 8.57; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1,shield_two=0.05,shield_one=0` 8.57; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1,shield_two=0.05,shield_one=0,swap_after_throw=1` 8.47
- reader: `website` 13.06; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh` 14.09; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0` 17.53; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1` 17.48; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1,shield_two=0.05,shield_one=0` 17.69; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1,shield_two=0.05,shield_one=0,swap_after_throw=1` 17.45
- timing: `website` 3.55; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh` 3.68; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0` 4.62; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1` 4.59; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1,shield_two=0.05,shield_one=0` 4.61; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1,shield_two=0.05,shield_one=0,swap_after_throw=1` 4.57
- crowd: `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh` 4.13; `website` 3.92; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0` 4.98; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1` 5.00; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1,shield_two=0.05,shield_one=0` 5.00; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1,shield_two=0.05,shield_one=0,swap_after_throw=1` 4.98
- pvpoke: `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh` 3.85; `website` 3.96; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0` 4.52; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1` 4.55; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1,shield_two=0.05,shield_one=0` 4.54; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1,shield_two=0.05,shield_one=0,swap_after_throw=1` 4.54
- h2h: `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh | website` 14.01; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1,shield_two=0.05,shield_one=0,swap_after_throw=1 | website` 15.49; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1 | website` 15.47; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1,shield_two=0.05,shield_one=0 | website` 15.40; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0 | website` 15.35
- smoke: 0.34 CPU hours, about 0.02 h on 14 workers, 0.17 h on 2
- screen: 30.16 CPU hours, about 2.15 h on 14 workers, 15.08 h on 2
- confirm: 95.25 CPU hours, about 6.80 h on 14 workers, 47.62 h on 2

Elapsed: 115.5 min in all; this invocation 115.5 min on 16 workers.
