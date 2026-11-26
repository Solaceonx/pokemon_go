# League samples-timing: screen preset, seed 6202, field mixed

Reference: `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1,q=runs/lab-pop-q.npz,opp_q=runs/general-decide/q.npz`. Shares and points are in percent with 95% margins; Δ is paired on the reference (same battles). Verdict: Luke's rule (above 50% head to head beyond the margin, no loss beyond the margin against the crowd or PvPoke's AI). ↓ lower is better.

| # | spec | verdict | head to head vs ref | crowd, Δ ref | PvPoke, Δ ref | round robin | reader's gain ↓, Δ ref | predictable (modal share) | live ms median / p99, cut | endgame points lost ↓, Δ ref | creator exam |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1,q=runs/lab-pop-q.npz,opp_q=runs/general-decide/q.npz` | reference | — | — | — | — | — | — | 109 / 588, cut 3.1 | — | — |
| 1 | `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1,q=runs/lab-pop-q.npz,opp_q=runs/general-decide/q.npz,samples=48` | no head to head | — | — | — | — | — | — | 156 / 776, cut 10.6 | — | — |
| 2 | `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1,q=runs/lab-pop-q.npz,opp_q=runs/general-decide/q.npz,samples=64` | no head to head | — | — | — | — | — | — | 203 / 938, cut 16.9 | — | — |

## Round robin (row's score against the column, %)

| | 0 | 1 | 2 |
|---|---|---|---|
| 0 | · | — | — |
| 1 | — | · | — |
| 2 | — | — | · |

No rock-paper-scissors cycle on the point estimates.

## Predictability by kind of decision (modal share; varies = positions with more than one answer)

| # | throw | switch | shield | replace | asks | battles |
|---|---|---|---|---|---|---|

## Live timing (searched decisions, CPU clock, the website's deadlines; † no deadline: CPU time per searched decision, or per decision if it does not count searches)

| # | battles | decisions | median ms | p99 ms (95%) | worst | cut short (95%) | no round | release limits | crowd under deadlines |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 100 | 2640 | 109 | 588 (523–672) | 1094 | 3.1 (1.8–4.6) | 0.1 | ok | 84.0 ± 7.1 |
| 1 | 100 | 2633 | 156 | 776 (719–858) | 1297 | 10.6 (8.6–13.0) | 0.3 | ok | 82.5 ± 7.4 |
| 2 | 100 | 2759 | 203 | 938 (828–1146) | 1297 | 16.9 (14.4–19.9) | 0.5 | over | 82.5 ± 7.3 |

## Exact endgames (points lost a decision ×100, clustered by game)

| # | all | moves | shields | blunders ≥ 0.1 | positions |
|---|---|---|---|---|---|

## Exploitability detail (score against the probe, not reading / reading)

| # | not read | read | gain ↓ | pairs |
|---|---|---|---|---|

Sizes: pairings 500, rr_pairings 200, crowd 1000, pvpoke 500, reader 250, predict 60, positions 3, asks 8, timing 100, endgame None

## Cost (CPU seconds per unit, this machine) and projected times

- timing: `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1,q=runs/lab-pop-q.npz,opp_q=runs/general-decide/q.npz` 4.05; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1,q=runs/lab-pop-q.npz,opp_q=runs/general-decide/q.npz,samples=48` 5.58; `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1,q=runs/lab-pop-q.npz,opp_q=runs/general-decide/q.npz,samples=64` 6.95
- smoke: 0.01 CPU hours, about 0.00 h on 14 workers, 0.01 h on 2
- screen: 0.46 CPU hours, about 0.03 h on 14 workers, 0.23 h on 2
- confirm: 0.92 CPU hours, about 0.07 h on 14 workers, 0.46 h on 2

Elapsed: 3.7 min in all; this invocation 3.7 min on 8 workers.
