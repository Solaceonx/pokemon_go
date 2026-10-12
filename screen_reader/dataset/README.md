# Reproducible video dataset

The manifests below describe the historical local library. Exact media and
generated predictions are not uploaded. Rebuilt media requires a rebuilt manifest;
the integration's shared-data lookup and launchers also produce new code hashes.
See ../README.md for the repository workflow and selected image fixtures.

The manifest assigns **nine Reis battles to training/development** and **nine
Henry battles to frozen regression testing**. It references existing files; no
video is copied or moved. Every clip from the same original YouTube video stays
in one partition. This prevents adjacent battles, creator overlays, layout,
compression and teams from leaking across a random frame-level split.

The active manifest is revision v2: Henry 07 contained two battles, now represented
by `henry-07a` and `henry-07b`. Its combined original is retained but excluded to
avoid duplicate examples. `manifest-v1.json` preserves the old split;
`manifest-v2.json` records the correction alongside active `manifest.json`.

Both original sources were already inspected while building the prototype,
including the Henry layout profile. Consequently this is an **exposed regression
test**, not a previously unseen accuracy benchmark. The creator/device difference
(Reis iPhone 30 fps, Henry Android 25 fps) also confounds this tiny two-source split.
Add untouched source videos, ideally independent iPhone recordings, for a final
unbiased test. Assign new sources explicitly in `dataset_tools.POLICY`; the builder
rejects silent assignments. Do not tune thresholds against the regression results
and continue calling them independent accuracy.

The manifest stores source intervals, media SHA256 hashes, size, frame rate,
completeness and prior exposure. It omits changing reader outputs so rebuilding
with the same videos and policy is deterministic. Compressed viewer packages and
tracker states are predictions, not ground truth. Sources are edited creator
footage; skipped endings and the truncated Henry 08 clip remain marked.

Run these from the project folder using Python (the existing project Python works):

```text
python dataset_tools.py build
python dataset_tools.py verify
python dataset_tools.py tasks --every-seconds 5
python dataset_tools.py evaluate --partition train --labels fixtures/reis-phase-labels-01.jsonl
python dataset_tools.py evaluate --partition test --labels dataset/human-labels.jsonl
python dataset_tools.py predict --partition train --output dataset/predictions
python dataset_tools.py predict --partition test --output dataset/predictions
python dataset_tools.py evaluate --partition test --labels dataset/human-labels.jsonl --predictions dataset/predictions --output dataset/fresh-test-evaluation.json
python -m unittest test_dataset_tools
```

The `predict` commands decode every frame of the frozen physical clips, run the
current reader with its existing creator profile, OCR every 0.5 seconds and causal
health estimation, and write deterministic compressed viewer-compatible packages
under a separate prediction folder. They do not replace the battle library, copy
videos or generate tracker assumptions. They require the project's existing reader
dependencies. Use `--only henry-01 --seconds 2 --output dataset/smoke-predictions`
for an explicitly partial smoke check. Full-library regeneration is an offline
job and can take hours on this machine; it has no real-time guarantee.

Scoring without `--predictions` checks **previously saved viewer data**, not a new
reader run. With `--predictions`, scoring checks that fresh prediction folder;
reports fingerprint all inputs so the distinction remains visible. Missing frame
coverage is counted as abstention, including partial runs. `python estimate_health.py`
refreshes health in existing library packages and `python build_lazy_viewer.py` rebuilds
the local HTML from those packages; neither command reruns video recognition.
`python organize_battles.py` regenerates the media library and remaps existing
source logs; it also does not rerun recognition. Rebuild the split with `build`,
run `verify`, then use `predict` for fresh recognition and `evaluate` for scoring.

`build` writes `dataset/manifest.json`; `verify` checks video hashes, partition
leakage, duplicate media across partitions, duplicate IDs and overlapping source
intervals. `tasks` writes a deterministic five-second sample plan containing blank
labels, with explicit unreviewed status. It does not assert what is on screen.
Five-second samples cover normal states; add frames around charge moves, health
changes, fainting and switches to test transition behavior. Use original video
frames, hide predictions while labelling, and preserve unreadable fields as null.

The independently supplied labels currently cover only **three individual Reis
phase frames and four Reis clip sequences**. Their scope differs: a clip sequence
does not mean every frame has the same phase. Assistant-reviewed half-second
transition brackets provide supporting review, not independent human frame truth.
There are no independent Henry health/species/phase labels yet. Blank tasks are
excluded from scoring. Zero labels produces `awaiting_independent_human_labels`,
with null accuracy and coverage, rather than a perfect score.

The viewer can export manual review labels in this format:

```json
{"battle_id":"henry-01","clip_seconds":12.4,"phase":"normal_fighting","mine":{"species":"Hydreigon","health_fraction_range":[0.7,0.74]},"opponent":{"species":null},"provenance":"human_review"}
```

This is a **format example**, not a label for that frame. Save or append actual
reviewed exports to the initially empty `human-labels.jsonl`. Omit fields not
reviewed; use null only when explicitly checked and unreadable. Unreadable human fields and
human phase `unknown` are excluded from accuracy and counted separately. A reviewer
flag `reviewed_without_predictions:false` excludes that label from independent
scoring and reports it separately. Legacy user fixtures lack that flag; they are
retained with their original user provenance. Fields supported by the
evaluator are phase, each side's species, CP, shields, party count and health
fraction range. Health refers to the settled visible extent, not guaranteed
applied HP; exact integer HP cannot be scored without independently known maximum
HP. Evaluator matching never reads a future row and requires a prediction no older
than one video frame plus 0.01 seconds. Stale/unknown fields remain abstentions.

The evaluator reports coverage, accuracy among covered fields, and correct fraction
over all scorable labels separately. For readable health, the estimate's point must fall inside
the human interval; a wide predicted interval does not enlarge acceptance. It also
reports the predicted interval for review. Existing coarse phase vocabulary is
mapped explicitly: `opponent_charge_imminent` to `opponent_charged_warning`,
`choose_next_after_my_faint` to `choose_next`; the minigame name is unchanged. These
three development examples establish plumbing only, not general accuracy.

Every evaluation report fingerprints the manifest, labels, relevant reader/viewer
code, profiles and viewer packages, and records the Python version. Freeze the
reader version and profile before each test run and keep evaluation reports
alongside the manifest and annotation file. Playback synchronization,
causal timestamp checks and software unit tests verify the viewer pipeline; they
do not replace independent annotations of the actual game values.

Phase evaluation defaults to direct screen observations. `--phase-source estimate`
scores the separate scene estimate, including explicitly inferred continuity.
Reports identify the selected output; inference never changes observation status.

## Preserved reader versions

All 18 active clips now have complete raw baseline logs (56,704 frames).
`reader-snapshots/v3` preserves reader/profile/template inputs and shared OCR
runtime fingerprints. `reader-snapshots/v4-refinement` preserves the subsequent
display refinement. Each clip keeps raw observations unchanged and records sparse
patches separately in `screen_refinements.jsonl.gz`. Earlier display packages are
archived without copying media. Reports include both baseline and refinement
generation provenance; scoring the current viewer checks the refined display.

The first Reis/Henry v3 packages lacked generation-time template fingerprints.
Their publication fingerprints are retained without asserting earlier verification.
Henry 01 also lacked an original-source checksum at generation. The later 16 raw
runs recorded those inputs during generation. These provenance limits remain
explicit in the packages and evaluation reports.

`python validate_library.py` independently decodes all media, checks frame counts,
original PTS alignment and causal evidence, and reconstructs display values from
raw plus refinement. `python check_visual_review.py` checks eight exposed
assistant-reviewed frames separately from human evaluation. Neither check measures
general recognition accuracy or substitutes predictions for human truth.
