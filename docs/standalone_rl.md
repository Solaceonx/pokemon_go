# Standalone reinforcement learning (task 37)

The owner requested a separate RL player that reliably beats the current engine, with up to two days
of computing or available usage. This experiment has its own policy and measurement code. The existing
engine, tracker, website and their defaults are unchanged.

## What is being trained

`pogo/standalone_rl.py` contains a NumPy actor-critic with two tanh layers, a six-action policy, a shield
policy, a replacement policy, and a critic. It chooses from all legal actions on every available turn,
without Planner advice, engine search, a hidden charged-move identity, or private simulator state.
The 366 public features include health, energy, shields, timers, all our Pokemon, their revealed Pokemon,
types, move stats, form state and pairwise damage. Unrevealed opponents are zero slots. There is no
species ID embedding. Runtime needs standard-library Python and NumPy.

Initialization imitates the frozen trained Learner on training teams only. That teacher is used only
to generate training examples. PPO then trains the separate policy against a mixture of the frozen
engine (80%), frozen Learner (10%) and current standalone policy (10%). Rewards are +1 for a win, 0
for a draw, -1 for a loss, with no hand-written strategy rewards. GAE uses gamma=1 and lambda=.98;
the update clips probability ratios at .2, clips gradient norm at .5, uses a learned critic, and retains
a small KL anchor to the imitation policy. Early training can use fewer engine samples as an explicit
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

An unordered trio's stable hash assigns it to train (70%), validation (15%), or final test (15%).
All leads and bench permutations stay together. Both sides' teams obey the split in all phases.
This holds out **team combinations**, not individual species. The old teacher's historical training
may have included these species and combinations; no new agent-training episode uses a held-out trio.
The mixed and standard fields each retain their own conditional distribution within a partition.
Teams are drawn with replacement, so each pairing is an independent draw, even if a trio repeats.
The standard field is a registered cross-check, not an unseen data source.

Validation schedules and seeds are fixed before training. Checkpoints are selected only on mixed-field
validation score. `lock` records the selected weights and source hashes, forbids further training of that
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

```sh
python scripts/standalone_rl.py prepare --run ppo-v1 --seed 37001 --validation-pairings 128
python scripts/standalone_rl.py train --run ppo-v1 --hours 32 --workers 3 --bootstrap-games 16384
python scripts/standalone_rl.py lock --run ppo-v1
python scripts/standalone_rl.py test --run ppo-v1 --pairings 1200 --workers 3
```

The training command resumes the committed round, including Adam moments. All batch RNG streams are
derived from the experiment seed, episode index and stream purpose; worker scheduling does not reorder
examples. A stopped command can be repeated. At most three below-normal-priority processes perform
battles, with one NumPy thread each. Do not edit the experiment source while workers use it. Large
replay/bootstrap batches and individual game logs stay local and ignored by Git. Small checkpoint files,
provenance, summary JSON, and `experiments.jsonl` can be retained with the PR. Keep the best/locked model
and representative checkpoints; do not commit every training batch or all intermediate models.

`runs/standalone-rl/<run>/` contains:

- `experiment.json`, `frozen_manifest.json`: protocol, source/model hashes and environment.
- `state.json`, `latest.npz`, `round_*.npz`: progress and resumable optimizer checkpoints.
- `bootstrap.npz`, `best.npz`, `locked.npz`: initialized, selected and final frozen policies.
- `experiments.jsonl`: every batch, update, validation and final decision.
- `replay_*.npz`, `bootstrap_*.npz`, `training_games_*.json`: local training examples and episode logs.
- `validation_schedule_*.json`, `validation_summary_*.json`: selection schedules and scores.
- `lock.json`, `test_plan.json`, `test_schedule_*.json`, `test_results.json`: final protocol and result.
- `validation_*.jsonl`, `test_*.jsonl`: append-only pairing outcomes with resume provenance.

Use a saved policy directly:

```python
from pogo.standalone_rl import ActorCritic, StandaloneAgent
model, metadata = ActorCritic.load("runs/standalone-rl/ppo-v1/locked.npz")
agent = StandaloneAgent(model, seed=123)  # act(view), shield(view, energy), replace(view)
```

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
