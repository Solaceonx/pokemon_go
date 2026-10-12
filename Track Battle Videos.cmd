@echo off
setlocal
cd /d "%~dp0"
if defined READER_PYTHON (
  "%READER_PYTHON%" scripts\recording\vod_track_menu.py
) else if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" (
  "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\recording\vod_track_menu.py
) else (
  py -3.12 scripts\recording\vod_track_menu.py
)
echo.
pause
