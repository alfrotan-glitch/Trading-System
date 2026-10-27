@echo off
REM Generate a local, read-only QTS Gold readiness report.
setlocal EnableExtensions DisableDelayedExpansion
set "QTS_GOLD_DIR=%~dp0"
cd /d "%QTS_GOLD_DIR%"
echo.
echo ======================================================
echo  QTS GOLD - LOCAL WINDOWS READINESS REPORT (NO ORDERS)
echo ======================================================
echo.
set "QTS_NO_OPEN_SWITCH="
if /I "%QTS_NO_OPEN%"=="1" set "QTS_NO_OPEN_SWITCH=-NoOpen"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%QTS_GOLD_DIR%research\MakeWindowsReport.ps1" %QTS_NO_OPEN_SWITCH%
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" (
  echo ERROR: Could not produce a verified local report.
  echo Check your MT5 Data Folder. No orders have been sent.
)
exit /b %RESULT%
