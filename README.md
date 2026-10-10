# pokemon_go

An automatic Pokémon GO battler, built in two halves: the decision-making, developed
and measured in a simulator, and (later) the link to a real iPhone.

Automating the real game breaks Niantic's terms of service and can get the account banned.

**Start with `docs/status.md`**: what has been measured, what was tried and did not work,
and what is open.

## Battle simulator

```bash
python3 scripts/arena.py
```

plays thousands of simulated Great League battles and prints how the Planner scores
against the expert model (a strong player as lyxia describes one) and against cruder
styles kept as sanity checks. `--parts` measures each part of the Planner on its own,
and `--show SEED` prints one battle move by move.

```bash
python3 scripts/team.py melmetal jellicent altaria --grid
```

reports on one team of three: its record against random opponents, the best lead, the
hardest opposing Pokémon, and every one-on-one against the top 50. Saved runs are in `reports/`.

- `pogo/gamedata.py` loads Pokémon, moves and stats and holds the damage formula.
- `pogo/battle.py` is the rules engine; its header lists the rules and simplifications.
- `pogo/agents.py` has the players: `Planner` (rule-based, each part configurable),
  `expert()` (the benchmark opponent), `Masher` and the other `STYLES`.
- `pogo/arena.py` runs the comparisons.
- `tests/test_rules.py` checks stats, damage and turn rules: `python3 -m unittest discover tests`

## Checked against PvPoke

```bash
python3 scripts/check_pvpoke.py
```

replays 108 one-on-one battles from PvPoke's own simulator (`tests/data/pvpoke_duels.txt`)
and confirms this engine gives the same hits, damage and final health and energy.
Switching and chance-based stat changes are not covered by that check.

## Self-play training

```bash
python3 scripts/selfplay.py --minutes 30
```

trains the `Learner` (`pogo/learner.py`) with nobody watching: it first imitates the
Planner, then improves by playing the Planner, the expert model and its own best
version. It uses one core at low priority, saves every round, and resumes when run
again. Results go to `runs/<run>/`; test a saved policy with

```bash
python3 scripts/arena.py --learner runs/default/best.npz
```

Add `--team a b c` to train a strategy for one team; it then prints the trained strategy
next to the Planner piloting the same team on the same fresh battles. Training opponents
include `varied()`: our own player with every habit shifted a little, drawn fresh each battle.

## Learning one decision at a time

```bash
python3 scripts/decide.py --team melmetal jellicent altaria --minutes 30
```

freezes battles at shield and throw decisions, plays each option out with everything
else equal (shield or not; throw either move, or hold for one, four or ten more fast
moves), and trains a network on which option went on to win. The Learner then follows
the Planner except where the network rates another option clearly higher. It ends with
a test against the Planner piloting the same team on the same fresh battles.

## Advice from any game state

```bash
python3 scripts/advise.py games/example --look 45
```

takes a game state written by the tracker and prints what to do now, whether to use the
next shield, the chance of winning, and one typical way the rest of the game goes. Add
`--q runs/<team>-decide/q.npz` to pilot with learned decisions.

## Tracking a live battle

`pogo/tracker.py` keeps a running picture of one battle from what the screen shows
(`Observation`), counting what the screen never shows, and offers it to a player in the
same shape as the simulator's view. Each game can be written to its own event file.

```bash
python3 scripts/check_tracker.py --game
```

tests it on simulated battles through a simulated camera of varying quality, and writes
one example game to `games/example/`.

```bash
python3 scripts/track.py games/example
```

builds the game state for one battle from `team.json` and `observations.jsonl` in that
folder, writing `state.json`, `states.jsonl` and `events.jsonl`. The formats, and the
instructions for an agent producing the looks from footage, are in `docs/agent_instructions.md`.

`scripts/train_value.py` trains a win-chance model for positions (`pogo/value.py`). It
predicts better than the hand-set tally but did not win more games, so it is off by default.

A player decides from a `View`, which holds only what a screen can show, so the same
player can later be driven by screenshots.

Data in `data/` comes from [PvPoke](https://github.com/pvpoke/pvpoke) (MIT licence):
`gamemaster.json`, `rankings-1500.json`, and `cpm.json` (the level multiplier table
taken from its source).

## Phone link (parked)

`helper/phonectl.swift`, `pogo/phone.py` and `scripts/probe.py` screenshot the iPhone
Mirroring window, read its text, and send taps and drags. Not yet tried on a real phone.

```bash
./build.sh
```

```bash
python3 scripts/probe.py
```

The app running the scripts needs Screen Recording and Accessibility permission
(`scripts/probe.py --request` shows the prompts).
