# Task: turn battle videos into tracked games, in bulk

You are being asked to feed recorded GO Battle League battles (the owner's own screen
recordings first, then public videos) through the pipeline on the `main` branch, and to make
the pipeline work on footage it has not seen. Everything you need is in the repository;
this file says what exists, how to run it, what is known to break, and what to send back.

## What the pipeline does

```bash
python3 scripts/recording/run.py recording1.mp4 recording2.mp4 ... [--jobs 2]
```

For each recording it reads the video once, splits it into battles, and for each battle
writes a folder `games/<recording>-<n>/` and a line in `games/report.json`:

| File | What it holds |
|---|---|
| `observations.jsonl` | One "look" per half-second: who is out, both health bars, shields, Pokémon left, charged moves thrown, our energy |
| `events.jsonl` | What the tracker concluded: switches, faints, each charged move and whether it was shielded, the opponent's energy at each throw |
| `states.jsonl`, `state.json` | The full game state after every look, and at the end |
| `timeline.json` | The bare timeline in seconds, for timing work |
| `verdict.json` | Pass or fail, with the reasons |

The steps and their scripts are in `scripts/recording/README.md`. Read `docs/status.md` from
"First real recording" to the end before changing anything: it records what was measured,
what was tried and did not help, and why each timing constant has its value.

## Setting up

The video is read with the screen reader on the `screen-reader-video-pipeline` branch (your
earlier work), which `main` does not contain. `run.py` looks for it in `.reader/`:

```bash
git worktree add .reader/branch origin/screen-reader-video-pipeline
conda create -y -p .reader/py312 python=3.12          # or any Python 3.12 environment
.reader/py312/bin/pip install av opencv-python onnxruntime rapidocr-onnxruntime==1.4.4
```

On Windows, or with the reader somewhere else, set `READER_PYTHON` (the Python 3.12 to use)
and `READER_DIR` (the branch's `screen_reader` folder) instead. Everything after reading is
plain `python3` with no packages. `python3 -m unittest discover -s tests` should pass.

To check your setup, run the pipeline on a recording that already has a folder under
`games/` (ask the owner for the file) with `--reread`, and compare the verdict line.

## What it has been run on

Only the owner's iPhone screen recordings: portrait, 1206 x 2622, 60 frames a second, the
game's English text, nothing else on screen. Battles so far all pass the verdict. On that
footage, per battle, it gets every switch, faint and charged move (by name, with shields),
works out the opponent's fast moves, and counts energy to within one fast move (checked
against our own energy read off the charged-move buttons).

## What will break on other footage, and what to do about it

1. **The game is not the whole frame.** A stream or an edited video has the phone screen as
   a rectangle inside the frame, with a webcam, overlays or borders. The reader's layout file
   (`scripts/recording/lyxia-great.json`, copied into the reader's `profiles/`) and
   `scripts/recording/buttons.py` both assume the frame is the phone screen. First step:
   crop each video to the game screen before reading (a crop rectangle per channel or per
   video, kept in a small JSON file beside the list of sources). Finding the rectangle
   automatically comes after that works by hand.
2. **Other phones.** Positions are shares of the screen's width and height measured on one
   iPhone. A different aspect ratio moves the header, the bars and the buttons. A new layout
   needs its own profile, and the three numbers at the top of `buttons.py`.
3. **Nobody's moves are known.** For the owner's team the moves are in `KNOWN` at the top of
   `assemble.py`. For anyone else both teams start from the usual moveset per species.
   Charged moves are learnt by name when thrown, on both sides. The opponent's fast move is
   worked out from the health steps and the SUPER EFFECTIVE / NOT VERY EFFECTIVE words; the
   same is not yet done for "our" side of the screen, and should be (`Tracker._fit_fast`,
   `_effect_words` and `_rule_out_fast` are written for the opponent only).
4. **Compression and size.** At 1080p the health bar is under half the width it has in the
   owner's recordings, so small health steps blur. The energy count does not depend on them;
   working out fast moves does.
5. **Cuts.** Edited videos jump between battles and may cut inside one. `assemble.py` splits
   battles on 25 s without a health bar and on the result screen. A battle cut in the middle
   should fail the verdict; check that it does.
6. **Language.** The text cues are English.

## How to tell whether a battle was tracked correctly

Nobody will watch these, so the verdict has to carry it (`scripts/recording/verdict.py`).
It fails a battle when: a look was rejected; a charged move has no name; the shields used do
not match the charged moves tracked as blocked; a thrower was more than one fast move short
of the cost of the move; or the ending disagrees with the result screen.

- Do not loosen a check to make battles pass. If a check is wrong, say why with an example.
- The checks need no ground truth, so a battle can pass and still be wrong in a way they do
  not cover. When you find such a case, add a check that would have caught it. (The shield
  check was added that way.)
- For a new layout, run `python3 scripts/track.py games/<name> --blind`. It compares the
  energy count with the buttons without correcting it; `track.json` then says how far apart
  they were. On the owner's recordings the count is within one fast move at the end of every
  stretch of fighting. A layout whose buttons are read wrongly shows up here at once.

## Where videos come from

- Start with the owner's own recordings. They are the only footage with a known team.
- For public videos, keep a list (`data/video_sources.csv`: URL, channel, date, league, and
  whatever is known of the player's rank), because the owner wants to weigh games by how good
  the players are. Whether and which videos may be downloaded is the owner's decision; ask
  before downloading from a new source.
- Keep video files out of the repository. Commit the compressed readings
  (`games/<recording>/raw/*.gz`, tens of kilobytes) and the game folders.

## What to send back

- `games/report.json` and the game folders, on a branch.
- A short note: how many battles from how many videos, how many passed, the commonest reasons
  for failing with one example each, and what you changed in the pipeline and why.
- Read speed on your machine (`raw/read.json` has it per recording).
- Anything in the tracked games that looks wrong but passed.

## Rules

- Work on a branch; do not push to `main`.
- Run the tests before you push. If you change the tracker, also run
  `python3 scripts/check_tracker.py` and report its numbers before and after.
- A change counts when it is measured: say what you measured and on how many battles.
- Do not rewrite `docs/status.md`; add to it.
