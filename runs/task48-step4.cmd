@echo off
cd /d "C:\Users\marco\Developer\pokemon_go-task48"
set "POGO_LEAGUE=2500"
set "OMP_NUM_THREADS=1"
set "PY=C:\Users\marco\Developer\pokemon_go\.venv\Scripts\python.exe"
rem Step 4: the best of step 3 (the new evaluation alone: ties the full pair at 50.5, better against the crowd) on fresh battles.
"%PY%" -X utf8 -u scripts\engine_versus.py --tag ul-nets-confirm --baseline website --candidates "website,eval=runs/ul-eval/eval.npz" --pairings 2000 --crowd 1000 --pvpoke 0 --workers 30 --seed 4802 >> runs\task48_confirm.out 2>&1
if errorlevel 1 exit /b 1
rem Diagnostic: the new bot without its mid_swap head (mid-matchup swaps back to the rulebook, as with the shipped bot) and the new evaluation, on step 3's battles.
"%PY%" -X utf8 -u scripts\engine_versus.py --tag ul-nets-nomid --baseline website --candidates "website,q=runs/ul-decide/q-no-midswap.npz,eval=runs/ul-eval/eval.npz" --pairings 1500 --crowd 1500 --pvpoke 0 --workers 30 --seed 4801 >> runs\task48_nomid.out 2>&1
if errorlevel 1 exit /b 1
