# Pokémon GO battle bot

A bot that plays Pokémon GO trainer battles (Great League, three against three). It is
being built brain first, in a simulator: the rules engine, the players and the training
all run on a laptop with no phone attached. Reading the phone screen and sending taps
come later.

Automating the real game breaks Niantic's terms of service and can get an account banned.

## Start here

Do these in order. Everything runs from the repository root.

1. Read [`docs/status.md`](docs/status.md). It has every measured result, what was tried
   and did not work, the owner's strategy guidance, and the open directions. Do not
   propose anything before reading the "Tried and did not help" list.
2. Check that the code works on your machine (under a second):
   ```bash
   python3 -m unittest discover tests
   ```
3. Check that the rules engine still matches PvPoke, the reference simulator:
   ```bash
   python3 scripts/check_pvpoke.py
   ```
   It must print `108 of 108 PvPoke battles reproduced exactly`.
4. Run the measurement in [How to measure a change](#how-to-measure-a-change). It takes
   about five seconds and shows the current best bot beating the hand-written one.
5. Pick a task from [What to do next](#what-to-do-next).

If you cannot run code, you can still help: read the status file and the code, and
propose changes as a patch plus the exact command that would measure them. Do not state
a result you have not measured.

## Requirements

- Python 3 (developed on 3.13). The engine, players and tracker use only the standard library.
- `numpy` for the learned parts (`pogo/learner.py`, `pogo/value.py`, the training scripts).
- Nothing to install or download otherwise; the game data is in `data/`.
- The phone link needs macOS and the Xcode command line tools. Nothing else depends on it.

## The ideas you need

**The game.** Time moves in half-second turns. A fast move takes one to five turns and
gives energy; a charged move costs energy and can be blocked by one of two shields; a
switch starts a 45-second timer. The engine header in `pogo/battle.py` lists the rules
and the simplifications.

**A player sees only a `View`.** That is what a screen could show, plus the opponent's
energy (countable from their fast moves) and their moves (assumed standard for the
species). Their unrevealed Pokémon are hidden. Every player decides from the `View`
alone, so a player trained in the simulator can later be driven by a screen.

**Three players matter.**

| Player | What it is |
|---|---|
| `Masher` | Throws when ready, always shields, never switches. A floor |
| `Planner` | The hand-written player: rules for move choice, timing, baiting, shields, switching, farming, sacrifices. Every rule can be switched off |
| `Learner` | A `Planner` whose judgement calls can be overruled by a trained network. **With `runs/general-decide/q.npz` this is the best bot** |

**Opponents are a crowd.** `varied()` gives a `Planner` with every habit shifted a
little, a different one each battle. Training and testing use that crowd, not one fixed
opponent.

**Per-decision learning is what works.** At a decision in an ordinary game the battle is
frozen and played out once for each option with identical dice. A network learns the
chance of winning after each option. The `Learner` follows the `Planner` unless the
network rates another option higher by a margin. Learning from the win or loss of whole
battles was tried and did not work.

## Map of the code

| File | What it holds |
|---|---|
| `pogo/gamedata.py` | `GameData`: Pokémon, moves, stats, type chart, damage constants. `gd.meta(50)` is the pool of the 50 best supported Pokémon; `gd.default("altaria")` is one Pokémon with its standard moves |
| `pogo/battle.py` | `Battle` (the rules engine), `Mon`, `Side`, `View`, `damage()`, the actions `FAST`, `CHARGED`, `SWITCH`. `Battle.clone()` copies a position for what-if play |
| `pogo/agents.py` | `Masher`, `Planner`, `varied()`, `expert()`, and helpers: `duel()`, `fasts_to_wait()`, `solve_2x2()`, `safety()` |
| `pogo/learner.py` | `Learner`, `QNet` (win chance per option), `describe()` (the 45 numbers a network sees), `Policy` (the older whole-battle learner) |
| `pogo/arena.py` | `compare()` and `field_results()`: play many battles and score them |
| `pogo/tracker.py` | `Tracker`: builds the full game state from `Observation`s (looks at the screen); `state()` writes it out |
| `pogo/teamlist.py` | Draws opponent teams from `data/teams.json` |
| `pogo/value.py` | A position-value model. Tried, did not help, off by default |
| `pogo/phone.py`, `helper/phonectl.swift` | Screenshot, text reading and taps through iPhone Mirroring. Never run against a phone |
| `scripts/` | One script per job; see the next section |
| `tests/test_rules.py` | 24 tests of stats, damage, turn rules, tracker and learner |
| `data/` | Game data from PvPoke, plus `teams.json` and `matchups.json` from the team search |
| `runs/` | Trained models and the printed output of each training run |
| `docs/` | `status.md` (read first), `what_to_see.md` (what recognition must read), `agent_instructions.md` (brief for an agent turning footage into looks) |
| `handoff/` | Self-contained briefs and bundles for agents that cannot see this repository |
| `games/example/` | A worked example of the tracker's input and output files |

## Commands

Every script prints its options with `--help`.

**Check**

| Command | What it tells you |
|---|---|
| `python3 -m unittest discover tests` | The code works |
| `python3 scripts/check_pvpoke.py` | The engine matches PvPoke hit for hit |
| `python3 scripts/check_tracker.py` | How well the tracker follows a battle through simulated cameras of three qualities |
| `python3 scripts/latency.py` | Time per tracker update and per decision, against the latency targets |
| `python3 scripts/check_pvpoke_ai.py` | Acceptance test for a port of PvPoke's AI (needs `pogo/pvpoke_ai.py`, which does not exist yet) |

**Measure players**

| Command | What it does |
|---|---|
| `python3 scripts/arena.py` | The `Planner` against the expert model and cruder styles |
| `python3 scripts/arena.py --parts` | What each `Planner` rule is worth against the `Masher` |
| `python3 scripts/arena.py --show 7` | One battle, seed 7, printed move by move |
| `python3 scripts/team.py melmetal jellicent altaria --grid` | A report on one team piloted by the `Planner`: record, best lead, hardest opponents, every one-on-one |

**Train** (unattended, one core, low priority; each ends with a test on fresh battles)

| Command | What it does |
|---|---|
| `python3 scripts/decide.py --minutes 60 --rounds 3` | Per-decision learning for any team. Writes `runs/general-decide/q.npz` |
| `python3 scripts/decide.py --team melmetal jellicent altaria --minutes 30` | The same for one team |
| `python3 scripts/decide.py --resume --opponents runs/general-decide/q.npz --teams data/teams.json --minutes 60 --rounds 3` | Carry on from the saved model, with half the opponents using our learned decisions and half the teams drawn from the team list |
| `python3 scripts/teams.py --include melmetal jellicent altaria` | Search for the strongest teams of three; writes `data/teams.json` (about 20 minutes) |
| `python3 scripts/selfplay.py --team a b c --minutes 60` | Whole-battle learning. Kept for reference; it did not beat the `Planner` |

**Follow a game and advise**

| Command | What it does |
|---|---|
| `python3 scripts/track.py games/example` | Builds the game state from `team.json` and `observations.jsonl` in that folder; writes `state.json`, `states.jsonl`, `events.jsonl` |
| `python3 scripts/advise.py games/example --look 45 --q runs/general-decide/q.npz` | From a game state: what to do now, what to do with the next shield, the chance of winning, one typical continuation |

**Phone** (parked)

| Command | What it does |
|---|---|
| `./build.sh` | Compiles the Swift helper to `bin/phonectl` |
| `python3 scripts/probe.py` | Looks at the iPhone Mirroring window: permissions, screenshot, text, timing. `--tap X Y` and `--drag` test input |

## How to measure a change

Strength is always a comparison on the same battles. This is the whole method:

```python
from pogo.gamedata import GameData
from pogo.agents import Planner, varied
from pogo.arena import field_results, mean_and_margin
from pogo.learner import Learner, QNet

gd = GameData()
pool = gd.meta(50)                                   # the 50 best supported Pokémon, standard movesets
q = QNet.load("runs/general-decide/q.npz")
crowd = lambda rng: varied(rng, pool)                # a different opponent each battle

new = field_results(None, pool, lambda: Learner(q=q, margin=0.02), crowd, battles=400, seed=1)
old = field_results(None, pool, Planner, crowd, battles=400, seed=1)   # same seed: same teams and opponents
gain, margin = mean_and_margin([a - b for a, b in zip(new, old)])
print(f"{100 * gain:+.1f} ± {100 * margin:.1f} points")
```

Save it as a file in the repository root and run it; it prints about `+14 ± 5 points`.
Replace `new` with your player to test an idea.

Rules for a result to count:

- **Same battles for both players.** Use the same `seed`. The first argument of
  `field_results` is our team; `None` means a random team each battle.
- **Report the margin.** 400 battles give about ±5 points; 3,000 give about ±2. A gain
  smaller than its margin is not a gain.
- **Never test on battles used for tuning.** If you chose a setting by trying several,
  test the chosen one on a new seed.
- **Compare with the right baseline.** A new learned model is compared with the
  `Planner` and with the current best model on the same battles.
- **Score** is wins plus half of draws, as a share of battles.

Speed, for planning: about 200 battles a second for `Planner` against the crowd on one
core, somewhat fewer with learned decisions.

## How to extend it

**A new player.** Any object with these methods can play (see `Masher` in
`pogo/agents.py`):

```python
def act(self, view) -> int                 # FAST, CHARGED[0], CHARGED[1], or SWITCH[slot]
def shield(self, view, foe_energy) -> bool # asked when the opponent throws and you have a shield
def replace(self, view) -> int             # team slot to send in after a faint
```

Optional: `saw_throw` and `saw_shield` (told what the opponent did), `clone()` (needed if
the player is used inside training play-outs), and `sees_move = True` (then `shield` gets
the incoming move as a third argument).

**A new rule in the `Planner`.** Add it behind a constructor flag that defaults to off,
measure it against the same `Planner` without it, and only then change the default.

**A new learned decision.** Route the choice through `Learner._decide(head, view, mask,
planner_choice)` and add the head with its number of options to `Q_HEADS` in
`pogo/learner.py`. `scripts/decide.py` then plays out its options automatically. The
network's input reserves three slots for the `Planner`'s own pick, so a head can have at
most three options unless that is widened.

**A new kind of opponent.** Return it from the `crowd` function. Keep the old crowd as a
second test so results stay comparable over time.

## The best bot, and how to use it

```python
from pogo.learner import Learner, QNet
bot = Learner(q=QNet.load("runs/general-decide/q.npz"), margin=0.02)
```

It beats the `Planner` by 13.6 ± 1.9 points on random teams (3,000 fresh battles). All
its results are against the `Planner` and its variations. Nothing yet says how it does
against an outside opponent or a person.

## What to do next

In order. `docs/status.md` has the reasoning.

1. **Upgrade the opponents.** Run the `--resume --opponents ... --teams ...` command from
   the training table. It reports against the new crowd and against the old crowd as a
   fixed yardstick. Accept the new model only if the yardstick score does not fall below
   the current +13.6 points. First check in `docs/status.md` whether `data/teams.json` is
   the wide team list; if not, run `scripts/teams.py` first.
2. **Test against PvPoke's AI.** The port is specified in
   `handoff/pvpoke_port_instructions.md`. When `pogo/pvpoke_ai.py` exists, run
   `scripts/check_pvpoke_ai.py`; it must print 108 of 108. Then measure the best bot
   against it. It does not switch, so treat it as a fixed outside test, not the only
   training partner.
3. **Use real games.** `docs/agent_instructions.md` tells an agent how to turn footage
   into looks. Run `scripts/track.py` on what comes back, then count the teams and Pokémon
   seen and put the counts in the `seen` field of `data/teams.json`.
4. **Late-game solving.** Positions with every Pokémon revealed can be solved exactly
   from the position reached. Measured scope is in `docs/status.md`; it is small for the
   final one-on-one.
5. **Opponent stats** from CP, charge-move priority and damage per hit. The tracker logs
   an `unexplained` event where the assumed stats do not fit.
6. **The phone.** Run `scripts/probe.py --drag` with iPhone Mirroring open. Whether
   synthetic drags reach the phone is the open question; ball throws and charged-move
   swipes need them.

## Working rules

- Training and testing run unattended on one core, with no language model in the loop.
- After a result, update `docs/status.md`: add it to the results or to "Tried and did not
  help". That file is how the next agent avoids repeating work.
- The owner is short on assistant usage. Prefer small, local changes that one command
  can verify.
- Large training examples are not kept in git (`runs/*/examples.npz`). The scripts
  regenerate them; `--resume` works without them.
- Ask the owner before sending any tap to a live game account.

## Mistakes already made, so you can skip them

- A rule that looks obviously right can measure as nothing. Several of the owner's
  expert rules did, probably because simulated opponents do not punish what people punish.
- A model that predicts better does not necessarily win more (the value model).
- Reading individual battle logs finds bugs that win rates hide. `scripts/arena.py --show`
  exists for this.
- A cheap score used as a filter can throw away good candidates (the first team search).
- Overruling the `Planner` too readily on little training data is badly wrong; the margin
  is chosen on separate battles for that reason.

## Data and credit

The game data in `data/` and the reference battles in `tests/data/` come from
[PvPoke](https://github.com/pvpoke/pvpoke), MIT licence (`data/PVPOKE_LICENSE`).
