# Double DQN continuation (task 38)

The owner authorized a new 48-hour allocation after the completed benchmark failed. The fixed deadline
is November 5, 2026 at 20:59:47 UTC / 12:59:47 p.m. Pacific. The registered plan and exclusion data are
under `runs/double-dqn/continue-v1/`. The tested implementation and immutable runtime are prepared.

Continue `teacher32-v1/endpoint.npz` and its exact target/optimizer/RNG/replay state from 457 games.
Keep all learning settings and the frozen full32-sample opponent unchanged. Train up to four eight-hour
stages, with persistent stage clocks and an absolute research cutoff35hours after approval. Compare
the initial policy and complete stage endpoints on64validation pairings, seed39011, then confirm only
the chosen endpoint on128fresh pairings, seed39012. Earlier checkpoints win point-score ties.

Reserve13hours for a real validation-only canary, locked final benchmark and closure. Final blocks use
1,000mirrored pairings each: mixed39091, mixed39092 and standard39091. Both mixed lower95 bounds must
exceed50%; standard upper95 must reach50%; all blocks must complete. Report losses honestly.

Both final teams must be in the original test-composition fold and absent from every prior final draw.
The compact exclusion manifest binds1,380prior compositions and17,751prior game seeds, reconstructed
from identity metadata only. There are787unused standard-field test compositions. Draw with replacement
from the field conditioned on those exclusions; this new population is not a paired comparison to the
old benchmark. Fresh validation teams remain fold8; all training teams remain folds0–7.

The old global final lock, prior verdict, data and checkpoints remain immutable. A new run-local lock
will bind the new policy, source/data hashes, selection evidence, exclusions, counts and deadline.
Use one numerical worker and one NumPy thread, with BelowNormal priority on Windows. Recovery must
retain the same original stage/overall deadlines and exact saved optimizer/target/RNG/replay state.
Never start a duplicate worker. Do not merge, deploy, send messages to the other chat or touch a phone.

Initial checks passed:317tests,7optional video skips;108/108 PvPoke battles exact. Implementation checks
now pass322tests,7skips;108/108 exact. Five new tests cover actual learning from the full saved state,
excluded compositions/seeds, complete-pair recovery and corruption, persistent allocation limits and
a real second process failing to acquire the worker lease. The old completed benchmark audit still passes.

The numerical runtime is `.dqn-cache/harness/continue-v1`; the separate immutable guard is
`.dqn-cache/harness/launch-continue-v1/scripts/run_dqn_continue.ps1`. Its39source hashes and preflight
results are bound in `activation.json`, `source_manifest.json` and `implementation.json` beside the plan.
The last research hour is reserved for validation; training stops no later than34hours after approval.
The guard can reattach to its verified orphaned worker, sets BelowNormal priority, serializes retries,
and stops only the exact own process at the new deadline. Check process identity before recovery.

From this experiment worktree, preflight without starting a job:

```powershell
python scripts/dqn_continue.py --prepare-only
pwsh -NoProfile -File .dqn-cache/harness/launch-continue-v1/scripts/run_dqn_continue.ps1 -CheckOnly
```

The authorized controller is launched hidden with its own stdout/stderr. Its identity is saved in
`.dqn-cache/continue_controller.json`; current child identity and exact log paths are under
`continue-v1/launch.json` and `controller_state.json`. Read these and confirm process start/path before
any action. Do not launch another worker when one is live. Do not edit the copied runtime or guard.
PR #12 retains the prior three clear held-out losses; no new strength result exists yet.

Activation: guard21804 started2026-11-03T21:17:06.4918047Z; numerical worker22396 started
21:17:06.9655231Z, verified BelowNormal. Exact full checkpoint/replay/data production copies match the
registered hashes. The initial fresh validation is running; actual training-stage clocks begin afterward.
The quiet30-minute heartbeat now follows this new allocation. Read current launch receipts before action.

After all final blocks complete, run the independent checker without replaying games:

```powershell
python scripts/check_dqn_continue.py --run continue-v1
```

It verifies complete raw pairings, fresh composition/seed exclusions, independent confidence intervals,
validation-only selection, actual canary, original/new locks, source/data/compact parameters and clocks.
It writes only small `audit.json`; `evidence_verified=true` alone is not proof of winning.
Auditor preparation checks pass323tests,7skips;108/108 PvPoke exact. Its corruption coverage uses only
validation games, and the checker is not imported by the long-running numerical worker.
