# Task 46: frozen collection and separate energy evaluation

Owner direction, 2026-11-20: stop optimizing strict pass counts. Keep the J4 reader fixed at commit `112a9813071093ede5c04d7ad26dbbd0455b574a` while two workers collect completed Twitch archives and one worker evaluates energy reconstruction.

## Collection

Use one shared newest-first queue across HomeSliceHenry, reis2occasion and ItsAXN, with exclusive per-VOD claims. Verify archive dates at intake. Keep only battles with in-game evidence establishing **open Great League**. A title, a Great League-sized CP or the presence of a league option in a menu is insufficient. Restricted cups, Remix, Ultra/Master and unresolved league contexts are excluded from the accepted collection. Preserve the reason and source witnesses for exclusions.

Store the VOD upload date separately from an actual in-game date. If the game does not display a date, leave the in-game date unknown. Do not turn the phone's clock or a stream upload date into a claimed game observation.

Keep the fixed detector's parameters and code unchanged. Source-specific phone rectangles are input metadata and require visual verification. Save each eligible cut, its full-frame verification, timestamp alignment, tracking output and typed game record. Failed game-state checks remain visible and do not invalidate a correctly saved video.

After every required cut passes source/frame verification and its evidence is retained, delete the corresponding full source download. Tracking can continue from retained cuts. Never delete cuts, reserved samples, old backups or unfinished source evidence. Record exact deletion targets, verification hashes and bytes. Keep at least 25 GB free; stop new downloads rather than deleting cuts if space is low.

Report after each ten completed VODs: VODs processed, battles saved, league mix, current media/data bytes, bytes retired and drive free space. Distinguish cut/verification completion, source retirement and tracking completion. Existing cuts can be reused but are not new saved battles merely because they are reviewed again.

## Public trainer handles

The owner's latest direction explicitly permits public **in-game handles** with game-only teams and play observations. This replaces Task 46's earlier blanket exclusion of trainer handles. Keep the frozen reader's export behavior unchanged; add a separate typed metadata sidecar.

Only publish a handle when it is clearly verified in the public game UI, with source-frame witnesses and side attribution. Do not export unrestricted OCR, chat, operating-system notifications, real-world identity links, locations or sensitive attributes. Uncertain handles stay unknown. A gameplay profile describes observed games, not a real-world identity or personality assessment.

## Energy

Develop a separate reconstruction using measured fast-move completions, verified moveset provenance and named charged releases. Preserve each Pokémon's banked energy across switches, cap energy at 100 and represent uncertain starts or missing completions as integer candidates. A charged release proves affordability and a spend; it does not prove an empty energy bank afterwards.

Score the same frozen references before any broader replay. Their current labels contain no numeric energy or fast-completion truth, so numeric accuracy on those labels is **unscorable**, not zero-error. Report availability separately. Prepare any necessary supplemental source-only labels separately, freeze them before estimator predictions and retain the original references unchanged. Report coverage, exact/range accuracy, margins and unscorable cases without using charge legality as independent ground truth. Distinguish causal estimates from any reconstruction that uses later evidence.

The twenty reserved official views and the three fifth-evaluation sources remain protected. New collection does not authorize recognition tuning on them.

## Reproducibility checks

`scripts/recording/reader_freeze.py` verifies the snapshot against the freeze manifest before/after collection. The private manifest includes all 511 snapshot file hashes; the public manifest in `runs/task46-reader-freeze-20261120.json` includes the same source/data hashes without local machine paths. External reader files override the matching repository copies; use their separate exact-byte hashes. Runtime tools are shared read-only rather than duplicated with each worker.

`scripts/recording/public_handles.py` accepts only the typed `public-trainer-handles-v1` receipt: source URL/id, battle id and at most one verified handle per side, each with at least two distinct public source timestamps from versus/result screens. Review the source images before setting `verified: true`; a valid receipt alone does not prove the reading correct. Unknown handles have no entry. This helper does not change the frozen exporter or infer a real-world identity.

The outer `scripts/recording/collection_ops.py` accepts `--work-root` and separate claim, detect, witness, export/verify, retirement and tracking steps. It can track verified retained cuts after the full source has been retired. `scripts/recording/collection_progress.py --work-root ... --out ...` produces the typed disk/count checkpoint; completed receipts count processing, not full-state accuracy. A pending verified cut is reported separately until tracking finishes. Keep at most two full sources per collector when prefetching, with only one OCR/tracking job per worker and space reserved for normalization.

The first portable energy pilot can be reproduced without videos or native dependencies:

```sh
python scripts/recording/energy_reference_eval.py --root . --context data/creator_energy_pilot_context_v1.json --labels data/creator_energy_source_supplement_v3.json --out runs/task46-energy-reference-reproduced-local.json
```

This pilot covers one development battle, with source-assisted move/phase metadata. It has not established general energy accuracy. The original frozen references have no numeric energy targets; their accuracy remains unscorable.

The unchanged detector's three-channel extension is independently reproducible from typed inputs:

```sh
python scripts/recording/energy_reference_batch.py --root . --manifest data/creator_energy_channel_eval_manifest_v1.json --out runs/task46-energy-three-channel-reproduced-local.json
```

Its 5/12 useful checkpoints include four exact scalar readings and one range-compatible reading. This is a small development check with source-assisted metadata and wide source-bootstrap margins, not readiness to replay or certify every game.

The completed original-six check keeps failed and unscorable attempts:

```sh
python scripts/recording/energy_reference_six.py --root . --manifest data/creator_energy_six_reference_eval_manifest_v1.json --out runs/task46-energy-six-original-reproduced-local.json
```

It reports6/18 useful predictions, including a false confident zero against source-labelled32–36. Five of six useful readings fit source bounds; scalar recovery is4/10. Two attempted windows have unresolved numeric truth. The prototype remains separate and is not ready for wider replay. Flat HP pixels alone do not prove zero completed fast moves.

Wholly non-open sources can use `collection_exclusion.py` after complete coarse coverage, source-reviewed league continuity and decoder evidence, verified stopped reader/orchestrator processes and matching actual source hashes. It explicitly records `reader_detection_completed: false`; it does not manufacture a completed broadcast-label scan or media-cut pass. Only the exact full source is retired; all context frames/coarse data/proofs remain. Accepted sources instead require the normal cut verification and source-byte checks before and after export.

The conservative v4 comparison and newly labelled windows are separately reproducible:

```sh
python scripts/recording/energy_bounds_eval_v4.py --root . --manifest data/creator_energy_v4_development_manifest_v1.json --out runs/task46-energy-v4-development-reproduced-local.json
python scripts/recording/energy_bounds_eval_v4.py --root . --manifest data/creator_energy_v4_new_window_validation_manifest_v1.json --out runs/task46-energy-v4-new-window-reproduced-local.json
```

These produce1/18 and0/6 useful readings. They preserve conservative candidate sets without falsely asserting zero, but do not establish full-game energy coverage or exact accuracy.
