@echo off
REM QTS - single Windows entry point. No live orders or automatic trading.
setlocal EnableExtensions DisableDelayedExpansion
set "QTS_ROOT_DIR=%~dp0"
cd /d "%QTS_ROOT_DIR%"
if not exist "gold_robot\SETUP_MT5_GOLD.bat" (
  echo ERROR: Missing gold_robot folder. Clone the complete main branch.
  pause
  exit /b 1
)
if /I "%~1"=="/verify-setup" goto VERIFY_SETUP
:MENU
cls
echo.
echo  ============================================================
echo                QTS GOLD - WINDOWS CONTROL
echo  ============================================================
echo  WMMarkets MT5 - XAUUSD@ - RESEARCH / STRATEGY TESTER
echo  LIVE: LOCKED             PROFITABLE EDGE: NOT VALIDATED
echo.
echo  [1] Install / update MT5 Gold Robot and broker check
echo  [2] Create professional local readiness report
echo  [3] Open QTS research desktop (no orders)
echo  [4] Read the short MT5 Windows guide
echo  [5] Create seven MT5 Strategy Tester presets (no orders)
echo  [6] Compare saved MT5 Strategy Tester reports
echo  [7] Exit
echo  [8] Find saved MT5 logs and open an easy-to-read report
echo.
choice /C 12345678 /N /M "Choose 1-8: "
if errorlevel 8 goto AUDIT
if errorlevel 7 goto END
if errorlevel 6 goto COMPARE
if errorlevel 5 goto PRESETS
if errorlevel 4 goto GUIDE
if errorlevel 3 goto DESKTOP
if errorlevel 2 goto REPORT
if errorlevel 1 goto INSTALL
goto END

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

:AUDIT
call "%QTS_ROOT_DIR%gold_robot\AUDIT_LOGS.bat"
set "CODE=%ERRORLEVEL%"
if not "%CODE%"=="0" echo Log audit could not be created. Check the saved QTS files.
echo.
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
REM Noninteractive Windows smoke test, validates menu -> setup BAT paths.
set "QTS_SETUP_VALIDATE_ONLY=1"
call "gold_robot\SETUP_MT5_GOLD.bat"
exit /b %ERRORLEVEL%

:END
echo QTS closed; no orders were requested by this menu.
exit /b 0
