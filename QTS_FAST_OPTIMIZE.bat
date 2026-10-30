@echo off
REM QTS FAST SCREEN: 9 M15 styles via local MT5 optimizer, then M1 scalp.
REM Screening only. Real-money orders always locked.
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
echo ====================================================
echo QTS GOLD FAST SCREEN - LOCAL PARALLEL OPTIMIZATION
echo Nine M15 research styles plus separate M1 scalp
echo LIVE LOCKED. This does not prove profitability.
echo ====================================================
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0QTS_FAST_OPTIMIZE.ps1"
set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" echo FAST SCREEN FAILED: check the message above; no live orders.
if /I not "%QTS_NO_PAUSE%"=="1" pause
exit /b %RC%
