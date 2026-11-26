# League engine-set: screen preset, seed 5801, field mixed

Reference: `website`. Shares and points are in percent with 95% margins; Δ is paired on the reference (same battles). Verdict: Luke's rule (above 50% head to head beyond the margin, no loss beyond the margin against the crowd or PvPoke's AI). ↓ lower is better.

| # | spec | verdict | head to head vs ref | crowd, Δ ref | PvPoke, Δ ref | round robin | reader's gain ↓, Δ ref | predictable (modal share) | live ms median / p99, cut | endgame points lost ↓, Δ ref | creator exam |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | `website` | reference | — | 76.0 ± 2.6 | 84.1 ± 3.2 | 46.5 ± 1.4 | +1.7 ± 3.1 | 98.3 ± 0.9, varies 6.7 (180) | 109 / 531, cut 3.9 | 5.77 ± 2.54 | 74.4 ± 3.3 |
| 1 | `bot` | fail: worse head to head; loses points to crowd | 26.6 ± 2.4 (500) | 65.8, -10.2 ± 3.2 | 83.4, -0.7 ± 3.7 | 21.9 ± 2.3 | +1.0 ± 1.3, -0.7 ± 3.3 | 100.0 ± 0.0, varies 0.0 (180) | 0 / 2 (no deadline) | 7.21 ± 2.97, +1.45 ± 1.28 | 70.9 ± 3.5 |
| 2 | `website,engine=tree,fix_stay=1` | no gain shown: head to head within margin | 52.2 ± 2.3 (500) | 75.8, -0.2 ± 1.4 | 84.5, +0.4 ± 1.4 | 48.7 ± 1.8 | +2.4 ± 3.2, +0.7 ± 1.9 | 98.3 ± 1.0, varies 6.1 (180) | 109 / 516, cut 4.3 | 5.77 ± 2.54, +0.00 ± 0.00 | 75.2 ± 3.3 |
| 3 | `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh` | pass: confirm on a fresh seed | 60.5 ± 2.4 (500) | 80.0, +4.0 ± 2.7 | 90.0, +5.9 ± 3.0 | 57.6 ± 2.2 | +2.4 ± 3.1, +0.7 ± 4.4 | 97.8 ± 1.1, varies 10.0 (180) | 109 / 516, cut 3.6 | 4.95 ± 2.34, -0.81 ± 1.20 | 75.0 ± 3.3 |
| 4 | `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1` | pass: confirm on a fresh seed | 62.6 ± 2.5 (500) | 80.0, +4.0 ± 2.9 | 90.1, +6.0 ± 3.1 | 61.3 ± 2.2 | +0.0 ± 3.1, -1.7 ± 4.6 | 97.1 ± 1.2, varies 12.2 (180) | 125 / 531, cut 4.5 | 4.01 ± 1.96, -1.76 ± 1.49 | 76.9 ± 3.2 |
| 5 | `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1,q=runs/lab-pop-q.npz,opp_q=runs/general-decide/q.npz` | pass: confirm on a fresh seed | 65.5 ± 2.5 (500) | 81.7, +5.7 ± 3.0 | 88.5, +4.4 ± 3.1 | 63.7 ± 2.7 | +3.8 ± 3.0, +2.1 ± 4.2 | 95.5 ± 1.8, varies 15.0 (180) | 125 / 543, cut 5.0 | 3.59 ± 1.69, -2.18 ± 1.71 | 74.7 ± 3.3 |

## Round robin (row's score against the column, %)

| | 0 | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|---|
| 0 | · | 73.4 ± 2.4 | 47.8 ± 2.3 | 39.6 ± 2.4 | 37.4 ± 2.5 | 34.5 ± 2.5 |
| 1 | 26.6 ± 2.4 | · | 26.6 ± 3.9 | 19.5 ± 3.6 | 19.1 ± 3.6 | 18.8 ± 3.5 |
| 2 | 52.2 ± 2.3 | 73.4 ± 3.9 | · | 41.8 ± 3.7 | 40.8 ± 4.1 | 35.2 ± 4.1 |
| 3 | 60.5 ± 2.4 | 80.5 ± 3.6 | 58.2 ± 3.7 | · | 45.1 ± 4.1 | 44.6 ± 4.2 |
| 4 | 62.6 ± 2.5 | 80.9 ± 3.6 | 59.2 ± 4.1 | 54.9 ± 4.1 | · | 47.9 ± 3.9 |
| 5 | 65.5 ± 2.5 | 81.2 ± 3.5 | 64.8 ± 4.1 | 55.4 ± 4.2 | 52.1 ± 3.9 | · |

No rock-paper-scissors cycle on the point estimates.

## Predictability by kind of decision (modal share; varies = positions with more than one answer)

| # | throw | switch | shield | replace | asks | battles |
|---|---|---|---|---|---|---|
| 0 | 99.4 (varies 3.3, 60) | 95.6 (varies 16.7, 60) | 100.0 (varies 0.0, 60) | — | 8 | 60 |
| 1 | 100.0 (varies 0.0, 60) | 100.0 (varies 0.0, 60) | 100.0 (varies 0.0, 60) | — | 8 | 60 |
| 2 | 99.4 (varies 3.3, 60) | 95.4 (varies 15.0, 60) | 100.0 (varies 0.0, 60) | — | 8 | 60 |
| 3 | 98.5 (varies 10.0, 60) | 95.0 (varies 20.0, 60) | 100.0 (varies 0.0, 60) | — | 8 | 60 |
| 4 | 97.7 (varies 8.3, 60) | 96.5 (varies 13.3, 60) | 97.1 (varies 15.0, 60) | — | 8 | 60 |
| 5 | 94.0 (varies 16.7, 60) | 95.8 (varies 13.3, 60) | 96.7 (varies 15.0, 60) | — | 8 | 60 |

## Live timing (searched decisions, CPU clock, the website's deadlines; † no deadline: CPU time per searched decision, or per decision if it does not count searches)

| # | battles | decisions | median ms | p99 ms (95%) | worst | cut short (95%) | no round | release limits | crowd under deadlines |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 100 | 2200 | 109 | 531 (484–594) | 797 | 3.9 (2.5–5.5) | 0.1 | ok | 72.5 ± 8.7 |
| 1 † | 100 | 6590 | 0 | 2 (2–2) | 45 | 0.0 (0.0–0.0) | 0.0 | n/a | 67.0 ± 9.3 |
| 2 | 100 | 2197 | 109 | 516 (484–562) | 797 | 4.3 (2.6–6.3) | 0.1 | ok | 73.5 ± 8.6 |
| 3 | 100 | 2297 | 109 | 516 (513–561) | 766 | 3.6 (2.4–4.8) | 0.1 | ok | 82.0 ± 7.6 |
| 4 | 100 | 2804 | 125 | 531 (500–547) | 797 | 4.5 (3.0–6.1) | 0.2 | ok | 80.5 ± 7.7 |
| 5 | 100 | 2827 | 125 | 543 (495–578) | 750 | 5.0 (3.1–6.7) | 0.1 | ok | 81.5 ± 7.6 |

## Exact endgames (points lost a decision ×100, clustered by game)

| # | all | moves | shields | blunders ≥ 0.1 | positions |
|---|---|---|---|---|---|
| 0 | 5.77 ± 2.54 | 6.24 | 3.12 | 8.8% | 318 |
| 1 | 7.21 ± 2.97 | 7.94 | 3.12 | 10.7% | 318 |
| 2 | 5.77 ± 2.54 | 6.24 | 3.12 | 8.8% | 318 |
| 3 | 4.95 ± 2.34 | 5.28 | 3.12 | 8.2% | 318 |
| 4 | 4.01 ± 1.96 | 4.17 | 3.12 | 7.2% | 318 |
| 5 | 3.59 ± 1.69 | 3.68 | 3.12 | 6.3% | 318 |

## Exploitability detail (score against the probe, not reading / reading)

| # | not read | read | gain ↓ | pairs |
|---|---|---|---|---|
| 0 | 59.8 | 58.1 | +1.7 ± 3.1 | 250 |
| 1 | 34.6 | 33.6 | +1.0 ± 1.3 | 250 |
| 2 | 61.9 | 59.5 | +2.4 ± 3.2 | 250 |
| 3 | 65.3 | 62.9 | +2.4 ± 3.1 | 250 |
| 4 | 67.6 | 67.6 | +0.0 ± 3.1 | 250 |
| 5 | 70.6 | 66.8 | +3.8 ± 3.0 | 250 |

Creator exam: from scripts/lab/creator_exam.py

Sizes: pairings 500, rr_pairings 200, crowd 1000, pvpoke 500, reader 250, predict 60, positions 3, asks 8, timing 100, endgame None

## Cost (CPU seconds per unit, this machine) and projected times

- h2h: `bot | website` 6.82; `website,engine=tree,fix_stay=1 | bot` 6.69; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh | bot` 7.36; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1 | bot` 8.78; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1,q=runs/lab-pop-q.npz,opp_q=runs/general-decide/q.npz | bot` 9.53; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1 | website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh` 15.75; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh | website` 13.68; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh | website,engine=tree,fix_stay=1` 13.75; `website,engine=tree,fix_stay=1 | website` 12.83; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1 | website` 15.38; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1,q=runs/lab-pop-q.npz,opp_q=runs/general-decide/q.npz | website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh` 16.53; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1,q=runs/lab-pop-q.npz,opp_q=runs/general-decide/q.npz | website` 16.00; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1 | website,engine=tree,fix_stay=1` 15.52; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1,q=runs/lab-pop-q.npz,opp_q=runs/general-decide/q.npz | website,engine=tree,fix_stay=1` 16.25; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1,q=runs/lab-pop-q.npz,opp_q=runs/general-decide/q.npz | website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1` 18.32
- reader: `website` 13.06; `bot` 1.18; `website,engine=tree,fix_stay=1` 13.26; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh` 14.44; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1` 17.34; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1,q=runs/lab-pop-q.npz,opp_q=runs/general-decide/q.npz` 18.45
- timing: `website` 3.37; `bot` 0.02; `website,engine=tree,fix_stay=1` 3.43; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh` 3.56; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1` 4.66; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1,q=runs/lab-pop-q.npz,opp_q=runs/general-decide/q.npz` 4.73
- endgame: `website` 0.01; `bot` 0.00; `website,engine=tree,fix_stay=1` 0.01; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh` 0.01; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1` 0.01; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1,q=runs/lab-pop-q.npz,opp_q=runs/general-decide/q.npz` 0.01
- crowd: `bot` 0.02; `website` 3.84; `website,engine=tree,fix_stay=1` 3.90; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh` 3.94; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1` 4.82; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1,q=runs/lab-pop-q.npz,opp_q=runs/general-decide/q.npz` 4.97
- pvpoke: `bot` 0.01; `website` 3.64; `website,engine=tree,fix_stay=1` 3.66; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh` 3.58; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1` 4.35; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1,q=runs/lab-pop-q.npz,opp_q=runs/general-decide/q.npz` 4.41
- predict: `bot` 0.02; `website` 6.12; `website,engine=tree,fix_stay=1` 6.35; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh` 6.35; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1` 8.08; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1,q=runs/lab-pop-q.npz,opp_q=runs/general-decide/q.npz` 8.36
- smoke: 0.41 CPU hours, about 0.03 h on 14 workers, 0.21 h on 2
- screen: 31.37 CPU hours, about 2.24 h on 14 workers, 15.68 h on 2
- confirm: 95.36 CPU hours, about 6.81 h on 14 workers, 47.68 h on 2

Elapsed: 136.6 min in all; this invocation 136.6 min on 14 workers.
