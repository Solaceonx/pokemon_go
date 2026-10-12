@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo First double-click Setup on Windows.cmd in this folder.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" import_video.py
if errorlevel 1 pause
