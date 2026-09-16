@echo off
REM One-click launch for QTS Trading System -- Windows
REM Double-click this file to open desktop
setlocal
cd /d "%~dp0.."

if not exist .venv\Scripts\python.exe (
  echo ERROR: .venv not found. Run scripts\setup_windows.bat or scripts\setup_windows.ps1 first.
  pause
  exit /b 1
)

set QTS_ENV=development
set QTS_MT5_MODE=MOCK
REM For paper/shadow use: set QTS_ENV=paper

.venv\Scripts\python.exe -m qts.desktop.launcher
if errorlevel 1 (
  echo Launcher exited with error %ERRORLEVEL%.
  pause
)
endlocal
