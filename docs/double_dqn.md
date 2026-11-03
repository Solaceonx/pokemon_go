# Standalone Double DQN (task 38)

`pogo.dqn.Agent` directly chooses fast moves, charged moves, switches, shields and replacements with a NumPy
network. It calls no Planner, Engine, search or service at inference. Inputs contain public health, energy,
clocks, types, stats, forms, moves, and damage against revealed opponents. Unrevealed opponents are zero padded.
Version 2 also uses the existing `data/matchups_wide.json` as numeric features, without a matchup action rule.

This is independent of task 37 / PR #11's PPO. It uses Double DQN, prioritized replay, a target network,
Monte Carlo auxiliary targets and demonstration margin loss. Double DQN's online action selection and separate
target evaluation follow [van Hasselt, Guez and Silver](https://arxiv.org/abs/1509.06461); the added losses and
schedule are this experiment's choices. Version 1 failed to improve in its initial trial (see status.md).
Version 2 has 400 inputs, two 256-unit hidden layers, an engine4 demonstration teacher, and engine32 RL opponents.

## Reproduce

Python 3 and NumPy only. From the repository root:

```powershell
python -m unittest discover tests
python scripts/check_pvpoke.py
python scripts/dqn_pipeline.py --run reproduce-v2 --prepare-only
python .dqn-cache/harness/v2/scripts/double_dqn.py bootstrap --run reproduce-v2 --seed 38002 --games 3000 --epochs 80 --demo-capacity 200000 --hidden 256 --teacher engine --teacher-samples 4 --demo-save-every 50 > runs/dqn-v2-bootstrap.out 2>&1
python scripts/dqn_pipeline.py --run reproduce-v2 --max-hours 44 --stage-hours 12 --final-pairs 1000
```

Use a fresh run name when reproducing; the committed `dqn-v1` and `dqn-v2` directories are experiment records.
Resume the same name only when its local checkpoints and replay are present. The bootstrap redirection is
required: the controller watches `runs/dqn-v2-bootstrap.out` for completion. The last command may start in a
second terminal while bootstrap runs. The pipeline waits for epoch 80, trains
for 12 hours, then tests the selected candidate on 300 full-engine validation pairings. If its lower 95% bound
is not above 50%, it trains a second 12-hour stage. It selects between stage candidates using that full-engine
validation score, exports a compact policy, and performs all final tests. The plan is saved before training.
The current run's maximum 44-hour pipeline budget fits within the owner's original two-day request.

The pipeline uses one numerical worker and one NumPy thread; training lowers priority (`nice` on Unix,
below-normal on Windows). Directory links keep artifacts under the normal `runs/`, while copied runtime
source under `.dqn-cache/harness/v2/` cannot change when another experiment edits its checkout. Preparing an
existing snapshot verifies its bytes and refuses to overwrite different source. Do not edit a running job's
snapshot. The initial 370-input version is retained in local `harness/v1` and Git commit `06c3996`.

`pipeline_state.json` records progress and the current child PID. `STOP` in the run directory stops the pipeline
and its current child at the last saved checkpoint; bootstrap started in the other terminal is managed
separately. Re-run the same command to resume. The original deadline is retained. The controller uses a
transient Windows execution request to avoid sleep, releasing it on exit; saved power settings are unchanged.
It never promotes a model, deploys, merges, or contacts anyone.

Network weights, Adam state, target weights, replay, RNG state and counters are saved. Two alternating
snapshots preserve the previous complete training state. Demonstration counters are stored atomically with
their replay arrays. Evaluation recovers a killed partial final JSONL row and preserves complete rows;
interior corruption raises an error. Incompatible observation/action checkpoint schemas are rejected.

The controller passed an end-to-end smoke through both training stages, validation, policy export and three
canary evaluation blocks. Every smoke game used validation teams and canary seeds 38991/38992. Its verdict
intentionally makes no strength claim; production final seeds remain untouched.

## Frozen baseline and measurement

`git archive` freezes main commit `59836c86f4c9ccf7e8d35ef7c94268e64c1a4ba9`, including simulator source,
data and both models. Every frozen file is hashed and rechecked; imports use a separate `dqn_frozen_pogo`
namespace. Each engine/player/game gets its own evaluator cache. The baseline uses all 32 search samples,
a 20-step horizon, trained-bot rollouts, edge 0.03, learned margin 0.02, the top-50 imagination pool and no
wall-clock cuts. Reduced-search training or screening results are explicitly labelled and cannot meet the target.

A team's sorted home species identify its composition regardless of lead or bench order. A fixed SHA-256
partition assigns 80% of compositions to training, 10% validation, and 10% final testing. Both teams in each
battle must belong to the intended split. Species can occur in several splits; the generalization test is
for new compositions, not unseen species. No final-test composition is used for bootstrap or RL.

During each stage, the maximum win share on validation seed 38031 wins (100 pairings against eight samples;
earliest wins ties). Each stage's winner is then scored on 300 full-engine validation pairings, seed 38032.
The higher of those stage scores selects the final policy. These selection scores are not final evidence.

`final_selection.json` records the choice, and `policy.npz` contains compact weights with unchanged predictions.
The first final command locks its SHA-256 and pair count in `test_lock.json`, preventing further training or
switching candidates. The pipeline runs 1,000 pairings per block: mixed field seeds 38091 and 38092, then
standard field seed 38091. Both teams are swapped within every pairing and player sides are balanced.
Score is wins plus half draws. Normal 95% margins cluster the two orientations as one independent pairing;
a bounded concentration guard avoids zero uncertainty when all observed pairing scores are identical.

The strength target is lower 95% bounds above 50% in both fresh mixed-field blocks, with no statistically
detectable loss on the standard cross-check. `verdict.json` states whether it passed. Never choose another
candidate from final outcomes; another experiment needs untouched test evidence. Simulator wins against this
frozen opponent do not establish strength against humans or under tracked observations.

## Further experiments after v2

V2's selected model lost the full-engine validation, **27.67% ± 3.27 points** over 300 mirrored pairings.
The owner requested further experiments. The second unchanged training stage was stopped with its last
complete 5,400-game checkpoint retained; do not restart that controller or change its original deadline.
The later trials retain the same frozen baseline and train/validation/test partitions. Final tests remain
unopened. All measurements below are validation, not evidence of meeting the final target.

`scripts/dqn_audit.py` measures training action agreement by type. It found that overall agreement hid
charged-move recall of only 69% / 61%. `scripts/dqn_refine.py` compares the warm-up with masked cross-entropy
and action-frequency-balanced cross-entropy, using the same retained demonstrations and 60 epochs.
All three screen on 64 mirrored engine8 pairings, seed 38111; only the selected model confirms on 128
full-engine32 pairings, seed 38112. Selected balanced refinement scored **24.80% ± 4.97 points**. The
improved training fit did not establish competitive playing strength. Plans, training curves, model hashes
and exact results are under `runs/double-dqn/refine-v3/`.

`pogo.rl_search.RolloutAgent` is a separate optional inference experiment. It compares legal actions by
playing imagined games to completion with neural policies for both sides. It reconstructs public state,
samples unrevealed opponents from the frozen public pool, and calls no existing Engine, Planner or service.
Charged-ready decisions, matchup changes and an eight-turn cadence determine when it spends computation;
the network chooses between searches. Shields and replacements still use the network. This adds planning
to the learned policy; the original `pogo.dqn.Agent` remains a direct neural policy.
`scripts/rl_search_trial.py` compares zero, eight and sixteen samples on 64 mirrored full-engine32
validation pairings, seed 38311, then confirms only the screen winner on 128 pairings, seed 38312.
Its source is frozen under `.dqn-cache/harness/v3/` while running. Source/model hashes and the protocol
are saved before the first game. Runtime and raw per-pair timing logs remain local.

`scripts/counterfactual_rl.py` implements a subsequent training alternative: sample decisions from both
wins and losses before consulting outcomes, replay every legal choice to the end against the frozen engine,
and fit centered paired returns with a small demonstration anchor. Actual-choice replay must reproduce
the original winner before any label is accepted. Immutable source should be copied to a fresh harness
before a long run. The canary mode verifies this control in training games on both player sides:

```powershell
python scripts/counterfactual_rl.py --run cf-canary --collection-canary --groups 4 --max-groups 4 --samples 32
```

Run it only when this experiment's numerical worker is free. This is a replay check, not a strength test.
The full research runner defaults to six rounds, at least 300 labelled decisions and 32 differing-outcome
positions per round (up to 1,200 decisions), 30 fitting epochs and an eight-hour cap. It screens on 64 full
engine32 validation pairings, seed 38211, then confirms its selected checkpoint on 128 fresh pairings,
seed 38212. Its original invocation deadline survives restart; it also respects the original overall
deadline. Optimizer moments reset for the new loss in each round, then resume exactly across interruptions.
No final-test mode is provided by this research runner. The frozen-engine canary passed all four sampled
original-choice controls across two training games/both player sides; no alternative changed the terminal
outcome in that tiny canary. The full paired-return trial has started; it has no strength result yet.

The local `scripts/queue_counterfactual.ps1` successor serializes this canary and trial behind search-v3.
It waits for both existing search processes to exit, and leaves a promising fresh planning confirmation
(lower95 above 50%) for review instead of starting another training trial. Otherwise its immutable v4
runtime is hash-checked before use. Inspect both `.dqn-cache/active_experiment.json` and
`.dqn-cache/next_experiment.json` before any process action; a waiting successor must not be duplicated.
The successor enforces the unchanged absolute deadline, saving partial artifacts if time runs out.

That CF-only waiting controller was superseded by `scripts/queue_followups_v5.ps1` after a training-only
audit found 73/256 changed decisions when equivalent own-bench slots were relabelled. Its active identity
is recorded in `next_experiment.json`; do not restart the old queue. The replacement leaves the ongoing
search unchanged, then prioritizes `scripts/dqn_symmetry_trial.py` from immutable harness/v5. It fits a
balanced CE model with independent own/foe bench permutations and tied frequencies for equivalent bench
actions, and compares both prior/augmented models with direct/four-permutation-average inference.
All four use 64 full-engine32 validation pairings on seed 38411; only the winner confirms on 128 pairings,
seed 38412. The training data and model/source hashes are recorded before fitting. The run has a persistent
four-hour cap and retains the original absolute deadline. If its confirmation is still below the required
threshold, the unchanged v4 replay canary and paired-return trial follow serially. No final tests are opened
by these runners. `scripts/dqn_symmetry_audit.py` reproduces the bench-order diagnostic without an engine
opponent; it uses training compositions and makes no playing-strength claim.

## Shared matchup encoder fallback

`pogo/dqn_relational.Network` consumes the same 400 public features. A shared pair encoder, pooled team
context and shared bench heads provide equivariant Q values under bench relabeling, rather than learning
each ordering independently. Width 64 has 22,439 parameters. It retains the original Double DQN TD/margin
objective and complete Adam/target checkpoint state, with an explicit architecture marker that rejects
incompatible flat checkpoints. `scripts/double_dqn_relational.py` is a process-local backend selection for
the unchanged trainer, requires a fresh named run/source receipt, and disallows final-test compositions.

Immutable `harness/relational-v1` has been prepared, but it has not started a strength trial. Its unit checks
and the full suite pass. Any future experiment must wait for the current numerical worker to finish,
preserve the original overall deadline, record its full plan before fitting, and verify source/data hashes.
The existing v2 engine4 demonstrations can be reused with their original seed 38002 and metadata; this
preparation does not collect another dataset. Use `--hidden 64` explicitly for the documented model size.
The existing final-v2 evaluator does not load this architecture; a measured winning candidate would need
an equivalent method-preserving loader and actual canary before any final test.
`relational-v1/proposal.json` records an unstarted fallback: reuse the unchanged engine4 demonstrations,
80 original-objective warm-up epochs at width 64, at most one hour of full-engine32 Double DQN, compare
warm-up/last complete endpoint on 64 validation pairings (seed 38511), and confirm only the winner on
128 fresh validation pairings (seed 38512). It must fit inside the original overall deadline and may start
only after the current worker is free and a run plan is recorded. The backend entrypoint and preparation
receipt are available; that proposal has not been executed or queued.

The serial follow-up is now implemented in `scripts/queue_relational.ps1`, snapshotted with its Python
drivers in immutable `harness/followup-v8`. Its `relational-v1/queue_plan.json` binds the predecessor process
identities and source hashes. It applies the already registered three-round allocation rule, waits for
both the CF worker and its original controller to exit, and completes the reserved seed-38212 confirmation
using `scripts/dqn_cf_confirm.py`. The stopped original result remains unchanged; its supplemental evidence
is `counterfactual-v4/allocation_confirmation.json`. A promising confirmation pauses the queue for final
evidence review. Otherwise the shared encoder follows, with no overlapping numerical worker.

`scripts/dqn_relational_trial.py` executes the unchanged proposal: byte-identical demonstrations, 80 warm-up
epochs, at most one persistent wall-clock hour in the original trainer (including its internal bootstrap
validation), then bootstrap/last-complete-endpoint selection and the fresh selected-only confirmation.
The controller enforces the original overall deadline during long phases. Recovery preserves the saved
RL deadline, optimizer/replay state and complete evaluation rows. The endpoint is copied out of the
rotating checkpoint slots before selection. `policy.npz` is exported with identical parameters and cleared
optimizer moments; its hash and all validation results are saved. This still opens no final-test teams.

`pogo/dqn_residual.py` is an unmeasured training-objective prototype. It fits centered *changes* from a
reference network to sampled return advantages, preserving old score differences between equally valued
actions, and can anchor no-signal/demo positions to the reference. Gradient and invariance checks pass.
It has no strength trial or queue entry; the active CF objective and its runtime remain unchanged.

The prepared validation-only `scripts/dqn_residual_trial.py` now implements a conditional follow-up, still
unstarted and unqueued. `residual-v1/proposal.json` fixes the first three complete 300-position CF training
batches, requires the same reference-policy hash and 900 matching original-choice controls, and includes
positions without outcome differences. It compares correction sizes 0.10/0.25 (30 epochs, seed 38601,
rate 0.0001, batch 128, reference-score demo anchor 1) with the unchanged reference on 64 full-engine32
validation pairings, seed 38611. Only the selected variant confirms on 128 fresh pairings, seed 38612.
There is no new rollout collection. Complete-epoch optimizer/RNG recovery reproduces an uninterrupted fit
exactly in its unit check, and fitting leaves the reference arrays unchanged. Immutable `harness/residual-v1`
is prepared. It may run only after the existing serial chain is finished, with the worker free and enough
original budget; its persistent cap is two hours and it cannot enable final-test compositions.

## Final evaluator and locked evidence

`scripts/dqn_final.py` preserves the selected inference method as well as its weights. It supports the
direct policy, four-permutation averaging, and independent planning with its complete opponent ensemble.
Production refuses to start unless the matching 128-pair fresh validation confirmation against engine32
has lower95 above 50%. It checks model, ensemble, selected recipe and validated source hashes and recomputes
the validation interval. Compact exports must retain identical parameter arrays.

The single `runs/double-dqn/final_test_lock.json` binds the candidate, method/settings, ensemble, source/data
hashes and all three predeclared **1,000-pairing** blocks before any final game. A changed candidate or sample
count is rejected across runs. Complete paired rows retain exact game seeds, team identities, player sides
and scores; resumption verifies these against the locked draw rather than silently accepting another journal.
Final verdicts require all three blocks; deadline/STOP exits retain partial rows without claiming completion.

An immutable `final-v2` runtime has been prepared locally. It supersedes the unrun v1 prototype and also
enforces a matching completed canary before production. Once the serialized research queue stops for
review of a promising confirmation, verify its source manifest and run a validation-only canary first:

```powershell
python .dqn-cache/harness/final-v2/scripts/dqn_final.py --source-run symmetry-v5 --canary
python .dqn-cache/harness/final-v2/scripts/dqn_final.py --source-run symmetry-v5
```

Use the actual selected source run (`search-v3`, `symmetry-v5`, or `counterfactual-v4`). The canary uses two
pairings per block on validation teams, seeds 38995/38996, writes no production lock, and reports no strength
claim. It must pass before production; do not overlap another numerical worker. The production counts,
fields and seeds cannot be set through CLI arguments. Both modes retain the original overall deadline.
Production checks the canary verdict, source/method/weight identity and raw artifact hashes before locking.
For a selected planning method the reproducible compact policy package includes `policy.npz` and both
compact `opponent_*.npz` files, with the protocol binding every hash; publishing the actor alone would omit
part of the measured inference method. Final-package ensemble files are allowed by the run-specific Git rule.
The new harness has passed its unit checks; the full frozen-engine canary has not yet run because research
still owns this experiment's numerical worker. Final holdouts remain unopened.

## Retained files

`runs/double-dqn/<run>/` contains protocols, exact invocations, training curves, checkpoints, replay, raw
evaluation rows and summaries. Large demonstrations, replay, intermediate models and raw rows remain local
and are ignored by Git. Small summaries, the compact selected policy, and source/model hashes are retained.

Draft PR #10 was reviewed for its energy reconstruction fixes and paired tracker diagnostics. Those camera
results measure observation cost. This task uses the exact public simulator View; task 15 stays on hold.
No reserved footage, phone interaction, tracker change or deployment is involved.
