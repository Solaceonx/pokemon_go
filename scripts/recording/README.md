# From screen recordings to tracked games

For Twitch originals and cropped battle clips, see [VOD_README.md](VOD_README.md).
That intake stage preserves source timing and review flags. `Track Battle Videos.cmd`
then reads the calibrated public clips, runs state reconstruction, and opens their
synchronized viewer. The public-footage path removes the owner's fixed movesets;
observed readings, model assumptions and consistency failures remain separate.

One command takes recordings and produces tracked games with a pass/fail report:

```bash
python3 scripts/recording/run.py ~/Downloads/ScreenRecording_*.MP4
```

For each recording it reads the video once, splits it into battles, and for each battle
builds the looks, runs the tracker and applies checks that need nobody watching. Battles go
to `games/<recording>-1`, `-2`, ...; the report is `games/report.json`.

## The steps

| Step | Script | Needs | Writes |
|---|---|---|---|
| Read the video | `read_recording.py` | the screen reader (below) | `games/<recording>/raw/readings.jsonl.gz`, `text.jsonl.gz`, `read.json` |
| Build the looks | `assemble.py` | plain python3 | `team.json`, `observations.jsonl`, `timeline.json` |
| Track | `scripts/track.py` | plain python3 | `state.json`, `states.jsonl`, `events.jsonl`, `track.json` |
| Judge | `verdict.py` | plain python3 | `verdict.json` |

Reading is the slow step and is done once; its output is kept, so everything after it can be
re-run whenever the assembly or the tracker changes:

```bash
python3 scripts/recording/assemble.py games/<recording>/raw/readings.jsonl.gz games/<recording>/raw/text.jsonl.gz games/<name> [--battle 2]
python3 scripts/track.py games/<name>
python3 scripts/recording/verdict.py games/<name>
```

`rhythm.py games/<name>` is an independent count of energy from exact times, for checking the
tracker's own count.

## The screen reader

Reading uses the reader on the `screen-reader-video-pipeline` branch, which is not merged
here. `run.py` looks for it in `.reader/` at the top of the project (not in git):

```bash
git worktree add .reader/branch origin/screen-reader-video-pipeline
conda create -y -p .reader/py312 python=3.12
.reader/py312/bin/pip install av opencv-python onnxruntime rapidocr-onnxruntime==1.4.4
```

To keep it somewhere else, set `READER_PYTHON` (that Python) and `READER_DIR` (the branch's
`screen_reader` folder).

`run.py` copies the layout file `lyxia-great.json` into the reader's `profiles/` the first
time. That layout is the reader's own iPhone layout with a full list of species names; it has
worked on two iPhone layouts and has not been tried on anything else.

## What the verdict checks

A battle fails if any of these fails: no look was rejected; one to three recognised Pokémon
on each side; every charged move read by name, and as many tracked as announced; whoever
threw a charged move had at least its cost by the tracker's count; the result screen agrees
with who had Pokémon left. It also notes, without failing: many unexplained changes in our
health, and opponent fast moves that are still only guessed.

## What is set by hand

Nothing per recording. `KNOWN` at the top of `assemble.py` holds the movesets we have been told
for the owner's own Pokémon; any other Pokémon gets the usual moves until the battle shows
otherwise. Results and open problems are in `docs/status.md`.


## Replaying saved creator records

`replay_creators.py` rebuilds existing canonical creator records from their cached readings. It does not download footage or repeat OCR. Use a fresh private work folder so the before records and checkpoints remain available:

```powershell
python scripts/recording/replay_creators.py --reader-dir ../pokemon-go-screen-reader --work .vod/creator-replay
python scripts/recording/replay_creators.py --reader-dir ../pokemon-go-screen-reader --work .vod/creator-replay --resume
```

The optional `--source` and `--channel` filters can be repeated. The normal video dependencies described above are still required. The work folder must be under `.vod`; backups and diagnostics stay out of Git. Raw-log changes and changed replay code block reuse of a checkpoint. Each record retains its strict verdict, including failures. Successful processing does not mean accurate game states; an actual processing error returns a nonzero exit and preserves the previous export. Each package is built in a temporary private folder before installation; the prior package is retained locally, with rollback if installation fails. Channel summaries and `games/catalog.json` follow completed replays. The result/empty-bar adapters apply only to creator exports; result words and surrender dialogs never imply a knockout.


## Source-reviewed creator events

`data/creator_ground_truth_v1.json` contains two source-reviewed clips per channel. It keeps uncertain/censored releases explicit, separates Protect Shield use from other BLOCKED messages, and pins witness frames by source PTS and hashes without storing images. Score the current records against a baseline checkout's creator packages:

```powershell
python scripts/recording/score_creator_events.py --before PATH_TO_BASELINE/games/creators --baseline-ref d856e542895ff23a42f4922353c5f5410bf4ad9e --out runs/task46-event-accuracy-20261118.json
```

The scorer reports precision, recall, false/missed events, per-channel results and descriptive whole-battle-bootstrap margins. Primary matches require identity and an annotated video-time interval with a three-second allowance; untimed identity scores are diagnostic only. Henry 002 was used to develop the centered-impact reader and is excluded in an additional five-clip result. These six nonrandom clips are not a general game-state accuracy claim. Centered-impact evidence is creator-only; the existing strict verdicts remain in force.
