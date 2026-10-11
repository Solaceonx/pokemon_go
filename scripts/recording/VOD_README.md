# Twitch intake, battle cuts and state tracking

This pilot downloads a completed Twitch VOD, keeps one playable original, and
exports each visible battle candidate as a cropped MP4 with its source timestamps.
A separate tracking stage reads each full clip and publishes its evidence and
model states to the viewer. Full recognition accuracy is not yet established.

On the owner's Windows PC, double-click `Cut Twitch VOD.cmd`, then choose the
recording. It uses the existing `pokemon-go-screen-reader` media folder when that
folder is beside this checkout. Matching completed downloads and cuts are reused.
After cutting, double-click `Track Battle Videos.cmd`. It reads the calibrated
clips, saves compressed results, and opens the viewer with its live values table.

## Track the saved clips

```bash
python scripts/recording/vod_track.py \
  --reader-dir ../pokemon-go-screen-reader \
  --library ../pokemon-go-screen-reader/battles --jobs 2
```

`--reader-dir` accepts the installed reader or the reader branch's `screen_reader`
directory. `--only <clip-id>` limits a run. Pixel reading samples 15 frames per
second; text reading runs at 3 Hz. This is offline video analysis. The viewer
follows the saved timeline during playback; live iPhone capture remains future work.

The public-footage adapter removes the owner's fixed team and charged templates.
Visible names, CP, health bars, shields, party markers and buttons feed an evidence
ledger. It remembers bench Pokemon and stored readings with their ages, and
confirms counters after repeated frames. Charged announcements, replacement waits
and button visibility also feed the main tracker. Its energy, fast-move, stage and
switch-clock assumptions are labelled inferred or guessed in separate columns.

Energy from visible discs is a range of compatible whole values, using observed
move costs. Fast-move fits stay ambiguous when legal moves share a rate. HP is a
measured fraction range; maximum HP and integer HP stay unknown. Mixed-color
damage animations require settled frames. A final charged announcement never
supplies an invented zero-HP reading or knockout.

Raw OCR is immutable and reused only when video, alignment, profile, template
and reader fingerprints match. Changed postprocessing reuses those readings;
faint-marker, health-region and disc refinement rereads pixels without repeating
OCR. `data/vod_tracking_layouts.json` calibrates the three camera layouts. Both
broadcast views are processed again after their peer timelines exist. Only
same-source, same-match announcements can recover an obscured move name; no
recovery succeeded in the measured run.

## Reproduce the pilot

Use Python 3.12 with the reader dependencies described in `README.md`. Set
`READER_DIR` to the reader branch's `screen_reader` folder, and install yt-dlp or
give its executable using `--downloader`.

```bash
python scripts/recording/vod.py https://www.twitch.tv/videos/2894502346 \
  --layout henry-20261007 --download
python scripts/recording/vod.py https://www.twitch.tv/videos/2897295240 \
  --layout official-louisville-20261010 --download
```

Defaults put sources, scan caches, candidates and cuts under `.vod/`, outside Git.
`--sources-root` and `--library` can point at an existing media library.
`--stage detect` stops before encoding clips. `--jobs 2` limits simultaneous exports.
`--resegment` rebuilds candidates using unchanged cached visual samples;
`--rescan` rebuilds visual samples and boundary candidates. A changed input must
never silently reuse a clip made from different footage or boundaries.

The layout names apply to the specific recording IDs in `data/vod_layouts.json`.
A creator can change their overlay or phone layout. Measure a new recording before
adding its ID; a channel name alone is insufficient calibration.

## What is stored

- One original per VOD, with public URL, creator, duration, checksum and download
  integrity evidence in `source.json`. Private Twitch access URLs are not saved.
- Each cropped clip has `battle.json`, compressed `frame_alignment.jsonl.gz`,
  `tracking-raw/` readings, compressed `tracker/` logs, `analysis-summary.json`
  and `viewer-data.json.gz`. Audio stays in the video when the source contains it.
- `games/twitch/` contains portable compressed observations, states, events,
  timelines, team hypotheses, verdicts and source/code fingerprints. It contains
  no videos or runtime installations. Historical analyses stay locally in
  `analysis-archive/`; identical output does not add another archive.
- `.vod/runs/<id>/` has compressed visual samples, boundary candidates and a run
  summary. These allow boundary review without a folder full of frame images.

Twitch's native HLS download can have a `.mp4` name while containing MPEG-TS and
timestamps starting after zero. Intake packet-copies it into MP4 without reencoding,
checks packet counts, duration and timestamp order, and retains the original offset
and checksum. A small journal recovers interrupted metadata updates. The old source
is replaced only after validation; there is one final source copy.

Unavailable fragments abort the download. A completed file whose duration disagrees
with Twitch metadata is rejected. A `.part` file is retained for resumption, never
treated as a finished recording.

## Boundaries and evaluation

Discovery uses CP headers, countdowns, sustained party resets and long lobby gaps.
Keyframes locate candidate intervals; quarter-second samples refine entrances and
endings. A charged-move animation alone must not become a separate match.

The official broadcast shows two phone views, labelled replays and a tournament
logo over gameplay. Paired views share one `match_id`; their clips must stay in the
same evaluation group. Replay intervals are excluded from the live match count.
The first battle begins before this VOD and stays marked incomplete. Covered or
unreadable values remain unknown.

All sampled boundaries retain review flags. `vod.py` creates unanalyzed clips;
`vod_track.py` changes them to `analyzed_with_unknowns` and saves an internal
consistency verdict. Partial coverage always prevents a complete battle pass.
Inspect entrances and endings before using clips for state evaluation.

Henry is development data; the official footage was inspected during calibration
and is exposed regression data. Neither is an untouched test set. A future test
VOD must be reserved before changing the detector using its contents. Possible
overlap with edited YouTube videos also needs checking before accuracy evaluation.

## Validation

```bash
python -m unittest discover -s tests
python scripts/check_pvpoke.py
python scripts/recording/vod_verify.py 2894502346
python scripts/recording/vod_verify.py 2897295240
```

The intake tests cover timestamp preservation, metadata recovery after interruption,
partial-download rejection, short result tails, lobby gaps, rapid party resets,
charged-animation gaps and grouping simultaneous perspectives.
The verifier decodes every saved video frame, compares it with the compressed
source-alignment log, and checks the checksum, duration, crop and audio presence.
That verifies media integrity, not recognition accuracy or exact action boundaries.
Tracking tests cover unknown stats, whole-energy alternatives, ambiguous fast
rates, stale identities, Unicode announcements, partial clips, same-match peer
evidence and compressed observations. The existing verdict's hard checks remain
in force. Its ending check requires a decisive roster state; unresolved terminal
knockouts remain failures even when a result screen is readable.

After both sources have passed verification, `vod_report.py` regenerates
`data/vod_pilot_report.json` with portable source intervals, checksums, split roles,
measured storage and media validation results. It does not copy media into Git.

## Measured pilot

The two recordings produced 19 match candidates in 23 player-view clips: Henry's
15 matches and the official broadcast's four matches with two views each. Three
broadcast replay sections (six views) were excluded. The official opening match
is incomplete in both views. All boundaries retain review flags.

All 228,285 saved frames decoded and matched their source-alignment logs within
0.000687 seconds. Chrome playback and seeking were checked on a Henry clip,
both official views and the partial opening clip, including the 17-column table
and remembered teams. All 62 pipeline tests and 107 reader tests passed; all 108
PvPoke reference duels reproduced exactly. The default simulated tracker check
produced byte-identical before/after output over 2,400 battles per run. Simulation
regression does not measure real-video accuracy.

All 23 views were read over their full saved clips: 57,079 sampled frames and
2,568 model states. None passes every strict consistency check: all 23 have
unresolved terminal roster/ending checks, four have charged-event disagreements,
three have energy failures, one has a shield failure, and two start mid-match.
Categories overlap. Terminal HP and party counts stay unreadable instead of
creating a knockout to satisfy the verifier.

Blind model energy differed from button estimates by 12.15 energy units on
average across 1,147 eligible looks. Two partial views supplied no energy looks.
The button readings are unvalidated, so this is a disagreement measurement, not
accuracy against labelled truth. Hidden teammates, forms/Shadow identity, maximum
HP, stage history and exact battle/switch timing still need more evidence.
Replaying a portable Henry export reproduced model states/events byte for byte
and retained the same failed ending verdict.

| Saved media | Henry | Official | Total |
|---|---:|---:|---:|
| One original per VOD | 3.045 GB | 1.003 GB | 4.047 GB |
| Cropped player-view videos | 421.1 MB | 264.0 MB | 685.1 MB |
| Alignment and metadata before tracking | 2.80 MB | 1.41 MB | 4.21 MB |

Current analysis, alignment and metadata occupy 35.75 MB, plus 84.06 MB of
historical analyses from calibration. The local total is 4.852 GB, excluding the
shared runtime, existing library, viewer HTML, scan caches and review images.
A typical complete player-view clip is 30.2 MB (median); current data averages
1.55 MB per view, or 5.21 MB including these historical versions. The portable
results committed for all 23 views occupy 2.23 MB total. The viewer HTML is a
separate 23.94 MB artifact covering all 41 local clips. It embeds no videos and
decompresses only the selected battle in memory.
Keeping the original averages about 232 MB per Henry match or 317 MB per official
match when allocated across these recordings; the official total includes both views.

Coarse discovery took 493.0 seconds for Henry's 6,790-second recording and 274.8
seconds for the official 1,307-second recording. These timings came from concurrent
workloads and are not single-core recognition benchmarks. Refinement and encoding
add time; rerunning unchanged cuts reuses their verified files.
The first OCR pass summed 3,278.6 worker-seconds across 3,804.4 clip-seconds under
concurrent load. This is a sum of worker timings, not elapsed single-core time.

`games/twitch/runtime-assets.json` records supplementary OCR-model and lexicon
hashes collected after the run. Raw-cache invalidation does not yet enforce these
asset hashes; changing the runtime requires a fresh reading version. Recognition
accuracy still needs human labels and a new untouched test source.
