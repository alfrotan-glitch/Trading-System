@echo off
REM One desktop path. This file exists so older shortcuts still work.
REM It does not start a second server and does not override QTS_ENV.
setlocal
cd /d "%~dp0.."
call "%~dp0run_qts.bat"
endlocal
