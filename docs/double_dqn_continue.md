# Double DQN continuation (task 38)

The owner authorized a new 48-hour allocation after the completed benchmark failed. The fixed deadline
is November 5, 2026 at 20:59:47 UTC / 12:59:47 p.m. Pacific. The registered plan and exclusion data are
under `runs/double-dqn/continue-v1/`. No continuation game has started; implementation is pending.

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

Initial checks passed:317tests,7optional video skips;108/108 PvPoke battles exact. Before activation,
test checkpoint recovery, exclusion enforcement, paired-row recovery and deadline behavior, then freeze
a new runtime and publish its source/launch receipts. Commands and actual process identities will be
recorded here when implementation is ready. PR #12 retains the prior three clear held-out losses.
