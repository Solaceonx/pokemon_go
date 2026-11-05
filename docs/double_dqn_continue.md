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
The checker verifies both the original teacher dataset and the actual copy loaded by this continuation;
its regression coverage rejects a changed copy even when the registered original remains intact.

The initial fresh64-pair validation completed34.765625%±6.7817400137points (95%), interval
27.9838849863–41.5473650137%, a clear loss. This is the unchanged starting policy's validation baseline.
Stage1 began21:28:56UTC, with persistent eight-hour deadlineNovember4 05:28:56UTC. Actual resumed
learning reached its first atomic checkpoint at475total/18new games,1,888batches/3,776Adam steps;
online weights changed, RNG advanced and target/optimizer state continued correctly. The checkpoint
and exact verification receipts are retained locally; no strength gain is claimed from training counters.

Stage1 completed5,391total/4,934new games,21,552batches/43,104Adam steps. Its64-pair validation scored
37.109375%±7.0718829786points (95%), interval30.0374920214–44.1812579786%. The matched change from
the initial policy is+2.343750±8.0727016100points (−5.7289516100 to+10.4164516100), so no gain is
established and it remains a clear validation loss. Raw draws/seeds/sides/scores/intervals,39runtime
sources,guard and95baseline hashes were independently checked; `stage_1_artifacts.json` binds them.
The endpoint was saved4.7374568seconds beyond the stage cutoff during ordinary whole-game/snapshot
completion, with no renewed allocation. Stage2 startedNovember4 05:40:56.4510396UTC and ends at its
persistent13:40:56.4510396UTC deadline. The same single worker continues unchanged; final teams remain
unopened. Required checks still pass323tests,7skips;108/108 PvPoke exact.

Stage2 completed10,352total/9,895new games (4,961during stage2),41,396replay batches/82,792Adam steps.
Its64-pair validation scored35.937500%±7.3916067735points (95%), interval28.5458932265–43.3291067735%:
another clear loss. Paired change from initial is+1.171875±8.0513505623points (−6.8794755623 to
+9.2232255623); versus stage1,−1.171875±7.9020441300points (−9.0739191300 to+6.7301691300).
Neither difference is established. The independent stage receipt verifies all draws/seeds/sides/intervals,
finite parameters/optimizer/target,39runtime files,guard,95baseline files, original/copied data and old locks.
The endpoint saved7.6652448seconds after its fixed stage cutoff during whole-game/snapshot completion;
the overall allocation did not change. `stage_2_artifacts.json` retains exact evidence/hashes.
Stage3 beganNovember4 13:51:47.818418UTC and ends21:51:47.818418UTC; the same single worker continues.
All three completed candidates stay eligible under the registered eventual selection rule. No new final
test has opened.323tests pass with7optional skips;108/108 PvPoke exact. The reliable-win goal is unmet.

Stage3 completed15,408total/14,951new games (5,056during stage3),61,620replay batches/123,240Adam steps.
Its64-pair validation scored31.640625%±6.6599107207points (95%), interval24.9807142793–38.3005357207%:
another clear loss. Change from initial−3.125000±7.7552625502points (−10.8802625502 to+4.6302625502),
and versus stage2−4.296875±7.8358280186points (−12.1327030186 to+3.5389530186), are both inconclusive.
The stage receipt independently verifies raw draws/seeds/sides/folds/scores/intervals, finite checkpoint
state and unchanged runtime/guard/baseline/data/old locks. Whole-game/snapshot completion ended
13.0150309seconds after the stored cutoff, without extending the allocation. `stage_3_artifacts.json`
retains exact evidence/hashes. Stage4, the final registered stage, runsNovember4 22:02:50.6474683UTC
throughNovember5 06:02:50.6474683UTC. The same worker continues; all four existing candidates remain
eligible pending that stage. No new final test has opened.323tests pass,7optional skips;108/108 PvPoke exact.

All four training stages completed. Stage4 saved20,198total/19,741new games (4,790in this stage),
80,780replay batches/161,560Adam steps atNovember5 06:03:08.4340785UTC,17.7866101seconds after its
stored cutoff during ordinary whole-game/snapshot completion. `stage_4_checkpoint_artifacts.json`
independently verifies finite online/optimizer/target state and unchanged runtime/guard/baseline/inputs.
Stage4 validation is still pending: by06:20UTC all16CPU cores were saturated with queue50, leaving the
same single runnable BelowNormal worker little CPU. `cpu_capacity_issue.json` records this resource
issue. A user choice about freeing capacity or explicitly allowing Normal priority is pending; do not
change priority based on elapsed time or restart the live worker. No source or deadline changed.
Checks pass323tests,7optional skips;108/108 PvPoke exact. No new strength result is established.

AtNovember5 08:10:00UTC the existing timeout path finished the in-progress battle after the fixed
07:59:47screening cutoff. Stage4 retained19of64required pairings and was excluded from selection;
its partial outcomes were not scored or used to choose a policy. The registered maximum-point/earliest-tie
rule selectedstage_1.npz from initial plus the three complete stage screens. Its previously reported
37.109375%±7.0718829786points is still a clear loss. `selection_artifacts.json` independently verifies
all four complete candidate blocks, exact model/source/data/baseline identities and selection-before-
confirmation order. The choice remains fixed for fresh128-pair confirmation39012, actual validation-only
canary and the new final benchmark. At that record no final test had opened, the priority question was
unanswered and the same BelowNormal worker continued under the20:59:47UTC absolute deadline.

The owner subsequently answered "Authorize Normal priority for this worker". AtNovember5
09:21:37.5117424UTC, only the exact identity-verified worker22396 changed toNormal, with the same
PID/start and one numerical thread. Separate authorization/application receipts retain this approved
OS scheduling exception; the original plan,guard and imported runtime stay unchanged. No process
restarted, other processes were untouched, and model selection/data/baseline/sample counts/deadline
stay fixed. At09:25:42UTC the worker used220.859375CPU seconds over245.0473796elapsed seconds
(90.1292539265%of one core), reaching50/128confirmation pairs. `priority_override_progress.json`
records this progress, which is not a strength result. Research stays closed and the selectedstage1
policy stays fixed; the reliable-win target still requires the complete registered benchmark.

Fresh selected-only confirmation39012 completed all128pairs/256games atNovember5 09:52:35UTC:
32.031250%±5.0384341895points (95%), interval26.9928158105–37.0696841895%, a clear validation loss.
`confirmation_artifacts.json` independently verifies draws/bothfolds/seeds/sides/scores/CIs and unchanged
model/source/data/baseline/old locks. Selection stayed fixed. The actual validation-only canary then
completed2pairs per block/12games total; its wide intervals are recorded in status/receipts and establish
no strength result. The91,443-byte compact policy SHA is
7ab364134eabc5ea04f2346c1140bb989113031ce0983be7105776c029bd6e46, exact selectedstage1 parameters.
`canary_lock_artifacts.json` verifies all canary evidence and the new local lock equal to final/protocol,
SHA69d59dd349b7990e32c90db078f64cb28dc91d88f90aaaa57a421379e2a35b62.
The three-block6,000-game held-out benchmark started09:54:37.9230423UTC with unchanged source,
baseline,exclusions,samples and20:59:47UTC absolute deadline. No partial/final outcomes were inspected
at startup. The same Normal worker/one numerical thread continues, and the reliable-win goal is unmet.

Infrastructure recovery atNovember5 16:18:50UTC followed the disappearance of both original processes.
System uptime suggests a restart around13:36:23UTC; the cause is unknown. Immutable recovery retained
717 complete paired rows and regenerated the incomplete final fragment's original pairing. Current
guard20796/worker8456 are serial attempt2, using the same runtime, selected policy, locks, inputs and
deadline. Owner-authorizedNormal priority persists; one numerical thread plus idle OS helpers were
verified. `recovery-20261105T1618/` retains prior receipts, journal hash, recovery and progress evidence.
The lost wall time makes all6,000games unlikely by20:59:47UTC. Do not reduce samples or extend the
deadline: save partial evidence and report the unmet target honestly if the benchmark remains incomplete.
