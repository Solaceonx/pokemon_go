# Instructions for the agent reading battle footage

This file is self-contained. You do not need anything else from the project to do Part A.

## What this is for

We are building a program that follows a Pokémon GO trainer battle from the screen alone.
It keeps a running "game state": every Pokémon on both sides, their moves, health and
energy, shields, switch timers. Much of that is never shown on screen (the opponent's
energy, for one), so the program works it out from what is shown.

Your job is the first half: for each battle in your videos, write down what the screen
shows, moment by moment, in the format below. Those files come back to us and are fed to
the program. If you were also given the tracker bundle, Part B lets you run it yourself.

Two rules matter more than the rest:

1. **Write only what you can see.** Leave a field out when you cannot read it with
   confidence. A missing value is fine; a wrong one is harmful.
2. **Never work out hidden things.** Do not write the opponent's energy, their fast move
   or their switch timer, and do not fill anything in from knowledge of the game.

Partial records are useful. If right now you can only identify some things (say, the
Pokémon and the health bars), record those and leave the rest out.

---

# Part A: what to write

## 1. One folder per battle

Make a folder `games/<name>/` for each battle, for example `games/video03_battle2/`.
Put three files in it: `team.json`, `observations.jsonl` and `report.md`.

"Our side" (fields starting `my_`) is the player whose screen is recorded. "Foe" is their
opponent.

## 2. Names

Write Pokémon and moves by name, as text.

- Pokémon: the species name, with the form in brackets when it applies:
  `Altaria`, `Ninetales (Shadow)`, `Ninetales (Alolan)`, `Stunfisk (Galarian)`,
  `Electrode (Hisuian)`, `Marowak (Alolan)`. Add `(Shadow)` only when the shadow marker
  is visible.
- The name shown in a battle can be a nickname. If the text is not a real species name,
  identify the species from how the Pokémon looks, and say so in a `note` field.
- Moves: the move's name, for example `Double Iron Bash`. Weather Ball needs its type:
  `Weather Ball (Fire)`, `Weather Ball (Ice)`, `Weather Ball (Rock)`, `Weather Ball (Water)`.

## 3. team.json

What is known about our side before the battle starts. Give only what the video shows.

```json
{"pokemon": [
  {"species": "Melmetal", "fast": "Thunder Shock", "charged": ["Double Iron Bash", "Dynamic Punch"]},
  {"species": "Jellicent"},
  {"species": "Altaria"}
]}
```

- Lead first. Fewer than three entries is fine, and so is `{"pokemon": []}` when nothing
  is known. Pokémon that appear later are picked up from your looks.
- `fast` and `charged` only when the video shows them (a team screen, or the move names
  in battle). Leave both out otherwise.

## 4. observations.jsonl

One look at the screen per line, in time order. Each line is one JSON object. Only `t` is
required.

| Field | Type | What to write |
|---|---|---|
| `t` | number | Seconds since the battle started: the first frame after the countdown when both sides can act |
| `my_species` | text | Our Pokémon now on the field |
| `my_hp` | 0 to 1 | Filled share of our health bar. Measure it; do not round to coarse steps |
| `my_cp` | whole number | CP shown for our Pokémon |
| `foe_species` | text | Their Pokémon now on the field |
| `foe_hp` | 0 to 1 | Filled share of their health bar |
| `foe_cp` | whole number | CP shown for their Pokémon |
| `my_shields` | 0, 1, 2 | Our shields left |
| `foe_shields` | 0, 1, 2 | Their shields left |
| `my_left` | 0 to 3 | Our Pokémon not yet fainted, from the party markers |
| `foe_left` | 0 to 3 | Theirs |
| `my_energy` | 0 to 100 | Our active Pokémon's energy. Only when a charged-move button is partly filled and you know that move's cost: fill share times cost. Otherwise leave out |
| `my_switch` | seconds | Our switch countdown; 0 when the switch is ready |
| `my_charged` | text | We threw a charged move since the last look: its name if shown, otherwise `"left"` or `"right"` for the button |
| `foe_charged` | true | They threw a charged move since the last look |
| `foe_move` | text | Its name, only if the screen named it |
| `note` | text | Anything worth flagging about this look |

Example lines:

```json
{"t": 0.0, "my_species": "Melmetal", "my_hp": 1.0, "my_cp": 1500, "foe_species": "Azumarill", "foe_hp": 1.0, "my_shields": 2, "foe_shields": 2, "my_left": 3, "foe_left": 3, "my_switch": 0}
{"t": 0.5, "my_species": "Melmetal", "my_hp": 1.0, "foe_species": "Azumarill", "foe_hp": 0.979}
{"t": 1.0, "my_species": "Melmetal", "my_hp": 0.973, "foe_species": "Azumarill", "foe_hp": 0.979, "my_energy": 9}
{"t": 19.5, "my_species": "Melmetal", "my_hp": 0.74, "foe_species": "Azumarill", "foe_hp": 0.80, "my_shields": 1, "foe_shields": 2, "foe_charged": true}
```

How to take looks:

- During normal fighting, at least two a second (one per half-second turn). More is fine.
  Fewer is acceptable if that is all you can do; say so in the report.
- Do not write looks while a charged move is playing (the swipe screen, the shield
  prompt, the attack animation). Write the next look on the first frame of normal
  fighting afterwards, and put `my_charged` or `foe_charged` on that look, together with
  health and shields as they now stand. If both sides threw, put both on that look.
- When a Pokémon faints, its health is 0 on the look where that happens. The next look
  names the replacement and has the lowered `my_left` or `foe_left`.
- If part of the screen is covered (a facecam, a banner), leave those fields out.
- If the video cuts and time is skipped, end this battle's folder there and say so in the
  report.

## 5. Check your own files

You can check these without any of our code:

1. Every line is valid JSON, and `t` never goes down.
2. Health only goes down, except when the Pokémon on that side changes.
3. Shield counts and `my_left` / `foe_left` only go down.
4. Every look with `foe_charged` shows either our health lower or `my_shields` one lower
   than the look before. Every look with `my_charged` shows the same for the foe.
5. A change of `foe_species` comes with either a lower `foe_left` (a faint) or the same
   `foe_left` (a switch). The same for ours.
6. Spot-check ten looks against the video frame at that time.

## 6. report.md

One per battle:

- which video it is, and the times in the video where the battle starts and ends
- how many looks you wrote and how often you took them
- which fields you could read reliably, which only sometimes, and which not at all
- what limited the health-bar readings (resolution, overlays, compression)
- anything the screen showed that has no field here, so we can add one

## 7. Send back

The whole `games/` folder.

---

# Part B: only if you were given the tracker bundle

The bundle (`tracker_bundle.zip`) holds the program and the game data. It needs Python 3
and nothing else. Unzip it, put your `games/` folder inside it, and run:

```bash
python3 scripts/track.py games/<name>
```

`games/example/` in the bundle is a complete worked example.

It prints the looks read, any lines rejected (with the reason and line number), the events
it concluded, and a count of "unexplained changes". It writes three files into the
battle's folder. Do not edit them; fix your looks and run again.

- `state.json`: the game state after the last look
- `states.jsonl`: the game state after every look
- `events.jsonl`: what it concluded happened (fast hits, charged moves, switches, faints)

## The game state

```
t, fighting_turns, warnings
me
  active              index into pokemon
  shields, left, switch_ready_in
  pokemon[]           every Pokémon of ours known so far
opponent
  active, shields, left
  unseen              how many of theirs have not appeared yet
  switch_ready_in     counted from when they last switched
  fast_move_turns_left
  pokemon[]           only those that have appeared
```

Each Pokémon has `species`, `hp`, `hp_max`, `hp_share`, `energy`, `fainted`, stat stages,
its `fast_move` and `charged_moves`, and `known_from`: `"team_sheet"` (you told it),
`"seen"` (shown on screen) or `"guessed"` (the usual choice for the species). The
opponent's `energy_range` is the lowest and highest their energy can be.

## Extra checks with the tracker

1. No rejected lines.
2. Read every `"unexplained"` line in `events.jsonl`. It means our health dropped by an
   amount that is not a whole number of the opponent's assumed fast move. Look at that
   moment in the video. If you misread something, fix the look. If your look was right,
   leave it and list it in the report: the opponent has a different fast move or unusual
   stats, which is what we want to find out.
3. Each time the opponent throws a charged move, the top of their `energy_range` in the
   state just before must be at least that move's cost. If it is lower, fast moves were
   missed earlier.
4. At five moments through the battle, compare the state with the video: who is active,
   shields, Pokémon left, both health shares.
