@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0QTS_DUAL_DIAGNOSE.ps1"
if errorlevel 1 (
 echo QTS read-only diagnostic failed. No MT5 orders were submitted.
 pause
 exit /b 2
)
pause
