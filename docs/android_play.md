# Playing on the Android phone: what the bot has learnt (task 40)

Everything measured while the bot played the owner's spare account on a moto g stylus 5G (2024), 7 and 8 November
2026, for other agents to build on. Results and their history are in `docs/status.md` (task 40). This file is the
reference: how the screen looks, how the minigame is swiped, what went wrong and what fixed it, and the tools.

The recordings themselves (`C:\pogo-media\live\<date>[-training]\battle-*.h264` with `.times`, an `.mp4`, and
`minigame-<epoch>-<move>/` frame folders) stay on the owner's PC, out of git. The logs of every battle are in git:
`runs/live/<stamp>.jsonl` (one battle) and `runs/live/runner-<stamp>.jsonl` (the menus between battles);
`runs/replay/` holds logs from replaying recordings through the player.

## The set-up

- The phone (adb serial `ZY22JPBNMW`, 1080 x 2400) is mirrored by a scrcpy 5.0.1 client written in Python
  (`pogo/android.py`): the server jar pushed and started over `adb forward`, the H.264 stream decoded with PyAV to
  540 x 1200 frames at up to 30 a second, touches sent on scrcpy's control channel. `POGO_SCRCPY_DIR` points at the
  scrcpy release folder (its bundled adb is used).
- Every screen position below is a share of the width and height, measured on this phone's frames
  (`pogo/android_screen.py`, `pogo/controls.py`). Other phones need them measured again.
- One battle: `scripts/live/play_android.py`. Team Leader battles back to back: `scripts/live/train_loop.py`. GO
  Battle League: `scripts/live/run_gbl.py`. The engine is the website's (`pogo.realtime.WEBSITE`, the `runs/general-decide`
  network), asked at each look (every 0.5 s), at most 300 ms a decision. The team: Jellicent (Hex; Shadow Ball, Bubble
  Beam), Vigoroth (Scratch; Bulldoze, Body Slam), Stunfisk (Thunder Shock; Discharge, Mud Bomb), `data/alt_team.json`.

## The charged-move minigame ("bubbles")

**Which icons.** The icons are the type of the move thrown, so the move decides the type before the minigame starts.
Each icon is a round disc of icon size (radius 0.085 of the width or more) with a white type symbol in the middle and
a ring of the type's colour around it. Colours measured on this phone (RGB of the ring):

| Type | Ring colour | Where they come up (centre; spread), shares of the screen |
|---|---|---|
| Ground | (210, 131, 86) | (0.50, 0.70); (0.31, 0.05): low in the middle, in a line |
| Electric | (245, 215, 82) | (0.49, 0.58); (0.22, 0.10) |
| Ghost | (101, 108, 188) | (0.60, 0.71); (0.24, 0.11): spread over all of Jellicent |
| Water | (94, 167, 218) | (0.86, 0.42); (0.10, 0.11): they stream in from the right edge and drift |
| Normal | grey-white, no colour | (0.53, 0.60); (0.29, 0.16) |

Other types fall back to `data/minigame/<type>.json` (measured on the owner's iPhone recordings, a screen of nearly
the same shape).

**Finding them** (`find_icons` in `play_android.py`): circles by their outline (OpenCV `HoughCircles` at a loose
threshold, `param2=15`, without the shape filters of `pogo.minigame.detect`, which dropped many real icons), kept when
the ring between the white symbol and the rim is the type's colour (within 45 per channel on average) and the core
has a white symbol (15% or more of it brighter than 205 in every channel). The white-symbol test is what stops sky,
clouds and the Pokémon's body from passing: Water icons cross Jellicent's body, the same blue, and Ghost icons sit on
a Jellicent dark with smoke. Normal (grey) uses the strict detector only. Ground also accepts blobs of its colour
(nothing else on screen is that orange-brown).

**Timing**, from the recordings at 30 frames a second (`scripts/live/minigame_timing.py`):
- "Get Ready!" shows in the box at the top middle (0.18-0.82 x 0.17-0.30) when our move starts. The player catches it
  within 0.15 s of its first frame.
- The icons come up 1.0 to 1.45 s after it. The rating stops changing 6.0 to 6.8 s after it.
- The stroke runs from 1.05 s to 6.28 s after Get Ready!.
- The swipe paths in `data/minigame/` start the stroke at `start_after_move_s`; the live player waits until 0.4 s
  before that.

**The stroke** (`minigame_stroke`): one touch held down for about 5 s, steered every 10 ms, its target re-chosen on
the newest frame every 50 ms:
- Go to the icons seen on the newest frame, nearest first, at 6.5 shares of the width a second (the screen is 2.2
  times taller than wide; distances are measured with that). An icon counts as reached within 0.02 (Water's drift,
  so the finger goes to the centre seen rather than stopping at the edge).
- Leave out icons the finger has passed within 0.06 in the last 0.4 s. A frame is 0.1 to 0.2 s old when it is read,
  so an icon already popped still shows; chasing it again cost the next icon its time. Before this, Shadow Ball
  (icons over all of Jellicent) once rated only Great.
- With no icon in sight, sweep a figure of eight over the type's zone.
- Never go near the run button at the top left (it forfeits): x kept at 0.22 or more above y 0.32
  (`pogo.controls.KEEP_OUT`). Lift the finger on the open field (`controls.FIELD`, (0.50, 0.45)), never over the
  bench portraits at the right edge, where a touch as the fight comes back would switch our Pokémon.
- Stop at once if a shield prompt comes up.

**Results.** Of the moves swiped in Team Leader batches 5 to 10, all but one rated Excellent (one Great in batch 5,
before the trail rule), and every GO Battle League minigame since the fixes has been Excellent. Ratings are read
from the kept frames with OCR (`scripts/live/ratings.py`; `report.py` per battle).

**What went wrong with minigames, and the fixes.** Each one was found on the recordings:
1. **A move that went off unseen, never swiped.** A charged tap is answered when the fast move under way ends, and
   a throw beaten by theirs plays after theirs. Get Ready! then comes when the player has stopped waiting. In batch 8,
   35 of 39 of our moves were swiped (`scripts/live/audit_cues.py` finds every Get Ready! on a recording and matches
   it to the log's swipes).
   - Fix: after a throw that has not started, the player keeps watching for Get Ready!. It watches for up to 40 s,
     dropping the watch when the fight has been back for 2 s or the buttons show the move not paid for.
   - Fix: the top box is read with OCR only while the fight is off the screen. OCR takes 0.3 to 0.5 s a read here,
     and the fight is always off the screen at Get Ready!.
   - Batches 9 and 10: 33 of 33 and 35 of 35 swiped.
2. **The wrong type hunted.** The game sometimes ignores a switch tap. The player then believed the new Pokémon was
   out, tapped its move on the old one's button, and hunted Ground icons in a Ghost minigame (no icons found).
   - Fix: at a throw, the button's paid-for colour names the move (see the buttons below). The move is corrected
     when the colour plainly is not the move's type: 463 right corrections against 4 wrong on recorded frames.
   - Fix: switches are now confirmed from the buttons (see switches below).
3. **Fast taps cancelling the charged tap.** A tap on the field after a charged tap takes its place in the game's
   queue; a paid-for Discharge went off only after the fourth tap. Fast taps stop from the charged tap until Get
   Ready!, and the button is tapped again every 0.6 s while it shows the move paid for.
4. **Lag.** Once the game lagged and never showed a minigame (batch 10), and it later crashed to the home screen.

## Our energy, from the charged-move buttons

Counting our own fast moves drifted 20 to 50 off, both ways: moves never seen, Pokémon seen late, and turns lost when a
tap came late. The buttons show it exactly, and the player reads them on every frame:
- Short of a move's cost, a button is a dark see-through disc with the type's colour rising from the bottom, and no
  name under it.
- At the cost, the whole disc turns a light shade of the type and the name shows in white under it.
- Past the cost, a darker shade rises again toward a second throw.
- `android_screen.my_energy` reads a level from 0 to 2 on each button and turns it into energy. Below the cost, the
  level is the share of the cost. Past it, the level is 1 plus the share toward a second throw. The cap is 100.
- A reading is accepted only when both buttons give the same energy (within max(3, 7% of the cost)) and each name
  shows exactly when its move is paid for. The player keeps a reading when two frames in a row agree within 5. On
  the recordings this gives clean staircases (13 a step for Hex, 4 for Scratch).
- For about 1 s after a move becomes paid for, the buttons flash and the fill cannot be read; the names can
  (`button_labels`). The player then keeps its count within what the names say (`paid_bounds`). Without this, Mud
  Bomb's name showed while the count said 43 of its 45, and the engine threw Discharge into Typhlosion instead.
- Paid-for shades (RGB): Ghost (134, 144, 195), Water (130, 177, 220), Electric (244, 221, 120), Ground (221, 156,
  120), Normal (177, 183, 186). `paid_type` names the type when one shade is within 25 and the next is 15 farther.

## Health bars

- The bars float over the Pokémon (they bob with it), each 148.5 pixels of fill when full on the 540-wide frame.
  Ours is the one whose left end is in the left third. `android_screen.bars` finds them by the fill colour, the
  light border left of the fill and above it, and the see-through dark after it.
- Fill colours: green about (20, 252, 188), yellow (244, 206, 57), red (235, 100, 105).
- A hit leaves an **orange strip** about (250, 155, 10) at the end of the fill for a second or so, shrinking. It is
  health already lost. Until 2026-11-08 it was counted as fill on some frames and not others, and the bars jumped 2
  to 6 pixels each frame after every hit. Now it is left out, and each fast move shows as one clean step. On
  Jellicent against Typhlosion the steps were 148 → 136 → 124 → 112 pixels.
- In close-ups and changes of Pokémon, false single-frame bars show. The player counts the fight as on screen only
  after three frames in a row with the header and a bar.

## Prompts, switches, the rest

- **Shield prompt:** the shield's centre is (0.50, 0.842), "NOT NOW" (0.50, 0.950). A tap while the prompt fades in
  is ignored, so the answer is tapped again every 0.4 s until it goes (for 5 s at most). Two prompts can come back
  to back (Garbodor's two Seed Bombs): a prompt back after 1.5 s away is a new one.
- **Switches:** the bench portraits are at (0.90, 0.603) and (0.90, 0.692). The game sometimes ignores the tap,
  and any camera cut changes the portraits too. So a switch counts only when the buttons become the new Pokémon's
  moves: its names under the buttons, or an energy reading that fits its costs and not the old one's, three frames
  running. The old one's names a second after the tap say it was not taken. The bench strip decides only if neither
  has said anything in 5 s. No charged tap goes until it is settled. A real switch is confirmed 2.1 to 3.3 s after
  the tap.
- **Replacement prompt:** one Pokémon left (0.50, 0.865); two, (0.33, 0.865) and (0.67, 0.865). It is tapped again
  every 0.5 s until it goes.
- **Fast moves** are taps on the open field (0.50, 0.45), every 0.25 s from their own thread, so the engine's
  thinking leaves no gaps. Before this, one tap in five came more than 0.45 s after the last, and a one-turn move
  (Scratch) loses its turn at such a gap.
- **Crash guards:** the player stops after 20 s with no fight on screen, and the runners tap only when Pokémon GO is
  the app in front (`dumpsys window`). Once the game crashed to the home screen, and the player went on for 200 s,
  tapping a prompt it thought it saw.
- **The engine on top:** shield a hit that would knock us out or take 35% of our health (unless we are nearly gone),
  always shield on our last Pokémon, and with health under 35% and a move paid for, throw the hardest-hitting one.

## Tools (all read the recordings on the owner's PC)

| Tool | What it does |
|---|---|
| `scripts/live/report.py MEDIA [--since EPOCH]` | per battle: result, throws, ratings, shields chosen and used |
| `scripts/live/ratings.py MEDIA` | each minigame's rating from its kept frames |
| `scripts/live/audit_cues.py MEDIA` | every Get Ready! on the recordings, matched to the swipes in the logs |
| `scripts/live/minigame_timing.py MEDIA STEM...` | when icons come and go, and the stroke, relative to Get Ready! |
| `scripts/live/replay.py STEM [MEDIA]` | the live player in dry run on a recording, in real time, logging to `runs/replay/` |
| `scripts/live/to_mp4.py RECORDING` | a playable video, timed to the log |
| `scripts/live/resim.py STAMP --foe-fast species=MOVE` | the battle's looks again, with their true fast moves, and the engine's decisions set beside the live ones |

Replaying is how every fix above was checked before it went to the phone. A recording is replayed at its own speed,
and the player's decisions and taps are logged but not sent.

## Open problems

- **Counting fast moves exactly, ours and theirs.** Ours is read off the buttons. Theirs is counted by rhythm: a fast
  move every so many turns while their Pokémon is out, in `pogo.tracker`. With the orange strip left out, the steps
  in our bar show each of their fast moves landing. Work on counting from those steps began on 2026-11-08.
- The game drops a touch that starts just after another ends (2026-11-08). So switch and charged taps wait 0.25 s
  after the last fast tap, and a switch that is still not taken is tried once more.
- The Team Leaders lose to this team every time, so training tests the mechanics, not the strategy.
