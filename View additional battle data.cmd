@echo off
setlocal
if exist "%~dp0.vod\enrichment-20261109\Battle data.html" (
  start "" "%~dp0.vod\enrichment-20261109\Battle data.html"
) else (
  echo The local evidence report has not been generated on this PC yet.
  echo See docs\battle_evidence.md for the saved-data workflow.
  pause
)
