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

## Saved work

`runs/double-dqn/<run>/` contains protocols, exact invocations, training curves, checkpoints, replay, raw
evaluation rows and summaries. Large demonstrations, replay, intermediate models and raw rows remain local
and are ignored by Git. Small summaries, the compact selected policy, and source/model hashes are retained.

Draft PR #10 was reviewed for its energy reconstruction fixes and paired tracker diagnostics. Those camera
results measure observation cost. This task uses the exact public simulator View; task 15 stays on hold.
No reserved footage, phone interaction, tracker change or deployment is involved.
