@echo off
REM QTS Gold: one canonical operator menu; no connected broker orders.
REM Advanced research utilities remain available without extra desktop bots.
setlocal EnableExtensions DisableDelayedExpansion
set "QTS_ROOT_DIR=%~dp0"
cd /d "%QTS_ROOT_DIR%"
if not exist "gold_robot\SETUP_MT5_GOLD.bat" (
  echo ERROR: Missing gold_robot folder. Obtain the complete main branch.
  pause
  exit /b 1
)
if /I "%~1"=="/verify-setup" goto VERIFY_SETUP

:MENU
cls
echo.
echo  ============================================================
echo                 QTS GOLD - SINGLE CONTROL PANEL
echo  ============================================================
echo  WMMarkets MT5 - XAUUSD@ - NATIVE STRATEGY TESTER
echo  LIVE LOCKED / NO VALIDATED PROFITABLE EDGE
echo.
echo  [1] Test Retest vs Sweep/Reclaim (Styles 1 and 3)
echo  [2] Test all ten strategy styles (M15 and M1 as required)
echo  [3] Install / update the canonical MT5 Gold Robot
echo  [4] Open the most recent native tester results
echo  [5] Generate broker and installation readiness report
echo  [6] Advanced research and diagnostics
echo  [7] Exit
echo.
choice /C 1234567 /N /M "Choose 1-7: "
if errorlevel 7 goto END
if errorlevel 6 goto ADVANCED
if errorlevel 5 goto REPORT
if errorlevel 4 goto LATEST_RESULTS
if errorlevel 3 goto INSTALL
if errorlevel 2 goto RUN_ALL
if errorlevel 1 goto RUN_CHAMPIONS
goto MENU

:RUN_CHAMPIONS
echo.
echo Research comparison: same EA, native broker real ticks, Styles 1 and 3.
echo Older positive screens are NOT proof of durable profit.
setlocal
set "QTS_NO_PAUSE=1"
call "%QTS_ROOT_DIR%QTS_AUTO_TEST.bat" champions
set "SUBCODE=%ERRORLEVEL%"
endlocal & set "CODE=%SUBCODE%"
if not "%CODE%"=="0" echo Research NO-GO: review the new run, not an older report.
echo.
pause
goto MENU

:RUN_ALL
echo.
echo Full ten-style research, never connected broker orders.
setlocal
set "QTS_NO_PAUSE=1"
call "%QTS_ROOT_DIR%QTS_AUTO_TEST.bat"
set "SUBCODE=%ERRORLEVEL%"
endlocal & set "CODE=%SUBCODE%"
if not "%CODE%"=="0" echo Native results incomplete or evidence unavailable.
echo.
pause
goto MENU

:LATEST_RESULTS
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -Command "$root='gold_robot\reports_local\auto_runs'; $dirs=Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending; $last=$dirs | ForEach-Object { Join-Path $_.FullName 'OPEN_RESULTS.html' } | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1; if($last){Start-Process -FilePath $last; Write-Host ('Opened: '+$last)}else{Write-Host 'No native result yet. Run option 1 or 2.'}"
echo.
pause
goto MENU

:ADVANCED
cls
echo.
echo  ============================================================
echo             QTS GOLD - ADVANCED RESEARCH TOOLS
echo  ============================================================
echo  Simulation/read-only controls. LIVE LOCKED.
echo.
echo  [1] Install and compile MT5 EA
echo  [2] Generate readiness report
echo  [3] Open separate Python research desktop (no orders)
echo  [4] Read MT5 Windows guide
echo  [5] Create ten Strategy Tester presets (no orders)
echo  [6] Compare saved MT5 reports
echo  [7] Exit QTS
echo  [8] Audit saved MT5 agent logs
echo  [9] Diagnose adaptive V4 decisions (last completed month)
echo  [A] Review historical post-stop broker quote paths
echo.
choice /C 123456789A /N /M "Choose 1-9 or A: "
if errorlevel 10 goto STOP_QUOTES
if errorlevel 9 goto V4_DIAGNOSE
if errorlevel 8 goto AUDIT
if errorlevel 7 goto END
if errorlevel 6 goto COMPARE
if errorlevel 5 goto PRESETS
if errorlevel 4 goto GUIDE
if errorlevel 3 goto DESKTOP
if errorlevel 2 goto REPORT
if errorlevel 1 goto INSTALL
goto MENU

:INSTALL
call "%QTS_ROOT_DIR%gold_robot\SETUP_MT5_GOLD.bat"
set "CODE=%ERRORLEVEL%"
if not "%CODE%"=="0" echo Installation is not verified. Review compiler messages above.
echo.
pause
goto MENU

:REPORT
call "%QTS_ROOT_DIR%gold_robot\MAKE_REPORT.bat"
set "CODE=%ERRORLEVEL%"
if not "%CODE%"=="0" echo Report generation failed. See details above.
echo.
pause
goto MENU

:DESKTOP
echo Starting the separate Python research desktop - no broker orders.
call "scripts\run_qts.bat"
set "CODE=%ERRORLEVEL%"
if not "%CODE%"=="0" echo Desktop was not launched. MT5 Gold Robot is independent.
echo.
pause
goto MENU

:COMPARE
call "%QTS_ROOT_DIR%gold_robot\MAKE_COMPARISON.bat"
set "CODE=%ERRORLEVEL%"
if not "%CODE%"=="0" echo Comparison report failed.
echo.
pause
goto MENU

:PRESETS
call "%QTS_ROOT_DIR%gold_robot\MAKE_TEST_PRESETS.bat"
set "CODE=%ERRORLEVEL%"
if not "%CODE%"=="0" echo Tester presets were not created.
echo.
pause
goto MENU

:STOP_QUOTES
call "%QTS_ROOT_DIR%QTS_POST_STOP_REVIEW.bat"
set "CODE=%ERRORLEVEL%"
if not "%CODE%"=="0" echo Post-stop tick evidence incomplete or MT5 history unavailable.
echo.
pause
goto MENU

:V4_DIAGNOSE
call "%QTS_ROOT_DIR%QTS_AUTO_TEST.bat" v4
set "CODE=%ERRORLEVEL%"
if not "%CODE%"=="0" echo Decision diagnosis is NO-GO or incomplete. Review its own run.
echo.
pause
goto MENU

:AUDIT
call "%QTS_ROOT_DIR%gold_robot\AUDIT_LOGS.bat"
set "CODE=%ERRORLEVEL%"
if not "%CODE%"=="0" echo Log audit could not be created. Check the saved QTS files.
echo.
pause
goto MENU

:GUIDE
if not exist "gold_robot\docs\WINDOWS_START.md" (
  echo ERROR: Windows guide is missing.
  pause
  goto MENU
)
start "" notepad.exe "%QTS_ROOT_DIR%gold_robot\docs\WINDOWS_START.md"
goto MENU

:VERIFY_SETUP
REM Noninteractive Windows CI smoke test; does not touch a real broker.
set "QTS_SETUP_VALIDATE_ONLY=1"
call "gold_robot\SETUP_MT5_GOLD.bat"
exit /b %ERRORLEVEL%

:END
echo QTS closed. No live orders were requested.
exit /b 0
