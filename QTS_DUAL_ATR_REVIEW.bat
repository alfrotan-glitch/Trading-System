@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0QTS_DUAL_ATR_REVIEW.ps1"
if errorlevel 1 (
 echo Read-only review incomplete. Inspect diagnostic report. LIVE LOCKED.
 pause
 exit /b 2
)
pause
