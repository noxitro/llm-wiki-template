@echo off
rem LLM Wiki lint. Double-click to run. Arguments are passed to scripts\wiki_lint.py as-is.
setlocal
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>&1
if %errorlevel%==0 (
  py -3 scripts\wiki_lint.py %*
) else (
  python scripts\wiki_lint.py %*
)
set rc=%errorlevel%
echo.
pause
exit /b %rc%
