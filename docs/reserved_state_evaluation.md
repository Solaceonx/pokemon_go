# Reserved official sample: state readings and timing comparison

This follows `handoff/vod_readings_request.md` at commit `0fd98ff`. The ten
reserved official games remain twenty paired player views, separate from the
earlier exposed footage. State recognition and timing are not fitted on these
games. `assemble.py`, `pogo/tracker.py` and `scripts/track.py` remain unchanged
from that commit.

The full clips are sampled at 15 frames and three text looks per second, using
the same reader as the first 23 public views. Each portable
`games/twitch/<clip>/` contains compressed refined readings and text, the raw
reading receipt, source/match metadata, observations, model states, events,
the persistent evidence ledger and a strict consistency verdict. Videos,
OCR installations, full pixel caches and review images remain on the PC.

Both new broadcasts have the earlier official recording's exact source crops
and 448×976 clip viewports. Their layout IDs inherit its existing button
positions and radius without changing any numeric parameters. The four aliases
and their provenance are saved in `data/vod_tracking_layouts.json`. Unchanged
pixel observations are reused; refinement does not repeat OCR. This avoids
silently using the generic iPhone button geometry for a broadcast layout.

## Reproduce the readings on the media PC

From the pipeline repository, with the reader dependencies installed:

```powershell
$clips = Get-ChildItem ../pokemon-go-screen-reader/battles -Directory |
    Where-Object Name -Match '^tw-(2897166800|2897312743)-'
$arguments = @('scripts/recording/vod_track.py', '--reader-dir',
    '../pokemon-go-screen-reader', '--library',
    '../pokemon-go-screen-reader/battles', '--fps', '15', '--text-rate', '3',
    '--jobs', '2')
foreach ($clip in $clips) { $arguments += @('--only', $clip.Name) }
python @arguments
python ../pokemon-go-screen-reader/build_lazy_viewer.py
```

The original video/alignment checksums and reader hashes are recorded with each
clip. Reusing a cache requires matching inputs. The source collection and video
verification remain documented separately in `docs/official_sample.md` and
`data/vod_additional_sample.json`.

## Compare timing without the videos

These are the handoff's fixed comparisons. `--told` supplies fast moves inferred
from the other player's own buttons when available; it does not establish those
inferences as independently verified moves.

```bash
python scripts/recording/retrack_public.py out-fitted --told
python scripts/recording/retrack_public.py out-before --told --swapped-theirs -1.0 --enter 0.2 --start 0.7 --resume-lead 0.5 --waits faint --header-waits no
python scripts/recording/paired_energy.py --all out-before --source 2897166800 --source 2897312743
python scripts/recording/paired_energy.py --all out-fitted --source 2897166800 --source 2897312743
python scripts/recording/paired_state.py --all out-before --source 2897166800 --source 2897312743
python scripts/recording/paired_state.py --all out-fitted --source 2897166800 --source 2897312743
```

Output folders keep the two reconstructions separate and leave the published
readings intact. The comparison groups by saved match ID; paired views remain
one evaluation unit. Only complete games from the two requested sources enter
the reported sample.

The reference is the other player's saved screen readings and model state.
Button fill, forms and fast-move inference remain imperfect. Agreement is
measured over eligible looks; unreadable fields and animations reduce coverage.
These measurements cannot establish exact HP, every action's frame timing or
full game-state accuracy. A failed strict ending check remains a failure.

## Video-review diagnostic

The first game of VOD B shows normal fighting on both phones at clip time
4.517 seconds (original source time 350.517). The left view's model origin is
20.7 seconds: it begins after at least 16.183 seconds of confirmed combat.
An obscured early bar prevents the assembler from finding both bars together.
This can miss early energy history even when the entire video was read.
`data/vod_reserved_visual_diagnostic.json` records frame PTS, source/video hashes
and the observed headers. This is agent review, not independent human
adjudication; the exact action-start frame is not labelled. No timing setting
was changed in response to this example.

## Frozen comparison results

The full twenty clips contain 56,034 refined screen readings,
11,192 text looks and 2,534 published model states.
All ten paired games enter both comparisons. The percentages below measure
agreement against the other camera over eligible looks. They do not measure
every frame or establish independently labelled accuracy. The scripts allow
1.25 and 2.25 fast-move gains for their one/two-move tolerances.

| Eligible-look comparison | Before fit | Frozen fitted timing |
|---|---:|---:|
| who is out | 98.3% (2411 looks) | 95.7% (2421 looks) |
| health within 3% | 76.3% (2369 looks) | 77.2% (2318 looks) |
| health within 10% | 88.4% (2369 looks) | 89.9% (2318 looks) |
| shields | 95.1% (2411 looks) | 95.1% (2421 looks) |
| Pokémon left | 99.5% (2411 looks) | 99.5% (2421 looks) |
| all of these but energy | 83.3% (2411 looks) | 82.6% (2421 looks) |
| everything, energy within two | 66.2% (777 looks) | 69.2% (756 looks) |
| Energy, all paired button looks: mean absolute disagreement | 16.32 (767 looks) | 14.15 (744 looks) |
| Energy, all paired button looks: within two fast moves | 73.4% | 75.7% |
| Energy, below both move costs: mean absolute disagreement | 13.04 (465 looks) | 10.68 (453 looks) |
| Energy, below both move costs: within two fast moves | 84.5% | 85.4% |
| Energy, below costs and same assumed fast move: mean absolute disagreement | 13.04 (405 looks) | 10.53 (413 looks) |
| Energy, below costs and same assumed fast move: within two fast moves | 84.2% | 85.7% |

The fit reduces mean energy disagreement and improves the within-two-move share,
but the gain is smaller than on the earlier fitting matches. Active-species
agreement falls from 98.3% to 95.7%, and the combined non-energy fields fall from
83.3% to 82.6%. This is a mixed result, not an overall accuracy improvement.

The eligibility counts differ because timing determines which observations
align. Health and energy comparisons require matching active species; energy
also needs an own-button reading. Many looks come from the same battle and are
correlated. `--told` supplies peer-inferred fast moves in both runs, so this is
not a blind one-camera recognition result. The published reconstruction uses
the default settings; these comparison outputs are separate diagnostics.

Strict consistency failures remain: ending checks fail in 20/20
views, energy checks in 10/20, and shield checks in
2/20. The viewer preserves those failures. A shown
Ninetales still uses generic species defaults and guessed moves; its form and
actual moves are not verified. Exact maximum HP, stat stages and hidden actions
also remain unresolved. No settings were changed to improve these numbers.

## Validation and storage

All twenty receipts confirm full-clip coverage at the original cadence. Export
checks verify paired match IDs, partial flags, source/video hashes, monotonic
timestamps, unchanged reader hashes and the inherited refinement fingerprint.
All 56,034 continuity records retain `accuracy_verified: false`. The protected
code remains byte-identical to 0fd98ff. All 102 pipeline tests and 108/108 PvPoke
reference duels pass.

Browser verification lists twenty tracked sample views, plays both cameras of
both VODs and checks twelve seek positions. The live table has two rows and
seventeen columns, only one selected view is decompressed, no JavaScript errors
occur, and the sample stays outside the training/regression filters. The saved
page screenshot was also inspected. This verifies integration, not recognition.

| Stored item | Measured size |
|---|---:|
| Cropped videos, twenty views | 774.40 MB |
| Current local readings, metadata and alignment | 55.36 MB |
| Retained processing history, separate | 10.16 MB |
| Portable compressed exports, separate Git copy | 15.31 MB |
| Two retained source VODs | 11.86 GB |
| Shared 61-view HTML, no video embedded | 58.92 MB |

Both views of a game average 77.44 MB of video,
5.54 MB of current local data and
1.53 MB in portable exports. The local
data and Git exports are separate copies. Source originals are reused for more
games; these sizes exclude the shared runtime, review frames, discovery caches
and temporary comparison outputs. The original collection receipt remains a
historical pre-analysis measurement.

`data/vod_reserved_state_evaluation.json` records exact denominators, per-match
results, exported input hashes, code fingerprints, browser checks, test receipts
and measured storage. `data/vod_reserved_visual_diagnostic.json` preserves the
early-clock example for later work without treating it as human ground truth.
