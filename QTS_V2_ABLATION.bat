@echo off
REM QTS GOLD V2 - one double-click four-arm exploratory native MT5 ablation.
REM No live-account orders, no account data or private keys included.
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
echo ============================================================
echo QTS GOLD V2 - FOUR ARM MECHANISM AUDIT
echo BASELINE / ENTRY_FILTER / NEAR_TP / COMBINED. LIVE LOCKED.
echo ============================================================
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0QTS_V2_ABLATION.ps1"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
 echo.
 echo TEST STOPPED: four-arm evidence incomplete. No live trades enabled.
 echo Please share the error above.
) else (
 echo.
 echo Completed. Send QTS_V2_ABLATION_EVIDENCE.zip for review.
)
if /I not "%QTS_NO_PAUSE%"=="1" pause
exit /b %RC%
