# Standalone reinforcement learning (task 37)

The owner requested a separate RL player that reliably beats the current engine, with up to two days
of computing or available usage. This experiment has its own policy and measurement code. The existing
engine, tracker, website and their defaults are unchanged.

**Current status (2026-11-03 13:47 UTC):** training stopped after 120 rounds / 30,720 games.
The selected greedy round-104 policy scores 39.26% on validation (95% CI 33.98–44.34%); round 120
scores 38.87% and does not replace it. Reliable wins have not been established. The final policy is
locked as `runs/standalone-rl/mc-ppo-v3/locked.npz`, and **9,600 final battles are running** on two
fresh seeds and the held-out mixed/standard fields. Sources, mode, sample count and weights are fixed.
`final_protocol_locked.json` records the lock and original deadline before the first complete test block.
Three evaluation workers were verified at BelowNormal priority with one thread each. No training or
selection follows test results. The handoff controller completed normally and no side jobs remain.
Earlier capacity, correction, ensemble and rollout trials below are historical negative results.
Main PPO used gamma=1/lambda=1 complete terminal returns; the .98 GAE description below applies
to earlier runs. The final strength verdict is pending.

## What is being trained

`pogo/standalone_rl.py` contains the public feature encoder, runtime player and first shared-network prototype.
`pogo/standalone_rl_v2.py` contains the current NumPy actor-critic: separate two-layer tanh networks for the
six-action policy, shield policy, replacement policy, and critic. It chooses from all legal actions on every available turn,
without Planner advice, engine search, a hidden charged-move identity, or private simulator state.
The 366 public features include health, energy, shields, timers, all our Pokemon, their revealed Pokemon,
types, move stats, form state and pairwise damage. Unrevealed opponents are zero slots. There is no
species ID embedding. Runtime needs standard-library Python and NumPy.

A separate candidate, `pogo/planning_rl.py`, improves the learned policy's physical actions with
its own complete-battle rollouts. It reconstructs worlds from public state, samples unrevealed
opponents from the public pool, and uses frozen neural policies on both sides of each imagined game.
Shields and replacements still use the learned heads. It imports the rules simulator and neither
Planner, Learner nor the search-player module. This is an RL policy with independent model-based
planning; its search contribution must be measured separately from a policy-training gain.

Initialization imitates the frozen trained Learner on training teams only. That teacher is used only
to generate training examples. PPO then trains the separate policy against a mixture of the frozen
engine (80%), frozen Learner (10%) and current standalone policy (10%). Rewards are +1 for a win, 0
for a draw, -1 for a loss, with no hand-written strategy rewards. GAE uses gamma=1 and lambda=.98;
the update clips probability ratios at .2, clips gradient norm at .5, uses a learned critic, and retains
a small KL anchor to the imitation policy. The second experiment also records the frozen engine's
actual public choices during the training games already being played and adds a .1-weight auxiliary
cross-entropy loss to PPO. These are action labels, not the short-horizon search values whose earlier
distillation failed. The critic is trained only from the RL player's trajectory, not the opponent's
rewards under a different policy. Separate networks and per-parameter Adam clocks prevent critic
updates and another head's unused momentum from directly moving a policy.
Early training can use fewer engine samples as an explicit
curriculum; validation and primary testing always use 32. No engine settings are learned or replaced.

Earlier whole-battle policy gradients, wider old Q-nets and distillation did not improve the project
(`docs/status.md`). This run changes the action interface, public representation and actor-critic update;
it is an experiment, not an assumption that more training must help.

## Frozen opponent and partitions

`prepare` archives the requested Git commit, not working files, under `.rl-cache/frozen/<commit>/`.
All archived source, game data and the baseline's Q/evaluation weights get SHA-256 hashes. Loading
checks every hash and imports the old `pogo` package under a separate namespace. The battle simulator
is that snapshot's simulator too. Each engine gets a fresh evaluator cache in each game.

The primary baseline is main commit `59836c86f4c9ccf7e8d35ef7c94268e64c1a4ba9`, samples=32,
horizon=20, rollout=bot, edge=.03, margin=.02, with no clock cuts. Its search mechanics are those of the
current engine. It uses the frozen mixed-field pool, including forms. This is a reproducible full-search
benchmark; browser hardware deadlines and camera errors are separate questions.

Upstream through `9bedfe1` later added rollout caches to the working-tree player. This branch includes
those changes, but neither active method imports that player module. A fresh initialization verified
the archived module path and all registered source guards still match. The benchmark retains the
original E0 implementation, without substituting upstream's new cache or timing measurements.

An unordered trio's stable hash assigns it to train (70%), validation (15%), or final test (15%).
All leads and bench permutations stay together. Both sides' teams obey the split in all phases.
This holds out **team combinations**, not individual species. The old teacher's historical training
may have included these species and combinations; no new agent-training episode uses a held-out trio.
The mixed and standard fields each retain their own conditional distribution within a partition.
Teams are drawn with replacement, so each pairing is an independent draw, even if a trio repeats.
The standard field is a registered cross-check, not an unseen data source.

Validation schedules and seeds are fixed before training. Checkpoints and greedy/stochastic inference
mode are selected only on mixed-field validation score. `lock` records the selected mode, weights and source hashes, forbids further training of that
run, and only then generates two final seed blocks. Changing sample size, weights, implementation,
or baseline after locking invalidates that test. A new attempted method requires a new run and new
final-test seeds. Test schedules, individual outcomes and summaries are all saved.

## What counts as beating it reliably

Each independent pairing plays both team allocations and both seats: agent on A against engine on B,
then engine on A against agent on B. Wins count 1, draws .5, losses 0. Bootstrap resampling uses whole
pairing clusters, never the two orientations as independent observations. Reports include a 95%
percentile bootstrap CI (10,000 replicates), a normal margin, wins/draws/losses, timing, and a conservative
distribution-free one-sided 97.5% Hoeffding lower bound.

The registered success gate requires **both fresh mixed-field blocks** to have bootstrap lower bound
above 50% and Hoeffding lower bound above 50%, plus bootstrap lower bound above 50% in both standard-field
blocks. At 1,200 pairings per block, the Hoeffding gate requires approximately 53.93% score. There are
2,400 battles per block, four blocks in all. A failure will be reported as a failure; validation gains,
imitation agreement, reduced-search wins or narrow CIs on a weak score do not meet the target.

These results concern simulated play with the public exact-energy View. They do not establish success
against people, independent battle rules, camera errors or the live app. Human exam answers and the
reserved official footage are not used to tune this policy.

## Commands and artifacts

Use the same Python interpreter that has NumPy. On Windows in the Codex workspace, it is
`C:/Users/lionl/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`.

Windows background launcher: `scripts/run_standalone_rl.ps1 -Run NAME -Python PATH -TrainingArguments @(...)`.
It starts Python in a hidden window with BelowNormal priority, saves its PID/arguments and stdout/stderr,
and rejects a second launch while that run's recorded PID is live. This avoids the existing Windows
priority helper's observed failure to lower a newly launched job. A help-only launch, duplicate-run
rejection and actual BelowNormal priority inheritance to an idle Python child were verified without
starting additional battle workers. The active run's parent and all three workers were explicitly
lowered and their priority classes read back; no training source was edited during the run.

```sh
python scripts/standalone_rl.py run --run ppo-v2 --ref 59836c86f4c9ccf7e8d35ef7c94268e64c1a4ba9 --seed 37001 --network independent --start runs/standalone-rl/ppo-v1/best.npz --bootstrap-games 0 --hours 36 --workers 3 --validation-every 8 --curriculum-rounds 16 --anchor 0.01 --demo-weight 0.1 --pairings 1200
```

`run` prepares, trains, locks and performs final testing without another command. The component
commands `prepare`, `train`, `lock`, and `test` are also available. The actual owner's run adds an
absolute `--budget-deadline` shared across experiments; it is saved in its command log. Training reserves
ten hours before that deadline for final testing. Workers stop accepting new battles at the deadline.
Every game's outcome is bounded by the simulator's time limit, so an in-flight battle may finish after it.

The training command resumes the committed round, including Adam moments. All batch RNG streams are
derived from the experiment seed, episode index and stream purpose; worker scheduling does not reorder
examples. A stopped command can be repeated. At most three below-normal-priority processes perform
battles, with one NumPy thread each. Do not edit the experiment source while workers use it. Large
replay/bootstrap/demonstration batches and individual game logs stay local and ignored by Git. Small checkpoint files,
provenance, summary JSON, and `experiments.jsonl` can be retained with the PR. Keep the best/locked model
and representative checkpoints; do not commit every training batch or all intermediate models.

`runs/standalone-rl/<run>/` contains:

- `experiment.json`, `frozen_manifest.json`: protocol, source/model hashes and environment.
- `state.json`, `latest.npz`, `round_*.npz`: progress and resumable optimizer checkpoints.
- `bootstrap.npz`, `best.npz`, `locked.npz`: initialized, selected and final frozen policies.
- `experiments.jsonl`: every batch, update, validation and final decision.
- `replay_*.npz`, `bootstrap_*.npz`, `training_games_*.json`: local training examples and episode logs.
- `demo_*.npz`: the opponent's public action examples, with no hidden-move identity or hidden team.
- `validation_schedule_*.json`, `validation_summary_*.json`: selection schedules and scores.
- `lock.json`, `test_plan.json`, `test_schedule_*.json`, `test_results.json`: final protocol and result.
- `validation_*.jsonl`, `test_*.jsonl`: append-only pairing outcomes with resume provenance.

Use a saved policy directly:

```python
from pogo.standalone_policy import load_agent
agent, metadata = load_agent("runs/standalone-rl/mc-ppo-v3/locked.npz", seed=123)
# agent.act(view), agent.shield(view, energy), agent.replace(view)
```

This loader reads the greedy/stochastic mode recorded in the selected checkpoint, so inference
uses the same mode as evaluation. Raw round checkpoints require an explicit `greedy=True` or
`greedy=False`; a previous champion's mode in their training state is not silently reused.

The generic loader accepts both network versions. Migrating the first prototype to independent networks
copies its policy and value outputs exactly, starts fresh Adam state, and records that reset in provenance.
Future independent-network checkpoints resume their per-parameter moments and clocks exactly.
Missing frozen caches are rebuilt from the recorded commit; all hashes are checked again.

## Development results so far

`ppo-v1`: 16,384 imitation games, then four PPO rounds / 1,024 RL games. At initialization it scored
19.34% (95% pairing-bootstrap CI 14.84–24.02%) against the full engine; after four rounds it scored
18.75% (14.26–23.44%). Each used the same 128 validation pairings / 256 battles. This pilot did not
improve. It was stopped at a saved round-4 checkpoint before changing its driver. Its best initialization
is retained as the second experiment's warm start; the network migration preserves its outputs exactly.
The original implementation is available at commit `ace8536c29f91445506ed1930b926f6d8215133e`.

`ppo-v2` changes network/optimizer isolation and adds public engine action demonstrations, with
greedy/stochastic inference mode selected on validation. It has passed the end-to-end pipeline checks;
Final strength results remain pending; development scores are in `docs/status.md` and
`validation_history.json`. The v1 and tiny pipeline outcomes are not final-test evidence for v2.

A separate training-only fallback is being prepared in `pogo/counterfactual_rl.py`: capture a complete
pre-step position, play every legal physical action to the end with common dice, and improve the policy
from those terminal-return labels. Inputs remain the public feature vector; the resulting checkpoint
uses the ordinary standalone network format. Continuations use the deployed greedy policy. Counterfactual
targets leave the on-policy critic unchanged by default, so its stochastic-policy targets are not mixed
with greedy-continuation targets. Six functional tests cover exact replay of the real choice on both
seats, independent controller/evaluator caches, repeatable returns, frozen captured policy weights and
the full-option gradient. Replay tests use one-sample engines for speed. No counterfactual training
trial or playing-strength result has been claimed; the active PPO experiment is unchanged.

The resumable trial driver is `scripts/counterfactual_rl.py`. Its `train` command opens no final
test; `run` performs training, locking and final testing. Collection uses greedy physical actions and
sampled shield/replacement choices. Only the sampled choices receive PPO updates; physical actions
use complete-option returns with fully greedy continuations. Recent terminal-return labels are kept
in a bounded replay window. Both training code and evaluation code are hashed and checked before
training, locking and final testing. Split and continuous training reproduce the same weights and
optimizer clocks in the unit control. Those controller tests use one-sample engines and mocked
validation. Separate real controls now pass full-32 exact replay on both seats and the multiprocessing
train/validate/lock/test pipeline; their reports are saved alongside the PPO development artifacts.
The two-pairing pipeline scores are functional checks only, and its strength verdict is false.

Example after selecting a warm start, with the shared work-budget deadline supplied explicitly:

```sh
python scripts/counterfactual_rl.py train --run cf-pilot --start runs/standalone-rl/ppo-v2/best.npz --hours 4 --workers 3 --train-samples 32 --playouts 2 --batch-games 64 --max-rounds 12 --budget-deadline 1793756530
```

On Windows, pass `-EntryScript scripts/counterfactual_rl.py -Command train` to the background launcher.
The deadline above is the original task deadline, 2026-11-03 17:42:10 Los Angeles; it does not reset
when starting a new method. Do not run a second pool alongside an existing three-worker experiment.

## Supervised initialization

The completed lower-weight correction follow-up is `mc-student-lowce-v1`, registered in
`runs/standalone-rl/low_ce_plan.json`: the unchanged correction implementation with demo weight 0.1,
up to 1,536 games/ten hours, one worker beside the main run's two. All 1,536 games and the round-12
validation completed; greedy score is 31.64% (95% CI 26.56–36.72%). The unchanged initialization
remains selected at 37.11%; no gain is established. The failed weight-1 pilot remains a separate
negative result. This was an adaptive validation experiment; it did not open its own final tests.
`scripts/run_low_ce_trial.ps1` records under `runs/standalone-rl/low-ce-control`; stop this controller
first when pausing while it is live. Its completed comparison retained main round 104 and resumed that
run on three verified workers; see `low_ce_allocation_decision.json` and `low_ce_handoff_audit.json`.
After a completed main checkpoint, `scripts/select_student_candidate.py` verifies
complete 128-pair records/source hashes and requires a positive paired lower bound before promotion.
The selected run resumes on three workers with the original deadline and twelve-hour final reserve.
The side training uses a fourteen-hour reserve to leave selection time.

`scripts/evaluate_greedy_rollouts_rl.py` is a separate follow-up to the independent rollout evaluator.
It fixes the learned opponent's continuations to greedy mode, leaving the original stochastic
experiment reproducible, and adds a ninth source hash. The registered screen uses four scenarios,
confidence 1.0, selected PPO round 24 and the frozen BC16 opponent. See
`runs/standalone-rl/greedy_rollout_plan.json` for the matched 32-pair screen and conditional fresh-seed
128-pair confirmation. The four-battle functional pipeline passed. The screen scored 35.94%
(95% CI 25.00–46.88%) versus its matched neural-control 28.91%, a paired change of +7.03 points
([-7.81, 22.66]). The preregistered fresh-seed 128-pair confirmation then scored **36.33%**
(30.86–41.41%), failing the reliable-win threshold. This fixed candidate does not trigger an early
switch to final testing; see `greedy_rollout_confirmation_audit.json`.
The actual paired-worker test checks
greedy continuations for both simulated sides. This is independent learned-policy simulation, with
no Planner/Learner/Engine call inside the agent.

`scripts/run_greedy_rollout_trial.ps1` temporarily allocates two main PPO workers and one evaluation
worker at committed checkpoints, then restores three PPO workers in its cleanup path. It records
under `runs/standalone-rl/greedy-rollout-control`; stop that live controller first when pausing work.
It preserves the original deadline and twelve-hour final reserve.

`pogo/slot_ensemble.py` is a separate inference-only adapter for a saved independent-head checkpoint.
It averages masked probabilities over all six equivalent own-slot representations and maps outputs
back to physical actions. It uses public features and neural inference only. Use its explicit
`load_agent` loader for deployment; the ordinary loader returns the ordinary single-view policy.
The saved training-label diagnostic improves agreement and cross-entropy on all heads. The real
four-battle evaluation pipeline passed, but the registered 128-pair validation failed promotion:
32.62% (95% CI 27.34–37.70%) versus the parent's 37.11%; paired change -4.49 points
([-11.33, 2.54]). This adapter is rejected. See `runs/standalone-rl/slot_ensemble_plan.json` and
`slot_ensemble_validation_decision.json`. It cannot produce PPO logs or
perform training, because ordinary single-view PPO would have the wrong mixture probability.

Prepare a separate run with `scripts/slot_ensemble_rl.py prepare --run NAME --start CHECKPOINT`, then
`scripts/slot_ensemble_rl.py validate --run NAME --workers 1` when a worker is free. The driver pins six
source hashes and reuses the frozen opponent, pairing schedule, confidence intervals and lock/test
protocol. It evaluates greedy mode only. The internal `train` alias is restricted to zero bootstrap
games and zero PPO rounds. Lock/test are available after validation; no substantive final data has
been opened for this adapter.

`scripts/student_correction_rl.py` is a separately registered training-only variant. It queries the frozen expert
at student-visited states, collects terminal-return PPO trajectories without expert intervention,
and aggregates eight rounds of public expert labels. The expert's unexecuted decision plans are
rolled back when the student chooses another action. Evaluation and deployment use the original
StandaloneAgent. Its source/protocol is separate, bootstrap games must be zero, and full 32-sample
training is the default. Full 32-sample expert-control replay matches terminal state and RNG in both
seats. The real four-game pipeline completed with audited legal expert labels and exact terminal
returns. The bounded 512-game pilot completed under `runs/standalone-rl/student_pilot_plan.json` and
failed promotion: greedy score fell from 37.11% to 32.42% (95% CI 27.34–37.50%), stochastic from
26.95% to 19.92% (15.62–24.41%). Its selected checkpoint is the unchanged initialization. These
checks did not consume final evaluation data; do not present the starting policy as a learned gain.

`scripts/widen_standalone_policy.py` provides a separate capacity initialization. It duplicates tanh
units, splits outgoing weights and adds balanced perturbations that preserve initial outputs while
allowing independent gradients. A parent checkpoint snapshot, source/hash provenance, numerical
transfer check and new optimizer state are saved. The 128-to-512-unit test preserves the actual PPO
policy/value outputs to floating-point precision. Epoch-four greedy validation scored 30.47%
(95% CI 25.98–34.96%); epoch sixteen scored 32.62% (27.93–37.30%). Both are below their
37.11% parent and neither passed the paired promotion gate. It uses
the same deployment schema and the existing training-only demonstration/refinement protocol.

`scripts/finish_capacity_trial.ps1` manages the registered capacity comparison: it waits for epoch-4
validation, evaluates epoch 16, runs the registered one-worker student-state pilot alongside the
two-worker main PPO run, and uses `scripts/select_capacity_candidate.py` to require a positive
paired interval before a promotion. It verifies the owned training process and waits for a committed
round before handing off. The selected run then uses three workers and a twelve-hour final reserve.
The original absolute deadline still applies. Its PID, events and decision are stored under
`runs/standalone-rl/capacity-control`. To pause the controlled work, stop that controller before the
owned Python jobs so it cannot initiate its queued handoff.

`scripts/evaluate_planning_rl.py` provides prepare/bench/validate/lock/test for that planning candidate.
It pins both neural checkpoints, search settings and rules-model sources. It checks that its local
rules match the frozen battle rules. `bench` uses two training pairings for timing only; `validate`
uses the registered validation partition. Locking and final testing reuse the original fresh-seed,
paired confidence-interval protocol. The new controller has functional tests and a full-size-network
physics replay check. Its real validate/lock/test pipeline passes, with actual rollout diagnostics
and all model/source hashes verified; the tiny strength verdict is false. Playing strength remains
under evaluation. The preregistered 32-pairing screens compare two confidence gates, then require
full validation confirmation of a promising variant. These screens share one worker while continued
terminal-return PPO uses two workers; the total remains three.

`scripts/monte_carlo_rl.py` exposes the same prepare/train/run/lock/test CLI as the original driver,
with complete terminal-return PPO advantages (gamma=1, lambda=1). It registers its extra source hash
and estimator in a separate experiment; spawned workers use the same estimator. Historical runs
keep their original source fingerprints. The real pipeline check now passes, including 295 saved
worker return labels equal to terminal rewards and all four tiny final blocks; the tiny strength
verdict is false. It uses the same standalone deployment checkpoint format.

An additional initialization trainer can use full-engine demonstrations already collected on the
training partition. It updates actors only and does not select a checkpoint or open evaluation:

```sh
python scripts/pretrain_engine_policy.py train --run engine-bc-v1 --start runs/standalone-rl/ppo-v2/best.npz --demo-folder runs/standalone-rl/ppo-v2 --first-round 17 --last-round 24 --epochs 16 --budget-deadline 1793756530
```

Each epoch saves `round_*.npz`; the next invocation resumes from the committed epoch and verifies
the source/data/initialization hashes and optimizer settings. Critic weights remain unchanged. The
saved training agreement is a fit diagnostic, not a strength estimate. Evaluate candidate epochs with
the standalone validation protocol, then continue RL from a selected candidate. The first real-data
fit completed 16 epochs; epochs 4 and 16 are being validated, with no strength gain claimed yet.
Candidate exports preserve weights and reset optimizer moments for the next method. Do not launch
pretraining alongside three existing battle workers;
on Windows the background launcher accepts `-EntryScript scripts/pretrain_engine_policy.py -Command train`.

## Draft PR #10 review

Reviewed head `5cce9110dfb4d17c9c6e6db6151ddc2dba8bf3c7`, including the tracker cap rollback,
form identity, Mimikyu protection, uncertainty sampling, paired measurement, hidden-move callback
boundary and new regressions. An isolated source archive passed **275 tests (7 video-dependent skips)**
and **108/108 PvPoke battles** on this machine. No blocking finding was reproduced in that scope.

Its reported roughly 59% exact-state Learner score is against a **Planner**, and its rough-camera
numbers measure observation cost. Neither establishes a win against the 32-sample search engine.
Its team pairings are freshly drawn but are not an explicit train/validation/test team partition.
It is useful tracker work and is kept separate from this frozen baseline and strength claim. No tracker
changes or PR #10 model weights were silently merged into this experiment.
