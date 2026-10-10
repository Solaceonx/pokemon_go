# From a screen recording to a tracked game

Used once so far, on a single iPhone recording (2026-10-10). It is a worked example, not a finished tool.

These scripts need the reader on the `screen-reader-video-pipeline` branch and its packages
(Python 3.12 with av, opencv, onnxruntime, rapidocr-onnxruntime). Check that branch out beside
this one, copy `lyxia-great.json` into its `screen_reader/profiles/` (and copy the
`profiles/reis-great/` template folder to `profiles/lyxia-great/`), then from `screen_reader/`:

```bash
PYTHONPATH=. python read_frames.py recording.mp4 readings.jsonl     # every frame: health bars, header
PYTHONPATH=. python read_text.py recording.mp4 text.jsonl 3         # announcement text, 3 looks a second
```

Then from this project's root, with plain Python 3:

```bash
python3 scripts/recording/assemble.py readings.jsonl text.jsonl games/<name>
python3 scripts/track.py games/<name>
```

Set by hand at the top of `assemble.py` for now: when the fight starts (`T0`), our three
Pokémon (`OURS`) and our team sheet. The readings of the first recording are kept, compressed,
in `games/lyxia-2026-10-10/raw/`. What worked and what did not is in `docs/status.md`.
