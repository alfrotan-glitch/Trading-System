@echo off
REM QTS Robot -- one menu, one existing engine, fail-closed DEMO controls.
setlocal EnableExtensions
cd /d "%~dp0"

if not exist "scripts\run_qts.bat" (
  echo ERROR: The canonical QTS launcher is missing.
  pause
  exit /b 1
)

REM Catch the previously reported Python init_import_site MemoryError.
REM The check does not alter account mode, state, or historical ticks.
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -I -c "import sys; sys.exit(0)" >nul 2>nul
  if errorlevel 1 (
    echo ERROR: Python could not start. If MemoryError appeared, restart
    echo Windows, close heavy programs, and check Windows pagefile settings.
    echo Do not delete QTS or the historical MT5 tick data.
    pause
    exit /b 1
  )
)

echo.
echo ========================================================
echo QTS GOLD ROBOT -- DEMO ONLY. LIVE LOCKED.
echo ========================================================
echo 1. Open desktop - no broker orders [default]
echo 2. Start authorized DEMO robot - may submit DEMO orders
echo No validated profitable strategy exists.
choice /C 12 /N /T 3 /D 1 /M "Choose 1 or 2: "
if errorlevel 2 goto DEMO_ROBOT

echo Opening the canonical QTS workstation...
call "scripts\run_qts.bat"
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" pause
exit /b %RESULT%

:DEMO_ROBOT
if not exist ".venv\Scripts\python.exe" (
  echo ERROR: Python is not installed. Choose option 1 to set up the desktop.
  pause
  exit /b 1
)
echo.
echo WARNING: This path can place orders on a verified DEMO account.
echo No strategy is validated profitable and demo losses may occur.
echo Brokerage account, authorization, registration, stop and risk gates apply.
set "ACK="
set /p "ACK=Type DEMO to acknowledge virtual DEMO orders, or Enter to cancel: "
if /I not "%ACK%"=="DEMO" (
  echo Cancelled. No orders requested.
  exit /b 0
)
echo Checking broker, permission, strategy and risk gates...
".venv\Scripts\python.exe" -m qts demo verify
if errorlevel 1 (
  echo BLOCKED: QTS DEMO verification refused execution.
  echo Use option 1 to finish guided account and policy setup.
  pause
  exit /b 2
)
echo Starting controlled DEMO robot. Press Ctrl+C to stop its loop.
echo IMPORTANT: Stopping the loop does NOT guarantee open DEMO positions close.
echo After stopping, check MetaTrader 5 positions and close them if needed.
".venv\Scripts\python.exe" -m qts demo run --confirm --risk-ack --poll-interval 5
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" (
  echo DEMO robot stopped or refused execution.
  pause
)
exit /b %RESULT%
