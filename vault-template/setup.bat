@echo off
rem LLM Wiki setup: link this vault to a working directory. Double-click to run (it asks for the path).
rem Arguments are passed to scripts\setup.py as-is (e.g. setup.bat D:\src\myapp --copilot-instructions).
setlocal
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>&1
if %errorlevel%==0 (
  py -3 scripts\setup.py %*
) else (
  python scripts\setup.py %*
)
set rc=%errorlevel%
echo.
pause
exit /b %rc%
