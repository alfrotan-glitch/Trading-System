@echo off
REM QTS GOLD - evidence-only STOP audit. Never connects MT5 or submits orders.
setlocal EnableExtensions DisableDelayedExpansion
set "REPO=%~dp0"
set "AUTO=%REPO%gold_robot\reports_local\auto_runs"
set "BUNDLE="
for /f "delims=" %%D in ('dir /b /ad /o:-n "%AUTO%" 2^>nul') do (
  if not defined BUNDLE if exist "%AUTO%\%%D\QTS_SHARE_RESULTS.zip" (
    set "BUNDLE=%AUTO%\%%D\QTS_SHARE_RESULTS.zip"
    set "OUT=%AUTO%\%%D\post_stop_review"
  )
)
if not defined BUNDLE (
  echo ERROR: no latest evidence ZIP. First run QTS_SHARE_RESULTS.bat
  goto FAIL
)
set "PY="
where py >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if not defined PY (
  where python >nul 2>&1
  if not errorlevel 1 set "PY=python"
)
if not defined PY (
  echo ERROR: Python 3 required to parse local evidence.
  goto FAIL
)
echo QTS STOP REVIEW - READ ONLY / LIVE LOCKED
%PY% "%REPO%gold_robot\research\build_post_stop_inputs.py" --bundle "%BUNDLE%" --out "%OUT%"
if errorlevel 1 goto FAIL
echo.
echo Stop cases created, but post-stop TP/reversal remains UNKNOWN without tick history.
if defined QTS_BROKER_TICKS_DIR (
  echo Auditing native broker quote path from QTS_BROKER_TICKS_DIR...
  %PY% "%REPO%gold_robot\research\stop_reversal_audit.py" --stops "%OUT%\QTS_STOP_CASES.csv" --tick-dir "%QTS_BROKER_TICKS_DIR%" --output "%OUT%\QTS_POST_STOP_REAL_TICK_REVIEW.json"
  if errorlevel 1 goto FAIL
) else (
  echo To replay future paths, export WMMarkets bid/ask ticks and set QTS_BROKER_TICKS_DIR.
)
explorer "%OUT%"
if /I not "%QTS_NO_PAUSE%"=="1" pause
exit /b 0
:FAIL
echo STOP REVIEW FAILED. No transactions were submitted or modified.
if /I not "%QTS_NO_PAUSE%"=="1" pause
exit /b 1
