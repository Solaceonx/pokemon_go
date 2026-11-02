# Standalone Double DQN experiment (task 38)

`pogo.dqn.Agent` uses a NumPy neural network to choose fast moves, charged moves, switches, shields and
replacements directly. It calls no Planner or Engine during inference. Its features contain public health,
energy, clocks, types, stats, form state, move effects and pairwise damage for our three Pokémon and the
opponents already revealed. Unrevealed opponents are zero padded. There is no search or language-model call.

This is a separate algorithm from task 37 / PR #11's PPO: replay-based Double DQN, eight-decision returns,
prioritized replay, a periodically copied target network, a Monte Carlo auxiliary loss and a demonstration
margin loss. The optional teacher in `Agent` is for collecting bootstrap data only. The first bootstrap
teacher is the frozen trained Learner. The Double DQN action-selection/target-evaluation separation follows
[van Hasselt, Guez and Silver](https://arxiv.org/abs/1509.06461); the additional losses and schedule are this
experiment's choices, not a claim to reproduce that paper.

## Reproduce

Use Python 3 and NumPy. From the repository root:

```powershell
python -m unittest discover tests
python scripts/check_pvpoke.py
python scripts/double_dqn.py prepare --run dqn-v1
python scripts/double_dqn.py bootstrap --run dqn-v1 --games 10000 --epochs 40 --demo-capacity 120000 --hidden 128
python scripts/double_dqn.py train --run dqn-v1 --hours 12
```

Every command lowers process priority (`nice` on Unix, below-normal priority on Windows) and forces one
NumPy thread. This harness uses one worker, leaving room within the shared three-worker limit for the other
chat. Do not edit imported code during a long run. Re-run an interrupted command with the same settings to
resume; `--hours` is a budget for that invocation. It saves the network, Adam optimizer, target network,
NumPy RNG state, replay and counters. Two alternating snapshot slots protect the last completed training
snapshot; `resume.json` switches only after both new files have been written.

`git archive` extracts baseline commit `59836c86f4c9ccf7e8d35ef7c94268e64c1a4ba9` under `.dqn-cache/`.
The harness hashes every frozen file, rechecks it at startup and imports it as `dqn_frozen_pogo`, independent
of current working modules. All games use the frozen simulator, data and opponent implementation. A fresh
Evaluator per engine/player prevents cross-game outlook-cache contamination. Immutable model arrays may be
shared. Training scripts never modify the baseline files.

The primary frozen opponent is the current website engine's full 32-sample search: bot rollouts, horizon 20,
edge 0.03, learned margin 0.02, top-50 imagination pool, no deadlines or time cuts. Training defaults to a
mixture of the frozen Learner and a cheaper four-sample engine. Default checkpoint screening uses eight
samples for cost. Every reduced-search result is labelled with its sample count and cannot establish the
requested win against the full engine.

## Selection and final tests

Team identity is the sorted set of starting/home species, independent of lead and bench order. SHA-256
assigns compositions to 80% training, 10% validation and 10% final test. Both teams in each battle must be
in the intended split. No validation or final-test composition is used for bootstrap or reinforcement
training. Species can appear in multiple splits; this measures generalization to new compositions, not
entirely unseen species. The hash prefix and proportions are fixed in `protocol.json` before training.

Checkpoints are screened on fixed validation seed 38031. The maximum validation win share wins; earlier
checkpoints win ties. Selection scores are biased by trying several checkpoints and are not final evidence.
Before final evaluation, record the selection and copy it to a stable filename, then run:

```powershell
python scripts/double_dqn.py evaluate --run dqn-v1 --checkpoint best.npz --split test --seed 38091 --pairs 1000 --samples 32 --field mixed --tag test_mixed_38091
python scripts/double_dqn.py evaluate --run dqn-v1 --checkpoint best.npz --split test --seed 38092 --pairs 1000 --samples 32 --field mixed --tag test_mixed_38092
python scripts/double_dqn.py evaluate --run dqn-v1 --checkpoint best.npz --split test --seed 38091 --pairs 1000 --samples 32 --field standard --tag test_standard_38091
```

The first final-test command locks checkpoint SHA-256 and pair count in `test_lock.json`, preventing further
training in that run or testing a different candidate. Final seeds 38091/38092 were declared before training.
The same locked checkpoint is used on both fresh mixed-field seeds and the standard-field cross-check.
Never pick another candidate after reading final outcomes. New experiments require new untouched test seeds.

Each independent pairing is played with the teams swapped, balancing player side across games. Score is
wins plus half draws. Confidence margins use the standard error across the pairing means, counting the two
orientations as one cluster. With zero observed variance, a conservative bounded concentration guard avoids
reporting zero uncertainty. The target is a lower 95% confidence bound above 50% on both fresh mixed-field
tests. The standard-field test checks for a detectable regression. These are simulator results against a
particular frozen opponent; they do not establish strength against humans or under tracked observations.

## Artifacts and prior tracker work

`runs/double-dqn/<run>/` holds protocols, exact invocations, per-game experiment logs, validation curves,
checkpoints, replay and evaluation outcomes. Small summaries stay in Git. Large demonstrations, replay,
intermediate checkpoints and raw evaluation rows stay local and are excluded by `.gitignore`. Do not add
these files with `git add -f`. Preserve a compact selected policy and its digest alongside the summary.

Draft PR #10 was reviewed for its energy reconstruction fixes and paired tracker benchmarks. Its rough
camera numbers diagnose observation cost. This experiment uses the exact public simulator View; no official
footage, uncertainty retraining, tracker changes, phone interaction or deployment is involved.
