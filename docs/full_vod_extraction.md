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

The earlier reserved state comparison and its settings remain intact. The
ten-battle sampling commands are still available explicitly in
`official_sample.md`; the Windows launcher now performs full extraction.
