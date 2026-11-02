@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo QTS GOLD - NATIVE MT5 HISTORICAL REPLAY (2025 TO TODAY)
echo DUAL_DIRECTIONAL: BUY Retest + SELL Sweep research only
echo MARKET ORDERS: NEVER REAL  ^|  LIVE: LOCKED
echo ============================================================
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0QTS_BACKTEST_2025_TO_DATE.ps1"
set "QTS_EXIT=%ERRORLEVEL%"
if "%QTS_EXIT%"=="2" (
 echo.
 echo HISTORICAL SAFETY OR EVIDENCE NO-GO: see ZIP and summary.
 echo This is NOT approval for real-money trading. LIVE LOCKED.
 pause
 exit /b 2
)
if not "%QTS_EXIT%"=="0" (
 echo.
 echo HISTORICAL RUN ERROR. Read the error above. LIVE LOCKED.
 pause
 exit /b 1
)
echo.
echo HISTORICAL REPLAY COMPLETED FOR REVIEW ONLY. LIVE LOCKED.
pause
