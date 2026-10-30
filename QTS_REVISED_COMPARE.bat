@echo off
REM QTS GOLD V2 - one double-click native holdout A/B test.
REM No live-account orders, no account data or private keys included.
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
echo ============================================================
echo QTS GOLD V2 - REVISED STRATEGY TESTS (OCT 2026 HOLDOUT)
echo BASELINE vs REVISED. FOUR STRATEGIES. LIVE LOCKED.
echo ============================================================
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0QTS_REVISED_COMPARE.ps1"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
 echo.
 echo TEST STOPPED: A/B evidence incomplete. No live trades enabled.
 echo Please share the error above.
) else (
 echo.
 echo Completed. Send QTS_V2_HOLDOUT_EVIDENCE.zip for review.
)
if /I not "%QTS_NO_PAUSE%"=="1" pause
exit /b %RC%
