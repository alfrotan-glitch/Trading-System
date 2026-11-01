@echo off
REM QTS Gold: fully automated, locally simulated MT5 strategy tests.
REM Does not send connected broker orders or enable live trading.
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
REM A single guided V4 diagnosis is opt-in; default ten-style tests unchanged.
if /I "%~1"=="v4" goto V4_DIAGNOSE
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


:V4_DIAGNOSE
echo ==========================================================
echo QTS GOLD - ADAPTIVE V4 NATIVE DECISION DIAGNOSTICS
echo Last completed calendar month / real ticks / test account only
echo No REAL orders. No historical threshold tuning. LIVE LOCKED.
echo ==========================================================
REM Date scoped to completed calendar month. Don't require manual date edits.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$end=(Get-Date -Day 1).Date; $start=$end.AddMonths(-1); & '.\gold_robot\research\RunAutomaticTester.ps1' -OnlyStyles 7 -ResearchVariant ADAPTIVE_V4 -FromDate $start.ToString('yyyy.MM.dd') -ToDate $end.ToString('yyyy.MM.dd') -NoOpen; exit $LASTEXITCODE"
set "RC=%ERRORLEVEL%"
REM Pack native gate-count CSV and original broker deals even on a NO-GO.
set "QTS_NO_PAUSE=1"
call "%~dp0QTS_SHARE_RESULTS.bat"
echo.
echo Review OPEN_RESULTS.html and the QTS_7_decisions.csv inside QTS_SHARE_RESULTS.zip.
echo The run is RESEARCH ONLY; zero trades or missing evidence is NOT a pass.
if /I not "%QTS_NO_PAUSE%"=="1" pause
exit /b %RC%
