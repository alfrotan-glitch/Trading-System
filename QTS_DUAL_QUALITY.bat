@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0QTS_DUAL_QUALITY.ps1"
set "QTS_EXIT=%ERRORLEVEL%"
if "%QTS_EXIT%"=="2" (
 echo.
 echo QTS SAFETY NO-GO: MT5 detected an unsafe fill and preserved the evidence ZIP.
 echo This is an EXPECTED protective stop, not a successful profitability test.
 echo Do not reset the execution halt or enable real-money orders.
 pause
 exit /b 2
)
if not "%QTS_EXIT%"=="0" (
 echo.
 echo QTS RESEARCH ERROR: Could not verify the test or collect required evidence.
 echo Examine the preceding error. LIVE LOCKED.
 pause
 exit /b 1
)
echo QTS research-only test completed. No real-money trade permission.
pause
