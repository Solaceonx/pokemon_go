# For agents working in this repository

A Pokémon GO battle bot (Great League, three against three), built in a simulator first. Several agents and
people work on it; the owner is short on assistant usage, so work that one command can verify is best.

## Start

1. Read `README.md` ("Start here"), then `docs/status.md` (every result, including what did not help),
   then `docs/tasks.md` (every task with its state and a self-contained brief).
2. `python3 -m unittest discover tests` and `python3 scripts/check_pvpoke.py` (108 of 108) must pass
   before you change anything and before you push.
3. Pick a task from `docs/tasks.md`. Put your name after its title and push that before starting, so two
   agents do not take the same one. Work on a branch named for the task and open a pull request; small
   fixes to documents can go straight to `main`. `git pull` before you start and before you push.

## Rules

- **Measure, with margins.** A result is a score with its 95% margin on battles not used for tuning. If you
  tried several settings, rerun the one you picked on a fresh `--seed`. Each brief's "Done when" says what
  counts; say plainly whether you ran it and what it printed.
- **Write every result into `docs/status.md`,** including results that did not help. That file is how the
  next agent avoids repeating work. Update the task's state in `docs/tasks.md`.
- **Standard library plus `numpy`.** No services and no language model in the loop at run time.
- **No large files in git:** videos, frames, `runs/*/examples.npz`, `runs/engine_habits.json`,
  `runs/distill/labels_*.npz`. Results go in small text files under `runs/`.
- **Computing.** Run long jobs with `nice`, one NumPy thread per worker (the scripts set it), and at most
  three workers unless the owner says otherwise. Do not edit code while a long run is using it: its worker
  processes import it afresh. Cloud containers are reclaimed when idle and kill running jobs, so prefer
  runs that save as they go and can resume.
- **Reserved footage.** The official sample in task 17 is for testing only. Do not tune anything on it.
- **The real game.** Automating it breaks Niantic's terms. Never send a tap to a live game account without
  the owner's say-so.
- **The owner's strategy ideas** are in `docs/status.md` under "Strategy guidance from the project owner".
  Implement what they describe and measure it; ask before inventing a rule.
