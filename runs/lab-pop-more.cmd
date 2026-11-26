@echo off
set "OMP_NUM_THREADS=1"
cd /d "C:\Users\marco\Developer\pokemon_go-lab-learn"
"C:\Users\marco\Developer\pokemon_go\.venv\Scripts\python.exe" -X utf8 -u scripts\lab\train_population.py --run lab-learn/population --generations 6 --minutes 360 --workers 14 --check 2000 >> runs\lab-learn-population-2.out 2>&1
if errorlevel 1 exit /b 1
copy /y "C:\Users\marco\Developer\pokemon_go-lab-learn\runs\lab-learn\population\q.npz" "C:\Users\marco\Developer\pokemon_go-lab-best\runs\lab-pop6-q.npz" >nul
if errorlevel 1 exit /b 1
cd /d "C:\Users\marco\Developer\pokemon_go-lab-best"
"C:\Users\marco\Developer\pokemon_go\.venv\Scripts\python.exe" -X utf8 -u scripts\engine_versus.py --field mixed --pairings 1000 --crowd 1000 --pvpoke 500 --workers 14 --seed 5701 --tag tune-2 --baseline "website,engine=tree,fix_stay=1,fix_judged=1,root=sh,shield_mix=0,finish_safe=1,opp_q=runs/general-decide/q.npz,depth=3,q=runs/lab-pop-q.npz" --candidates "website,engine=tree,fix_stay=1,fix_judged=1,root=sh,shield_mix=0,finish_safe=1,opp_q=runs/general-decide/q.npz,depth=3,q=runs/lab-pop6-q.npz" >> runs\lab-tune-2.out 2>&1
if errorlevel 1 exit /b 1
