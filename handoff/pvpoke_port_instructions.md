# Task: port PvPoke's battle AI into our Python simulator

**Done (2026-10-09).** The port is `pogo/pvpoke_ai.py` and prints 108 of 108 in `scripts/check_pvpoke_ai.py`. Kept as a record.

You are being asked to translate one piece of an open-source JavaScript project into
Python, and to prove the translation is exact using a test we supply. Everything you need
is in this file and in `pvpoke_port_bundle.zip`. You cannot see the rest of our project
and do not need to.

## Background

We are building a bot that plays Pokémon GO trainer battles. We have a Python simulator
of the battle rules, verified against PvPoke (pvpoke.com, the standard community
simulator): it reproduces 108 PvPoke battles hit for hit.

Every opponent our bot trains and tests against is some version of our own logic. We
want an outside opponent. PvPoke's simulator has its own AI that decides, inside a single
matchup, when to throw a charged move, which one, when to bait, and when to shield. We
want that AI as a player in our simulator.

PvPoke is MIT-licensed, so porting it is allowed. Keep a comment at the top of your file
crediting PvPoke and its licence.

## What to deliver

1. `pogo/pvpoke_ai.py`, defining a class `PvpokeAI` that works as a player in our
   simulator (interface below) and makes the same choices PvPoke's AI would.
2. `PORT_NOTES.md`: which PvPoke functions you ported and where each lives in your file;
   anything you could not port exactly and why; the acceptance-test result; any battle
   that still differs, with your best explanation.

Rules:

- Pure Python 3, standard library only.
- Do not change any other file in the bundle. If you think the engine is missing
  something, describe it in `PORT_NOTES.md` instead.
- Translate faithfully. Do not "improve" the AI or simplify its logic; we want PvPoke's
  behaviour, including its quirks. Keep function and variable names close to the
  originals so the two can be read side by side.

## The source to port

From `https://github.com/pvpoke/pvpoke`, branch `master`, under `src/js/`:

| File | What you need from it |
|---|---|
| `battle/actions/ActionLogic.js` | `decideAction` and everything it calls. This is the core of the task (about 1,300 lines) |
| `battle/Battle.js` | How `decideAction` is called each turn in `"simulate"` mode, and the shield decision made when a charged move is used in that mode (search for `useShield`) |
| `pokemon/Pokemon.js` | Default settings of a Pokémon (`baitShields`, `farmEnergy`, `optimizeMoveTiming` and similar) and the derived values the AI reads (`fastestChargedMove`, `bestChargedMove`, `activeChargedMoves`, and so on) |
| `battle/DamageCalculator.js` | The damage formula, for reference. Ours already matches it |

Raw file URLs have the form
`https://raw.githubusercontent.com/pvpoke/pvpoke/master/src/js/battle/actions/ActionLogic.js`.
If you cannot fetch them, stop and ask the person you are working with to upload those
four files.

Scope: only the single-matchup AI used in `"simulate"` mode. Do not port
`training/TrainingAI.js` (team play and switching). That is a later task.

## What is in the bundle

```
pogo/gamedata.py      Pokémon, moves, stats, damage formula
pogo/battle.py        the rules engine; read its header and step() first
pogo/agents.py        two existing players, as examples of the interface
scripts/check_pvpoke_ai.py   the acceptance test
scripts/check_pvpoke.py      the engine's own check against PvPoke (already passes)
tests/data/pvpoke_duels.txt  the 108 reference battles
data/                 game data from PvPoke
```

It needs Python 3 and nothing else. Put your file at `pogo/pvpoke_ai.py`.

## Our simulator: what a player is

A player is any object with these methods. `pogo/agents.py` has two examples.

```python
def act(self, view) -> int
def shield(self, view, foe_energy) -> bool        # or, with sees_move = True:
def shield(self, view, foe_energy, move) -> bool
def replace(self, view) -> int                    # not needed in one-on-one; return view.me.bench()[0]
```

- `act` is called at the start of each half-second turn, only when your Pokémon is not in
  the middle of a fast move. Return `FAST` (0), `CHARGED[0]` (1) or `CHARGED[1]` (2), all
  importable from `pogo.battle`. Returning a charged move without enough energy raises
  an error. There is no "wait" action; when PvPoke's logic chooses no action, it uses a
  fast move, and so should you.
- `shield` is called when the opponent throws a charged move and you still have a shield.
  `foe_energy` is their energy before the move's cost is taken. By default the player is
  not told which move is coming. PvPoke's simulate-mode shield choice does depend on the
  move, so set the class attribute `sees_move = True` and the engine will pass the `Move`
  as a third argument.
- Both sides choose at the same time. Neither sees the other's choice for the turn.

What `view` gives you:

| Expression | Meaning |
|---|---|
| `view.me.mon`, `view.foe` | The two active Pokémon (`Mon` objects) |
| `mon.hp`, `mon.energy` | Current health and energy (0 to 100) |
| `mon.atk_stage`, `mon.def_stage` | Stat changes, -4 to +4 |
| `mon.build` | Fixed facts: `species_id`, `types`, `hp` (maximum), `atk`, `defense`, `cmp_atk`, `fast`, `charged` (tuple of 1 or 2 moves) |
| `move.id`, `.name`, `.type`, `.power`, `.energy` (cost), `.energy_gain`, `.turns` (length of a fast move), `.buff_chance`, `.self_buffs`, `.foe_buffs` | A move |
| `view.me.shields`, `view.foe_shields` | Shields left |
| `view.foe_busy` | Turns left on the opponent's fast move in progress, counting this turn; 0 if they are also choosing now |
| `view.turn` | Clock in half-second turns. Each charged move adds 20, so this is not PvPoke's `turns` counter |
| `damage(user, move, target)` from `pogo.battle` | Damage that move would do right now, stat changes included |

Stats: `build.atk` includes the shadow attack bonus and `build.defense` the shadow defence
penalty. `build.cmp_atk` is attack without the shadow bonus, which is what PvPoke calls
`stats.atk`.

Turn rules, which match PvPoke's:

- A fast move started on turn t with length d lands at the end of turn t + d - 1, giving
  its damage and energy then.
- A charged move resolves on the turn it is chosen. Order within a turn: charged moves
  (higher `cmp_atk` first), then fast moves. A Pokémon knocked out by the first charged
  move does not get its own off.
- A fast move in progress when a charged move is thrown lands straight after it, unless
  its user was just knocked out by that charged move. After any charged move, both sides
  are free to choose on the next turn.

Correspondence with PvPoke's variables, to check rather than trust:

- PvPoke measures time in milliseconds with 500 per turn. Its `opponent.cooldown` at the
  moment of deciding should equal `view.foe_busy * 500`.
- PvPoke inserts one idle turn after a charged move; we do not. If the AI counts turns,
  keep your own counter inside the player.
- PvPoke's AI reads the opponent's true energy. So may you: `view.foe.energy` is exact.

## The acceptance test

`tests/data/pvpoke_duels.txt` holds 108 battles: 36 matchups, each at 0, 1 and 2 shields
per side, with **PvPoke's AI playing both sides**. For each side it records the exact
sequence of actions, the shield choices, every hit's damage, and the final health and
energy. The file's header explains the format.

The reference battles were produced on pvpoke.com with this, and nothing else changed
from a freshly constructed Pokémon:

```js
const battle = new Battle();
battle.setCP(1500);
const p = new Pokemon(speciesId, index, battle);
p.initialize(1500);
p.selectMove("fast", fastMoveId);
p.selectMove("charged", chargedMoveId1, 0);
p.selectMove("charged", chargedMoveId2, 1);
p.setShields(shields);
battle.setNewPokemon(p, index);
// ... both Pokémon set up this way, then:
battle.simulate();
```

So every setting you do not see here is at the default found in `Pokemon.js`. None of the
moves in these battles has a chance-based effect, so nothing is random.

Run:

```bash
python3 scripts/check_pvpoke_ai.py
```

It plays your `PvpokeAI` against itself in all 108 matchups and compares with the record.
For each battle that differs it prints both action sequences side by side:

```
quagsire v mantine, 1 shields each
    PvPoke  A 7fB6fB5f     B 7fA5fB5fA    shields 100/10  end 0,43,33,6
    yours   A 4fA4fA4fA4fA2f  B 5fA5fA5fA4f  shields 1/1  end 0,22,48,32
```

`7fB6fB5f` means seven fast moves, the second charged move, six fast moves, the second
charged move, five fast moves. Shield strings have one digit per incoming charged move,
1 for shielded. With no shields PvPoke's record shows zeros where ours shows `-`.

**The target is 108 of 108 identical.** For reference, our two existing players score 13
and 25. Add `-v` to list every differing battle, and
`--agent pogo.agents:Planner` to see what the output looks like for another player.

## How to go about it

1. Read `pogo/battle.py` (header and `step`) and `pogo/agents.py` (`Masher`) to see the
   interface in use. Run the test with `--agent pogo.agents:Masher` to see it working.
2. Read `ActionLogic.decideAction` end to end before writing anything. Note every value
   it reads from the Pokémon, the opponent and the battle, and find where each is set.
3. Get the 0-shield battles right first. They involve no shield decisions and no baiting.
4. Then the shield decision from `Battle.js`, then the 1- and 2-shield battles.
5. When a battle differs, find the first action that differs and work out which branch of
   the JavaScript PvPoke took there. The first difference is the only one that matters;
   everything after it follows from it.

If you can run Python, iterate against the test until it passes. If you cannot, port as
carefully as you can, say so plainly in `PORT_NOTES.md`, and list the places you are
least sure of. The file will be tested when it comes back.

## What to send back

`pogo/pvpoke_ai.py` and `PORT_NOTES.md`. State the test result as a count out of 108, or
state that you could not run it. Do not describe the port as verified unless the test
printed 108 of 108.
