@echo off
REM Generate a local, read-only QTS Gold readiness report.
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
echo.
echo ======================================================
echo  QTS GOLD - LOCAL WINDOWS READINESS REPORT (NO ORDERS)
echo ======================================================
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0research\MakeWindowsReport.ps1"
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" (
  echo ERROR: Could not produce a verified local report.
  echo Check your MT5 Data Folder. No orders have been sent.
)
exit /b %RESULT%
