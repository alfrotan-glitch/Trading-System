@echo off
REM QTS Gold: fully automated, locally simulated MT5 strategy tests.
REM Does not send connected broker orders or enable live trading.
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
set "QTS_NO_OPEN_OPTION="
if /I "%QTS_NO_OPEN%"=="1" set "QTS_NO_OPEN_OPTION=-NoOpen"
echo ==========================================================
echo QTS GOLD - ONE-CLICK AUTOMATIC MT5 TESTER
echo Seven fixed M15 + adaptive M15 + SMC M15 + scalp M1 / REAL TICKS / LIVE LOCKED
echo ==========================================================
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0gold_robot\research\RunAutomaticTester.ps1" %QTS_NO_OPEN_OPTION%
set "RC=%ERRORLEVEL%"
REM Package only research JSON and broker-deal CSV; never share MT5 native HTML.
if exist "%~dp0gold_robot\research\PackTradeEvidence.ps1" (
  "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0gold_robot\research\PackTradeEvidence.ps1" -NoOpen
  if errorlevel 1 echo Local evidence ZIP unavailable; use QTS_SHARE_RESULTS.bat to diagnose.
)
echo.
if not "%RC%"=="0" (
  echo The automatic test did not finish. The HTML report explains what blocked it.
) else (
  echo QTS automatic research step finished. Real-money trading remains locked.
)
if /I not "%QTS_NO_PAUSE%"=="1" pause
exit /b %RC%
