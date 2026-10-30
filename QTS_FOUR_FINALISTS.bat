@echo off
REM Native full-forensic MT5 tests of the four positive-screen styles.
REM Style 1 Retest; 3 Sweep/Reclaim; 7 Adaptive; 8 SMC.
REM Research only; real-money orders remain locked.
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
echo ==========================================================
echo QTS GOLD - FOUR FINALISTS - REAL TICKS - LIVE LOCKED
echo Styles 1, 3, 7, 8 - Broker deal evidence required
echo ==========================================================
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0gold_robot\research\RunAutomaticTester.ps1" -OnlyStyles "1,3,7,8" -NoOpen
set "RC=%ERRORLEVEL%"
if "%RC%"=="0" (
  "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0gold_robot\research\PackTradeEvidence.ps1" -NoOpen
  if errorlevel 1 set "RC=2"
) else (
  echo Evidence gap or test failure: inspect latest OPEN_RESULTS.json in reports_local\auto_runs.
)
echo.
echo Research only: no verified trading edge and NO real-money orders.
if /I not "%QTS_NO_PAUSE%"=="1" pause
exit /b %RC%
