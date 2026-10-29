@echo off
REM QTS Gold: fully automated, locally simulated MT5 strategy tests.
REM Does not send connected broker orders or enable live trading.
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
set "QTS_NO_OPEN_OPTION="
if /I "%QTS_NO_OPEN%"=="1" set "QTS_NO_OPEN_OPTION=-NoOpen"
echo ==========================================================
echo QTS GOLD - ONE-CLICK AUTOMATIC MT5 TESTER
echo Four M15 strategies / REAL TICKS / LIVE LOCKED
echo ==========================================================
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0gold_robot\research\RunAutomaticTester.ps1" %QTS_NO_OPEN_OPTION%
set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" (
  echo The automatic test did not finish. The HTML report explains what blocked it.
) else (
  echo QTS automatic research step finished. Real-money trading remains locked.
)
if /I not "%QTS_NO_PAUSE%"=="1" pause
exit /b %RC%
