@echo off
REM QTS GOLD - ONE DOUBLE-CLICK: tests (if needed), broker tick history,
REM stop replay, and privacy-filtered evidence ZIP. NO REAL BROKER ORDERS.
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
echo ================================================================
echo QTS GOLD ONE-CLICK ROBOT - AUTOMATIC STOP ANALYSIS
echo MT5 broker quote data - no live orders - no manual MT5 script
echo ================================================================
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0QTS_ONE_CLICK_ROBOT.ps1"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
 echo.
 echo STOPPED SAFELY: No trades sent. Please share the error shown above.
) else (
 echo.
 echo FINISHED: QTS_POST_STOP_REVIEW.zip created. No trades sent.
)
if /I not "%QTS_NO_PAUSE%"=="1" pause
exit /b %RC%
