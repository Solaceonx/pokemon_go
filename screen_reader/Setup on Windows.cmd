@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto install
where py >nul 2>nul
if not errorlevel 1 (
    py -3 -m venv .venv
    if errorlevel 1 goto failed
    goto install
)
where python >nul 2>nul
if not errorlevel 1 (
    python -m venv .venv
    if not errorlevel 1 goto install
)
if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" (
    "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m venv .venv
    if not errorlevel 1 goto install
)
echo Install Python 3.12 from https://www.python.org/downloads/ and try again.
pause
exit /b 1
:install
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo Setup finished. Double-click Open Battle Viewer or Import Battle Video.
pause
exit /b 0
:failed
echo Setup could not finish. The error is shown above.
pause
exit /b 1
