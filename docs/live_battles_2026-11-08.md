# GO Battle League on the phone, 2026-11-08: every battle, and what went wrong

The bot played the owner's spare account on the Android phone (task 40; `scripts/live/play_android.py`,
`scripts/live/run_gbl.py`). Our team all day: Jellicent (Hex; Shadow Ball, Bubble Beam), Vigoroth (Scratch; Bulldoze,
Body Slam), Stunfisk (Thunder Shock; Discharge, Mud Bomb). 24 league battles: 15 won, 9 lost. The owner watched most of
the afternoon and named the faults quoted below.

## Where everything is

- **Logs** (in git): `runs/live/<STAMP>.jsonl`, one line per event: every tap, every look given to the tracker (what
  the screen showed and what the tracker believed: `"foe": [species, energy lo, energy hi, fast move, ...]`), every
  engine decision, throws, minigames with the stroke's path. `runs/live/runner-*.jsonl` are the menu runner's logs.
  `runs/replay/<STAMP>-replay.jsonl` are dry runs of later code on the same recording.
- **Recordings** (not in git; see the end): `battle-<STAMP>.h264` with `battle-<STAMP>.times` (one wall-clock time
  per frame) and an `.mp4` copy; `minigame-<epoch>-<move>/` folders of frames every 0.3 s during each swipe. A log's
  `start` row has the `epoch` that lines it up with the `.times`.
- **Tools:** `scripts/live/replay.py STAMP FOLDER` (the player, dry, on a recording: every fix below was checked so);
  `scripts/live/resim.py STAMP --foe-fast species=MOVE --window T0 T1` (the engine again on the looks, every decision
  in a window); `scripts/live/throw_check.py` (their energy count against their named throws);
  `scripts/live/ratings.py FOLDER --since EPOCH` (minigame ratings); `docs/android_play.md` (how the phone works).
- **Results and measurements:** `docs/status.md`, task 40.

## The battles

Times are seconds from the battle's start, as in its log.

| Stamp | Result | Their team | What went wrong | Fixed |
|---|---|---|---|---|
| 20261108-010017 | win | Raichu, Cranidos, Magneton | | |
| 20261108-012546 | loss | Unfezant, Ninetales | fast taps stalled: a text reading ran on the main loop | yes |
| 20261108-013604 | loss | Jolteon, Kabutops | the opening switch went in during GO! and was ignored; Jellicent fainted trusting a stale energy reading; Stunfisk held both moves into Water Pulse (Kabutops's fast move wrong) | yes |
| 20261108-023522 | loss | Galarian Stunfisk, Oinkologne | "Stunfisk" built as the regular form; its EARTHQUAKE words taken for ours; the engine imagined a fourth Pokémon | yes |
| 20261108-030643 | win | Corviknight, Toxtricity, Cinderace | | |
| 20261108-031928 | win | Suicune, Liepard, Froslass | | |
| 20261108-032349 | win | Hypno, Obstagoon, Altaria | Jellicent, sent in unasked as our last, taken for Vigoroth for 30 s | yes |
| 20261108-033502 | win | Throh, Snorlax, Timburr | | |
| 20261108-033748 | win | Greedent, Vaporeon, Toxtricity | | |
| 20261108-094103 | win | Regice, Pidgeot, Darmanitan | "Darmanitan" read as Galarian Zen (unranked): the tracker failed for the whole stretch and Discharge was thrown where Mud Bomb was super effective; three Thunder Shocks before a throw where two would do (owner) | yes |
| 20261108-101407 | win | Magcargo, Zeraora, Celebi | arming a throw two fast moves ahead stalled (a fast tap during a move is not kept) | yes |
| 20261108-103130 | win | Rapidash, Alolan Raichu, Rhyhorn | a decision for Jellicent tapped as Stunfisk's move after a switch; one frame's health misread fired a throw | yes |
| 20261108-104053 | loss | Leafeon, Dachsbun, Aerodactyl | lost with both shields; farmed on, believing Dachsbun far from a move (16 counted, threw Psychic Fangs, 35); Body Slams Great (owner) | partly: their energy given a margin |
| 20261108-105348 | loss | Hisuian Arcanine, Bruxish, Houndoom | Arcanine taken for the regular form until Rock Slide; at 20% Vigoroth threw Body Slam (38, resisted) where Bulldoze, five Scratches away, would have knocked it out (owner); its fast move counted as Snarl, really Fire Fang | form: yes (type icons); waiting for the better move: partly |
| 20261108-111429 | loss | Toxtricity, Galarian Rapidash, Jolteon | fast taps fell from ~530 a battle to ~200: the fight was made to need a button on screen, and Vigoroth hides them (owner: "Rapidash got 5 fast moves before you started tapping") | yes |
| 20261108-113003 | win | Quagsire, Lucario, Charizard | a Body Slam started with no Get Ready! and went unswiped; its "used" words came off Charizard's count (owner: "missed all the bubbles") | yes |
| 20261108-114819 | loss | Haunter, Galarian Stunfisk, Melmetal | charged taps held 7 to 10 s waiting to see a button (a guard added an hour before); Stunfisk fainted with Mud Bomb chosen and never tapped | yes |
| 20261108-115820 | win | Salazzle, Flygon, Machamp | 5 throws not taken (tapped on the count, the buttons unread) | partly |
| 20261108-120216 | win | Doublade, Incineroar, Pangoro | 5 throws not taken | partly |
| 20261108-121028 | win | Goodra, Umbreon, Espeon | 6 throws not taken; one Body Slam Great | partly |
| 20261108-121556 | win | Haunter, Slowbro, Vaporeon | | |
| 20261108-122012 | win | Mega Beedrill, Drifblim, Gengar | Vigoroth threw nothing at Gengar (owner): our energy count ran 43 to 63 in a 3 s wait with the taps off; two throws tried on it, not taken; fainted | partly |
| 20261108-123505 | loss | Gastrodon, Mega Charizard X, Scrafty | 10 throws not taken; 3 started 2.4 to 5 s after the tap, after a shortened wait gave them up, and were swiped late (Bulldoze Nice) | wait restored |
| 20261108-124100 | loss | Alolan Raichu, Mandibuzz, Hoopa | 9 throws not taken, none of which started later: Vigoroth tried Bulldoze three times at 31% and fainted with none thrown, Jellicent the same with Shadow Ball at the end; two Dark Pulses unshielded on Stunfisk | count-only throws now need the names or a margin (untested live) |

## What is still wrong, for whoever takes it up

1. **Our energy when the buttons cannot be read.** By day the buttons give a reading on 22 to 26% of fight frames
   (33 to 45% at night), and an empty button is see-through, so Vigoroth's white body behind it hides it. In between,
   the count stands in and is often off by a fast move or more both ways. Most "not taken" throws are this. A better
   daylight reading of the buttons (`pogo/android_screen.py`: `my_energy`, `button_level`, `button_labels`) is
   the root fix; the names under the buttons (shown exactly when a move is paid for) are the most reliable signal.
2. **Their energy.** Judged by their named throws, the count is short by a fast move or two at about 3 in 8; the
   engine is given it two fast moves higher (`FOE_MARGIN`). Their fast move is sometimes wrong (Snarl for Fire Fang):
   the gaps between their hits (`HitSteps`) should rule moves out faster.
3. **When a throw starts.** "Get Ready!" is not always shown. Normal moves are now seen starting by their icons
   (`minigame_on`); the colour detectors for other types find icons in the fight (brown earth for Ground) and are not
   used for this yet.
4. **Body Slam's icons.** Found by matching a cut-out of the icon (`scripts/live/normal_icons.py`): Excellent 13 times
   in the 14 Body Slams swiped since, against 1 in 6 before (one more went unswiped, item 3). Icons under the stroke's trail or the stars are still missed.
5. **Shields and farming** follow the engine and the owner's rules (`docs/status.md`, "Strategy guidance"); with
   their energy uncertain the engine both farmed too long and shielded too little in the losses above.
