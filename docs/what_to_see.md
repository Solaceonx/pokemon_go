# What the bot needs to see in a battle

This is the checklist for recording battles and for building the image recognition.
Everything here feeds a number the battle engine already tracks (health, energy,
shields, timers, whose fast move is where), so a recording is "good" when all of it
can be read off the footage.

Items marked **(confirm)** are my expectation of where the game shows something.
Check them against the first recordings and correct this file.

One turn is 0.5 seconds. At 30 frames a second that is 15 frames a turn.

## 1. How to record

- Record on the phone itself with iOS screen recording, portrait, full screen. Do not film the phone or record a stream.
- Same phone and same game settings for every video, game language English.
- Do Not Disturb on, so no banners cover the screen.
- Keep the whole battle in one file: from the opponent appearing to the result screen.
- 30 frames a second is the minimum, 60 is better. Do not trim, crop, speed up or re-encode.
- Sound is not needed. Recordings usually have none, so nothing may depend on it.
- Great League only for now. That is what the simulator's data covers.
- One battle per file, named `YYYY-MM-DD_NN.mov`.

## 2. A note to save with every video

A text file with the same name as the video. This is the ground truth for our side and costs a minute per battle.

- My three Pokémon in lead order: species, fast move, both charged moves, CP, and IVs if known.
- Result: win, loss or draw.
- Anything unusual: lag, a freeze, a disconnect, a misclick.

## 3. On screen the whole battle

Read once per turn unless noted.

| # | What | What we need from it | How exact |
|---|---|---|---|
| 1 | Phase of the battle | Which of: countdown, normal fighting, my charged-move minigame, opponent's charged move (shield prompt), a Pokémon switching in, my choose-next screen after a faint, result screen | Exact, to the frame it changes |
| 2 | My active Pokémon | Species (name text) and CP | Exact |
| 3 | My health bar | Filled share of the bar | Within 1 HP if the bar is wide enough, else 1% |
| 4 | Opponent's active Pokémon | Species (name text) and CP **(confirm CP is shown)** | Exact |
| 5 | Opponent's health bar | Filled share of the bar | Within 1% |
| 6 | Shields left | Mine and theirs, 0 to 2 each | Exact |
| 7 | Pokémon left | Mine and theirs, 0 to 3 each, from the party markers | Exact |
| 8 | My charged-move buttons | How many (1 or 2), which move each is (type colour and icon), how full each is, whether it is ready, and whether it shows enough energy for a second use **(confirm how that looks)** | Fill within 5 energy |
| 9 | Switch button | Ready, or the seconds left on its countdown | Exact seconds |
| 10 | Battle clock | Seconds left | Exact |
| 11 | Stat changes in effect | Attack and defence stages for both active Pokémon, if the game keeps a marker on screen **(confirm)** | Exact |
| 12 | My bench | Which two are on the bench and their health, visible when the switch menu or choose-next screen is open **(confirm health is shown there)** | Within 5% |

## 4. Events to catch

Each needs a time. "Turn" means within a quarter of a second. "Frame" means within one or two frames, because it is used for move timing.

| # | Event | What we need | When |
|---|---|---|---|
| 1 | My fast move lands | That it landed (opponent's bar steps down) | Frame |
| 2 | Opponent's fast move lands | That it landed (my bar steps down) and how much it took | Frame |
| 3 | I throw a charged move | Which one, and the charge result (Nice, Great, Excellent) | Frame for the start |
| 4 | My minigame targets | Where the swipe targets are and how they move, since the bot has to hit them | Every frame of the minigame |
| 5 | Opponent throws a charged move | The first frame the game shows it, since that is when the shield decision starts | Frame |
| 6 | Shield prompt | Where the button is and how long I have | Frame |
| 7 | Which move the opponent threw | Move name from the on-screen text **(confirm it is shown)**, otherwise its type from the effect colour | Turn |
| 8 | Shield used | By me or by them (shield count drops) | Turn |
| 9 | Charged-move damage | Size of the health-bar drop | Within 1% |
| 10 | Effectiveness text | Super effective, not very effective, or none | Turn |
| 11 | Stat change | Whose, which stat, up or down, and by how much | Turn |
| 12 | I switch | Which Pokémon comes in | Frame |
| 13 | Opponent switches | That the Pokémon changed, and the new species | Frame, since it starts their 45 s timer |
| 14 | A Pokémon faints | Whose, and what comes in next | Turn |
| 15 | Both act again | First frame after a charged move, switch or faint when fast moves resume | Frame |
| 16 | Battle ends | Result | Turn |
| 17 | Lag | Frozen frames, health bars jumping back, input not registering | Flag the stretch |

## 5. Not on screen: has to be worked out

| What | Worked out from |
|---|---|
| Opponent's energy | Count of their fast moves that landed, times the move's energy, minus the cost of each charged move they threw |
| Which fast move the opponent has | Section 6 |
| Where the opponent is in their fast move | Time since their last fast move landed, given its length. Breaks if they stop tapping, so gaps must be detected |
| Opponent's charged moves | Revealed when thrown. Before that, the usual moveset for the species |
| Opponent's switch timer | 45 s from event 13, counting down through charged moves |
| Opponent's bench | Species seen so far, plus the count from item 7 |
| Opponent's exact stats | Unknown. Narrowed by their CP and by how much damage moves actually do |
| My exact health and energy | The engine tracks these from my known team. Items 3 and 8 are the cross-check |

## 6. Opponent fast moves, the hard one

The game never names the opponent's fast move, and recognising attack animations for every species is not realistic.

First assumption (lyxia's idea): once the species is recognised, assume its most common fast move. The health bar is then only a check on that assumption, and the way to count their fast moves for energy.

- Every fast move that lands takes the same amount off my bar, at a fixed rhythm.
- The rhythm gives the move's length in turns (1 to 5).
- The amount, with the opponent's species and CP, picks the move out of the few that species can have.
- Once the move is known, each step on my bar is one more unit of their energy.

What the footage has to make possible:

- Seeing a drop of 1 or 2 HP on my health bar. This decides whether the plan works. Resisted fast moves do this little.
- Telling whether the bar drops in one step or slides down, and how many frames the slide takes.
- Telling a fast-move hit from the start of a charged move when both happen close together.
- A fallback cue for tiny hits: the hit flash on my Pokémon. Not sound; recordings usually have none.

Cases that stay ambiguous (two candidate moves with the same length and nearly the same damage) should be logged as ambiguous, not guessed.

## 6b. Playing live: how often to look, and keeping track

The bot keeps its own running copy of the battle, the same state the simulator uses:
both teams' health and energy, shields, switch timers, where each side is in its fast
move, and the clock. It moves that copy forward by the rules every turn and uses the
screen to correct it. The screen wins for what it shows directly (health, shields, my
energy, my switch countdown); the count is kept for what it never shows (their energy,
their switch timer). A disagreement beyond a small tolerance is logged.

How often to look (targets, not yet measured on the phone):

| How often | What |
|---|---|
| 15 to 20 times a second | Both health bars, shield icons, my charged-button fill, and whether a shield prompt or minigame is on screen. Small fixed regions, no text reading |
| Once a second | Switch countdown and battle clock (digits) |
| Only when something changes | Pokémon names and CP, the bench |

Decisions are made once per turn (twice a second). The looks in between are there to put
each hit in the right turn and to stay lined up with the game's turn clock. Delay matters
more than rate: from screen to tap should stay well under one turn, aiming for under 150 ms.

## 7. Timing to measure from the footage

These settle open questions in the simulator. A handful of clean examples of each is enough.

1. Length of a charged move from first sign to both sides acting again: unshielded, shielded, mine and theirs.
2. How many seconds come off the switch countdown across each of those.
3. Whether the opponent's fast move in progress still lands when I throw, and when I can first act afterwards.
4. Both sides throwing on the same turn: what it looks like and who goes first.
5. Time allowed on the choose-next screen after a faint, and whether the switch countdown keeps running during it.
6. Delay between a switch and the new Pokémon being able to act.
7. Total length of the battle clock, and whether it runs during charged moves.
8. Spacing between fast-move hits for each move length, to confirm 0.5 s turns under real lag.

## 8. What the first batch must contain

Ten to twenty battles is enough to build and test the recognition, if between them they include:

- My fast moves of at least three different lengths, and opponents' of at least three.
- Both of my charged moves thrown, shielded and unshielded.
- Opponent charged moves that I shield and that I take.
- At least one clear bait by each side (cheap move thrown with energy for the big one).
- A resisted fast move doing 1 to 2 damage to me (for section 6).
- Switches by me and by the opponent, including a switch straight after a charged move.
- Faints on both sides, with the choose-next screen.
- A move that changes stats, and a shadow Pokémon on each side.
- One battle with visible lag.
- Wins and losses.

## 9. Order of work

1. Record the first batch with notes (sections 1 and 2).
2. Build the recognition on those, running on the Mac. It turns each video into a text log of sections 3 and 4.
3. Check each log by replaying it through the battle engine: if the health numbers do not line up, the recognition or the engine is wrong at that point.
4. Take the timing measurements (section 7) and fix the simulator.
5. Only then record the large set.

Recognition and checking run locally and use no assistant time. The assistant is needed to write the detectors from a few sample frames and to look at the cases the check flags.
