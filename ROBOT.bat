@echo off
REM QTS Robot -- single-click Windows entry; forwards to canonical desktop.
REM No strategy selection, no change to execution modes, no broker orders.
setlocal EnableExtensions
cd /d "%~dp0"

if not exist "scripts\run_qts.bat" (
  echo ERROR: The canonical QTS launcher is missing.
  echo Restore the project files before opening QTS.
  pause
  exit /b 1
)

REM Detect the user's previously observed Python-startup MemoryError early.
REM No existing state, brokerage setting, tick history or virtualenv is changed.
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -I -c "import sys; sys.exit(0)" >nul 2>nul
  if errorlevel 1 (
    echo ERROR: The local Python environment could not initialize.
    echo If Python reports MemoryError, restart Windows, close heavy apps,
    echo and ensure Windows-managed pagefile is enabled with free disk space.
    echo Do not delete QTS data or reinstall before checking memory.
    pause
    exit /b 1
  )
)

echo ====================================================
echo QTS GOLD ROBOT -- DEMO WORKSTATION
echo ====================================================
echo This opens the existing QTS desktop, not a second robot.
echo No strategy is validated profitable; LIVE remains locked.
echo Launching never places an order. Existing DEMO approval is required.
echo.
call "scripts\run_qts.bat"
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" (
  echo.
  echo QTS exited with error %RESULT%.
  echo Review the message above. No safety gate was bypassed.
  pause
)
exit /b %RESULT%
