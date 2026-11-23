@echo off
cd /d "C:\Users\marco\Developer\pokemon_go-task48"
set "POGO_LEAGUE=2500"
set "OMP_NUM_THREADS=1"
set "PY=C:\Users\marco\Developer\pokemon_go\.venv\Scripts\python.exe"
rem Task 48 steps 1-3 (docs/tasks.md on main). Each finished step leaves a marker, so a restart skips it.
if not exist runs\task48-step1.done (
  "%PY%" -X utf8 -u scripts\decide.py --start runs/general-decide/q.npz --opponents runs/general-decide/q.npz --minutes 120 --rounds 3 --workers 30 --run ul-decide >> runs\task48_decide.out 2>&1
  if errorlevel 1 exit /b 1
  echo done> runs\task48-step1.done
)
if not exist runs\task48-step2.done (
  "%PY%" -X utf8 -u scripts\train_eval.py --wide --battles 40000 --workers 30 --q runs/ul-decide/q.npz --out runs/ul-eval/eval.npz >> runs\task48_eval.out 2>&1
  if errorlevel 1 exit /b 1
  echo done> runs\task48-step2.done
)
"%PY%" -X utf8 -u scripts\engine_versus.py --tag ul-nets --baseline website --candidates "website,q=runs/ul-decide/q.npz,eval=runs/ul-eval/eval.npz" "website,q=runs/ul-decide/q.npz" "website,eval=runs/ul-eval/eval.npz" --pairings 1500 --crowd 1500 --pvpoke 0 --workers 30 --seed 4801 >> runs\task48_versus.out 2>&1
if errorlevel 1 exit /b 1
