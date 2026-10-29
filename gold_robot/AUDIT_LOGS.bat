@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "REPORT_DIR=%~dp0reports_local\native"
set "OUTPUT=%~dp0reports_local\QTS_Agent_Log_Audit.json"
set "HTML=%~dp0reports_local\QTS_Agent_Log_Audit.html"
if not exist "%REPORT_DIR%" mkdir "%REPORT_DIR%"
where py >nul 2>&1
if %ERRORLEVEL%==0 (
  py -3 "%~dp0research\audit_mt5_logs.py" --directory "%REPORT_DIR%" --include-downloads --pick-on-empty --output "%OUTPUT%" --html-output "%HTML%"
) else (
  where python >nul 2>&1
  if errorlevel 1 (
    echo Python 3 is required for the optional agent-log audit.
    echo Use the PowerShell native comparison for saved HTML reports.
    pause
    exit /b 1
  )
  python "%~dp0research\audit_mt5_logs.py" --directory "%REPORT_DIR%" --include-downloads --pick-on-empty --output "%OUTPUT%" --html-output "%HTML%"
)
if errorlevel 1 (
  echo No valid agent logs were found or the audit could not run.
  pause
  exit /b 1
)
echo.
echo Read-only QTS log analysis saved to:
echo %OUTPUT%
echo HTML: %HTML%
echo If there were no saved logs, the report explains which folders were checked.
echo This is NOT a validated trading edge. LIVE remains locked.
if /I not "%QTS_NO_OPEN%"=="1" start "" "%HTML%"
pause
