# Official broadcast sample

The owner requested about ten battles from the official `pokemongo` Twitch
channel, with both players' views. `data/vod_additional_sample_plan.json` reserves
two original Louisville broadcasts and fixes the selection rule before gameplay
inspection: the first five complete, paired games with visible results in each
source, ordered chronologically and reviewed for entrances, endings and replays.
Two perspectives count as one battle. Rebroadcast VODs and instant replays do
not count.

The source IDs are `2897166800` and `2897312743`. Twitch labels both recordings
“GO Day 1 | 2027 Pokémon Louisville Regional Championships”; their recorded
upload date is 2026-10-10. Preserve the supplied title and date separately.
The source broadcast intervals do not overlap each other or the earlier
`2897295240` official pilot recording. This does not rule out edited copies on
other services.

## Run on the owner's PC

Double-click `Cut Twitch VOD.cmd` and choose either new official sample option.
Repeat for the other recording. The launcher keeps one full original per VOD,
reuses matching clips, verifies their saved frames and opens the viewer. Choose
**New official sample** in the viewer's Set menu. The two player clips of each
match share one battle ID and stay in the same evaluation group.

These clips are reserved for evaluating state tracking. Their analysis is
pending; collecting and playing complete video does not establish recognition
accuracy. The state tracker is frozen at `7fd46503e4c9f414f356579113cf5346934d416b`.
Only intake selection, bounded discovery and viewer filtering change for this
collection. Layout and boundary review expose the videos to the agent, so this
is a reserved state-evaluation sample rather than a completely untouched source.
Review and adjudicate state labels independently before publishing accuracy.

## Reproduce with Python

With the reader dependencies installed and this checkout beside
`pokemon-go-screen-reader`, run from this repository:

```bash
python scripts/recording/vod.py https://www.twitch.tv/videos/2897166800 --layout official-louisville-sample-a --download --reader-dir ../pokemon-go-screen-reader --sources-root ../pokemon-go-screen-reader/sources --library ../pokemon-go-screen-reader/battles --scan-end 2700 --limit-battles 5 --complete-only --paired-only
python scripts/recording/vod.py https://www.twitch.tv/videos/2897312743 --layout official-louisville-sample-b --download --reader-dir ../pokemon-go-screen-reader --sources-root ../pokemon-go-screen-reader/sources --library ../pokemon-go-screen-reader/battles --scan-end 2400 --limit-battles 5 --complete-only --paired-only
python scripts/recording/vod_verify.py 2897166800 --reader-dir ../pokemon-go-screen-reader --library ../pokemon-go-screen-reader/battles
python scripts/recording/vod_verify.py 2897312743 --reader-dir ../pokemon-go-screen-reader --library ../pokemon-go-screen-reader/battles
python ../pokemon-go-screen-reader/build_lazy_viewer.py
```

Use `--stage detect` to review boundaries before encoding. Both originals have
1920×1080 dual-phone layouts: left `[508,56,448,976]`, right
`[970,56,448,976]`. Those crops reuse the old official layout, checked against
the new recordings. Keep source checksums, normalized source timestamps,
original container offsets and compressed per-frame alignment logs. Verification
decodes every exported video frame and checks its source timestamp, crop, audio,
duration and checksum. It does not verify game state or exact action boundaries.

The first recording needs a 45-minute discovery window to include the fifth
game's ending; the second uses 40 minutes. The broadcast's full-screen
**GAME WIN** graphic supplies result-boundary evidence when the phone result
screens are replaced. The new layouts add this broadcast cue without changing
state recognition or the old pilot's layout.

Brief result graphics can fall entirely between two-second video keyframes.
Unresolved endings receive quarter-second result-cue sampling in narrow windows;
the replay scan and interiors reuse their saved samples. Paired intervals share
their beginning and ending when their coverage agrees. If only one phone shows
the result, the other is explicitly marked `paired_result_visible` and retains
the original camera's evidence instead of claiming its own result was read.

The replay filter now keeps a live game starting immediately after the last
replay badge. When one camera is split by header gaps, adjacent fragments can
join inside the other camera's complete result-bounded interval. The join
requires matching source, start/end coverage, no missing interval and no new
countdown cue; fragment provenance is retained. These are intake improvements
developed during boundary review, separate from the frozen state recognizer.

`data/vod_additional_sample.json` records the selected IDs, review evidence,
measured storage and validation receipts. Videos, runtime installations, scan
caches and contact sheets stay local, outside Git. Current analysis is compressed
and separate from historical versions. The original two-source pilot report is
preserved as an earlier measurement.

## Collection results

Ten complete games produced twenty player-view clips. All 224,002 saved video
frames passed media/source alignment checks; four browser checks played both
views of both sources and verified the new filter and pending/unknown displays.
All 102 pipeline tests and 108 PvPoke reference duels pass. Agent review covered
each game's entrance, midpoint and resolution. Exact action timing and game
state remain unverified, and the new clips contain no state readings yet.

| New stored files | Measured size |
|---|---:|
| Cropped videos, both views of ten games | 774.40 MB |
| Alignment and metadata before state analysis | 4.27 MB |
| Two retained originals, one per VOD | 11.86 GB |
| New media and clip data combined | 12.64 GB |

A sampled battle averages 77.44 MB of video and 0.427 MB of metadata/alignment
for its two views. The median player-view video is 38.21 MB. Full originals
include broadcast breaks and unused games; retaining more games from them reuses
the same originals. These decimal sizes exclude the shared runtime, prior
library, scan caches, review images and the separate 31.22 MB viewer HTML. The
viewer covers 61 video views, embeds no video and keeps pending state values
unknown. State-analysis storage will be measured when those readings are made.

## Subsequent frozen state evaluation

The collection results above record the pre-analysis intake. All twenty reserved
views have since been read and published at the unchanged 15 FPS / three text
looks cadence, following the GitHub handoff at 0fd98ff. The new measurement,
current storage and before/fitted comparison are in
`reserved_state_evaluation.md` and `data/vod_reserved_state_evaluation.json`.
The original intake receipt is preserved; full game-state accuracy remains
unverified, and these games remain excluded from recognition tuning.
