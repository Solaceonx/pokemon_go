# Extract whole recordings, including partial battles

The owner's acceptance target is every individual battle visible in a recording;
a clipped beginning or ending is acceptable. Video extraction is evaluated
separately from reconstructing HP, energy, shields and final knockouts.

The earlier ten-battle job was intentionally a sample: the Windows menu silently
used each layout's `sample_export`, scanned only 40–45 minutes and requested five
complete paired games. The intake command also required an allowlisted Twitch ID
and rejected YouTube. The reader discarded intervals under 15 seconds. Those
restrictions prevented this from being a whole-recording importer.

The twenty failed ending verdicts in the reserved state report describe the
tracker's final Pokemon counts. They do not mean those twenty videos failed to
extract. Do not weaken the state verdict to make a cut video appear trustworthy.

## Use on the PC

Double-click `Extract all battles.cmd` (the older launcher also works). Choose an existing recording or paste a
completed Twitch VOD / YouTube video link. The default scans the full recording,
keeps incomplete and unpaired games, and imposes no battle-count limit. Existing
source downloads and matching saved cuts are reused. The source and its analysis
are not re-downloaded or overwritten to repeat extraction.

```bash
python scripts/recording/vod.py VIDEO_URL --download --reader-dir ../pokemon-go-screen-reader --sources-root ../pokemon-go-screen-reader/sources --library ../pokemon-go-screen-reader/battles
```

Known recordings reuse their calibrated phone rectangles. New sources probe
several times throughout the recording, propose phone rectangles from existing
arrangements and visible screen edges, and require repeated reads of both CP
headers. Party markers help distinguish a correct crop from a wide crop that
happens to include the numbers. A named `--layout` can also be reused on a new
video; its rectangles scale to the recording resolution. Unrecognised layouts
produce an explicit error and a review receipt, never a successful empty job.

Full intake uses approximate keyframe boundaries and keeps fragments down to
three seconds. `--precise-boundaries` adds the earlier quarter-second edge scan.
The sampling limits still matter for very brief or obscured fragments. Replay
labels are checked throughout the source. Large result graphics are read near
candidate endings; reading that region throughout hours of gameplay was an
unnecessary cost. Newly inferred arrangements either inherit matching broadcast
label regions or search for a standalone REPLAY label.

## Outputs and meaning of success

Full-run receipts use `.vod/runs/<platform>-<video ID>-full/`, separately from
the older sampled runs. `--run-dir` can select another receipt directory.
`battle-candidates.json` and `run.json` record source duration, scanned duration,
whether the whole recording was scanned, selection limits, partial flags,
paired views and excluded replays. `extraction_succeeded` means all selected
videos were written; state tracking is not required for this field.

Existing cuts of the same camera, source and encoding are reused if their edges
match, or begin within three seconds for a battle at least thirty seconds
long. Unreviewed endings must also agree within three seconds. Previously
confirmed result-bounded endings may use a wider tolerance, recorded in the
reuse receipt. Their saved analysis, reserved evaluation role and provenance remain
unchanged. Distinct cuts get new IDs. Every new clip retains source timestamps
and a compressed alignment log. Videos stay outside Git.

```bash
python scripts/recording/vod_verify.py VIDEO_ID --run-dir .vod/runs/PLATFORM-VIDEO_ID-full --reader-dir ../pokemon-go-screen-reader --library ../pokemon-go-screen-reader/battles
python ../pokemon-go-screen-reader/build_lazy_viewer.py
```

Frame verification proves a saved cut matches its proposed source interval; it
does not prove that the detector found every real game. Boundary review measures
misses, duplicates, merges and false splits. Whole-source scan coverage must not
be reported as perfect battle recall. Changing overlays, unlabelled replays,
non-English cues and unreadable headers remain cases to test on new footage.

Official layouts also read the displayed player names. Sustained changes of
matchup split edited highlight sequences into separate partial excerpts. These
are retained as footage, without counting them as complete new games or assuming
they are duplicates. Superseded mixed cuts remain on disk but are hidden from
the active library. Empty selections never retire existing clips.

`--reuse-broadcast-labels` can reuse a completed label scan when source hash,
duration and geometry match. Its receipt retains the original reading fingerprint
and limitation: result-marker windows are not expanded. Ordinary runs rescan the
needed label regions when the cache no longer matches.

## Measured run, 2026-10-13

The two official recordings, 2897166800 and 2897312743, were scanned across all
15,206 seconds (4 hours 13 minutes). They produced 32 ordinary battle interval
candidates and 10 partial edited excerpts, each with both player views: 84 saved
videos. The 10 excerpts came from two highlight montages; they can repeat earlier
games. Forty-two candidates therefore does not mean forty-two unique games.

All 760,904 decoded frames passed source/crop/timestamp verification, with maximum
alignment error 0.0016671 seconds. No uncovered run of detected HUD frames lasting
ten seconds remained outside the selected footage or labelled replay exclusions.
This is a coverage check against the detector's own observations, not independent
recall. On the previously reviewed Henry and Reis YouTube recordings, all 18
reviewed intervals matched distinct predictions with intersection-over-union
at least 0.5 and no extra predictions. These exposed fixtures are regression data.

The protected twenty evaluation clips' metadata, viewer packages and raw reading
files retained their original hashes. The new clips remain unassigned; all cuts
from these reserved sources must stay out of recognition/tracking parameter
fitting. New clips display pending analysis. Existing tracked clips still populate
the playback table. Browser checks covered four new and four tracked player clips,
twelve tracked seeks, sample filters, and no JavaScript errors. All 187 repository
tests and 108 reference duels pass after two upstream Windows compatibility fixes.

The originals occupy 11.86 GB, selected clips 2.63 GB, and their saved data 73.08 MB
(decimal units; saved data includes existing analysis and archives). Original
sources are stored once and 19 earlier cuts were reused. Four superseded montage
videos are retained outside the active selection. The viewer has 126 active views,
a 58.93 MB HTML file, and no embedded video copies. The complete measured receipt,
source and code hashes, per-clip intervals and storage are in
`data/vod_full_extraction_validation.json`. Full game-state accuracy is a separate,
unfinished acceptance target.

The earlier reserved state comparison and its settings remain intact. The
ten-battle sampling commands are still available explicitly in
`official_sample.md`; the Windows launcher now performs full extraction.
