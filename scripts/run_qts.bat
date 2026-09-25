@echo off
REM QTS Trading System -- Launch Desktop
REM Double-click this file OR run from PowerShell: .\scripts\run_qts.bat
setlocal
cd /d "%~dp0.."

REM Fail clearly if prerequisites missing
if not exist .venv\Scripts\python.exe (
  echo ERROR: .venv not found. Run scripts\setup_windows.bat first.
  pause
  exit /b 1
)

if not exist src\qts\desktop\launcher.py (
  echo ERROR: src\qts\desktop\launcher.py not found. Run from repository root.
  pause
  exit /b 1
)

REM Default to development MOCK -- no real trading
if "%QTS_ENV%"=="" set QTS_ENV=development
if "%QTS_MT5_MODE%"=="" set QTS_MT5_MODE=MOCK

echo === QTS Trading System -- Desktop ===
echo Environment: %QTS_ENV%   MT5: %QTS_MT5_MODE%
echo Starting FastAPI + webview...
echo UI source: src\qts\desktop\ui

.venv\Scripts\python.exe -m qts.desktop.launcher
if errorlevel 1 (
  echo.
  echo Desktop exited with error %ERRORLEVEL%. Check logs\audit.jsonl
  pause
)
endlocal
