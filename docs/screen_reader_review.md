# Review of the screen reader branch

Branch `screen-reader-video-pipeline`, reviewed 2026-10-10 against one question: can it
give the tracker a reliable look every half-second turn, with no person in the loop?

Short answer: the fast per-frame path is fast enough and what it reads looks right, but
it does not yet deliver a steady stream of health readings, and health is the one thing
the tracker cannot do without. Nothing measures its accuracy yet.

## What was checked

- Its own 109 tests, on macOS with Python 3.12: all pass. (It does not install on
  Python 3.13; one package requires an older Python.)
- The reader run on its 33 sample frames, timed, and two frames compared by eye.
- Not checked: any video. None is in the repository, so nothing here says how it behaves
  across a whole battle.

## Measurements

| What | Result |
|---|---|
| Time per frame, text reading off | 11 ms median, 16 ms worst |
| Time per frame, text reading on | 950 ms median, 1,407 ms worst |
| Width of a health bar in these recordings | 138 pixels, so one pixel is 0.7% of the bar (about 1 HP for a 150-HP Pokémon) |
| Sample frames in normal fighting with both health bars read | 3 of 5 |
| Three consecutive frames 0.2 s apart (`henry-420.2`, `.4`, `.6`) | mine only, then theirs only, then neither |
| A charge-minigame frame (`henry-150`) | phase came back unknown |

Where a value was read it matched the frame: names, CP, shields, Pokémon left, and a
health bar at about a tenth. In the same frame the opponent's bar, plainly visible with
a teal part and an orange part, came back unknown.

## What stands between this and the tracker

1. **Health is intermittent.** Bars float above the Pokémon, move, and are overlaid by
   effect text right when a hit lands, which is exactly when the tracker needs them.
2. **Health is not exported automatically.** `export_tracker.py` needs a person to
   approve each health value, because the reader does not decide whether an orange
   segment is health or damage still draining.
3. **Charged moves are not events yet.** The exporter takes them from a review file.
4. **Text reading is a second per frame.** It must leave the per-frame path entirely.
5. **Profiles carry per-video knowledge** (`known_moves`, `team_moves`,
   `species_lexicon`). A layout profile should describe the layout only.
6. **No accuracy figure.** The human-labels file is empty.

## The bar to clear

Report each of these per battle, on recordings not used during development.

1. **Coverage.** For every half-second of normal fighting, is there at least one settled
   health value for each side? Target: 99% of half-seconds. Report the longest gap.
2. **Automatic health.** Export the settled value with no approval step. Decide the
   orange-segment question once (see below) and state the rule.
3. **Automatic charged-move events.** Detect that a charged move started and ended, and
   put `my_charged` or `foe_charged` on the first fighting look after it.
4. **Speed.** Per-frame path at or under 50 ms with text reading off; text read only
   when a Pokémon changes.
5. **End to end, no person.** Export a whole battle, run
   `python3 scripts/track.py games/<name>`: no rejected lines; report the number of
   `unexplained` events; the final state must agree with the result screen.
6. **Accuracy.** At least 300 hand-labelled frames from a third, untouched source:
   health within 1% on 95% of frames; shields, Pokémon left and phase right on 99%.
7. **One function for live use.** `look(frame, t) -> Observation` as in task 3 of
   `docs/tasks.md`, so the same code reads a captured frame.

The quickest first step: commit one exported battle under `games/`, however rough, so
the tracker can be run on it.

## Health bar colours (from the owner)

The colour of a health bar tells the health level: yellow means 25% to 50%, red means
under 25%, and the normal colour means above 50%.

Two uses for the reader:

- **A free cross-check on every reading.** A bar measured at 10% must be red; one
  measured at 40% must be yellow. A mismatch means the measurement or the bar's bounds
  are wrong, and the look should be marked unreadable instead of exported.
- **The two-colour bar.** Since colour follows level, a bar that is one colour up to a
  point and orange beyond it is not showing two health levels. The first part is the
  new health and the orange part is damage still draining away (confirmed by the owner,
  2026-10-10). Export the first part as the health value the moment a hit lands.
