# Mixed engine lab, 2026-11-24

Built on `lab-mixed`, starting at `e1ab01d8`. No commits, model changes, website changes, or default policy changes.

## Implementation

- `pogo/engine.py`: constructor keys, `shield`, `_decide`, `_draw`, `_matrix`, `_mixed_actions`, `_mixed`, `_look`,
  `_land_their_throw`, and the `_FirstShield` rollout wrapper.
- `pogo/lab/mixed.py`: stable logit distribution, close-call shield floor, and exact 2x2 equilibrium distribution.
- `scripts/engine_versus.py`: small additions to `parse`, `Counted`, and `activity_summary`. Existing shield/prompt
  counting and resumable per-battle aggregation are reused.
- `tests/test_lab_mixed.py`: 23 tests, including the pre-edit fixtures in `default-digests.json`.

`shield_mix=tau` explicitly enables shield search at real prompts, preserving the last-Pokemon rule. `throw_mix=tau` explicitly
enables the throw head. Omitting either key preserves its old behavior. `shield_floor=p` alone also enables shield
search, using deterministic search plus the close-call floor. Temperatures must be finite and nonnegative;
the floor must lie in [0, 0.5]. Explicit lab shield controls take precedence over `people_shield` shortcuts
at real prompts with more than one Pokemon left. Hypothetical shield advice uses the ordinary Learner answer.

For searched worths `v[k]` and the trained bot's pick `b`, the score is
`s[k] = v[k] + edge * (k == b)`. Positive temperatures give
`P(k) = exp((s[k] - max(s)) / tau) / sum(exp((s[j] - max(s)) / tau))`.
At zero temperature the existing strict search test is used: override the bot only if the best value beats it
by more than `edge`; ties keep the bot. No mixing RNG draw is consumed for a pure distribution.
Thus `shield_mix=0` is deterministic **shield search**, not the shipped website shield policy, which does not
normally search shields. A positive shield floor can still randomize a zero-temperature close call.

For ordinary shield search, clamp `P(shield)` to [p, 1-p] only if the two unadjusted searched values differ by at
most `edge`. The remaining probability takes the hit. Throws use the searched legal hold/move options.
The existing `no_tell_bait` override, when explicitly combined with these keys, sends the prohibited move's mass
to hold.

`equilibrium=1` reuses task 29's common-seed matrix-cell search, task 25's incoming-move selection and shield
continuation, and `pogo.agents.solve_2x2` (exact closed form, not task 29's 3,000-step fictitious play).
At our shield prompt the rows are take/shield and columns are both affordable incoming charged moves, using
the supplied pre-cost energy. With just one affordable incoming move, ordinary shield search applies (or the
specified shield temperature). No actual hidden move or unshown team member is read.

At our throw head, with both differently priced moves affordable and opposing shields available, the rows
are our two moves and columns are their shield/take responses to that step's throw. If CMP cancels our throw,
the fixed response expires; a later Pokemon's throw uses the rollout policy. The ordinary search decides hold
versus throw first; the equilibrium splits
only the probability assigned to throwing. With `throw_mix`, this retains the logit's hold probability.
This is an exact solution of that local 2x2 game, not an equilibrium of the whole battle or of hold/switch play.
If a shield floor is combined with equilibrium, closeness uses the two rows' security values (worst columns);
clamping can deliberately move the policy away from the exact equilibrium.

Only complete paired search rounds count. Existing RealTime deadlines and fallback behavior are reused.
The opt-in shield landing uses `Battle._throw` for damage, buffs, Disguise, Gulp Missile and form changes;
the default task-25 landing is retained unchanged. Timing and both sides' simultaneous faint/replacement handling then
continue from the post-hit position. The usual shield lookup remains an approximation to a paused battle,
as in task 25; it does not model a second already-queued CMP throw explicitly.

New policies draw from the player's private `_mix_rng`, deterministically derived from a copy of its seeded
`rng`, without advancing search dice. The legacy initializer uses `hash(rng.getstate())`, whose None component
is process-dependent; the new opt-in initializer avoids that. Clones copy the stream; the existing Reader
reseeds its prediction clone's private mixing stream. Legacy/default RNG initialization remains unchanged.

`mean P(chosen)` is the realized average probability assigned to the sampled shield/throw-head choice.
It excludes forced fast moves, switch/replacement decisions, imagined players and Reader prediction clones.
For distribution p its expectation is sum(p[k]^2), not max(p). Default deterministic decisions contribute 1.
Legacy `temperature`, `mix`, `mix_shield` and simultaneous `mix_switch` random decisions are excluded; the
printout says so. Deterministic fallbacks still count. Active legacy mix options cannot be combined with
active lab options: the constructor and spec parser both raise an error naming the conflicting keys.
Counting version `per-battle-v3-mixed` prevents resuming older probability totals under these semantics.
Shield use retains the existing denominator: real prompts with a shield available. Saved totals are sums and
counts, so chunk sizes and resuming do not average averages. This is a conditional head-choice diagnostic,
not a calibrated opponent predictor or a probability for a whole turn after every possible rule override.

## Review fixes and validation

The independent review's six requests are addressed:

1. `Engine.act`, `_pick_move` and `_decide` maintain a decision-depth guard. Nested `shield` calls use
   `Learner.shield` / `Learner._decide`, without lab search, private mixing draws or probability bookkeeping.
   The search body is now `_search_decision`. The Altaria (10 HP, 65 energy) versus Melmetal (100 energy)
   regression keeps the default doomed=True and Moonblast advice for 30 mixing seeds each with shield mix,
   equilibrium, and both enabled. It checks unchanged looks, search dice and mixing dice inside the callback.
   Separate tests cover the Learner timing post-check, exception cleanup and real prompts still searching.
2. `Engine.shield` returns the ordinary Learner answer on our last Pokemon. Tests exercise all shield controls,
   `last_always=True/False`, 30 seeds, and no search or RNG advancement, including RealTime bookkeeping.
3. `_FirstShield.shield` scopes its answer to the construction turn, supplied by `_look` and `_land_their_throw`.
   The CMP regression knocks out Azumarill before it can throw, then verifies that the replacement's actual
   throw does not consume the opponent's shield. The existing first-response test still passes.
4. `Engine._search_decision`, `_mixed` and `_act` clear probability diagnostics for legacy random paths.
   `activity_summary` labels their exclusion; `validate_mixing` in `pogo/lab/mixed.py` is shared by the
   constructor and `engine_versus.parse`. Tests cover all four legacy paths and all 16 old/new key pairings.
5. `_land_their_throw` gathers both replacement choices before either `_enter`, matching `Battle.step`.
   A real Gulp Missile double-faint test compares the landing state to `Battle.step` and verifies that neither
   player sees the other's new Pokemon while choosing a replacement.
6. `runs/lab-mixed-screen.cmd` remains one cmd.exe line, now with `website,shield_mix=0` first and `--workers 10`.
   Only the one-worker smoke below was executed here.

Before these fixes: 436 tests in 42.111 seconds, no assertion failures, three known missing-OCR errors and
seven skips (`tests-review-before.out`). After: **445 tests in 40.948 seconds**, no assertion failures, the same
three OCR errors and seven skips (`tests-review-after.out`). All **23 mixed-strategy tests pass** (8.409 seconds).
The initial focused run had one test-fixture failure because `respect_timing` defaults to False; the regression
now explicitly enables that option to reach the post-check it tests. No production behavior was changed for it.
The full suite used the same test-process-only temporary-directory workaround described below; no tests were
filtered. PvPoke before and after: **`108 of 108 PvPoke battles reproduced exactly`** (`pvpoke-review.out`).

## Initial validation (before review; retained for history)

Before changes: 422 tests, zero assertion failures, three expected missing-OCR errors, seven skips with the
test-process workaround below. PvPoke: `108 of 108 PvPoke battles reproduced exactly`.
After changes: 436 tests in 41.231 seconds, zero failures, the same three OCR errors, seven skips.
The 14 new tests pass, including all three pre-edit move/hit/winner SHA-256 fixtures (one uses full `website`
settings, two use small search budgets), tau-zero equivalence, empirical frequencies over 12,000 draws per
head, 50/50 matching pennies, dominant/pure strategies, asymmetric equilibrium, deadlines, last-Pokemon
prompts, matrix cells, form handling, counters, cloning and replay in two independent Python processes.
The final PvPoke line is again `108 of 108 PvPoke battles reproduced exactly`.

The literal full-suite command was also run before and after. In this Windows sandbox it has 18 errors:
the three OCR errors plus 15 temporary-directory permission errors. Moving TEMP into the worktree does not
fix Python 3.13's mode-0700 directory ACL behavior. For the compatible runs only, a fresh test process set
`tempfile.tempdir` to `runs/lab-mixed/tmp` and wrapped `os.mkdir` to substitute mode 0777 for 0700, leaving
all other arguments intact. Then `unittest.defaultTestLoader.discover('tests')` and `TextTestRunner` ran the
entire suite. No tests were filtered and no repository/system permissions or test implementations changed.
The compatible logs are `tests-before-compatible.out` and `tests-after.out`; raw logs and temporary files
are retained locally but ignored. The coordinator can use the ordinary suite command outside this sandbox.

## Scope and assumptions

- Great League, existing WEBSITE models, 32 imagined battles, one worker and one NumPy thread locally.
- `engine_versus` deliberately removes RealTime limits. Smoke timing is not a live-budget acceptance result.
- The existing Reader probes next throw decisions when both sides have charged moves ready; it does not
  directly predict the target's shield answer. Shield-reader results are indirect, not a full exploitability test.
- The requested creators' shield/bait-habits section is absent from this checkout's `docs/status.md`. The rates
  in the task prompt were background context, not calibration data. No creator recordings were used for tuning.
- Task 25, task 29 and task 41 previously found no confirmed gain. These options are experimental; a screen
  winner still needs a fresh-seed confirmation, including the reader, before any promotion.

## Post-review smoke: all seven screen candidates

Completed successfully with **one worker**, one NumPy thread, WEBSITE models, 32 samples, Great League,
mixed field, seed **5102**, and fresh tag `lab-mixed-review-smoke`. All seven candidates use exactly the
screen's specifications. There are two H2H pairings both ways, two crowd battles, two PvPoke battles, and
two reader pairings both ways per candidate. Total: **62 jobs, 92 actual battles, 455.7 seconds**.
This was one invocation, not a resume of the pre-review results.

Executed arguments (with the shared venv Python, `-X utf8 -u`, and `OMP_NUM_THREADS=1`):

```text
scripts/engine_versus.py --workers 1 --chunk 1 --field mixed --pairings 2 --crowd 2 --pvpoke 2 --reader 2 --seed 5102 --tag lab-mixed-review-smoke --baseline website --candidates "website,shield_mix=0" "website,shield_mix=0.02" "website,shield_mix=0.05" "website,shield_mix=0.1" "website,throw_mix=0.03" "website,equilibrium=1" "website,shield_mix=0.05,throw_mix=0.03"
```

Raw stdout: [`smoke-review.out`](smoke-review.out). Per-battle scores and counts, copied from the checkpoint:
[`smoke-review-scores.json`](smoke-review-scores.json). Scores below are percentages with the script's
printed 95% margins. With these tiny counts, margins can be zero or extend beyond 0..100%; neither implies
precision. These results check functionality and do not establish a strength gain or a best setting.

| WEBSITE setting | H2H vs website | Crowd | PvPoke | Reader |
|---|---:|---:|---:|---:|
| Default | — | 50.0 ± 98.0 | 50.0 ± 98.0 | 75.0 ± 49.0 |
| `shield_mix=0` | 50.0 ± 0.0 | 50.0 ± 98.0 | 50.0 ± 98.0 | 75.0 ± 49.0 |
| `shield_mix=0.02` | 25.0 ± 49.0 | 50.0 ± 98.0 | 50.0 ± 98.0 | 75.0 ± 49.0 |
| `shield_mix=0.05` | 50.0 ± 0.0 | 50.0 ± 98.0 | 50.0 ± 98.0 | 75.0 ± 49.0 |
| `shield_mix=0.1` | 50.0 ± 0.0 | 50.0 ± 98.0 | 100.0 ± 0.0 | 75.0 ± 49.0 |
| `throw_mix=0.03` | 50.0 ± 98.0 | 50.0 ± 98.0 | 50.0 ± 98.0 | 75.0 ± 49.0 |
| `equilibrium=1` | 25.0 ± 49.0 | 100.0 ± 0.0 | 50.0 ± 98.0 | 0.0 ± 0.0 |
| `shield_mix=0.05,throw_mix=0.03` | 50.0 ± 0.0 | 50.0 ± 98.0 | 50.0 ± 98.0 | 75.0 ± 49.0 |

| Setting | Shields/prompts, all 12 candidate battles | Mean P(chosen), pooled choices | Search median / p99 / worst, ms |
|---|---:|---:|---:|
| `shield_mix=0` | 21/54 | 1.0000 | 125 / 573 / 641 |
| `shield_mix=0.02` | 21/53 | 0.9767 | 109 / 545 / 703 |
| `shield_mix=0.05` | 22/57 | 0.9563 | 94 / 543 / 688 |
| `shield_mix=0.1` | 23/52 | 0.9343 | 78 / 483 / 609 |
| `throw_mix=0.03` | 22/69 | 0.7758 | 109 / 599 / 609 |
| `equilibrium=1` | 22/53 | 0.9855 | 156 / 757 / 906 |
| `shield_mix=0.05,throw_mix=0.03` | 24/57 | 0.7170 | 109 / 500 / 516 |

Equilibrium lost all four reader battles in its two pairings; its printed paired reader change is
**-75.0 ± 49.0 points**. The other candidates' reader changes are +0.0 ± 0.0 in this tiny sample. The
deterministic searched-shield control contributes exactly 1.000 to the probability diagnostic, as intended.
Legacy-random exclusion is stated in every activity printout and separately tested for each legacy path.

## Initial smoke results (before review; retained for history)

All smokes used `--field mixed --workers 1 --chunk 1 --seed 5100 --tag lab-mixed-smoke --baseline website
--pairings 2 --crowd 2 --pvpoke 2 --reader 3`. They were run in three resumable invocations, adding shield,
then shield+throw, then equilibrium; baseline battles were not repeated. Elapsed times were 98.1, 62.0 and
70.8 seconds (230.9 seconds total, 52 actual battles). The final combined output is `smoke.out`; per-battle
scores and counts are in `smoke-scores.json`. Individual invocation output is also retained.

Scores below are **smoke only**, percentages plus the script's printed 95% margins. H2H has two independent
pairings played both ways; crowd/PvPoke have two battles each; reader has three pairings played both ways.
At this size the normal-approximation margin can be zero or extend outside 0..100%; neither indicates precision.

| WEBSITE setting | H2H vs website | Crowd | PvPoke | Reader | Reader paired change, points |
|---|---:|---:|---:|---:|---:|
| Default | — | 100.0 ± 0.0 | 100.0 ± 0.0 | 66.7 ± 32.7 | — |
| `shield_mix=0.05` | 50.0 ± 98.0 | 100.0 ± 0.0 | 100.0 ± 0.0 | 33.3 ± 32.7 | -33.3 ± 32.7 |
| `shield_mix=0.05,throw_mix=0.03` | 25.0 ± 49.0 | 100.0 ± 0.0 | 50.0 ± 98.0 | 33.3 ± 32.7 | -33.3 ± 65.3 |
| `equilibrium=1` | 25.0 ± 49.0 | 100.0 ± 0.0 | 100.0 ± 0.0 | 66.7 ± 32.7 | +0.0 ± 56.6 |

| Setting | Shields/prompts, all its smoke battles | Mean P(chosen), all heads counted | Search median / p99 / worst, ms |
|---|---:|---:|---:|
| Default, outside opponents only | 20/50 (40.0%) | 1.0000 | — |
| Shield | 27/61 (44.3%) | 0.9486 | 78 / 581 / 641 |
| Shield + throw | 27/62 (43.5%) | 0.6955 | 78 / 500 / 547 |
| Equilibrium | 27/62 (43.5%) | 0.9936 | 102 / 803 / 1094 |

Baseline H2H shield use pooled across candidates was 24/54 (44.4%). These pooled counts describe different
sets of battles; the per-field paired comparison is in `smoke.out`. There is no measured reader improvement
to claim. Equilibrium was mostly pure in these positions; exact equilibrium need not produce much randomness.
The combination is much less predictable by the probability diagnostic but did not play better in this smoke.

## Coordinator screen (updated after review)

`runs/lab-mixed-screen.cmd` is one cmd.exe line with seven candidates, starting with
`website,shield_mix=0` as the deterministic searched-shield control. It specifies **10 workers**, mixed field,
1,500 pairings both ways, 1,500 crowd, 750 PvPoke, 250 reader pairs, seed 5101, and tag `lab-mixed-screen`.
The other candidates are shield temperatures 0.02, 0.05 and 0.1, throw temperature 0.03, equilibrium, and
shield 0.05 plus throw 0.03. There is no statistically supported best combination yet.

The screen has **43,000 actual battles**, including baseline outside-opponent games. This command was
written, not run. Only one worker and one NumPy thread were used locally. The script lowers Windows process
priority and resumes completed per-battle results with the same tag; older counting-version checkpoints
must use a new tag to avoid combining incompatible probability totals.

A simple proportional extrapolation of this smoke is 455.7 s × (43,000 / 92) / 10 = **5.9 hours** before
shared-PC overhead. Plan roughly **6–9 hours on 10 workers**; battle mix, contention and sample variance make
this a planning estimate, not a measured full-screen runtime.

Open questions: do any gains survive a fresh seed; does a shield-specific reader reveal benefits missed by
this throw reader; do positive shield temperatures improve over deterministic shield search; does equilibrium
leave too little entropy; and do the extra searches fit live budgets? No default should be promoted from a smoke.
