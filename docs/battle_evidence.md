# Additional evidence from saved live battles

The owner's request, 2026-11-09: inspect the newer live-game reader on GitHub and
recover more information about the games. This is offline analysis. It imports no
phone controller, sends no taps, changes no live-player code, and writes sidecars
separately from task 45's existing game records. The official VOD test footage and
its recognition settings are untouched.

Double-click **View additional battle data.cmd** on this PC. The standalone report
lets you select a saved battle, play its existing video, follow the evidence table,
filter events, inspect a source line, and export that battle's evidence as JSON.
It embeds compressed evidence and references existing media; it copies no videos.
Only the selected battle is decompressed. Frames and recordings remain local.

## What was recovered

The input snapshot contains 214 ended logs. Requiring a start, an end and at least
one usable look leaves 207 records, with **19,553 screen looks and 127,215 evidence
rows**. Six other logs were still incomplete or invalid when snapshotted and seven
ended logs lacked enough usable battle evidence. This is a snapshot, not a monitor.
Training battles and fragments are not a count of distinct completed league games.

| Recorded context | Records | Screen looks | Looks with button energy | Full logged engine views |
|---|---:|---:|---:|---:|
| League | 71 | 8,399 | 2,944 | 36 |
| Team Leader training | 110 | 9,406 | 2,925 | 0 |
| Context unknown | 26 | 1,748 | 995 | 0 |

Context is taken from an existing game record or an explicit league field. Unknown
context is left unknown. End results and all diagnostic event counts remain what
the player logged, not independently checked outcomes. The per-battle sidecars add:

- Every saved screen look, button measurements, counted energy and opposing energy
  range, with source-line references and an explicit distinction between observations
  and tracker beliefs.
- Input attempts, charged-move starts, tap-to-start delays, missed throws and switches,
  shield choices, name-based energy constraints, corrections, and decision runtimes.
- Full decision views when actually logged: active/bench state, assumed moves and
  stats, switch waits, stages, and opponent move/energy hypotheses. These builds,
  IVs, levels and integer HP are the engine's assumptions, not verified actual stats.
- The most recent preceding look and its age for every decision; no future look or
  imagined decision view fills missing historical state.
- Health increases over 10 percentage points within two seconds for the same logged
  species, marked for review. There are 612 such flags, **not 612 proven errors**:
  switches, effects, OCR changes and incorrect bar assignment can all contribute.

The 71 league-context records contain 118 logged `throw_not_taken` events, 91
`throw_beaten` events, 43 `switch_not_taken` events and 37 `tracker_error` events.
They are event counts, not mutually exclusive failures or confirmed lost games.
Only 35.1% of league looks contain a button-energy estimate. The full engine view
was available for just two newest records (26 and 10 views); older views cannot be
recovered from the logs. The report makes these omissions visible.

## Additional readings from three videos

The screen-only module and button dependency were frozen from live-reader commit
`615b30e69c8ff9515c4cedbb6de788059352956a`. Without changing thresholds, the offline
reader sampled the original `.h264` recordings at up to five looks per second.
Saved `.times` frame-arrival values align the frames to each log's start epoch.

| Battle | Pixel samples | Energy estimates where preceding look had none | Our bar read where preceding look had none |
|---|---:|---:|---:|
| 20261108-235420 | 562 | 20 | 13 |
| 20261109-003216 | 850 | 37 | 31 |
| 20261109-120903 | 883 | 28 | 87 |
| Total | 2,295 | 85 | 131 |

Those additions use only the most recent preceding logged look within 0.75 seconds,
across 890 eligible sample frames. They are repeated sample-frame opportunities,
not independent new moves or verified corrections. Changes between sample times
can explain disagreements. Pixel outputs include raw bar fractions, filtered or
reacquired bar hypotheses, header types, shields and remaining-party indicators,
button levels, move-name visibility and conservative button-energy estimates. Move
costs and active-species context come from the logged team, not new name recognition.

The three recordings decode to 16,482 frames but have 16,479 saved arrival-time
rows. One untimed buffered tail frame per recording was skipped. No timestamp was
invented; frame-order alignment is recorded as an assumption, not independent proof.

Inspection of the largest discrepancies illustrates why both sources are retained:

- At 21.349 s in 235420, Gastrodon's visible bar is mostly full; the earlier log at
  21.183 s says 1.3%. The fresh estimate is 92.9%, visually plausible but not an exact
  human-labelled bar measurement.
- At 99.063 s in 003216, the frame says **Go, Lapras!**, with a nearly full Lapras.
  The earlier log still names Toxtricity at 12.8%. That disagreement is a switch,
  not evidence that health recognition improved by 86 percentage points.
- At 169.691 s in 120903, Snorlax's bar is around two-fifths full, against a prior
  logged 30.3%. The fresh 41.1% reading needs temporal review before replacing it.

More readable fields are useful, but this run does not establish increased accuracy.
There are no independent labels, score improvements or strategy changes in this work.
The Android geometry is calibrated to a 540:1200 phone. Applying it directly to the
older iPhone/broadcast crops would require layout adaptation and separate validation.

## Reproduction and storage

The two export steps accept explicit paths, avoiding the active session's outputs:

```bash
python scripts/live/enrich_records.py --logs SAVED_LOGS --records games/live --out EVIDENCE
python scripts/live/read_saved_pixels.py STAMP --media MEDIA_FOLDER --log SAVED_LOGS/STAMP.jsonl --reader-root PINNED_READER --out EVIDENCE/STAMP --hz 5
python scripts/live/build_evidence_viewer.py --evidence EVIDENCE --media-root MEDIA_ROOT --out "Battle data.html"
```

`PINNED_READER` contains `pogo/android_screen.py` and
`scripts/recording/buttons.py` from the stated reader commit. Pixel extraction uses
the already installed PyAV and NumPy, while log export and HTML generation use the
standard library. No runtime services or language-model calls are involved.

On this PC the frozen inputs, compressed sidecars, three pixel reads and HTML live
under `.vod/enrichment-20261109/`. Logs are compressed losslessly; views and raw
pixels are distinguished. Video stays in its existing media folder. Public small
receipts are in `runs/live-evidence-20261109.json`; bulky generated row packages and
the HTML stay local. The sidecars occupy 3.26 MB and the standalone HTML 3.36 MB;
three pixel packages use 121 KB, with zero additional video bytes. The receipt
includes source hashes and per-record denominators,
not trainer names, account names, OCR text, or machine-local paths.
