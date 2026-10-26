@echo off
REM QTS - single Windows entry point. No live orders or automatic trading.
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
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
echo  [5] Exit
echo.
choice /C 12345 /N /M "Choose 1-5: "
if errorlevel 5 goto END
if errorlevel 4 goto GUIDE
if errorlevel 3 goto DESKTOP
if errorlevel 2 goto REPORT
if errorlevel 1 goto INSTALL
goto END

:INSTALL
call "gold_robot\SETUP_MT5_GOLD.bat"
set "CODE=%ERRORLEVEL%"
if not "%CODE%"=="0" echo Installation is not verified. Review compiler messages above.
echo.
pause
goto MENU

:REPORT
call "gold_robot\MAKE_REPORT.bat"
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

:GUIDE
if not exist "gold_robot\docs\WINDOWS_START_DARI.md" (
  echo ERROR: Windows guide is missing.
  pause
  goto MENU
)
start "" notepad.exe "%~dp0gold_robot\docs\WINDOWS_START_DARI.md"
goto MENU

:VERIFY_SETUP
REM Noninteractive Windows smoke test, validates menu -> setup BAT paths.
set "QTS_SETUP_VALIDATE_ONLY=1"
call "gold_robot\SETUP_MT5_GOLD.bat"
exit /b %ERRORLEVEL%

:END
echo QTS closed; no orders were requested by this menu.
exit /b 0
