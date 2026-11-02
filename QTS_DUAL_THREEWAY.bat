@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0QTS_DUAL_THREEWAY.ps1"
set "QTS_EXIT=%ERRORLEVEL%"
if "%QTS_EXIT%"=="2" (
 echo.
 echo QTS SAFETY NO-GO: Unsafe broker fill detected during native three-way testing.
 echo The available safety evidence ZIP was preserved; no strategy ranking was produced.
 echo LIVE LOCKED. Do not reset the halt or enable real-money orders.
 pause
 exit /b 2
)
if not "%QTS_EXIT%"=="0" (
 echo.
 echo QTS THREE-WAY RESEARCH ERROR: Test or evidence checks failed.
 echo See the preceding error. LIVE LOCKED.
 pause
 exit /b 1
)
echo QTS three-arm research-only comparison finished. No trade permission.
pause
