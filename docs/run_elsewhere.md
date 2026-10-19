# Running a long job on another machine

For an agent (or a person) on a machine other than the owner's Mac, for example the owner's PC. Read `AGENTS.md`
first; its rules apply. The worked example is **task 33** (retrain the bot's networks, `docs/tasks.md`).

## 1. Set up (once)

Python 3.10 or newer and numpy; nothing else. Windows (PowerShell):

```
git clone https://github.com/Solaceonx/pokemon_go.git
cd pokemon_go
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
pip install numpy
```

macOS or Linux: the same, with `python3 -m venv .venv` and `source .venv/bin/activate`. Later sessions: `cd
pokemon_go`, activate, `git pull`.

Check before anything long; both must pass:

```
python -m unittest discover tests
python scripts/check_pvpoke.py
```

The second prints `108 of 108 PvPoke battles reproduced exactly`. Then switch off sleep while plugged in (Windows:
Settings, System, Power, Screen and sleep: Never), so the job is not paused overnight.

## 2. Workers

Use the number of CPU cores minus two (`python -c "import os; print(os.cpu_count())"`), at most 8. The scripts
lower their own priority (below normal on Windows), so the machine stays usable. Task 33 needs about 2 GB of
memory for 4 workers; 16 GB is plenty.

## 3. Example: a two-minute trial of task 33

Same options as the real run, tiny sizes, to see that everything works (`--workers 2`):

```
python scripts/decide.py --run trial-33 --forms --playouts 2 --field mixed --both-sides 0.5 --start runs/general-decide/q.npz --minutes 1 --rounds 1 --workers 2 --val-battles 20 --final-battles 20
```

It prints lines like these (numbers vary; on the owner's Mac about 7,000 examples a minute with 2 workers):

```
first round piloted by runs/general-decide/q.npz (margin 0.02)
field: mixed; form inputs: True; play-outs per option: 2
collected this round: 1600 shield, 520 throw, 1100 swap, 240 replace, 3500 mid_swap
...
final test on 20 fresh battles, overruling when ahead by 0.1
files: runs/trial-33/q.npz, margin.txt, examples.npz
```

A one-minute model is meant to be bad; the trial only shows the pipeline runs. Delete `runs/trial-33` afterwards.

## 4. The real run

Task 33 wants about 16 core-hours of collecting. With W workers, `--minutes` is 960 divided by W (4 workers: 240,
6 workers: 160, 8 workers: 120). For W = 6:

```
python scripts/decide.py --run qnet-1 --forms --playouts 2 --field mixed --both-sides 0.5 --start runs/general-decide/q.npz --minutes 160 --rounds 4 --workers 6 > runs/qnet-1.out
python scripts/compare_models.py runs/general-decide/q.npz:0.02 runs/qnet-1/q.npz:auto --field mixed --battles 4000 --workers 3 --seed 3301 > runs/qnet-1-compare-mixed.out
python scripts/compare_models.py runs/general-decide/q.npz:0.02 runs/qnet-1/q.npz:auto --field usual --battles 4000 --workers 3 --seed 3302 > runs/qnet-1-compare-usual.out
```

Expect about 160 minutes of collecting plus about an hour of fitting, testing and comparing. The first command saves
after every round; if it stops, rerun it with `--resume --rounds R --minutes M`, where R is the rounds still to do
and M is 160 × R / 4 (`runs/qnet-1/training.json` lists the rounds done).

## 5. Bring the results back

Read the adoption rule in task 33 (`docs/tasks.md`) and apply it to the two comparison files. Then, on a branch:

```
git checkout -b qnet-1-results
git add runs/qnet-1.out runs/qnet-1-compare-mixed.out runs/qnet-1-compare-usual.out runs/qnet-1/q.npz runs/qnet-1/margin.txt runs/qnet-1/training.json
git commit -m "Task 33 results"
git push -u origin qnet-1-results
```

Never add `runs/qnet-1/examples.npz` (hundreds of MB). Write the result into `docs/status.md` (adopted or not, with the
numbers and margins) in the same commit. If the push is refused for lack of access, leave the commit and tell the owner.
