# Engine lab: combined tree and tactics

Built from `lab-best` at `57116741ea8e645dce3f2cea3790083134890382`, merging
`lab-search` at `17de46c840bbf880d36afc3188fe471d19f0c7a1`, then `lab-tactics`
at `609a7aa5df3ded7622b8ec5b10f33c7041762697`. No push, model changes,
website changes, package installs, or live-game actions.

## Git location and conflicts

The registered worktree's Git metadata is outside the writable sandbox:
`C:/Users/marco/Developer/pokemon_go/.git/worktrees/pokemon_go-lab-best`.
The first merge failed creating `ORIG_HEAD.lock`, before modifying the tree.
A local clone attempt also failed in Git's shell helper. A repository initialized
at `runs/lab-best/git` instead uses the existing object store as a read-only
alternate and this worktree as its working directory. All merges and the final
commit are on its local `lab-best` branch. The registered branch remains at the
starting commit until the bundle is imported outside this sandbox.

`lab-search` conflicts:

- `pogo/lab/__init__.py`: add/add, the existing package docstring versus the tree
  key registry. Kept the registry, parser and engine factory.
- `scripts/engine_versus.py`: the learned-opponent factory versus the tree factory.
  Kept both, loading `opp_q`/`opp_policy` after selecting the engine class and
  preserving the caller's live-timing subclass and deadlines. `opp_sample` also
  selects the modelled engine when supplied by itself.

The search merge is `ecfa487f`; the tactics merge is `45f547f4` and had no conflicts.

## Composition fixes

- TreeEngine now overrides `_search_decision`, retaining `Engine._decide`.
  Previously its override bypassed the completed-search marker, so
  `swap_after_throw=1` never acted on its searched switches. It also bypassed
  the guard against searching hypothetical shield advice inside another decision.
- `shield_mix=0` already enabled the shield head, but tree choices bypassed the
  common mixed-choice path. Flat and tree searches now share `_choose_worth`;
  the tree still produces the values with its requested depth and halving root.
  This also preserves `throw_mix`, `shield_floor`, and equilibrium choices.
  Matrix looks now honor the fixed first shield response from each column.
- `shield_two`/`shield_one` already reached the inherited learned choice, but
  tree prior calculations still read the old single shield margin. All tree
  advice/prior calculations now use `_head_margin(head, view)`. The margins
  influence learned advice, fallback and priors; a decisive search result can
  still overrule that advice. They do not replace searched shield values.
- `finish_safe` and `bait_mix` already work through inherited Learner methods.
  Tests exercise the unsafe Empoleon fast finish and final bait choice with a tree.
- `fix_stay` already covered the mid-swap stay option while a tree search was
  active. Direct looks now apply it too. `fix_judged` now carries our settled
  matchup into `mid_swap` looks as well as throw/shield looks, including direct
  calls. Opponent judgement reaches the player inside any first-action wrappers.
- TreeEngine inherits ModelledEngine so learned-opponent keys also work with
  the tree. An explicit `opponents=people` still selects PeopleLike.

No defaults changed. `tree-before.json` contains two game digests recorded after
the merges and before these fixes, at depth 3 with halving and both look fixes.
They replay identically with omitted tactics and with tactics explicitly off.
The existing website/default digest and flat-tree equivalence tests pass too.

## Validation

All commands used the repository venv, `-X utf8`, one worker and
`OMP_NUM_THREADS=1`. No code was edited during the test or smoke runs.

| Check | Result |
|---|---|
| Initial plain baseline discovery | 469 tests, 0 failures, 19 errors, 7 skips |
| Baseline with inherited temporary-directory ACLs | 469 tests, 0 failures, 3 expected OCR errors, 7 skips; 46.057 s |
| First lab branch run, including integration | 82 tests passed, no errors/skips; 23.913 s |
| First merged full discovery | 504 tests, 0 failures, 3 expected OCR errors, 7 skips; 59.778 s |
| Final lab branch run | 83 tests passed, no errors/skips; 23.005 s |
| Final full discovery | 505 tests, 0 failures, 3 expected OCR errors, 7 skips; 58.945 s |
| PvPoke, before and after | `108 of 108 PvPoke battles reproduced exactly` |

The initial baseline's extra 16 errors were the documented Windows sandbox
temporary-directory ACL issue. The three remaining errors are `test_form_icons`
imports of the unavailable `rapidocr_onnxruntime`. No tests were changed or
skipped to suppress errors. The test process used the tactics branch's documented
workaround: temporary directories below `runs/lab-best/tmp`, and `os.mkdir`
mapping mode `0o700` to `0o777` for inherited ACLs. No system settings changed.
The original failure log is `../lab-best-baseline-tests.out`; corrected baseline,
branch tests and final tests are `baseline-tests.out`, `branch-tests.out`, and
`tests.out` here.

The 12 new integration tests cover construction of the full spec, modelled
opponents with live deadlines, real versus hypothetical shield calls, both shield
margins and tree priors, the last-Pokemon rule, safe finishing, both searched swap
heads, all four combinations of the mid-swap look fixes, bait/throw/shield mixing,
equilibrium shield columns, and unchanged games with tactics off.

Review added one more regression to keep `switch_edge` and `no_tell_bait` confined
to their respective decision heads. The selection guard was narrowed accordingly;
both keys are off in A-E, so this has no effect on the smoke results below.
Final branch counts: tree 8, tactics 16, mixed 23, learn 11, league 13,
integration 12. All passed.

## Candidate screen

- A: `website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh`
- B: A plus `shield_mix=0`
- C: B plus `finish_safe=1`
- D: C plus `shield_two=0.05,shield_one=0`
- E: D plus `swap_after_throw=1`

Smoke: `engine_versus.py --baseline website --candidates <A..E> --pairings 2
--crowd 0 --people 0 --pvpoke 0 --reader 0 --workers 1 --field mixed --seed 5502
--tag lab-best-smoke`. The exact command and complete output are in `smoke.out`;
the small result checkpoint is `smoke-scores.json`. Exit 0, **20 actual battles
in 123.9 seconds**, two pairings played both ways per candidate.

| Candidate | H2H score, 95% margin | Shields/prompts | Searches/battle | Search ms median / p99 / worst |
|---|---|---|---|---|
| A | 75.0% ± 49.0 | 7/17 | 17.00 | 141 / 438 / 438 |
| B | 75.0% ± 49.0 | 8/19 | 21.75 | 141 / 473 / 500 |
| C | 75.0% ± 49.0 | 8/19 | 21.75 | 141 / 489 / 516 |
| D | 75.0% ± 49.0 | 8/19 | 21.75 | 141 / 489 / 516 |
| E | 75.0% ± 49.0 | 8/19 | 21.75 | 141 / 468 / 562 |

All five had zero mid-matchup searches; the shipped q has no mid-swap head and
the specs do not enable `mid_swap_search`. E had zero throw-before-swap overrides
in these four games. Both gates execute in the integration fixtures. This tiny
sample neither establishes a gain nor isolates the tactics' effects. Timing is
from the unbounded engine-versus run, not a live deadline check. Normal margins
at two pairings can extend beyond 0..100%.

`../lab-best-screen.cmd` contains exactly one cmd.exe line, with these five specs
quoted, website reference, screen preset, 16 workers, tag `best-screen`, seed 5501,
and measures `h2h,crowd,pvpoke,reader,predict,timing,endgame,creator`, appending to
`runs/lab-best-screen.out`. It was written for the coordinator and not launched.

The screen requests about 20,960 battles plus position queries, endgame and
creator scoring. Scaling this smoke gives about 2.25 hours on 16 workers for
the battle portion. Allow **roughly 3-5 hours on 16 workers**, potentially more
under shared-PC contention; this is an estimate, not a measured screen runtime.

The full screen and any fresh-seed confirmation remain unmeasured. No strength
gain or adoption is claimed by this integration work.

## Importing the local commit

`lab-best.bundle` contains the two merges and integration commit, with the
already-present branch tips as prerequisites. It is an untracked delivery
artifact, excluded from commits along with the local Git metadata.

Outside the restricted sandbox, from this worktree on `lab-best`:

```text
git fetch runs/lab-best/lab-best.bundle lab-best
git reset --mixed FETCH_HEAD
```

The files are already in this worktree; this imports the commits and advances
the registered branch and index without replacing working files or pushing.
Run the screen only after importing, so the league records the correct commit.

## Exam variant factory follow-up (2026-11-25)

`scripts/exam_variants.py` delegates to the versus parser/factory. Its adapter
keeps 32 samples for bare specs, the old `stay_after_replace` interpretation and
the old invalid-mid-swap exception. `scripts/engine_versus.py` accepts optional
worker state in `pilot`, `evaluator` and `network`, so the exam supplies its own
models/pool without overwriting versus globals. Website reference construction,
replay dice, variant seed offsets, and exam-key checks stay unchanged.

`tests/test_exam_variants.py` builds the four lab specs below and the legacy
`switch_edge=0.1`, then calls action/shield decisions on a constructed position.
It checks the selected classes/settings, both Q models, evaluator isolation and
the exam pool/seeds. A second test compares 12 legacy specs at seeds 7 and 17
against the previous direct Engine construction: action, shield, replacement,
search count and both random states match in all 24 cases.

Validation, one worker and `OMP_NUM_THREADS=1`, repository venv with `-X utf8`:

| Check | Result |
|---|---|
| Initial plain baseline discovery | 511 tests, 0 failures, 19 errors, 7 skips |
| Baseline with documented temporary-directory workaround | 511 tests, 0 failures, 3 expected OCR errors, 7 skips; 45.607 s |
| New test module | 2 tests pass; 11.797 s |
| Five-variant smoke alone | 1 test passes; 1.432 s |
| Final full discovery, same workaround | 513 tests, 0 failures, 3 expected OCR errors, 7 skips; 56.238 s |
| PvPoke before and after | 108 of 108 reproduced exactly |

The three expected errors are missing `rapidocr_onnxruntime` in `test_form_icons`.
The first plain baseline also hit the 16 documented Windows temporary-directory
ACL errors. The same process-local `os.mkdir` wrapper documented above removed
those environment errors; temporary files stayed under `runs/lab-best/tmp`.
Logs: `exam-baseline-tests.out` and `exam-tests.out`. No package installations,
test suppressions, model changes, commits or pushes. `git pull --ff-only` was
denied access to the registered worktree's external `FETCH_HEAD`.

No private answer files were used and no exam score or strength gain is claimed.
No long run is proposed here. Luke can run this from the repository root on his
Mac, replacing the two positional filenames with his actual answer files:

```bash
OMP_NUM_THREADS=1 nice python3 -X utf8 scripts/exam_variants.py ANSWERS_1.json ANSWERS_2.json --variants \
  'website,engine=tree,fix_stay=1' \
  'website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh' \
  'website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1' \
  'website,engine=tree,fix_stay=1,fix_judged=1,depth=3,root=sh,shield_mix=0,finish_safe=1,q=runs/lab-pop-q.npz,opp_q=runs/general-decide/q.npz' \
  --workers 1
```
